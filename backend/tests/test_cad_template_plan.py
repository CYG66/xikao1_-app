from copy import deepcopy
from unittest.mock import Mock, patch

import pytest

from app.agent_service import robot_agent
from app.cad_construction import ConstructionPlanError, execute_construction_plan
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_template_plan import template_plan_for_project, template_plan_from_text
from app.creative_projects import CreativeProjectStore


def test_articulated_parts_are_not_replaced_by_scalar_template():
    from app.cad_requirement_contract import requirement_contract
    text = '画一个L形走廊，宽1米，两条臂分别长3米和2米，直角连接'
    assert template_plan_from_text(text) is None
    contract = requirement_contract([{'source_id':'user-1','text':text}])
    width = next(f for f in contract['facts'] if f['field']=='width')
    assert width['status']=='unresolved'
    assert width['value_mm']==1000


def test_template_strategy_uses_ir_without_model():
    model = Mock(side_effect=AssertionError('template must not need LLM'))
    result = interpret_construction_request('画一个标准篮球场', model)
    assert result['status'] == 'ready'
    assert result['parser'] == 'parameterized_template'
    assert result['plan']['steps'][0]['op'] == 'add_template'
    assert result['trial_result']['feasibility']['ok']
    model.assert_not_called()


def test_confirmed_dimensions_override_original_template_size():
    plan = template_plan_for_project({'name': '篮球场', 'original_prompt': '标准篮球场',
        'requirements': {'shape': 'basketball', 'dimensions': {'width_m': 20, 'height_m': 10}}}, {})
    match = plan.steps[0].matches[0]
    assert (match.width_m, match.height_m) == (20, 10)
    trial = execute_construction_plan(plan)
    bounds = trial['logical_objects'][0]['bounds']
    assert bounds['max_x'] - bounds['min_x'] == 20000


def test_shared_parking_topology_survives_plan_execution():
    plan = template_plan_from_text('画三个标准停车位')
    trial = execute_construction_plan(plan)
    assert len(trial['logical_objects']) == 3
    assert len(trial['topology']['shared_geometries']) == 2
    assert trial['graph_validation']['verified']


def test_template_expansion_obeys_entity_budget():
    plan = template_plan_from_text('画一个标准篮球场').model_dump(mode='json')
    plan['budgets']['max_entities'] = 1
    with pytest.raises(ConstructionPlanError) as error:
        execute_construction_plan(plan)
    assert error.value.code == 'entity_budget_exceeded'


def test_multiple_template_steps_keep_unique_geometry_and_object_ids():
    plan = template_plan_from_text('画一个标准篮球场').model_dump(mode='json')
    other = deepcopy(plan['steps'][0])
    other.update(step_id='second', output_ref='second', origin={'x': 50000, 'y': 0}, rotation_deg=90)
    plan['steps'].append(other)
    trial = execute_construction_plan(plan)
    assert trial['graph_validation']['verified']
    assert len(trial['logical_objects']) == 2
    ids = [item['id'] for item in trial['geometries']]
    assert len(ids) == len(set(ids))
    second = trial['logical_objects'][1]['bounds']
    assert second['max_x'] - second['min_x'] == pytest.approx(15000)


def test_template_chat_and_toolbar_commit_same_project_once(tmp_path):
    store = CreativeProjectStore(tmp_path / 'projects.json')
    with patch('app.agent_service.get_creative_project_store', return_value=store), patch.object(
        robot_agent, '_structured_review_text', side_effect=AssertionError('LLM called')):
        result = robot_agent._formal_cad_construction('画一个标准篮球场',
            {'name': 'drawing_design', 'operation': 'create'}, mode='advanced')
        assert result['ok'] and result['preview_paths']
        project_id = result['project_id']
        variant = result['variant']
        assert variant['construction_record']['parser'] == 'parameterized_template'
        assert variant['construction_record']['plan']['steps'][0]['op'] == 'add_template'
        confirmed = robot_agent.generate_project_candidate(project_id)
        assert confirmed['ok'] and confirmed['project_id'] == project_id
        assert len(store.list()) == 1
        assert len(store.get(project_id)['variants']) == 1


def test_legacy_confirmation_also_records_plan(tmp_path):
    store = CreativeProjectStore(tmp_path / 'projects.json')
    project = store.create('标准篮球场划线', '绘制边线、端线、中圈、罚球线、罚球半圈和三分线',
                           {'shape': None, 'dimensions': {}}, {}, ['shape', 'dimensions'])
    with patch('app.agent_service.get_creative_project_store', return_value=store):
        robot_agent.reconcile_creative_projects(project['id'])
        result = robot_agent.generate_project_candidate(project['id'])
    assert result['ok'] and result['preview_paths']
    assert result['variant']['construction_record']['parser'] == 'parameterized_template'


def test_imported_template_snapshot_is_not_regenerated():
    assert template_plan_for_project({'name': '标准篮球场', 'requirements': {},
        'source_drawing': {'geometries': [{'id': 1}]}}, {}) is None


def test_local_template_adapter_uses_common_commit_without_auto_selection(tmp_path):
    from app.agent_skills import recognize_drawing_template
    store = CreativeProjectStore(tmp_path / 'projects.json')
    text = '画一个标准篮球场28x15米'
    with patch('app.agent_service.get_creative_project_store', return_value=store):
        result = robot_agent._local_template_intent(raw_message=text,
            match=recognize_drawing_template(text), allow_design=True)
    assert result['ok'] and result['preview_paths']
    assert result['variant']['construction_record']['parser'] == 'parameterized_template'
    assert result['project'].get('selected_variant_id') is None


