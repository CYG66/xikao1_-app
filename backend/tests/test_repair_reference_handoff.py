from copy import deepcopy
import json
from pathlib import Path
import pytest

from app.cad_plan_component_repair import normalize_component_repair_context,merge_component_repair
from app.cad_construction import CadConstructionPlan,execute_construction_plan,ConstructionPlanError
from app.cad_construction_interpreter import normalize_composite_path_connections_once

DATA=json.loads((Path(__file__).parent/'fixtures/recorded_repair_reference_handoff.json').read_text(encoding='utf-8'))


def test_recorded_assembly_scope_resolves_to_exact_original_components():
    context=deepcopy(DATA['component_context']);before=deepcopy(context)
    normalized=normalize_component_repair_context(context)
    refs=[s['output_ref'] for s in context['plan']['steps']]
    assert normalized['construction_error']['details']['affected_output_refs']==refs
    assert normalize_component_repair_context(normalized)==normalized
    merged=merge_component_repair(context,DATA['component_payload'])['plan']
    assert [s['output_ref'] for s in merged['steps']]==refs
    assert context==before
    # Reference resolution is not geometric acceptance; the recorded replacement
    # still has bad dimensions and must remain rejected by the normal executor.
    with pytest.raises(ConstructionPlanError):execute_construction_plan(merged)


@pytest.mark.parametrize('alias',['assembly:group','object:left','left'])
def test_exact_scope_aliases_preserve_unaffected_parts(alias):
    plan={'units':'m','steps':[{'step_id':name,'output_ref':name,'op':'add_line',
        'semantic':{'label':name,'object_id':name,'assembly_id':'group' if name!='protected' else 'other'},
        'start':{'x':i,'y':0},'end':{'x':i,'y':1}} for i,name in enumerate(['left','right','protected'])]}
    context={'plan':plan,'construction_error':{'details':{'affected_output_refs':[alias]}}}
    refs=['left','right'] if alias.startswith('assembly') else ['left']
    payload={'plan':{'units':'m','steps':[deepcopy(s) for s in plan['steps'] if s['output_ref'] in refs]}}
    for s in payload['plan']['steps']:s['end']['y']=2
    merged=merge_component_repair(context,payload)['plan']
    for old,new in zip(plan['steps'],merged['steps']):
        if old['output_ref'] not in refs:assert old==new
        else:assert new['end']['y']==2


def test_unknown_or_ambiguous_alias_is_not_guessed():
    context=deepcopy(DATA['component_context'])
    context['construction_error']['details']['affected_output_refs']=['assembly:missing']
    with pytest.raises(ValueError):normalize_component_repair_context(context)


def test_recorded_shared_points_are_resolved_before_arc_connection_checks():
    payload=deepcopy(DATA['shared_point_payload']);before=deepcopy(payload)
    repaired,changes=normalize_composite_path_connections_once(payload,'绘制闭合轮廓')
    assert payload==before
    assert any(c['kind']=='resolve_shared_points_before_connection_checks' for c in changes)
    CadConstructionPlan.model_validate(repaired['plan'])
    # Remaining wrong geometry is still rejected, rather than disguised as a
    # successful source delivery by the reference-evaluation fix.
    with pytest.raises(ConstructionPlanError):execute_construction_plan(repaired['plan'])


def test_shared_point_cycles_remain_invalid():
    payload=deepcopy(DATA['shared_point_payload'])
    payload['plan']['shared_points']['left_center']['x']='@left_center.x'
    with pytest.raises(ValueError,match='循环'):normalize_composite_path_connections_once(payload,'闭合轮廓')


def test_ambiguous_object_identity_cannot_expand_repair_scope():
    context=deepcopy(DATA['component_context'])
    for s in context['plan']['steps']:s['semantic']['object_id']='duplicate'
    context['construction_error']['details']['affected_output_refs']=['object:duplicate']
    with pytest.raises(ValueError,match='歧义'):normalize_component_repair_context(context)


def test_only_original_aggregate_assertion_can_be_corrected():
    context=deepcopy(DATA['component_context']);payload=deepcopy(DATA['component_payload'])
    failed=context['construction_error']['assertion_id']
    original=next(a for a in context['plan']['assertions'] if a['assertion_id']==failed)
    replacement={**deepcopy(original),'height':1975}
    payload['plan']['assertions']=[replacement]
    result=merge_component_repair(context,payload)['plan']
    assert next(a for a in result['assertions'] if a['assertion_id']==failed)==replacement
    assert [a for a in result['assertions'] if a['assertion_id']!=failed]==[
        a for a in context['plan']['assertions'] if a['assertion_id']!=failed]


