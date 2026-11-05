from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, PropertyMock

import pytest

from app.agent_service import RobotAgentService
from app.agent_skills import parameterize_design
from app.conversation_memory import ConversationMemoryStore
from app.creative_projects import CreativeProjectStore
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_project_candidates import normalize_design_requirements


def test_explicit_arc_and_straight_lengths_resolve_old_curve_question(tmp_path):
    store = CreativeProjectStore(tmp_path / 'projects.json')
    project = store.create('复合边界', '生成半圆拱门，宽2米高3米',
        requirements={'shape': 'generic_2d_cad', 'dimensions': {'width_m': 2, 'height_m': 3},
                      'curve_constraints': 'pending'}, missing_parameters=['curve_constraints'])
    service = RobotAgentService(restore_pending_actions=False)
    with patch('app.agent_service.get_creative_project_store', return_value=store):
        service._apply_design_requirement_followup(
            '顶部半圆半径1米，两侧直墙各长2米，底边闭合，整体宽2米高3米。',
            {'selected_project_id': project['id']})
    restored = CreativeProjectStore(tmp_path / 'projects.json').get(project['id'])
    assert 'curve_constraints' not in restored['missing_parameters']
    assert restored['requirements']['curve_constraints']['status'] == 'specified'


def test_confirmation_with_preview_suffix_keeps_existing_design_context():
    service = RobotAgentService(restore_pending_actions=False)
    text = "确认需求并生成CAD候选，只预览，不执行小车。"
    route = service._design_generation_confirmation_followup_route(text, "advanced", [])
    assert route["decision_source"] == "design_confirmation_followup"
    assert not service._is_design_generation_confirmation("确认生成一个圆和一个矩形")


@pytest.mark.parametrize('streaming',[False,True])
def test_partial_revision_before_first_candidate_survives_restart_without_history(tmp_path,streaming):
    path=tmp_path/'projects.json'
    store=CreativeProjectStore(path)
    original='生成一个由三个圆组成的图案。外圆：圆，圆心(0,0)，半径1米，坐标单位米；左眼：圆，圆心(-0.35,0.35)，半径0.09米，坐标单位米；右眼：圆，圆心(0.35,0.35)，半径0.09米，坐标单位米'
    project=store.create('三圆',original,requirements={'shape':'generic_2d_cad','dimensions':{'radius_m':1}},missing_parameters=[])
    service=RobotAgentService(restore_pending_actions=False)
    route={'name':'drawing_design','mode':'advanced','operation':'modify','selected_project_id':project['id']}
    with patch('app.agent_service.get_creative_project_store',return_value=CreativeProjectStore(path)),patch.object(service,'_run_advanced_cad_pipeline') as pipeline:
        if streaming:
            result=list(service._chat_stream_impl('左眼半径改为12厘米',[],mode='advanced',route=route))[-1]
        else:
            result=service._chat_impl('左眼半径改为12厘米',[],mode='advanced',route=route)
        pipeline.assert_not_called()
    assert result['project_id']==project['id']
    restored=CreativeProjectStore(path).get(project['id'])
    assert restored['original_prompt']==original
    assert restored['requirements']['source_followups']==['左眼半径改为12厘米']
    contract=restored['requirements']['requirement_ledger']['requirement_contract']
    latest=[f for f in contract['facts'] if f['status']=='effective' and f['subject']=='左眼']
    assert latest[0]['value_mm']==120
    assert len(CreativeProjectStore(path).list())==1


def test_new_creation_does_not_become_old_project_parameter_followup(tmp_path):
    store=CreativeProjectStore(tmp_path/'projects.json')
    old=store.create('旧项目','画一个圆',requirements={'shape':'circle'},missing_parameters=['dimensions'])
    with patch('app.agent_service.get_creative_project_store',return_value=store):
        assert RobotAgentService(restore_pending_actions=False)._apply_design_requirement_followup(
            '生成一个爱心，宽4米高4米',{'selected_project_id':old['id']}) is None
    assert 'source_followups' not in store.get(old['id'])['requirements']


