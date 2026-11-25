from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.cad_plan_component_repair import normalize_component_repair_context,merge_component_repair

DATA=json.loads((Path(__file__).parent/'fixtures/recorded_full_segment_conflict.json').read_text(encoding='utf-8'))


def recorded_context():
    from app.cad_construction_interpreter import interpret_construction_request
    return interpret_construction_request(DATA['source'],lambda *_:deepcopy(DATA['payload']),force_structured_model=True)


def test_recorded_whole_conflict_is_forwarded_without_guessing_references():
    context=recorded_context();before=deepcopy(context)
    assert context['construction_error']['code']=='self_intersecting_composite_path'
    result=normalize_component_repair_context(context)
    details=result['construction_error']['details']
    assert details['requires_structural_replan'] is True
    assert details['structural_replan_evidence']['segment_indices']==[0,1,2,3]
    assert context==before and normalize_component_repair_context(result)==result


@pytest.mark.parametrize('mutation',['subset','protected','other_step','wrong_id','wrong_code','invalid_indices'])
def test_local_or_unproven_failures_cannot_escape_scope(mutation):
    context=recorded_context();details=context['construction_error']['details']
    if mutation=='subset':details['affected_segment_indices']=[0,1]
    elif mutation=='protected':details['local_repair_scope']={'editable_fields_by_ref':{}}
    elif mutation=='other_step':
        plan=context.get('plan') or context['rejected_plan']
        plan['steps'].append({'step_id':'protected','output_ref':'protected','op':'add_line'})
    elif mutation=='wrong_id':context['construction_error']['step_id']='missing'
    elif mutation=='wrong_code':context['construction_error']['code']='assertion_failed'
    else:details['affected_segment_indices']=[0,1,2,3,99]
    result=normalize_component_repair_context(context)
    assert not result['construction_error']['details'].get('requires_structural_replan')


def test_local_merger_still_rejects_decomposition_into_new_refs():
    context=recorded_context()
    payload={'plan':{'units':(context.get('plan') or context['rejected_plan'])['units'],
        'steps':[{'step_id':'new','output_ref':'new','op':'add_line'}]}}
    with pytest.raises(ValueError,match='原输出引用'):merge_component_repair(context,payload)


def test_production_repair_can_change_representation_and_commit(monkeypatch,tmp_path):
    import math
    from app.agent_service import RobotAgentService
    from app.creative_projects import CreativeProjectStore
    from app.cad_candidate_state import candidate_is_accepted
    a=math.radians(17)
    def p(x,y):return {'x':210+x*math.cos(a)-y*math.sin(a),'y':-370+x*math.sin(a)+y*math.cos(a)}
    parts=[{'op':'add_arc','center':p(-1270,0),'radius':465,'start_angle':107,'end_angle':287},
           {'op':'add_line','start':p(-1270,-465),'end':p(1270,-465)},
           {'op':'add_arc','center':p(1270,0),'radius':465,'start_angle':287,'end_angle':467},
           {'op':'add_line','start':p(1270,465),'end':p(-1270,465)}]
    for i,s in enumerate(parts):
        s.update(step_id=f'new-{i}',output_ref=f'new-{i}',semantic={'label':f'part-{i}','object_id':f'new-{i}','assembly_id':'replacement','assembly_label':'整体'})
    good={'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
          'confidence':.99,'evidence_text':[DATA['source']],'assumptions':[],
          'plan':{'units':'mm','steps':parts}}
    calls=[]
    def callback(text,schema):
        calls.append(text)
        return deepcopy(DATA['payload'] if len(calls)==1 else good)
    service=RobotAgentService(restore_pending_actions=False)
    service.mode='deepseek'
    monkeypatch.setattr(service,'_cad_construction_model_callback',lambda **kw:(callback,{'provider_attempted':True,'request_attempts':1}))
    store=CreativeProjectStore(tmp_path/'projects.json')
    monkeypatch.setattr('app.agent_service.get_creative_project_store',lambda:store)
    result=service._formal_cad_construction(DATA['source'],{'name':'drawing_design','operation':'create'},mode='advanced')
    assert len(calls)==2 and '后端部件合并协议' not in calls[1]
    assert result['ok'] and candidate_is_accepted(result['variant']),result


def test_failed_complete_request_without_clarification_returns_failure(monkeypatch,tmp_path):
    from app.agent_service import RobotAgentService
    from app.creative_projects import CreativeProjectStore
    service=RobotAgentService(restore_pending_actions=False)
    monkeypatch.setattr(service,'_interpret_cad_construction_plan',lambda *a,**kw:{
        'status':'invalid','provider_attempted':True,'error':{'code':'invalid_plan','message':'invalid geometry'}})
    store=CreativeProjectStore(tmp_path/'projects.json')
    monkeypatch.setattr('app.agent_service.get_creative_project_store',lambda:store)
    result=service._formal_cad_construction(DATA['source'],{'name':'drawing_design','operation':'create'},mode='advanced')
    assert result['ok'] is False and result['error_code']=='candidate_generation_failed'
    assert not result.get('variant') and not result.get('clarification')
