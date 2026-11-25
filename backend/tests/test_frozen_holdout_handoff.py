from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from app.cad_construction_interpreter import interpret_construction_request
from app.cad_source_acceptance import verify_scoped_primitives
from app.cad_structure_contract import explicit_composition, StructureContractError
from app.cad_vertex_acceptance import verify_open_straight_path
from app.cad_circle_group_acceptance import verify_circle_group_source
from app.cad_semantic_source_coverage import source_dimension_relation_guidance
from app.conversation_memory import ConversationMemoryStore


RECORDED=json.loads((Path(__file__).parent/'fixtures/frozen_holdout_handoff_20261124.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('noun',['圆','矩形','三角形'])
def test_new_local_noun_does_not_use_historical_selection(noun,tmp_path):
    store=ConversationMemoryStore(tmp_path/'memory.json')
    message=f'画一个{noun}，只保留这个{noun}。'
    result=store.resolve('new-local',message)
    assert not result['required'] and result['message']==message
    mixed=store.resolve('new-local',message+'放到之前的图纸上。')
    assert mixed['required'] and mixed['ambiguous']


def test_inverted_creation_grammar_reaches_create_route(tmp_path):
    from app.cad_creation_intent import local_creation_objects
    from app.agent_service import RobotAgentService
    text='请以(1.35,-0.85)为圆心作圆，直径取1.44米。图纸里只保留这个圆，不标尺寸。坐标单位米。'
    assert local_creation_objects(text)==['圆']
    result=ConversationMemoryStore(tmp_path/'memory.json').resolve('circle',text)
    assert not result['required']
    route=RobotAgentService(restore_pending_actions=False).resolve_intent(text,mode='advanced')
    assert route['operation']=='create',route
    plan={'units':'m','steps':[{'op':'add_circle','step_id':'round','output_ref':'round',
        'semantic':{'label':'圆'},
        'center':{'x':1.35,'y':-.85},'radius':.72}]}
    result=interpret(text,plan)
    assert result.get('acceptance_summary',{}).get('status')=='passed',result


def interpret(text,plan):
    return interpret_construction_request(text,lambda *_:{'schema_version':'cad.construction-interpretation.v1',
        'is_construction_request':True,'confidence':.99,'evidence_text':[text],'assumptions':[],
        'plan':deepcopy(plan)},force_structured_model=True)


@pytest.mark.parametrize('case',['L3','L7','L8'])
def test_recorded_correct_geometry_reaches_commit_gate(case,tmp_path):
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    from app.cad_candidate_state import candidate_is_accepted
    record=RECORDED[case];result=interpret(record['source'],record['plan'])
    assert result.get('acceptance_summary',{}).get('status')=='passed',result
    store=CreativeProjectStore(tmp_path/'projects.json')
    saved=commit_construction_interpretation(record['source'],result,store=store)
    assert candidate_is_accepted(store.get(saved['project_id'])['variants'][0])


@pytest.mark.parametrize('outer,inner,center',[(2400,810,[-345,678]),(520,135,[950,-1830]),(1700,650,[400,-700])])
def test_concentric_radii_are_scoped_and_measured(outer,inner,center):
    text=f'绘制两个同心圆，外圆半径{outer}毫米，内圆半径{inner}毫米，共同圆心({center[0]},{center[1]})，坐标单位毫米。只保留内外两个圆，不加其他线条。'
    gs=[{'id':i+1,'type':'circle','center':dict(zip(('x','y'),center)),'radius':r} for i,r in enumerate([outer,inner])]
    assert 'radius_m' not in explicit_composition(text)['dimensions']
    assert verify_circle_group_source(text,gs)['coverage']=='complete'
    bad=deepcopy(gs);bad[1]['radius']+=25
    with pytest.raises(StructureContractError):verify_circle_group_source(text,bad)
    bad=deepcopy(gs);bad[1]['center']['x']+=10
    with pytest.raises(StructureContractError):verify_circle_group_source(text,bad)
    assert verify_circle_group_source(text+'再画一条直线。',gs)['coverage']=='partial'


@pytest.mark.parametrize('x,y,angle,turn,a,b',[(-650,350,24,-63,2150,950),(275,-320,-17,83,1370,620)])
def test_walk_paraphrase_reuses_existing_path_measurement(x,y,angle,turn,a,b):
    direction='右' if turn<0 else '左'
    text=f'从({x},{y})出发画折线，先沿与x轴正向成{angle}度的方向走{a}毫米，再向{direction}转{abs(turn)}度接着画{b}毫米。两段连在一起，末端不连回起点，不加其他图形。坐标单位毫米。'
    points=[{'x':x,'y':y}]
    for length,d in [(a,angle),(b,angle+turn)]:
        p=points[-1];r=math.radians(d);points.append({'x':p['x']+length*math.cos(r),'y':p['y']+length*math.sin(r)})
    gs=[{'id':1,'type':'polyline','closed':False,'vertices':points}]
    proof=verify_open_straight_path(text,gs)
    assert proof['coverage']=='complete'
    assert all(c['source_evidence'] in text for c in proof['checks'] if 'source_evidence' in c)
    bad=deepcopy(gs);bad[0]['vertices'][-1]['x']+=20
    with pytest.raises(StructureContractError):verify_open_straight_path(text,bad)
    assert verify_open_straight_path(text+'，整体旋转10度',gs)['coverage']=='partial'


def test_measured_inventory_does_not_swallow_unmeasured_clauses():
    from app.cad_construction import execute_construction_plan
    row=RECORDED['L7'];executed=execute_construction_plan(row['plan'])
    gs=executed['geometries']
    assert verify_scoped_primitives(row['source'],gs)['coverage']=='complete'
    assert verify_scoped_primitives(row['source']+'面积为5平方米。',gs)['coverage']=='explicit_scoped_primitives_only'
    extra={'id':998,'type':'circle','center':{'x':5000,'y':5000},'radius':50}
    with pytest.raises(StructureContractError):verify_scoped_primitives(row['source'],gs+[extra])
    bad=deepcopy(gs);bad[0]['radius']+=15
    with pytest.raises(StructureContractError):verify_scoped_primitives(row['source'],bad)


def test_same_source_parser_supplies_relative_height_and_local_length():
    arch=source_dimension_relation_guidance(RECORDED['H2']['source'])[0]
    assert arch['derived_relations']=={'radius_mm':1150,'wall_height_mm':2000,'floor_y_mm':250,'top_y_mm':3400,'arc_center_y_mm':2250}
    capsule=source_dimension_relation_guidance(RECORDED['R2']['source'])[0]
    assert capsule['derived_relations']=={'radius_mm':465,'straight_length_mm':2540,'end_center_offset_from_midpoint_mm':1270}
    assert not source_dimension_relation_guidance(RECORDED['H2']['source']+'另有一个内圆。')
    for case in ['H2','R2']:
        result=interpret(RECORDED[case]['source'],RECORDED[case]['plan'])
        assert result.get('acceptance_summary',{}).get('status')!='passed'


def test_planning_callback_receives_derived_contract():
    calls=[];record=RECORDED['R2']
    def callback(text,schema):
        calls.append(text)
        return {'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
            'confidence':.99,'evidence_text':[record['source']],'assumptions':[],'plan':deepcopy(record['plan'])}
    interpret_construction_request(record['source'],callback,force_structured_model=True)
    assert calls and 'end_center_offset_from_midpoint_mm' in calls[0] and '1270' in calls[0]


REPAIR=json.loads((Path(__file__).parent/'fixtures/frozen_holdout_repair_context_20261124.json').read_text(encoding='utf-8'))


def test_recorded_two_bounded_repairs_reach_formal_persistence(monkeypatch,tmp_path):
    from app.agent_service import RobotAgentService
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    from app.cad_candidate_state import candidate_is_accepted
    source=REPAIR['original']['evidence_text'][0]
    payloads=iter([REPAIR['original'],REPAIR['identity_repair'],REPAIR['geometry_repair']])
    service=RobotAgentService(restore_pending_actions=False)
    monkeypatch.setattr(service,'_cad_construction_model_callback',lambda **kw:(
        lambda *_:deepcopy(next(payloads)),{'provider_attempted':False,'request_attempts':0}))
    first=service._interpret_cad_construction_plan(source)
    assert first['status']=='invalid'
    second=service._interpret_cad_construction_plan(source,component_repair_context=first)
    assert second['status']=='invalid'
    first_plan=first.get('plan') or first['rejected_plan']
    second_plan=second.get('plan') or second['rejected_plan']
    assert len({s['semantic']['object_id'] for s in second_plan['steps']})==4
    for a,b in zip(first_plan['steps'],second_plan['steps']):
        assert {k:v for k,v in a.items() if k!='semantic'}=={k:v for k,v in b.items() if k!='semantic'}
    third=service._interpret_cad_construction_plan(source,component_repair_context=second)
    assert third.get('acceptance_summary',{}).get('status')=='passed',third
    assert any(c['kind']=='complete_source_proof_replaces_model_bounds' for c in third['deterministic_repairs'])
    store=CreativeProjectStore(tmp_path/'projects.json')
    saved=commit_construction_interpretation(source,third,store=store)
    assert candidate_is_accepted(store.get(saved['project_id'])['variants'][0])


@pytest.mark.parametrize('mutation',['unknown_source','wrong_source_size','protected_target','valid_bounds','other_assertion'])
def test_source_proof_does_not_discard_protected_or_unproven_assertions(mutation):
    from app.cad_plan_component_repair import merge_component_repair
    from app.cad_construction import execute_construction_plan, construction_geometry_bounds
    source=REPAIR['original']['evidence_text'][0]
    payload=deepcopy(REPAIR['geometry_repair']);plan=deepcopy(payload['plan'])
    bound={'kind':'bounds_size','assertion_id':'old-bounds','target_ref':'assembly:capsule','width':5.85,'height':2.631862,'tolerance':.0005}
    if mutation=='unknown_source':source+='再画一个矩形。'
    if mutation=='wrong_source_size':source=source.replace('572厘米','582厘米')
    if mutation=='protected_target':bound['target_ref']='cap_a'
    if mutation=='other_assertion':bound={'kind':'entity_count','assertion_id':'old-count','target_ref':'assembly:capsule','equals':6}
    if mutation=='valid_bounds':
        b=construction_geometry_bounds(execute_construction_plan(plan)['geometries'])
        bound.update(width=(b['max_x']-b['min_x'])/1000,height=(b['max_y']-b['min_y'])/1000)
    plan['assertions'].append(bound)
    context={'plan':plan,'construction_error':{'assertion_id':'capsule-closed','details':{'affected_output_refs':['assembly:capsule']}}}
    resolutions=[]
    result=merge_component_repair(context,payload,source_text=source,resolutions=resolutions)
    assert bound in result['plan']['assertions'] and not resolutions