def test_legacy_confirmation_delegates_to_production_entry(tmp_path):
    store=CreativeProjectStore(tmp_path/'projects.json')
    project=store.create('矩形','画一个矩形',requirements={'shape':'rectangle','dimensions':{'width_m':5,'height_m':3}},missing_parameters=[])
    service=RobotAgentService(restore_pending_actions=False)
    expected={'ok':True,'project_id':project['id'],'preview_paths':[]}
    with patch('app.agent_service.get_creative_project_store',return_value=store),patch.object(service,'_formal_cad_construction',return_value=expected) as production:
        result=service._deterministic_design_confirmation('确认生成',{'selected_project_id':project['id']})
    assert result is expected
    assert production.call_count==1
    assert production.call_args.args[1]['operation']=='create'
    assert production.call_args.args[1]['selected_project_id']==project['id']


def test_confirmation_preflight_blocks_incomplete_requirements_before_model(tmp_path):
    store=CreativeProjectStore(tmp_path/'projects.json')
    project=store.create('图案','画一个自定义图案',requirements={'shape':'generic_2d_cad'},missing_parameters=['dimensions'])
    service=RobotAgentService(restore_pending_actions=False)
    with patch('app.agent_service.get_creative_project_store',return_value=store),patch.object(service,'_interpret_cad_construction_plan') as model:
        result=service.generate_project_candidate(project['id'])
        model.assert_not_called()
    assert result['ok'] is False
    assert result['error_code']=='candidate_requirements_incomplete'
    assert store.get(project['id'])['variants']==[]


def test_confirmation_without_project_does_not_invent_a_design():
    service=RobotAgentService(restore_pending_actions=False)
    with patch.object(service,'_interpret_cad_construction_plan') as model:
        result=service._deterministic_design_confirmation('确认生成',{})
        model.assert_not_called()
    assert result['ok'] is False


def test_model_unavailable_preserves_confirmed_project_without_confirmation_loop(tmp_path):
    from copy import deepcopy
    store=CreativeProjectStore(tmp_path/'projects.json')
    project=store.create('拱门','半圆拱门 宽2米高3米',
        requirements={'shape':'closed_semicircular_arch','dimensions':{'width_m':2,'height_m':3}},missing_parameters=[])
    before=deepcopy(store.get(project['id']))
    service=RobotAgentService(restore_pending_actions=False)
    with patch('app.agent_service.get_creative_project_store',return_value=store),patch.object(service,'_cad_construction_model_callback',
            return_value=(None,{'provider_attempted':False,'request_attempts':0})):
        result=service.generate_project_candidate(project['id'])
        repeated=service.generate_project_candidate(project['id'])
    assert result['ok'] is False
    assert result['error_code']=='construction_model_unavailable'
    assert repeated['error_code']==result['error_code']
    assert result['retryable'] is True
    assert 'clarification' not in result
    assert store.get(project['id'])==before
    assert len(store.list())==1


@pytest.mark.parametrize('original_has_size',[True,False])
def test_nested_crossbar_height_cannot_override_whole_letter_height(tmp_path,original_has_size):
    store=CreativeProjectStore(tmp_path/'projects.json')
    project=store.create('A','生成一个大写字母A的轮廓'+('，高3米宽2米' if original_has_size else ''),
        requirements={'shape':'generic_2d_cad','dimensions':{'width_m':2,'height_m':3} if original_has_size else {}},
        missing_parameters=[] if original_has_size else ['dimensions'])
    followup='字母A总高3米、总宽2米，两斜笔端点(-1,0)(0,3)(1,0)，横笔在高度1.5米处，坐标单位米。'
    service=RobotAgentService(restore_pending_actions=False)
    with patch('app.agent_service.get_creative_project_store',return_value=store):
        result=service._apply_design_requirement_followup(followup,{'selected_project_id':project['id']})
    assert result['requirements']['dimensions']['height_m']==3
    assert result['requirements']['dimensions']['width_m']==2
    assert 'height_m=1.5' not in result['message']
    assert followup in result['requirements']['source_followups']
    legacy=store.get(project['id']);legacy['requirements']['dimensions']['height_m']=1.5
    prompt=service._project_construction_prompt(legacy)
    assert '高度3.0米' in prompt
    assert '高度1.5米处' in prompt