def test_structured_model_can_emit_same_template_plan():
    text = '画一个标准篮球场'
    plan = template_plan_from_text(text).model_dump(mode='json')
    model = Mock(return_value={'schema_version':'cad.construction-interpretation.v1',
        'is_construction_request':True, 'plan':plan, 'evidence_text':[text], 'confidence':1.0})
    result = interpret_construction_request(text, model, force_structured_model=True)
    assert result['status'] == 'ready'
    assert result['parser'] == 'structured_model'
    assert result['trial_result']['graph_validation']['verified']
    model.assert_called_once()


@pytest.mark.parametrize('text', [
    '画一个标准篮球场，旁边再画一个半径1米的圆',
    '画一个标准篮球场，再画一个边长2米的正方形',
    '画一个标准篮球场和一个半径1米的圆',
    '画一个标准篮球场，旁边有一个半径1米的圆',
])
def test_partial_template_never_silently_succeeds(text):
    assert template_plan_from_text(text) is None
    result = interpret_construction_request(text)
    assert result['status'] != 'ready'
    assert not result.get('trial_result')
    callback = Mock(return_value={'schema_version':'cad.construction-interpretation.v1',
        'is_construction_request':True, 'plan':None, 'evidence_text':[text],
        'confidence':1, 'clarification':{'question_key':'size','question':'请说明额外图形的位置。'}})
    interpret_construction_request(text, callback)
    callback.assert_called_once()


def test_confirmed_template_position_and_rotation_are_executed():
    plan = template_plan_for_project({'name':'篮球场', 'original_prompt':'标准篮球场',
        'requirements':{'origin':{'x':10,'y':20}, 'rotation_deg':90}}, {})
    trial = execute_construction_plan(plan)
    bounds = trial['logical_objects'][0]['bounds']
    assert (bounds['min_x'] + bounds['max_x']) / 2 == pytest.approx(10000)
    assert (bounds['min_y'] + bounds['max_y']) / 2 == pytest.approx(20000)
    assert bounds['max_x'] - bounds['min_x'] == pytest.approx(15000)


def test_text_and_confirmed_project_share_position_parser():
    text = '画一个标准篮球场，中心(10,20)米，顺时针旋转90度'
    fresh = template_plan_from_text(text)
    confirmed = template_plan_for_project({'name':'篮球场','original_prompt':text,'requirements':{}}, {})
    assert fresh == confirmed
    assert fresh.steps[0].origin.x == 10000
    assert fresh.steps[0].rotation_deg == -90


def test_confirmed_position_overrides_original_and_mm_is_not_scaled_twice():
    plan = template_plan_for_project({'name':'篮球场','original_prompt':'标准篮球场，中心(10,20)米，旋转90度',
        'requirements':{'origin':{'x':100,'y':200,'units':'mm'},'rotation_deg':45}}, {})
    assert plan.steps[0].origin.x == 100
    assert plan.steps[0].rotation_deg == 45


def test_confirmation_failure_has_false_status_and_no_candidate(tmp_path):
    store = CreativeProjectStore(tmp_path/'projects.json')
    project = store.create('篮球场','标准篮球场',{'shape':'basketball',
        'layout_conflicts':['布局冲突']}, {}, [])
    with patch('app.agent_service.get_creative_project_store',return_value=store):
        result = robot_agent.generate_project_candidate(project['id'])
    assert result['ok'] is False
    assert not store.get(project['id'])['variants']


def test_mixed_template_confirmation_uses_model_not_template(tmp_path):
    store = CreativeProjectStore(tmp_path/'projects.json')
    text = '画一个标准篮球场，再画一个半径1米的圆'
    project = store.create('复合图纸',text,{'shape':'basketball','dimensions':{'width_m':28,'height_m':15}}, {}, [])
    with patch('app.agent_service.get_creative_project_store',return_value=store), patch.object(robot_agent,
        '_interpret_cad_construction_plan',return_value={'status':'invalid'}) as interpreter:
        result = robot_agent.generate_project_candidate(project['id'])
    interpreter.assert_called_once()
    assert '半径1米' in interpreter.call_args.args[0]
    assert result['ok'] is False
    assert not store.get(project['id'])['variants']


@pytest.mark.parametrize('stage', ['prepare', 'persist'])
def test_candidate_stage_failure_is_never_success(tmp_path, stage):
    store = CreativeProjectStore(tmp_path/'projects.json')
    project = store.create('篮球场','标准篮球场',{'shape':'basketball'}, {}, [])
    target = 'prepare_new_candidate' if stage == 'prepare' else 'persist_prepared_candidate'
    with patch('app.agent_service.get_creative_project_store',return_value=store), patch('app.agent_service.'+target,
        return_value={'ok':False,'message':'测试失败'}):
        result = robot_agent.generate_project_candidate(project['id'])
    assert result['ok'] is False
    assert result['message'] == '测试失败'
    assert not store.get(project['id'])['variants']


def test_latest_position_followup_is_used():
    plan = template_plan_for_project({'name':'篮球场','original_prompt':'标准篮球场，中心(1,2)米，旋转30度',
        'requirements':{'source_followups':['中心(3,4)米，旋转60度','中心(5,6)毫米，顺时针旋转90度']}}, {})
    assert plan.steps[0].origin.x == 5
    assert plan.steps[0].origin.y == 6
    assert plan.steps[0].rotation_deg == -90
