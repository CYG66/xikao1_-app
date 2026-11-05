from app.cad_generation_recovery import (
    recovery_category, should_repair, recovery_record, bounded_repair_available,
)


def test_recovery_records_step_level_changes_without_claiming_geometric_equivalence():
    retained={'step_id':'good','output_ref':'good','op':'add_line'}
    before={'status':'invalid','plan':{'steps':[retained,{'output_ref':'bad','op':'add_polyline'},{'output_ref':'removed'}]}}
    after={'status':'ready','plan':{'steps':[retained,{'output_ref':'bad','op':'add_line'},{'output_ref':'new'}]}}
    diff=recovery_record('source',[before,after])['attempts'][1]['step_diff']
    assert diff['unchanged_refs']==['good'] and diff['modified_refs']==['bad']
    assert diff['added_refs']==['new'] and diff['removed_refs']==['removed']
import pytest


def test_partial_inventory_is_not_a_model_plan_repair():
    result={'status':'invalid','provider_attempted':True,'construction_error':{
        'code':'structure_requirement_failed','details':{
            'reason':'unverified_geometry','inventory_scope':'partial'}}}
    assert recovery_category(result)=='requirements_unverified'
    assert should_repair(result) is False
    result['construction_error']['details']={'reason':'extra_geometry','inventory_scope':'complete'}
    assert should_repair(result) is True


@pytest.mark.parametrize('code,category,repair',[
    ('invalid_model_output','model_plan_invalid',True),('sampling_error_exceeded','sampling_budget',True),
    ('constraint_conflict','constraint_conflict',True),('provider_timeout','network_failure',False),
    ('persistence_failed','persistence_failure',False)])
def test_retry_policy_distinguishes_failure_causes(code,category,repair):
    result={'status':'invalid','provider_attempted':True,'error':{'code':code}}
    assert recovery_category(result)==category
    assert should_repair(result)==repair


def test_repair_records_both_plans_without_altering_input():
    first={'status':'invalid','plan':{'steps':[1]},'error':{'code':'invalid_model_output'}}
    second={'status':'ready','plan':{'steps':[2]}}
    record=recovery_record('用户原文',[first,second])
    assert record['repair_count']==record['max_repairs']==1
    assert record['attempts'][0]['plan_sha256']!=record['attempts'][1]['plan_sha256']
    assert record['attempts'][1]['changed_plan_fields']==['steps']
    first['plan']['steps'].append(3)
    assert record['attempts'][0]['plan']=={'steps':[1]}
    assert record['background_job'] is None


def test_second_repair_requires_a_changed_plan_and_a_different_failure():
    first={'status':'invalid','provider_attempted':True,'plan':{'steps':[1]},
           'error':{'code':'assertion_failed','message':'部件A失败'}}
    progressed={'status':'invalid','provider_attempted':True,'plan':{'steps':[2]},
                'construction_error':{'code':'structure_requirement_failed','message':'部件B失败'}}
    repeated={'status':'invalid','provider_attempted':True,'plan':{'steps':[2]},
              'construction_error':{'code':'structure_requirement_failed','message':'部件B失败'}}
    assert bounded_repair_available([first]) is True
    assert bounded_repair_available([first,progressed]) is True
    assert bounded_repair_available([first,progressed,repeated]) is False


def test_service_performs_one_plan_repair_and_returns_both_failures(tmp_path):
    from unittest.mock import patch
    from app.agent_service import RobotAgentService
    from app.creative_projects import CreativeProjectStore
    service=RobotAgentService(restore_pending_actions=False)
    store=CreativeProjectStore(tmp_path/'projects.json')
    project=store.create('图案','生成图案',requirements={'shape':'generic_2d_cad','dimensions':{'width_m':5,'height_m':5}},missing_parameters=[])
    failed={'status':'invalid','provider_attempted':True,'error':{'code':'invalid_model_output','message':'计划格式错误'}}
    with patch('app.agent_service.get_creative_project_store',return_value=store),patch.object(service,'_interpret_cad_construction_plan',return_value=failed.copy()) as model:
        result=service._formal_cad_construction('生成图案，宽5米高5米',{'name':'drawing_design','operation':'create','stage':'candidate_generation','selected_project_id':project['id']},mode='advanced')
    assert model.call_count==2
    assert result['ok'] is False
    recovery=result['construction_interpretation']['recovery']
    assert recovery['repair_count']==1 and len(recovery['attempts'])==2
    assert not store.get(project['id'])['variants']