@pytest.mark.parametrize('missing',[['curve_constraints'],[]])
def test_non_size_parameter_answer_reuses_unfinished_creation_project(missing):
    from app.cad_construction import execute_construction_plan
    service=RobotAgentService(restore_pending_actions=False)
    answer='二维等轴投影，三个投影轴夹角120度，棱长2米'
    trial=execute_construction_plan({'units':'m','steps':[{
        'op':'add_line','step_id':'edge','output_ref':'edge','semantic':{'label':'投影棱线'},
        'start':{'x':0,'y':0},'end':{'x':2,'y':0}}]})
    with TemporaryDirectory() as folder:
        store=CreativeProjectStore(Path(folder)/'projects.json')
        project=store.create('投影','画一个立方体的透视轮廓，边长2米',
            requirements={'shape':'generic_2d_cad'},missing_parameters=missing)
        with patch('app.agent_service.get_creative_project_store',return_value=store),patch.object(
            service,'_interpret_cad_construction_plan',return_value={
                'schema':'cad.construction-interpretation-result.v1','status':'ready','trial_result':trial}) as model:
            result=service._formal_cad_construction(answer,{'name':'drawing_design','operation':'create',
                'selected_project_id':project['id'],'user_message':answer},mode='advanced')
        assert result.get('project_id')==project['id'], result
        assert len(store.list())==1
        assert answer in store.get(project['id'])['requirements']['source_followups']
        assert project['original_prompt'] in model.call_args.args[0]


def test_followup_retains_component_coordinates_not_only_global_dimensions():
    service = RobotAgentService(restore_pending_actions=False)
    prompt = "画一个矩形灯箱，里面有三个圆"
    supplement = "灯箱宽1米、高3米；三个圆半径0.35米，圆心分别为(0.5,2.4)、(0.5,1.5)、(0.5,0.6)，坐标单位米"
    with TemporaryDirectory() as folder:
        store = CreativeProjectStore(Path(folder)/"projects.json")
        project = store.create("灯箱", prompt, requirements={"shape":"generic_2d_cad"}, missing_parameters=["dimensions"])
        with patch("app.agent_service.get_creative_project_store", return_value=store):
            service._apply_design_requirement_followup(supplement, {"selected_project_id":project["id"]})
            updated = store.get(project["id"])
            assert supplement in service._project_construction_prompt(updated)
            with patch.object(service, "_interpret_cad_construction_plan", return_value={"status":"invalid"}) as constructor:
                service.generate_project_candidate(project["id"])
            assert supplement in constructor.call_args.args[0]


def test_new_local_creation_does_not_overwrite_selected_old_project():
    service=RobotAgentService(restore_pending_actions=False)
    with TemporaryDirectory() as folder:
        store=CreativeProjectStore(Path(folder)/"projects.json")
        old=store.create("国旗","生成一个五星红旗",requirements={"shape":"generic_2d_cad"},missing_parameters=["shape"])
        text="生成一个爱心和一个五角星，它们的长宽均为5米"
        with patch("app.agent_service.get_creative_project_store",return_value=store):
            new=service._persist_clarification_requirements(text,{
                "question_key":"construction_scope","recognized_shape":"轮廓","recognized_size":True},
                {"operation":"create","stage":"requirements","selected_project_id":old["id"]})
        assert new["id"]!=old["id"]
        assert store.get(old["id"])["original_prompt"]=="生成一个五星红旗"
        assert store.get(old["id"])["missing_parameters"]==["shape"]