def test_service_repair_prompt_uses_canonical_leaf_refs(monkeypatch):
    from app.agent_service import RobotAgentService
    service=RobotAgentService.__new__(RobotAgentService);service.mode='local'
    seen=[]
    def callback(source,schema):
        seen.append(source);return deepcopy(DATA['component_payload'])
    monkeypatch.setattr(service,'_cad_construction_model_callback',lambda **kw:(callback,{'provider_attempted':False,'request_attempts':0}))
    service._interpret_cad_construction_plan('生成一个自由封闭轮廓，宽2300毫米、高3150毫米',component_repair_context=DATA['component_context'])
    assert seen
    assert '"affected_output_refs": ["arch_wall_left", "arch_arc_top", "arch_wall_right", "arch_bottom"]' in seen[0]


@pytest.mark.parametrize('angle',[0,17,-31,90])
def test_tangent_direction_is_determined_by_connections_not_shape_name(angle):
    from evaluations.relation_pilot.cases import expected_entities
    from app.cad_connection_direction import resolve_tangent_arc_directions
    row={'family':'capsule_tangency','angle':angle,'unit':'毫米','length':4310,'height':1170,'origin':[-371,283]}
    entities=expected_entities(row)
    segments=[{'kind':g['type'],**{k:v for k,v in g.items() if k not in {'type','id'}}} for g in entities]
    for s in segments:
        if s['kind']=='arc':s['clockwise']=True
    step={'op':'add_composite_path','step_id':'p','output_ref':'p','semantic':{'label':'边界'},'closed':True,'segments':segments}
    original=deepcopy(step)
    changes=resolve_tangent_arc_directions(step,f'直线与圆弧相切，长轴相对x轴正向逆时针{angle}度')
    assert len(changes)==2
    for old,new in zip(original['segments'],step['segments']):
        assert {k:v for k,v in old.items() if k!='clockwise'}=={k:v for k,v in new.items() if k!='clockwise'}
    execute_construction_plan({'units':'mm','steps':[step]})
    for source in ['闭合轮廓','不要求相切','不相切','不平滑','相切，所有圆弧必须顺时针','相切，起始角为107度']:
        unchanged=deepcopy(original)
        assert resolve_tangent_arc_directions(unchanged,source)==[] and unchanged==original


def test_recorded_arc_direction_repair_preserves_geometric_design():
    from evaluations.production_contract_pilot import cases,oracle
    source=next(c['text'] for c in cases() if c['id']=='R2')
    row=next(c for c in cases() if c['id']=='R2')
    repaired,changes=normalize_composite_path_connections_once(deepcopy(DATA['shared_point_payload']),source)
    assert any(c['kind']=='resolve_source_tangent_arc_direction' for c in changes)
    diagnostic=deepcopy(repaired['plan']);diagnostic['assertions']=[]
    result=execute_construction_plan(diagnostic)
    assert oracle(row,result['geometries'])['passed']


def test_recorded_plan_reaches_source_delivery_after_generic_handoff_repairs(tmp_path):
    from evaluations.production_contract_pilot import cases,oracle
    from app.cad_construction_interpreter import interpret_construction_request
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    from app.cad_candidate_state import candidate_is_accepted
    row=next(c for c in cases() if c['id']=='R2');source=row['text']+'只生成预览，不执行小车。'
    payload=deepcopy(DATA['shared_point_payload']);payload['evidence_text']=[source]
    result=interpret_construction_request(source,lambda *_:deepcopy(payload),force_structured_model=True)
    assert result.get('acceptance_summary',{}).get('status')=='passed',result.get('construction_error') or result.get('source_acceptance')
    assert oracle(row,result['trial_result']['geometries'])['passed']
    assert any(r['kind']=='source_local_axis_proof_replaces_world_bounds' for r in result['deterministic_repairs'])
    store=CreativeProjectStore(tmp_path/'projects.json');saved=commit_construction_interpretation(source,result,store=store)
    assert candidate_is_accepted(store.get(saved['project_id'])['variants'][0])


@pytest.mark.parametrize('change',['unknown_source','wrong_source_size','unrelated_assertion'])
def test_local_frame_proof_cannot_hide_unproven_requirements_or_assertions(change):
    from evaluations.production_contract_pilot import cases
    from app.cad_construction_interpreter import normalize_explicit_outline_size_once
    source=next(c['text'] for c in cases() if c['id']=='R2')
    payload,_=normalize_composite_path_connections_once(deepcopy(DATA['shared_point_payload']),source)
    if change=='unknown_source':source+='，世界外包框宽度3470毫米'
    elif change=='wrong_source_size':source=source.replace('3470毫米','3570毫米')
    else:
        next(a for a in payload['plan']['assertions'] if a['kind']=='bounds_size')['width']=1234
    original=deepcopy(payload)
    result,repairs=normalize_explicit_outline_size_once(payload,source)
    assert result==original and not repairs