def test_one_repair_receives_geometry_and_identity_errors_and_keeps_all_parts(tmp_path):
    from unittest.mock import patch
    from copy import deepcopy
    from app.agent_service import RobotAgentService
    from app.creative_projects import CreativeProjectStore
    from app.cad_construction_interpreter import interpret_construction_request
    service=RobotAgentService(restore_pending_actions=False)
    store=CreativeProjectStore(tmp_path/'projects.json')
    source='新建CAD图纸，画两条竖直线，整体宽2米高1米，坐标单位米'
    project=store.create('两线',source,requirements={'shape':'generic_2d_cad','dimensions':{'width_m':2,'height_m':1}},missing_parameters=[])
    bad={'units':'m','steps':[{'op':'add_line','step_id':f's{i}','output_ref':f'r{i}',
        'semantic':{'label':f'线{i}','object_id':'outline','assembly_id':'whole','assembly_label':'图案'},
        'start':{'x':i,'y':0},'end':{'x':i,'y':1}} for i in (0,1)],
        'assertions':[{'kind':'bounds_size','assertion_id':'size','width':2,'height':1}]}
    calls=[]
    def interpret(text,**kwargs):
        calls.append(text);plan=deepcopy(bad)
        if len(calls)==2:
            assert 'identity_conflicts' in text and 'outline' in text
            assert 'source_steps' in text and 'r1' in text
            for step in plan['steps']:step['semantic'].pop('object_id')
            plan['steps'][1]['start']['x']=plan['steps'][1]['end']['x']=2
        result=interpret_construction_request(source,lambda *_:{
            'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
            'confidence':.99,'evidence_text':[source],'plan':plan},force_structured_model=True)
        result['provider_attempted']=True
        return result
    with patch('app.agent_service.get_creative_project_store',return_value=store),patch.object(service,'_interpret_cad_construction_plan',side_effect=interpret):
        result=service._formal_cad_construction(source,{'name':'drawing_design','operation':'create',
            'stage':'candidate_generation','selected_project_id':project['id']},mode='advanced')
    assert result['ok'] is True,result
    assert len(calls)==2
    variant=store.get(project['id'])['variants'][0]
    assert len(variant['geometries'])==2
    assert len({o['object_id'] for o in variant['logical_objects']})==2
    assert {o['assembly_id'] for o in variant['logical_objects']}=={'whole'}


@pytest.mark.parametrize('repair_confidence',[.72,.98])
def test_grounded_low_confidence_gets_one_structural_repair_without_lowering_gate(tmp_path,repair_confidence):
    from unittest.mock import patch
    from app.agent_service import RobotAgentService
    from app.creative_projects import CreativeProjectStore
    from app.cad_construction_interpreter import interpret_construction_request
    service=RobotAgentService(restore_pending_actions=False);store=CreativeProjectStore(tmp_path/'projects.json')
    source='生成一个大写字母A的轮廓，高3米宽2米，横笔在高度1.5米处'
    project=store.create('A',source,requirements={'shape':'generic_2d_cad','dimensions':{'width_m':2,'height_m':3}},missing_parameters=[])
    calls=[]
    def interpret(text,**kwargs):
        calls.append(text)
        if len(calls)==1:
            steps=[{'op':'add_polyline','step_id':'triangle','output_ref':'triangle','semantic':{'label':'A'},
                'vertices':[{'x':-1,'y':0},{'x':0,'y':3},{'x':1,'y':0}],'closed':True}]
        else:
            assert '三角区域' in text and source in text
            steps=[{'op':'add_line','step_id':f's{i}','output_ref':f'r{i}',
                'semantic':{'label':f'A笔画{i}','assembly_id':'A','assembly_label':'A'},
                'start':{'x':a[0],'y':a[1]},'end':{'x':b[0],'y':b[1]}}
                for i,(a,b) in enumerate([((-1,0),(0,3)),((0,3),(1,0)),((-.5,1.5),(.5,1.5))])]
        result=interpret_construction_request(source,lambda *_:{'schema_version':'cad.construction-interpretation.v1',
            'is_construction_request':True,'confidence':.72 if len(calls)==1 else repair_confidence,
            'evidence_text':[source],'plan':{'units':'m','steps':steps}},force_structured_model=True)
        result['provider_attempted']=True
        return result
    with patch('app.agent_service.get_creative_project_store',return_value=store),patch.object(service,'_interpret_cad_construction_plan',side_effect=interpret):
        result=service._formal_cad_construction(source,{'name':'drawing_design','operation':'create',
            'stage':'candidate_generation','selected_project_id':project['id']},mode='advanced')
    assert len(calls)==2
    restored=CreativeProjectStore(tmp_path/'projects.json').get(project['id'])
    assert restored['original_prompt']==source and not restored['missing_parameters']
    assert bool(restored['variants'])==(repair_confidence>=.75)
    assert result['ok']==(repair_confidence>=.75)
    if repair_confidence<.75:
        assert result['construction_interpretation']['recovery']['repair_count']==1
        assert result['construction_interpretation']['recovery']['attempts'][-1]['confidence']==.72


def test_confidence_number_only_change_does_not_unlock_candidate_save(tmp_path):
    from unittest.mock import patch
    from app.agent_service import RobotAgentService
    from app.creative_projects import CreativeProjectStore
    from app.cad_construction_interpreter import interpret_construction_request
    source='新建CAD图纸，画一条线段，从(0,0)到(1,1)，坐标单位米'
    service=RobotAgentService(restore_pending_actions=False);store=CreativeProjectStore(tmp_path/'projects.json')
    project=store.create('线段',source,requirements={'shape':'generic_2d_cad','dimensions':{'width_m':1,'height_m':1}},missing_parameters=[])
    calls=[]
    def interpret(text,**kwargs):
        calls.append(text)
        result=interpret_construction_request(source,lambda *_:{'schema_version':'cad.construction-interpretation.v1',
            'is_construction_request':True,'confidence':.72 if len(calls)==1 else .99,'evidence_text':[source],
            'plan':{'units':'m','steps':[{'op':'add_line','step_id':'line','output_ref':'line',
                'semantic':{'label':'线段'},'start':{'x':0,'y':0},'end':{'x':1,'y':1}}]}},force_structured_model=True)
        result['provider_attempted']=True
        return result
    with patch('app.agent_service.get_creative_project_store',return_value=store),patch.object(service,'_interpret_cad_construction_plan',side_effect=interpret):
        result=service._formal_cad_construction(source,{'name':'drawing_design','operation':'create',
            'stage':'candidate_generation','selected_project_id':project['id']},mode='advanced')
    assert len(calls)==2 and result['ok'] is False
    assert not store.get(project['id'])['variants']
    assert result['construction_interpretation']['error']['code']=='confidence_only_repair'