def test_supported_primitive_cannot_reduce_compound_project_on_confirmation():
    from app.cad_construction import execute_construction_plan
    service=RobotAgentService(restore_pending_actions=False)
    trial = execute_construction_plan({'units':'m', 'steps':[
        {'op':'add_circle', 'step_id':'a', 'output_ref':'a', 'semantic':{'label':'左圆'},
         'center':{'x':0,'y':0}, 'radius':1},
        {'op':'add_circle', 'step_id':'b', 'output_ref':'b', 'semantic':{'label':'右圆'},
         'center':{'x':1.5,'y':0}, 'radius':1}]})
    with TemporaryDirectory() as folder:
        store=CreativeProjectStore(Path(folder)/"projects.json")
        project=store.create("双圆", "画一个由两个相交圆组成的眼镜轮廓，两圆心距离1.5米",
                             requirements={"shape":"circle","dimensions":{"radius_m":1}},missing_parameters=[])
        with patch("app.agent_service.get_creative_project_store",return_value=store), patch.object(
            service,"_interpret_cad_construction_plan",return_value={
                "schema":"cad.construction-interpretation-result.v1", "status":"ready", "trial_result":trial}
        ) as constructor:
            result=service.generate_project_candidate(project["id"])
    assert len(result["preview_paths"])==2
    assert "半径1米" in constructor.call_args.args[0]
    assert result["project_id"]==project["id"]
    assert len(store.get(project["id"])["variants"]) == 1


@pytest.mark.parametrize("name", ["企鹅标志", "蝴蝶", "齿轮"])
def test_model_named_object_clarification_preserves_object_and_requests_size(name):
    text = f"生成一个{name}，大小按照目前标准"
    payload = {"schema_version": "cad.construction-interpretation.v1",
        "is_construction_request": True, "plan": None, "evidence_text": [text],
        "confidence": .95, "clarification": {"question_key": "standard_spec",
            "question": "请指定具体规格或实际宽高。", "recognized_shape": name}}
    interpretation = interpret_construction_request(text, model_callback=lambda *_: payload)
    assert interpretation["status"] == "clarification_required"
    service = RobotAgentService(restore_pending_actions=False)
    with TemporaryDirectory() as folder:
        store = CreativeProjectStore(Path(folder)/"projects.json")
        with patch("app.agent_service.get_creative_project_store", return_value=store), patch.object(
            service, "_interpret_cad_construction_plan", return_value={**interpretation, "provider_attempted": True}
        ):
            result = service._formal_cad_construction(
                text, {"name": "drawing_design", "operation": "create"}, mode="advanced")
    assert result["clarification"]["question_key"] == "standard_spec"
    assert result["project"]["missing_parameters"] == ["dimensions"]
    assert result["project"]["requirements"]["shape"] == name
    assert "请指定具体规格" in result["message"]
    assert "你要生成什么图形" not in result["message"]


def test_model_clarification_rejects_invented_object():
    text = "生成一个齿轮"
    payload = {"schema_version": "cad.construction-interpretation.v1",
        "is_construction_request": True, "plan": None, "evidence_text": [text],
        "confidence": .95, "clarification": {"question_key": "size",
            "question": "请补尺寸", "recognized_shape": "蝴蝶"}}
    result = interpret_construction_request(text, model_callback=lambda *_: payload)
    assert result["error"]["code"] == "ungrounded_model_output"


def test_standard_details_question_does_not_mark_existing_dimensions_missing():
    text = "生成五星红旗，实际宽度3米、高度2米"
    service = RobotAgentService(restore_pending_actions=False)
    clarification = {"question_key": "standard_spec", "question": "请确认采用的制图规格",
                     "recognized_shape": "五星红旗", "recognized_size": True}
    with TemporaryDirectory() as folder:
        store = CreativeProjectStore(Path(folder)/"projects.json")
        with patch("app.agent_service.get_creative_project_store", return_value=store):
            project = service._persist_clarification_requirements(text, clarification, {})
    assert project["missing_parameters"] == ["standard_spec"]
    assert project["requirements"]["dimensions"]["width_m"] == 3
    assert project["requirements"]["dimensions"]["height_m"] == 2


