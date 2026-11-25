from copy import deepcopy
import json
import math
from pathlib import Path
import pytest
from app.cad_vertex_acceptance import open_straight_path_requirements,verify_open_straight_path
from app.cad_length_units import planning_unit_contract
from app.cad_construction_interpreter import clarify_construction_request,interpret_construction_request
from app.cad_source_acceptance import verify_single_round_primitive
from app.cad_structure_contract import StructureContractError

DATA=json.loads((Path(__file__).parent/'fixtures/recorded_transfer_source_handoff.json').read_text(encoding='utf-8'))


def test_three_segment_contract_is_shared_with_planning_and_readiness(monkeypatch,tmp_path):
    from app.agent_service import RobotAgentService
    from app.creative_projects import CreativeProjectStore
    source=DATA['T4']['source'];path=open_straight_path_requirements(source)
    assert path['coverage']=='complete' and path['count']==3 and path['start_mm']==[380,-470]
    assert [r['length_mm'] for r in path['requirements']]==[1730,920,1370]
    assert [r['angle_deg'] for r in path['requirements']]==[-32,78,-41]
    planned=planning_unit_contract(source)['ordered_path']
    assert planned['start_plan_values']=={'mm':[380,-470],'m':[.38,-.47]}
    assert clarify_construction_request(source)['question_key']=='construction_scope'
    service=RobotAgentService(restore_pending_actions=False);store=CreativeProjectStore(tmp_path/'projects.json')
    monkeypatch.setattr('app.agent_service.get_creative_project_store',lambda:store)
    project=service._persist_clarification_requirements(source,{'question_key':'size'}, {'operation':'create'})
    assert project['missing_parameters']==[]
    assert project['requirements']['requirement_ledger']['sources'][0]['text']==source


@pytest.mark.parametrize('unit,scale',[('米',1000),('厘米',10),('毫米',1)])
def test_parameter_and_unit_variants_use_the_same_measurement(unit,scale):
    text=f'从(-12,9)出发画折线，先沿与x轴正向成19度的方向走27{unit}，再向左转61度接着画18{unit}，再向右转37度接着画13{unit}。三段连在一起，末端不连回起点，不加其他图形。坐标单位{unit}。'
    points=[{'x':-12*scale,'y':9*scale}]
    for length,angle in [(27,19),(18,80),(13,43)]:
        p=points[-1];a=math.radians(angle);points.append({'x':p['x']+length*scale*math.cos(a),'y':p['y']+length*scale*math.sin(a)})
    gs=[{'id':1,'type':'polyline','closed':False,'vertices':points}]
    assert verify_open_straight_path(text,gs)['coverage']=='complete'
    for p in gs[0]['vertices']:p['x']+=5
    with pytest.raises(StructureContractError):verify_open_straight_path(text,gs)
    assert 'ordered_path' not in planning_unit_contract(text+'另加一个圆。')


def test_recorded_bad_origin_is_still_rejected():
    row=DATA['T4'];result=interpret_construction_request(row['source'],lambda *_:deepcopy(row['payload']),force_structured_model=True)
    assert result.get('acceptance_summary',{}).get('status')!='passed'


def test_recorded_circle_paraphrase_reaches_formal_save(tmp_path):
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    from app.cad_candidate_state import candidate_is_accepted
    row=DATA['T3'];result=interpret_construction_request(row['source'],lambda *_:deepcopy(row['payload']),force_structured_model=True)
    assert result.get('acceptance_summary',{}).get('status')=='passed',result
    store=CreativeProjectStore(tmp_path/'projects.json')
    saved=commit_construction_interpretation(row['source'],result,store=store)
    assert candidate_is_accepted(store.get(saved['project_id'])['variants'][0])


@pytest.mark.parametrize('mutation',['radius','annotation','extra','unknown'])
def test_outline_scope_does_not_hide_geometry_or_unmeasured_requirements(mutation):
    text='画圆：圆心(10,-20)，直径180毫米。只要圆的轮廓，不要尺寸标注。坐标单位毫米。'
    gs=[{'id':1,'type':'circle','center':{'x':10,'y':-20},'radius':90}]
    proof=verify_single_round_primitive(text,gs)
    assert proof['coverage']=='complete'
    for i in proof['intent_evidence']:
        if 'source_text' in i:assert i['source_text'][i['start']:i['end']]==i['text']
    if mutation=='unknown':
        assert verify_single_round_primitive(text+'面积为5平方米。',gs)['coverage']=='partial';return
    if mutation=='radius':gs[0]['radius']=100
    elif mutation=='annotation':gs.append({'id':2,'type':'text','role':'annotation','text':'180'})
    else:gs.append({**deepcopy(gs[0]),'id':2})
    with pytest.raises(StructureContractError):verify_single_round_primitive(text,gs)