@pytest.mark.parametrize("failure_status", ["clarification_required", "invalid"])
def test_grounded_model_failure_does_not_invent_missing_shape_or_printer(failure_status) -> None:
    service = RobotAgentService(restore_pending_actions=False)
    message = "生成一个阿基米德螺旋线，从(0,0)出发，旋转3圈，最大半径2米"
    failure = {
        "status": failure_status, "provider_attempted": True,
        "construction_request_recognized": failure_status == "clarification_required",
        "error": {"code": "low_confidence", "message": "模型构造置信度不足"},
    }
    with TemporaryDirectory() as folder:
        store = CreativeProjectStore(Path(folder) / "projects.json")
        with patch("app.agent_service.get_creative_project_store", return_value=store), patch.object(
            service, "_interpret_cad_construction_plan", return_value=failure
        ):
            result = service._formal_cad_construction(
                message, {"name": "drawing_design", "operation": "create"}, mode="advanced"
            )
    assert result["ok"] is False
    assert result["error_code"] == "candidate_generation_failed"
    assert result["project"]["original_prompt"] == message
    assert result["project"]["missing_parameters"] == []
    assert "你要生成什么图形" not in result["message"]
    assert "喷码机" not in result["message"]


def test_truncated_provider_json_is_reported_explicitly() -> None:
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"
    with patch.object(RobotAgentService, "configured", new_callable=PropertyMock, return_value=True), patch.object(service, "_deepseek_request", return_value={
        "choices": [{"finish_reason": "length", "message": {"content": ""}}],
    }):
        with pytest.raises(RuntimeError, match="max_tokens=16384"):
            service._structured_review_text([], mode="advanced", max_tokens_override=16384)


def test_reasoning_stream_collects_only_final_json() -> None:
    import io
    import json
    chunks = [
        {"choices": [{"delta": {"reasoning_content": "private reasoning"}}]},
        {"choices": [{"delta": {"content": '{"plan":'}}]},
        {"choices": [{"delta": {"content": 'null}'}, "finish_reason": "stop"}]},
    ]
    response = io.BytesIO(("".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode())
    response.status = 200
    service = RobotAgentService(restore_pending_actions=False)
    with patch.object(service, "_deepseek_response", return_value=(None, response)) as request:
        result = service._deepseek_request([], tools=[], stream_structured=True, json_output=True)
    assert request.call_args.args[0]["stream"] is True
    assert request.call_args.args[0]["response_format"] == {"type": "json_object"}
    assert result["choices"][0]["message"]["content"] == '{"plan":null}'
    assert result["choices"][0]["finish_reason"] == "stop"
    assert response.closed


def test_reasoning_truncation_retries_same_schema_with_json_model() -> None:
    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"
    with patch.object(RobotAgentService, "configured", new_callable=PropertyMock, return_value=True), patch.object(service, "_model_for_agent_mode", return_value="deepseek-reasoner"), patch.object(service, "_deepseek_request", side_effect=[
        {"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": '{"plan":null}'}}]},
    ]) as request:
        messages = [{"role": "user", "content": "strict schema"}]
        assert service._structured_review_text(messages, mode="advanced", max_tokens_override=4096) == '{"plan":null}'
        assert request.call_count == 2
        assert request.call_args.args[0] == messages
        assert request.call_args.kwargs["model_override"] == "deepseek-chat"
        assert request.call_args.kwargs["tools"] == []
        assert all(call.kwargs["json_output"] is True for call in request.call_args_list)


def test_free_outline_is_not_a_missing_shape_when_no_template_exists() -> None:
    prompt = "画一朵花的轮廓，5片花瓣，闭合曲线"
    parsed = parameterize_design(prompt)
    requirements, missing = normalize_design_requirements(parsed, prompt)
    assert requirements["shape"] == "generic_2d_cad"
    assert missing == ["dimensions"]
    assert requirements["dimensions"] == {}


def test_model_project_tool_keeps_free_outline_and_accepts_size_followup() -> None:
    prompt = "画一朵花的轮廓，5片花瓣，闭合曲线"
    with TemporaryDirectory() as directory:
        store = CreativeProjectStore(Path(directory) / "projects.json")
        service = RobotAgentService(restore_pending_actions=False)
        with patch("app.agent_service.get_creative_project_store", return_value=store):
            created = service._execute_safe("create_creative_project", {
                "name": "五瓣花轮廓", "prompt": prompt, "constraints": {},
            }, mode="advanced")
            assert created["ok"] is True, created
            project = created["project"]
            assert project["missing_parameters"] == ["dimensions"]
            assert project["original_prompt"] == prompt
            response = service._result("项目已创建", service._empty_usage(), tool_results=[
                service._tool_result_summary("create_creative_project", created)
            ])
            assert response["project_id"] == project["id"]
            assert response["project"]["id"] == project["id"]
            updated = service._apply_design_requirement_followup("宽高为5m", {
                "mode": "advanced", "selected_project_id": project["id"],
            })
            assert updated["project"]["status"] == "ready_for_design"
            assert updated["missing_parameters"] == []
            assert updated["requirements"]["shape"] == "generic_2d_cad"
            # Confirmation must enter the structured construction producer,
            # rather than grow a shape-specific template or generator.
            with patch.object(service, "_interpret_cad_construction_plan", return_value={
                "status": "failed", "error": {"message": "model unavailable"},
                "provider_attempted": True,
            }) as construct:
                result = service._pending_design_followup(raw_message="确认", route={
                    "selected_project_id": project["id"],
                })
            assert construct.call_count == 1
            assert "5片花瓣" in construct.call_args.args[0]
            assert "宽度5.0米" in construct.call_args.args[0]
            assert result["ok"] is False
            assert "shape" not in store.get(project["id"])["missing_parameters"]


def test_dense_closed_curve_is_not_misclassified_as_self_intersecting() -> None:
    import math
    from app.cad_construction import ConstructionPoint, _self_intersection_count

    points = [ConstructionPoint(x=2.5 * math.cos(i * math.tau / 256),
                                y=2.5 * math.sin(i * math.tau / 256)) for i in range(256)]
    assert _self_intersection_count(list(zip(points, points[1:] + points[:1])), closed=True, tolerance=0.001) == 0
    crossing = [ConstructionPoint(x=x, y=y) for x, y in [(0, 0), (1, 1), (0, 1), (1, 0)]]
    assert _self_intersection_count(list(zip(crossing, crossing[1:] + crossing[:1])), closed=True, tolerance=0.001) == 1


def test_confirmed_custom_outline_generates_from_latest_dimensions() -> None:
    import math

    captured = []
    def interpret(message, **kwargs):
        captured.append(message)
        vertices = []
        for index in range(200):
            angle = 2 * math.pi * index / 200
            radius = 2 + 0.5 * math.cos(5 * angle)
            vertices.append({"x": radius * math.cos(angle), "y": radius * math.sin(angle)})
        result = interpret_construction_request(message, lambda *_: {
            "schema_version": "cad.construction-interpretation.v1",
            "is_construction_request": True,
            "plan": {
                "schema_version": "cad.construction-plan.v1", "units": "m",
                "steps": [{"op": "add_polyline", "step_id": "outline",
                           "output_ref": "outline", "layer_id": 1,
                           "semantic": {"object_type": "outline", "label": "五瓣轮廓"},
                           "vertices": vertices, "closed": True}],
                "assertions": [{"kind": "closed", "assertion_id": "closed", "target_ref": "outline"}],
            },
            "confidence": 0.95, "evidence_text": ["5片花瓣", "闭合曲线"], "assumptions": [],
        }, force_structured_model=True)
        assert result["status"] == "ready", result
        return result

    with TemporaryDirectory() as directory:
        store = CreativeProjectStore(Path(directory) / "projects.json")
        project = store.create("五瓣轮廓", "画一朵花的轮廓，5片花瓣，闭合曲线",
                               {"shape": "generic_2d_cad", "dimensions": {"width_m": 5, "height_m": 5}}, {}, [])
        service = RobotAgentService(restore_pending_actions=False)
        with patch("app.agent_service.get_creative_project_store", return_value=store), patch.object(service, "_interpret_cad_construction_plan", side_effect=interpret):
            result = service.generate_project_candidate(project["id"])
            response = service._result("已生成", service._empty_usage(), tool_results=[{
                "ok": True, "project_id": result["project_id"], "variant_id": result["variant"]["id"],
            }])
            assert response["project"]["id"] == result["project_id"]
            assert response["variant"]["id"] == result["variant"]["id"]
            assert response["preview_paths"]
        assert "宽度5米" in captured[0]
        assert "高度5米" in captured[0]
        assert result["ok"] is True, result
        assert result["project_id"] == project["id"]
        assert store.get(project["id"]) is not None
        assert len(store.list()) == 1
        assert result["variant"]["geometries"]
        from app.cad_construction import construction_geometry_bounds
        bounds = construction_geometry_bounds(result["variant"]["geometries"])
        assert bounds["max_x"] - bounds["min_x"] == pytest.approx(5000, abs=1)
        assert bounds["max_y"] - bounds["min_y"] == pytest.approx(5000, abs=1)
        assert result["preview_paths"]
        assert result["project"]["status"] == "designing"


def test_failed_custom_construction_preserves_confirmed_requirements() -> None:
    with TemporaryDirectory() as directory:
        store = CreativeProjectStore(Path(directory) / "projects.json")
        project = store.create("五瓣轮廓", "画一朵花，5片花瓣，闭合曲线",
                               {"shape": "generic_2d_cad", "dimensions": {"width_m": 5, "height_m": 5}}, {}, [])
        service = RobotAgentService(restore_pending_actions=False)
        with patch("app.agent_service.get_creative_project_store", return_value=store), patch.object(service, "_interpret_cad_construction_plan", return_value={
            "status": "failed", "error": {"message": "provider timeout"}, "provider_attempted": True,
        }) as model:
            result = service.generate_project_candidate(project["id"])
        assert result["ok"] is False
        assert model.call_count == 1
        assert store.get(project["id"])["missing_parameters"] == []
        assert store.get(project["id"])["requirements"] == project["requirements"]
        assert result["construction_interpretation"]["error"]["message"] == "provider timeout"


def test_plain_confirmation_runs_candidate_generation() -> None:
    with TemporaryDirectory() as directory:
        store = CreativeProjectStore(Path(directory) / "projects.json")
        project = store.create("自定义轮廓", "新建闭合轮廓", {"shape": "generic_2d_cad"}, {}, [])
        service = RobotAgentService(restore_pending_actions=False)
        expected = {"ok": True, "preview_paths": [{"points": []}]}
        with patch("app.agent_service.get_creative_project_store", return_value=store), patch.object(service, "generate_project_candidate", return_value=expected) as generate:
            result = service._pending_design_followup(raw_message="确认", route={"selected_project_id": project["id"]})
        assert result == expected
        generate.assert_called_once_with(project["id"])


def test_invalid_plan_has_only_one_controlled_retry() -> None:
    with TemporaryDirectory() as directory:
        store = CreativeProjectStore(Path(directory) / "projects.json")
        project = store.create("自定义轮廓", "新建闭合轮廓", {"shape": "generic_2d_cad", "dimensions": {"width_m": 5}}, {}, [])
        service = RobotAgentService(restore_pending_actions=False)
        rejected_plan = {"schema_version": "cad.construction-plan.v1", "units": "m", "steps": []}
        failure = {"status": "invalid", "provider_attempted": True, "error": {"message": "self intersection"},
                   "plan": rejected_plan}
        with patch("app.agent_service.get_creative_project_store", return_value=store), patch.object(service, "_interpret_cad_construction_plan", return_value=failure.copy()) as model:
            result = service.generate_project_candidate(project["id"])
        assert result["ok"] is False
        assert model.call_count == 2
        assert "self intersection" in model.call_args.args[0]
        assert '"schema_version": "cad.construction-plan.v1"' in model.call_args.args[0]


def test_parameter_only_width_height_answer_is_parsed() -> None:
    parsed = parameterize_design("宽高为4m")

    assert parsed["dimensions"] == {"width_m": 4.0, "height_m": 4.0}
    assert "dimensions" not in parsed["missing"]


@pytest.mark.parametrize("streaming", [False, True])
def test_selected_project_dimension_reply_precedes_general_clarification(streaming) -> None:
    with TemporaryDirectory() as directory:
        store = CreativeProjectStore(Path(directory) / "projects.json")
        project = store.create("轮廓", "画一朵花的轮廓，5片花瓣，闭合曲线",
                               {"shape": "generic_2d_cad"}, {}, ["dimensions"])
        service = RobotAgentService(restore_pending_actions=False)
        route = {"name": "clarification", "operation": "query", "mode": "advanced",
                 "decision_source": "model_clarification", "clarification_required": True,
                 "clarification_question": "请明确操作", "selected_project_id": project["id"]}
        with patch("app.agent_service.get_creative_project_store", return_value=store):
            if streaming:
                result = list(service.chat_stream("宽度5米，高度5米", [], mode="advanced", route=route))[-1]
            else:
                result = service.chat("宽度5米，高度5米", [], mode="advanced", route=route)
        assert result["ok"] is True
        assert store.get(project["id"])["missing_parameters"] == []
        assert store.get(project["id"])["requirements"]["dimensions"] == {"width_m": 5, "height_m": 5}


def test_parameter_only_single_dimension_is_parsed() -> None:
    assert parameterize_design("宽度为4m")["dimensions"] == {"width_m": 4.0}
    assert parameterize_design("高度为3m")["dimensions"] == {"height_m": 3.0}


def test_parameter_only_answer_merges_into_active_project() -> None:
    with TemporaryDirectory() as directory:
        store = CreativeProjectStore(Path(directory) / "projects.json")
        project = store.create(
            "对称爱心轮廓 CAD 图纸",
            "绘制一个对称爱心轮廓，闭合，中心在原点",
            {
                "shape": "heart_outline",
                "printer": "center",
                "closed": True,
                "symmetric": True,
            },
            {},
            ["dimensions"],
        )
        service = RobotAgentService(restore_pending_actions=False)
        route = {
            "mode": "advanced",
            "name": "drawing_design",
            "operation": "create",
            "selected_project_id": project["id"],
        }

        with patch("app.agent_service.get_creative_project_store", return_value=store):
            result = service._apply_design_requirement_followup("宽高为4m", route)

        assert result is not None
        assert result["requirements"]["shape"] == "heart_outline"
        assert result["requirements"]["dimensions"] == {
            "width_m": 4.0,
            "height_m": 4.0,
        }
        assert result["missing_parameters"] == []
        assert result["project"]["status"] == "ready_for_design"
        assert result["requirements_confirmation_required"] is True


def test_conversation_memory_keeps_parameter_only_answer() -> None:
    assert ConversationMemoryStore._extract_requirements("宽高为4m") == {
        "width_m": 4.0,
        "height_m": 4.0,
    }


def test_coordinate_unit_followup_completes_scale_without_printer_or_bounds(tmp_path):
    service=RobotAgentService(restore_pending_actions=False)
    store=CreativeProjectStore(tmp_path/'projects.json')
    prompt='画一条闭合样条曲线，控制点(0,0)(1,2)(2,-1)(3,2)(4,0)，平滑闭合'
    project=store.create('样条',prompt,requirements={'shape':'generic_2d_cad'},missing_parameters=['dimensions'])
    answer='坐标单位为米，使用原文给出的五个控制点，要求平滑闭合。'
    with patch('app.agent_service.get_creative_project_store',return_value=store):
        result=service._apply_design_requirement_followup(answer,{'selected_project_id':project['id']})
    assert result['missing_parameters']==[]
    assert result['requirements_confirmation_required']
    assert result['project_id']==project['id']
    assert result['requirements']['scale_source']=='explicit_coordinates_and_units'
    assert store.get(project['id'])['requirements']['source_followups']==[answer]
    assert '喷码机' not in result['message']


def test_new_drawing_wording_does_not_enter_existing_layout_edit_route():
    service=RobotAgentService(restore_pending_actions=False)
    route=service.resolve_intent('画两个并排的停车位','advanced',[])
    assert route['operation']=='create'
    assert service._drawing_layout_followup_route('画两个并排的停车位','advanced',[]) is None
    assert service._drawing_layout_followup_route('把这两个停车位调整为并排，间距1米','advanced',[]) is not None
