from __future__ import annotations


def test_constrained_arc_branch_is_solved_without_overriding_user_direction():
    import math
    from copy import deepcopy
    from app.cad_construction_interpreter import interpret_construction_request
    def point(r,a):return {'x':r*math.cos(math.radians(a)),'y':r*math.sin(math.radians(a))}
    for count in (5,8):
        source=f'生成一个齿轮轮廓，外径2米，{count}个齿，齿根圆直径1.5米，各齿齿顶角宽15度'
        payload={'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
            'confidence':.95,'evidence_text':[source],'assumptions':[],
            'plan':{'units':'m','steps':[{'op':'add_rotational_path','step_id':'period','output_ref':'outline',
                'semantic':{'label':'周期外边界'},'center':{'x':0,'y':0},'count':count,
                'constrain_sector_end':True,'direction':'auto','segments':[
                    {'kind':'line','start':point(.75,0),'end':point(1,0)},
                    {'kind':'arc','center':{'x':0,'y':0},'radius':1,'start_angle':0,'end_angle':15},
                    {'kind':'line','start':point(1,15),'end':point(.75,30)},
                    {'kind':'arc','center':{'x':0,'y':0},'radius':.75,'start_angle':30,'end_angle':360/count,'clockwise':True}]}]}}
        before=deepcopy(payload)
        result=interpret_construction_request(source,lambda *_:deepcopy(payload),force_structured_model=True)
        assert result['status']=='ready',result
        assert any(r['kind']=='resolve_constrained_arc_branch' for r in result['deterministic_repairs'])
        assert result['plan']['steps'][0]['segments'][-1]['clockwise'] is False
        assert result['plan']['steps'][0]['segments'][-1]['radius']==.75
        assert payload==before
        explicit=source+'，所有圆弧必须顺时针'
        payload['evidence_text']=[explicit]
        assert interpret_construction_request(explicit,lambda *_:deepcopy(payload),force_structured_model=True)['status']!='ready'


def test_center_binding_does_not_reuse_stale_size_from_previous_geometry():
    from copy import deepcopy
    from app.cad_construction_interpreter import bind_explicit_outline_center
    from app.cad_construction import execute_construction_plan
    source='生成一个正四边形，外接圆半径1米，中心(2,3)，坐标单位米'
    payload={'plan':{'units':'m','steps':[{'op':'add_polyline','step_id':'shape','output_ref':'shape',
        'semantic':{'label':'正四边形'},'closed':True,
        'vertices':[{'x':1,'y':0},{'x':0,'y':1},{'x':-1,'y':0},{'x':0,'y':-1}]}],
        'free_outline_layout':[{'target_ref':'shape','width':1.8,'height':1.8,'center':{'x':0,'y':0}}]}}
    fixed,_=bind_explicit_outline_center(deepcopy(payload),source)
    layout=fixed['plan']['free_outline_layout'][0]
    assert 'width' not in layout and 'height' not in layout
    result=execute_construction_plan(fixed['plan'])
    assert [(p['x'],p['y']) for p in result['geometries'][0]['vertices']]==[(3000,3000),(2000,4000),(1000,3000),(2000,2000)]
    explicit,_=bind_explicit_outline_center(deepcopy(payload),source+'，整体宽2米高2米')
    assert explicit['plan']['free_outline_layout'][0]['width']==2
    assert explicit['plan']['free_outline_layout'][0]['height']==2


def test_radial_source_can_correct_model_bounds_without_changing_geometry():
    import math
    from copy import deepcopy
    from app.cad_construction_interpreter import interpret_construction_request
    source='生成一个正六边形，外接圆半径1米'
    payload={'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
        'confidence':.95,'evidence_text':[source],'assumptions':[],
        'plan':{'units':'m','steps':[{'op':'add_polyline','step_id':'hex','output_ref':'hex',
            'semantic':{'label':'正六边形'},'closed':True,
            'vertices':[{'x':math.cos(i*math.pi/3),'y':math.sin(i*math.pi/3)} for i in range(6)]}],
            'assertions':[{'kind':'bounds_size','assertion_id':'wrong_bbox','target_ref':'hex','width':2,'height':2}]}}
    before=deepcopy(payload)
    result=interpret_construction_request(source,lambda *_:deepcopy(payload),force_structured_model=True)
    assert result['status']=='ready'
    assert any(r['kind']=='source_radial_acceptance_replaces_unrequested_bounds'
        and r['geometry_unchanged'] for r in result['deterministic_repairs'])
    assert result['plan']['steps'][0]['vertices']==payload['plan']['steps'][0]['vertices']
    assert payload==before
    explicit=source+'，整体宽2米高2米'
    payload['evidence_text']=[explicit]
    assert interpret_construction_request(explicit,lambda *_:deepcopy(payload),force_structured_model=True)['status']!='ready'
    payload=deepcopy(before)
    for point in payload['plan']['steps'][0]['vertices']:
        point['x']*=.9;point['y']*=.9
    assert interpret_construction_request(source,lambda *_:deepcopy(payload),force_structured_model=True)['status']!='ready'


def test_contract_snapshot_keeps_coordinate_command_parseable():
    from app.cad_construction_interpreter import interpret_construction_request
    import json

    source = "画一条线段从(0,0)到(5,3)，坐标单位米"
    snapshot = source + "\n[CAD_REQUIREMENT_CONTRACT_SNAPSHOT.v1]\n" + json.dumps({
        "original_prompt": source,
        "requirements": {},
        "source_followups": [],
        "status": "unpersisted_initial_request",
    }, ensure_ascii=False)
    result = interpret_construction_request(snapshot)
    assert result["status"] == "ready"
    assert result["plan"]["steps"][0]["op"] == "add_line"


def test_circle_radius_before_center_is_parseable_without_model_guessing():
    from app.cad_construction_interpreter import interpret_construction_request

    result = interpret_construction_request(
        "生成一个圆形：半径2米，圆心(0,0)，坐标单位米。"
    )
    assert result["status"] == "ready"
    assert result["plan"]["steps"][0]["op"] == "add_circle"
    assert result["acceptance_summary"]["status"] == "passed"


def test_explicit_control_points_only_need_coordinate_units_before_model():
    from unittest.mock import Mock
    from app.cad_construction_interpreter import interpret_construction_request,clarify_construction_request
    source='画一条闭合样条曲线，控制点(0,0)(1,2)(2,-1)(3,2)(4,0)，平滑闭合'
    model=Mock()
    result=interpret_construction_request(source,model)
    assert result['error']['code']=='missing_coordinate_units'
    assert '坐标单位' in result['clarification']['question']
    model.assert_not_called()
    completed=clarify_construction_request(source+'\n坐标单位为米')
    assert completed['recognized_size'] and completed['question_key']=='construction_scope'


def test_spline_diagnostics_preserve_points_and_do_not_override_explicit_degree():
    from app.cad_construction_interpreter import interpret_construction_request
    source='画一条闭合样条曲线，控制点(0,0)(1,2)(2,-1)(3,2)(4,0)，平滑闭合，坐标单位为米'
    payload={'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
        'confidence':.95,'evidence_text':[source],'assumptions':[],'plan':{'units':'m','steps':[{
            'op':'add_spline','step_id':'s','output_ref':'s','semantic':{'label':'样条'},
            'degree':3,'closed':True,'control_points':[{'x':x,'y':y} for x,y in [(0,0),(1,2),(2,-1),(3,2),(4,0)]]}]}}
    result=interpret_construction_request(source,lambda *_:payload,force_structured_model=True)
    diagnostic=result['construction_error']['details']['spline_degree_diagnostics']
    assert diagnostic['feasible_degrees']==[4] and diagnostic['control_points_unchanged']
    assert diagnostic['persisted'] is False and result['status']!='ready'
    fixed_source=source+'，指定三次样条'
    payload['evidence_text']=[fixed_source]
    fixed=interpret_construction_request(fixed_source,lambda *_:payload,force_structured_model=True)
    assert not fixed['construction_error'].get('details',{}).get('spline_degree_diagnostics')


def test_explicit_star_structure_is_bound_independently_of_model_assertions():
    from app.cad_construction_interpreter import bind_outline_requirements, outline_requirements
    text='生成一个五角星，外接圆半径2米，内外半径比0.381966，尖角朝上'
    requirement=outline_requirements(text)
    assert requirement['radial_lobes']==5
    assert requirement['profile']=='polygonal'
    payload={'plan':{'steps':[{'output_ref':'outline'}],'assertions':[]}}
    result=bind_outline_requirements(payload,text)
    radial=next(a for a in result['plan']['assertions'] if a['kind']=='radial_pattern')
    assert radial['lobes']==5 and radial['profile']=='polygonal'
    assert outline_requirements('生成一个爱心和一个五角星，各宽5米') is None
    assert outline_requirements('生成五星红旗，宽3米高2米') is None


def test_source_star_contract_rejects_circle_even_if_model_claims_success():
    import pytest
    from app.cad_construction import RadialPatternAssertion, ConstructionPlanError, _run_assertions
    assertion=RadialPatternAssertion(kind='radial_pattern',assertion_id='source-star',
        target_ref='outline',lobes=5,profile='polygonal')
    # The verifier consumes actual geometry rather than a model success flag.
    with pytest.raises(ConstructionPlanError):
        _run_assertions([assertion],[{'id':1,'type':'circle','center':{'x':0,'y':0},'radius':2000}],
            {'outline':[1]},1000)


def test_periodic_outline_without_dimensions_never_calls_model():
    from unittest.mock import Mock
    from app.cad_construction_interpreter import interpret_construction_request
    model = Mock()
    result = interpret_construction_request("画一朵花的轮廓，5片花瓣，闭合曲线", model)
    assert result["error"]["code"] == "missing_outline_dimensions"
    model.assert_not_called()


def test_outline_contract_is_grounded_and_cannot_be_overridden_by_model():
    from app.cad_construction_interpreter import bind_outline_requirements, outline_requirements
    text = "画一朵花的轮廓，5片花瓣，闭合曲线"
    requirement = outline_requirements(text + "\n后端试算反馈：实际8瓣花")
    assert requirement["radial_lobes"] == 5
    payload = {"plan": {"steps": [{"output_ref": "boundary"}], "assertions": [
        {"kind": "radial_pattern", "lobes": 8, "target_ref": "boundary"},
    ]}}
    result = bind_outline_requirements(payload, text)
    assertions = result["plan"]["assertions"]
    assert next(a for a in assertions if a["kind"] == "radial_pattern")["lobes"] == 5
    assert next(a for a in assertions if a["kind"] == "entity_count")["equals"] == 1
    assert any(a["kind"] == "closed" for a in assertions)
    assert outline_requirements("画两朵花的轮廓，5片花瓣，闭合曲线") is None


def test_outline_contract_rejects_ambiguous_multi_output_binding():
    import pytest
    from app.cad_construction_interpreter import bind_outline_requirements
    with pytest.raises(ValueError, match="唯一构造输出"):
        bind_outline_requirements({"plan": {"steps": [
            {"output_ref": "boundary"}, {"output_ref": "decoration"},
        ]}}, "画一朵花的轮廓，5片花瓣，闭合曲线")


def test_misplaced_assertions_are_preserved_without_overwriting_plan_assertions():
    from app.cad_construction_interpreter import repair_construction_references_once
    assertion = {"kind": "closed", "assertion_id": "closed", "target_ref": "outline"}
    payload = {"plan": {"steps": [{"op": "add_polyline", "output_ref": "outline", "closed": True}]},
               "assertions": [assertion]}
    repaired, repairs = repair_construction_references_once(payload)
    assert repaired["plan"]["assertions"] == [assertion]
    assert "assertions" not in repaired
    assert repairs[0]["kind"] == "move_assertions_to_plan"
    assert payload["assertions"] == [assertion]
    payload["plan"]["assertions"] = [{"kind": "entity_count", "equals": 2}]
    repaired, _ = repair_construction_references_once(payload)
    assert repaired["assertions"] == [assertion]
    assert repaired["plan"]["assertions"] == payload["plan"]["assertions"]


def test_semantic_object_id_alias_is_resolved_before_strict_plan_validation():
    from app.cad_construction_interpreter import interpret_construction_request

    source = "生成两个独立闭合轮廓，尺寸单位米"
    payload = {
        "schema_version": "cad.construction-interpretation.v1",
        "is_construction_request": True,
        "confidence": .95,
        "evidence_text": [source],
        "assumptions": [],
        "plan": {
            "units": "m",
            "steps": [{
                "op": "add_polyline", "step_id": "part", "output_ref": "part_polygon",
                "semantic": {"label": "部件", "object_id": "part_outline"},
                "closed": True,
                "vertices": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 0, "y": 1}],
            }],
            "assertions": [{
                "kind": "closed", "assertion_id": "closed", "target_ref": "part_outline",
            }],
        },
    }

    result = interpret_construction_request(source, lambda *_: payload, force_structured_model=True)

    assert result["status"] == "ready"
    assert result["plan"]["assertions"][0]["target_ref"] == "part_polygon"
    assert any(item["kind"] == "target_ref_alias" for item in result["deterministic_repairs"])


def test_named_component_radial_count_becomes_independent_assertion():
    from app.cad_construction_interpreter import bind_named_radial_requirements

    payload = {"plan": {"steps": [
        {"output_ref": "left", "semantic": {"label": "爱心外轮廓", "assembly_label": "爱心"}},
        {"output_ref": "right", "semantic": {"label": "右侧轮廓", "assembly_label": "星形部件"}},
    ], "assertions": []}}
    contract = {"names": ["爱心", "星形部件"]}

    bound, repairs = bind_named_radial_requirements(
        payload, contract, "爱心在左；星形部件为5个尖角并位于右侧。",
    )

    assertion = bound["plan"]["assertions"][0]
    assert assertion == {
        "kind": "radial_pattern", "assertion_id": "source-radial-2",
        "target_ref": "right", "lobes": 5, "profile": "polygonal",
    }
    assert repairs[0]["kind"] == "bind_named_radial_requirement"


def test_named_radial_binding_never_reads_serialized_contract_snapshot():
    from app.cad_construction_interpreter import bind_named_radial_requirements

    payload = {"plan": {"steps": [
        {"output_ref": "heart", "semantic": {"label": "爱心", "assembly_label": "爱心"}},
        {"output_ref": "star", "semantic": {"label": "五角星", "assembly_label": "五角星"}},
    ], "assertions": []}}
    source = (
        "生成一个爱心和一个五角星，爱心在左，五角星在右。"
        "爱心宽4米高4米；五角星外接圆半径2米、固定为5个尖角。"
        "\n[CAD_REQUIREMENT_CONTRACT_SNAPSHOT.v1]\n"
        '{"objects":[{"name":"爱心"},{"name":"五角星","points":5}]}'
    )

    bound, _ = bind_named_radial_requirements(
        payload, {"names": ["爱心", "五角星"]}, source,
    )

    assertions = bound["plan"]["assertions"]
    assert len(assertions) == 1
    assert assertions[0]["target_ref"] == "star"


def test_composition_contract_overrides_invalid_model_helper_bounds_before_validation():
    from app.cad_construction_interpreter import compile_composition_plan

    source = "生成甲和乙，甲宽4米高4米，乙宽4米高4米，两者中心相距6米。"
    semantic = lambda label: {"label": label, "assembly_label": label}
    payload = {"plan": {
        "units": "m",
        "steps": [
            {"op": "add_rectangle", "step_id": "a", "output_ref": "a",
             "semantic": semantic("甲"), "origin": {"x": 0, "y": 0}, "width": 1, "height": 1},
            {"op": "add_rectangle", "step_id": "b", "output_ref": "b",
             "semantic": semantic("乙"), "origin": {"x": 0, "y": 0}, "width": 1, "height": 1},
        ],
        "assertions": [{
            "kind": "bounds_size", "assertion_id": "bad-helper", "target_ref": "b",
            "width": "-sqrt(4)", "height": 4,
        }],
        "free_outline_layout": [{
            "target_ref": "b", "width": "-sqrt(4)", "height": 4,
        }],
    }}
    contract = {
        "kind": "named_components", "names": ["甲", "乙"],
        "left_to_right": True, "gap_m": 6, "gap_reference": "center",
        "dimensions": {"width_m": 4, "height_m": 4},
    }

    compiled, _ = compile_composition_plan(payload, contract, source)

    sizes = [item for item in compiled["plan"]["assertions"] if item["kind"] == "bounds_size"]
    assert len(sizes) == 2
    assert all(item["width"] == 4 and item["height"] == 4 for item in sizes)


def test_bad_fixed_radius_component_does_not_cancel_other_component_sizing():
    from app.cad_construction_interpreter import bind_component_layout

    def semantic(label):
        return {"label": label, "assembly_label": label}
    payload = {"plan": {"units": "m", "steps": [
        {"op": "add_polyline", "step_id": "free", "output_ref": "free",
         "semantic": semantic("自由部件"), "closed": True,
         "vertices": [{"x": 0, "y": 0}, {"x": 3.9, "y": 0}, {"x": 3.9, "y": 4}, {"x": 0, "y": 4}]},
        {"op": "add_polyline", "step_id": "fixed", "output_ref": "fixed",
         "semantic": semantic("定半径部件"), "closed": True,
         "vertices": [{"x": 0, "y": 0}, {"x": 3, "y": 0}, {"x": 0, "y": 3}]},
    ], "assertions": []}}
    contract = {
        "kind": "named_components", "names": ["自由部件", "定半径部件"],
        "component_dimensions": {
            "自由部件": {"width_m": 4, "height_m": 4},
            "定半径部件": {"circumradius_m": 2},
        },
        "left_to_right": True, "gap_m": 6, "gap_reference": "center",
    }

    bound, repairs = bind_component_layout(payload, contract, "生成自由部件和定半径部件，坐标单位米")

    layout = bound["plan"]["free_outline_layout"]
    assert layout[0]["width"] == 4 and layout[0]["height"] == 4
    assert layout[1]["width"] == 3 and layout[1]["height"] == 3
    assert layout[1]["gap_reference"] == "center"
    assert repairs[0]["kind"] == "bind_scoped_component_layout"


def test_post_execution_composition_acceptance_resolves_parametric_preflight_review():
    from app.cad_construction_interpreter import construction_acceptance_summary

    result = construction_acceptance_summary(
        preflight_structure={"status": "unverified", "review_required": True},
        structure_contract=None,
        structure_validation=None,
        composition_contract={"kind": "named_components"},
        composition_validation={"status": "passed"},
        source_acceptance={"status": "not_checked", "checks": [], "coverage": "partial"},
    )

    assert result["status"] == "passed"
    assert result["review_required"] is False
    assert result["verified_checks"] == 1


def test_zero_independent_acceptance_checks_can_never_pass():
    from app.cad_construction_interpreter import construction_acceptance_summary

    result = construction_acceptance_summary(
        preflight_structure=None,
        structure_contract=None,
        structure_validation=None,
        composition_contract=None,
        composition_validation=None,
        source_acceptance={"status": "not_checked", "checks": []},
    )
    assert result["status"] == "review_required"
    assert result["verified_checks"] == 0

from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from app.agent_service import RobotAgentService
from app.cad_construction_interpreter import (
    clarify_construction_request,
    construction_interpretation_json_schema,
    interpret_construction_request,
    interpret_sketch_graph_candidates,
    normalize_construction_request,
    normalize_explicit_area_once,
    normalize_explicit_outline_size_once,
    parse_rule_construction_plan,
    repair_construction_references_once,
    sketch_graph_interpretation_json_schema,
)


@pytest.mark.parametrize("units,factor", [("m", 1), ("mm", 1000)])
def test_free_outline_fits_explicit_size_and_preserves_closed_topology(units, factor):
    payload = {"plan": {
        "schema_version": "cad.construction-plan.v1", "units": units,
        "steps": [{"op": "add_polyline", "step_id": "outline", "output_ref": "outline",
                   "layer_id": 1, "semantic": {"object_type": "outline", "label": "自由轮廓"},
                   "vertices": [{"x": x * factor, "y": y * factor} for x, y in [(0, 0), (1.1736, 0), (1, 4), (0, 8.25)]],
                   "closed": True}],
        "assertions": [{"kind": "closed", "assertion_id": "closed", "target_ref": "outline"}],
    }}
    source = "绘制自由闭合轮廓，宽度5米，高度5米"
    repaired, evidence = normalize_explicit_outline_size_once(payload, source)
    assert evidence[0]["kind"] == "normalize_explicit_outline_size"
    result = interpret_construction_request(source, lambda *_: {
        "schema_version": "cad.construction-interpretation.v1", "is_construction_request": True,
        **repaired, "confidence": 0.95, "evidence_text": ["自由闭合轮廓"], "assumptions": [],
    }, force_structured_model=True)
    assert result["status"] == "ready", result
    assert payload["plan"]["steps"][0]["vertices"][1]["x"] == 1.1736 * factor
    assert repaired["plan"]["steps"][0]["closed"] is True


def test_outline_size_repair_does_not_override_fixed_coordinates():
    payload = {"plan": {"steps": []}}
    assert normalize_explicit_outline_size_once(payload, "轮廓宽度5米，高度5米，固定顶点(1,2)") == (payload, [])


def test_free_outline_size_normalization_uses_same_safe_coordinate_evaluator_as_executor():
    from copy import deepcopy
    from app.cad_construction import execute_construction_plan,construction_geometry_bounds
    payload={'plan':{'units':'m','steps':[{'op':'add_polyline','step_id':'outline','output_ref':'outline',
        'semantic':{'label':'轮廓'},'closed':True,'vertices':[
            {'x':0,'y':0},{'x':'1+1','y':0},{'x':'sqrt(4)','y':'2+0.5'},{'x':0,'y':'5/2'}]}]}}
    original=deepcopy(payload)
    fitted,evidence=normalize_explicit_outline_size_once(payload,'绘制一个闭合轮廓，宽度4米，高度5米')
    assert evidence
    assert payload==original
    b=construction_geometry_bounds(execute_construction_plan(fitted['plan'])['geometries'])
    assert abs(b['max_x']-b['min_x']-4000)<.5
    assert abs(b['max_y']-b['min_y']-5000)<.5
    malicious=deepcopy(payload)
    malicious['plan']['steps'][0]['vertices'][1]['x']='__import__("os").getcwd()'
    assert normalize_explicit_outline_size_once(malicious,'闭合轮廓宽度4米，高度5米')==(malicious,[])


def test_free_outline_schema_keeps_existing_parametric_primitive_available():
    from app.cad_construction_interpreter import _request_construction_schema
    schema=_request_construction_schema('绘制一个平滑闭合轮廓，宽度5米，高度5米')
    refs=schema['$defs']['CadConstructionPlan']['properties']['steps']['items']['oneOf']
    assert {'$ref':'#/$defs/AddParametricCurveStep'} in refs
    assert schema['$defs']['AddParametricCurveStep']['properties']['closed']['const'] is True
    periodic=_request_construction_schema('画一朵花的轮廓，5片花瓣，闭合曲线，宽度5米，高度5米')
    assert periodic['$defs']['CadConstructionPlan']['properties']['steps']['items']['oneOf']==[
        {'$ref':'#/$defs/AddParametricCurveStep'}]
    retry=_request_construction_schema('画一朵花的轮廓，5片花瓣，闭合曲线，宽度5米，高度5米\n后端试算反馈：控制点与半径不匹配')
    assert retry==periodic


def test_mathematical_curve_or_formula_does_not_inherit_polygonal_star_contract():
    from app.cad_construction_interpreter import outline_requirements
    assert outline_requirements('生成一个星形线（内凹四角星），最大半径2米') is None
    assert outline_requirements('画一个四角星，参数式x=2*cos(t)^3、y=2*sin(t)^3') is None
    assert outline_requirements('画一个四角星，外接圆半径2米')['profile']=='polygonal'


def test_scoped_layout_does_not_refit_fixed_coordinate_circle_or_rectangle():
    from copy import deepcopy
    from app.cad_structure_contract import explicit_composition
    from app.cad_construction_interpreter import bind_component_layout
    source='生成一个圆形和一个矩形，圆形在矩形正上方。圆半径1米，圆心(0,3)；矩形左下角(-1,-1)，宽2米高2米；坐标单位米'
    payload={'plan':{'units':'m','steps':[
        {'op':'add_circle','step_id':'circle','output_ref':'circle','semantic':{'label':'圆形'},'center':{'x':0,'y':3},'radius':1},
        {'op':'add_rectangle','step_id':'rect','output_ref':'rect','semantic':{'label':'矩形'},'origin':{'x':-1,'y':-1},'width':2,'height':2}]}}
    original=deepcopy(payload)
    result,repairs=bind_component_layout(payload,explicit_composition(source),source)
    assert result==original and not repairs
    interpreted=interpret_construction_request(source,lambda *_:{'schema_version':'cad.construction-interpretation.v1',
        'is_construction_request':True,'confidence':.99,'evidence_text':[source],**payload},force_structured_model=True)
    assert interpreted['status']=='ready',interpreted
    assert interpreted['trial_result']['geometries'][0]['center']['y']==3000


def test_astroid_rejects_inapplicable_model_smoothness_only_after_independent_proof():
    from copy import deepcopy
    plan={'units':'m','steps':[{'op':'add_parametric_curve','step_id':'outline','output_ref':'outline',
        'semantic':{'label':'星形线'},'x_expression':'2*cos(t)**3','y_expression':'2*sin(t)**3',
        't_start':'0','t_end':'2*pi','max_sampling_error':.001,'closed':True}],
        'assertions':[{'kind':'radial_pattern','assertion_id':'smooth','target_ref':'outline','lobes':4,'profile':'smooth'}]}
    def run(p,source='生成星形线，最大半径2米'):
        return interpret_construction_request(source,lambda *_:{
            'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
            'plan':p,'confidence':.99,'evidence_text':[source],'assumptions':[]},force_structured_model=True)
    result=run(plan)
    assert result['status']=='ready',result
    assert any(r['kind']=='source_curve_identity_replaces_inapplicable_smoothness'
               and r['geometry_unchanged'] for r in result['deterministic_repairs'])
    assert run(plan,'生成星形线，最大半径2米，无尖角')['status']=='invalid'
    wrong=deepcopy(plan);wrong['steps'][0]['x_expression']='cos(t)**3';wrong['steps'][0]['y_expression']='sin(t)**3'
    assert run(wrong)['status']=='invalid'


def test_failed_model_assertion_reports_independent_curve_failure_in_same_attempt():
    source='生成心形线（cardioid），尖点朝下，最大宽度3米'
    result=interpret_construction_request(source,lambda *_:{
        'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
        'plan':{'units':'m','steps':[{'op':'add_parametric_curve','step_id':'outline','output_ref':'outline',
            'semantic':{'label':'心形线'},'x_expression':'1.5*sin(t)',
            'y_expression':'-1.5*cos(t)-1.5*cos(2*t)+1.5','t_start':'0','t_end':'2*pi',
            'max_sampling_error':.001,'closed':True}],
            'assertions':[{'kind':'radial_pattern','assertion_id':'wrong-lobes','target_ref':'outline',
                           'lobes':2,'profile':'smooth'}]},
        'confidence':.99,'evidence_text':[source],'assumptions':[]},force_structured_model=True)
    assert result['status']=='invalid'
    failure=result['construction_error']['details']['independent_source_failure']
    assert failure['details']['check']=='cardioid_polar_identity'
    assert failure['details']['measurements']['passed'] is False
    assert failure['candidate_accepted'] is False and failure['diagnostic_only'] is True
    assert result['construction_error']['details']['affected_output_refs']==['outline']


def test_astroid_identity_rejects_diamond_circle_and_wrong_radius():
    import math
    from app.cad_curve_fit_acceptance import verify_astroid
    def geometry(x,y):
        return {'closed':True,'vertices':[{'x':x(t),'y':y(t)} for t in [i*math.tau/720 for i in range(720)]]}
    astroid=geometry(lambda t:2000*math.cos(t)**3,lambda t:2000*math.sin(t)**3)
    assert verify_astroid(astroid,2000)['passed']
    assert not verify_astroid(astroid,1000)['passed']
    assert not verify_astroid(geometry(lambda t:2000*math.cos(t),lambda t:2000*math.sin(t)),2000)['passed']
    diamond=geometry(lambda t:2000*math.cos(t)/(abs(math.cos(t))+abs(math.sin(t))),
                     lambda t:2000*math.sin(t)/(abs(math.cos(t))+abs(math.sin(t))))
    assert not verify_astroid(diamond,2000)['passed']


def test_parametric_free_outline_fits_size_without_replacing_formula_or_source():
    from copy import deepcopy
    from app.cad_construction import execute_construction_plan, construction_geometry_bounds
    payload={'plan':{'units':'m','steps':[{'op':'add_parametric_curve','step_id':'boundary',
        'output_ref':'boundary','semantic':{'label':'周期轮廓'},'x_expression':'2*cos(t)',
        'y_expression':'sin(t)','t_start':'0','t_end':'2*pi','closed':True,'max_sampling_error':.001}]}}
    original=deepcopy(payload)
    repaired,evidence=normalize_explicit_outline_size_once(payload,'绘制一个平滑闭合轮廓，宽度5米，高度5米')
    assert evidence and payload==original
    step=repaired['plan']['steps'][0]
    assert '2*cos(t)' in step['x_expression'] and 'sin(t)' in step['y_expression']
    bounds=construction_geometry_bounds(execute_construction_plan(repaired['plan'])['geometries'])
    assert abs(bounds['max_x']-bounds['min_x']-5000)<1
    assert abs(bounds['max_y']-bounds['min_y']-5000)<1
    assert normalize_explicit_outline_size_once(payload,'轮廓宽度5米，高度5米，半径2米')==(payload,[])
    assert normalize_explicit_outline_size_once(payload,'闭合轮廓宽度5米，高度5米，x=2*cos(t)，y=sin(t)')==(payload,[])


def test_free_layout_is_applied_after_parametric_size_normalization():
    source='画一朵花的轮廓，5片花瓣，闭合曲线，宽度5米，高度5米'
    plan={'units':'m','steps':[{'op':'add_parametric_curve','step_id':'outline','output_ref':'outline',
        'semantic':{'label':'自由轮廓'},'x_expression':'(1+0.5*cos(5*t))*cos(t)',
        'y_expression':'(1+0.5*cos(5*t))*sin(t)','t_start':'0','t_end':'2*pi',
        'max_sampling_error':.001,'closed':True}],
        'free_outline_layout':[{'target_ref':'outline','width':5,'height':5}]}
    result=interpret_construction_request(source,lambda *_:{
        'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
        'plan':plan,'confidence':.99,'evidence_text':[source],'assumptions':[]},force_structured_model=True)
    assert result['status']=='ready',result.get('error')
    assert result['deterministic_repairs']


@pytest.mark.parametrize("lobes,expected", [(5, "ready"), (8, "invalid")])
def test_requested_radial_count_is_verified_from_geometry(lobes, expected):
    import math
    vertices = []
    for i in range(240):
        angle = i * math.tau / 240
        radius = 2 + 0.5 * math.cos(lobes * angle)
        vertices.append({"x": radius * math.cos(angle), "y": radius * math.sin(angle)})
    result = interpret_construction_request("画5片花瓣的闭合轮廓，宽度5米，高度5米", lambda *_: {
        "schema_version": "cad.construction-interpretation.v1", "is_construction_request": True,
        "plan": {"schema_version": "cad.construction-plan.v1", "units": "m", "steps": [{
            "op": "add_polyline", "step_id": "outline", "output_ref": "outline", "layer_id": 1,
            "semantic": {"object_type": "outline", "label": "径向重复轮廓"},
            "vertices": vertices, "closed": True,
        }], "assertions": []},
        "confidence": 0.95, "evidence_text": ["5片花瓣"], "assumptions": [],
    }, force_structured_model=True)
    assert result["status"] == expected, result
    if expected == "invalid":
        assert "要求 5" in result["error"]["message"]
from app.cad_construction_evaluation import evaluate_construction_interpretation


def test_vague_heart_request_gets_one_cad_specific_question() -> None:
    result = clarify_construction_request("绘画一个大小不超过5m的爱心")

    assert result["status"] == "clarification_required"
    assert result["question_key"] == "curve_constraints"
    assert result["recognized_shape"] == "爱心"
    assert result["recognized_size"] is True
    assert "闭合" in result["question"]
    assert "新建 CAD 图纸" in result["suggested_prompt"]


def test_cad_clarification_prioritizes_shape_then_size() -> None:
    missing_shape = clarify_construction_request("帮我画一个好看的图")
    assert missing_shape["question_key"] == "shape"

    missing_size = clarify_construction_request("创建一个闭合爱心轮廓")
    assert missing_size["question_key"] == "size"
    assert "最大宽" in missing_size["question"]


def test_square_metres_are_a_complete_scale_constraint() -> None:
    result = clarify_construction_request(
        "新建cad图纸，画一朵花的轮廓，5片花瓣，闭合曲线，大小为25平方米"
    )

    assert result["recognized_size"] is True
    assert result["question_key"] != "size"
    normalized, facts = normalize_construction_request(
        "画一朵花的轮廓，5片花瓣，闭合曲线，大小为25平方米"
    )
    assert "目标面积=25平方米" in normalized
    assert any("无需再要求宽度或高度" in item for item in facts)


def test_path3_normalizes_one_closed_output_to_explicit_area() -> None:
    payload = {
        "plan": {
            "schema_version": "cad.construction-plan.v1",
            "units": "m",
            "steps": [{
                "op": "add_polyline", "step_id": "flower", "output_ref": "flower",
                "layer_id": 1,
                "semantic": {"object_type": "outline", "label": "五瓣花轮廓"},
                "vertices": [
                    {"x": -1, "y": -1}, {"x": 1, "y": -1},
                    {"x": 1, "y": 1}, {"x": -1, "y": 1},
                ],
                "closed": True,
            }],
            "assertions": [{
                "kind": "closed", "assertion_id": "closed", "target_ref": "flower",
            }],
        }
    }

    repaired, repairs = normalize_explicit_area_once(
        payload, "画一个闭合轮廓，面积25平方米",
    )
    result = interpret_construction_request(
        "画一个闭合轮廓，面积25平方米",
        lambda _text, _schema: {
            "schema_version": "cad.construction-interpretation.v1",
            "is_construction_request": True,
            **repaired,
            "evidence_text": ["闭合轮廓", "面积25平方米"],
            "assumptions": [],
            "confidence": 0.95,
        },
        force_structured_model=True,
    )

    assert repairs[0]["kind"] == "normalize_explicit_area"
    assert result["status"] == "ready"
    area_assertion = next(
        item for item in result["plan"]["assertions"] if item["kind"] == "area"
    )
    assert area_assertion["area"] == 25


def test_explicit_square_metres_are_converted_for_millimetre_plans() -> None:
    payload = {
        "plan": {
            "schema_version": "cad.construction-plan.v1", "units": "mm",
            "steps": [{
                "op": "add_rectangle", "step_id": "outline", "output_ref": "outline",
                "layer_id": 1,
                "semantic": {"object_type": "outline", "label": "闭合轮廓"},
                "origin": {"x": 0, "y": 0}, "width": 1000, "height": 1000,
            }],
        }
    }

    repaired, repairs = normalize_explicit_area_once(payload, "闭合轮廓面积25平方米")

    assert repairs[0]["to_square_metres"] == 25
    assertion = repaired["plan"]["assertions"][0]
    assert assertion["area"] == 25_000_000
    assert repaired["plan"]["steps"][0]["width"] == pytest.approx(5000)
    assert repaired["plan"]["steps"][0]["height"] == pytest.approx(5000)


def test_rules_construct_multiple_explicit_primitives() -> None:
    result = interpret_construction_request(
        "画一个宽5米高3米的矩形，左下角在(0,0)；"
        "画一个圆，圆心(2.5,1.5)，半径50厘米"
    )

    assert result["status"] == "ready"
    assert result["parser"] == "deterministic_rules"
    assert len(result["trial_result"]["geometries"]) == 2
    assert result["trial_result"]["geometries"][0]["type"] == "polyline"
    assert result["trial_result"]["geometries"][1]["radius"] == 500.0


def test_rules_parse_line_polyline_arc_and_ellipse() -> None:
    text = (
        "画一条线段从(0,0)到(5,3)；"
        "画一条闭合多段线，经过(0,0)、(3,0)、(3,2)、(0,2)；"
        "画一条圆弧，圆心(0,0)，半径2米，起始角0度，终止角90度；"
        "画一个椭圆，中心(5,5)，长半轴3米，短半轴1米，旋转30度"
    )

    result = interpret_construction_request(text)

    assert result["status"] == "ready"
    assert [item["type"] for item in result["trial_result"]["geometries"]] == [
        "line", "polyline", "arc", "ellipse",
    ]
    assert result["trial_result"]["geometries"][1]["closed"] is True


def test_ellipse_and_arc_assertions_use_exact_axis_aligned_bounds() -> None:
    ellipse = interpret_construction_request(
        "画一个椭圆，中心(0,0)，长半轴15米，短半轴9米，旋转0度"
    )
    assert ellipse["status"] == "ready"

    def callback(_text: str, _schema: dict) -> dict:
        return {
            "schema_version": "cad.construction-interpretation.v1",
            "is_construction_request": True,
            "plan": {
                "schema_version": "cad.construction-plan.v1", "units": "m",
                "steps": [{
                    "op": "add_arc", "step_id": "arc-1", "output_ref": "arc-1",
                    "layer_id": 1,
                    "semantic": {"object_type": "door", "label": "门弧"},
                    "center": {"x": 0, "y": 0}, "radius": 2,
                    "start_angle": 0, "end_angle": 90,
                }],
                "assertions": [{
                    "kind": "bounds_size", "assertion_id": "arc-bounds",
                    "target_ref": "arc-1", "width": 2, "height": 2,
                }],
            },
            "evidence_text": ["四分之一圆弧"],
            "assumptions": [], "confidence": 0.9,
        }

    arc = interpret_construction_request("画半径2米的四分之一圆弧", callback)
    assert arc["status"] == "ready"


def test_trial_failure_keeps_validated_plan_for_diagnostics() -> None:
    def callback(_text: str, _schema: dict) -> dict:
        return {
            "schema_version": "cad.construction-interpretation.v1",
            "is_construction_request": True,
            "plan": {
                "schema_version": "cad.construction-plan.v1", "units": "m",
                "steps": [{
                    "op": "add_circle", "step_id": "circle-1",
                    "output_ref": "circle-1", "layer_id": 1,
                    "semantic": {"object_type": "circle", "label": "圆"},
                    "center": {"x": 0, "y": 0}, "radius": 1,
                }],
                "assertions": [{
                    "kind": "entity_count", "assertion_id": "wrong-count",
                    "target_ref": "circle-1", "equals": 2,
                }],
            },
            "evidence_text": ["半径1米"], "assumptions": [], "confidence": 0.9,
        }

    result = interpret_construction_request("画一个半径1米的圆", callback)
    assert result["status"] == "invalid"
    assert result["construction_error"]["code"] == "assertion_failed"
    assert result["plan"]["steps"][0]["output_ref"] == "circle-1"


def test_structured_model_polyline_vertex_count_is_not_treated_as_entity_count() -> None:
    source = "按顺序连接6个坐标形成闭合施工边界，并在内部画一个圆"

    def callback(_text: str, _schema: dict) -> dict:
        return {
            "schema_version": "cad.construction-interpretation.v1",
            "is_construction_request": True,
            "plan": {
                "schema_version": "cad.construction-plan.v1",
                "units": "m",
                "steps": [
                    {
                        "op": "add_polyline", "step_id": "boundary",
                        "output_ref": "boundary", "layer_id": 1,
                        "semantic": {"object_type": "boundary", "label": "边界"},
                        "vertices": [
                            {"x": 0, "y": 0}, {"x": 12, "y": 0},
                            {"x": 15, "y": 6}, {"x": 9, "y": 11},
                            {"x": 2, "y": 9}, {"x": -2, "y": 4},
                        ],
                        "closed": True,
                    },
                    {
                        "op": "add_circle", "step_id": "circle",
                        "output_ref": "circle", "layer_id": 1,
                        "semantic": {"object_type": "circle", "label": "内部圆"},
                        "center": {"x": 6, "y": 5}, "radius": 1.5,
                    },
                ],
                "assertions": [
                    {"kind": "closed", "assertion_id": "closed", "target_ref": "boundary"},
                    {
                        "kind": "entity_count", "assertion_id": "vertex-count",
                        "target_ref": "boundary", "equals": 6,
                    },
                ],
            },
            "evidence_text": ["按顺序连接6个坐标形成闭合施工边界"],
            "assumptions": [],
            "confidence": 0.95,
        }

    result = interpret_construction_request(
        source,
        callback,
        force_structured_model=True,
    )

    assert result["status"] == "ready"
    assert len(result["trial_result"]["geometries"]) == 2
    assert any(
        item["kind"] == "remove_polyline_vertex_count_misuse"
        for item in result["deterministic_repairs"]
    )


def test_incomplete_rule_request_requires_clarification_without_guessing() -> None:
    result = interpret_construction_request("画一个好看的复杂厂房轮廓")

    assert result["status"] == "clarification_required"
    assert result["error"]["code"] == "unsupported_or_incomplete_request"
    assert "trial_result" not in result


def test_non_construction_text_does_not_create_geometry() -> None:
    assert parse_rule_construction_plan("帮我看看今天的设备状态") is None


def test_rule_parser_uses_centered_rectangle_and_rotated_bounds() -> None:
    result = interpret_construction_request(
        "创建一个宽6米、高4米的矩形，中心点(10,-2)，旋转30度"
    )

    assert result["status"] == "ready"
    step = result["plan"]["steps"][0]
    assert step["op"] == "add_centered_rectangle"
    assert step["center"] == {"x": 10.0, "y": -2.0}
    vertices = result["trial_result"]["geometries"][0]["vertices"]
    assert sum(value["x"] for value in vertices) / 4 == pytest.approx(10000)
    assert sum(value["y"] for value in vertices) / 4 == pytest.approx(-2000)


def test_structured_model_plan_must_pass_grounding_and_trial_execution() -> None:
    def callback(text: str, schema: dict) -> dict:
        assert schema["properties"]["schema_version"]
        return {
            "schema_version": "cad.construction-interpretation.v1",
            "is_construction_request": True,
            "plan": {
                "schema_version": "cad.construction-plan.v1",
                "units": "m",
                "steps": [{
                    "op": "add_rectangle", "step_id": "building-1",
                    "output_ref": "building", "layer_id": 1,
                    "semantic": {"object_type": "building", "label": "厂房主体"},
                    "origin": {"x": 0, "y": 0}, "width": 20, "height": 10,
                    "rotation_deg": 0,
                }],
                "assertions": [{
                    "kind": "bounds_size", "assertion_id": "building-size",
                    "target_ref": "building", "width": 20, "height": 10,
                }],
                "budgets": {"max_steps": 20, "max_entities": 100},
            },
            "evidence_text": ["厂房主体宽20米高10米"],
            "assumptions": [],
            "confidence": 0.92,
        }

    result = interpret_construction_request(
        "创建厂房主体宽20米高10米，并预留后续内部隔断", callback,
    )

    assert result["status"] == "ready"
    assert result["parser"] == "structured_model"
    assert result["trial_result"]["feasibility"]["ok"] is True


def test_structured_model_hallucinated_evidence_is_rejected() -> None:
    def callback(_text: str, _schema: dict) -> dict:
        return {
            "schema_version": "cad.construction-interpretation.v1",
            "is_construction_request": True,
            "plan": {
                "schema_version": "cad.construction-plan.v1", "units": "m",
                "steps": [{
                    "op": "add_circle", "step_id": "circle-1", "output_ref": "circle",
                    "layer_id": 1,
                    "semantic": {"object_type": "circle", "label": "圆"},
                    "center": {"x": 0, "y": 0}, "radius": 9,
                }],
            },
            "evidence_text": ["半径9米"], "assumptions": [], "confidence": 0.99,
        }

    result = interpret_construction_request("生成一个圆形区域", callback)

    assert result["status"] == "clarification_required"
    assert result["error"]["code"] == "ungrounded_model_output"


def test_structured_model_invalid_plan_is_rejected_before_execution() -> None:
    def callback(_text: str, _schema: dict) -> dict:
        payload = {
            "schema_version": "cad.construction-interpretation.v1",
            "is_construction_request": True,
            "plan": {
                "schema_version": "cad.construction-plan.v1", "units": "m",
                "steps": [{
                    "op": "add_circle", "step_id": "circle-1", "output_ref": "circle",
                    "layer_id": 1,
                    "semantic": {"object_type": "circle", "label": "圆"},
                    "center": {"x": 0, "y": 0}, "radius": 1,
                }],
            },
            "evidence_text": ["半径1米"], "assumptions": [], "confidence": 0.9,
        }
        payload["plan"]["steps"][0]["unexpected"] = True
        return deepcopy(payload)

    result = interpret_construction_request("创建一个半径1米的圆", callback)

    assert result["status"] == "invalid"
    assert result["error"]["code"] == "invalid_model_output"
    assert result["rejected_plan"]["steps"][0]["unexpected"] is True


def test_low_confidence_grounded_plan_remains_rejected_after_diagnostic_trial() -> None:
    def callback(_text: str, _schema: dict) -> dict:
        return {
            "schema_version": "cad.construction-interpretation.v1",
            "is_construction_request": True,
            "plan": {
                "schema_version": "cad.construction-plan.v1", "units": "m",
                "steps": [{
                    "op": "add_line", "step_id": "line-1", "output_ref": "line",
                    "layer_id": 1,
                    "semantic": {"object_type": "line", "label": "线段"},
                    "start": {"x": 0, "y": 0}, "end": {"x": 1, "y": 1},
                }],
            },
            "evidence_text": ["连接两点"], "assumptions": [], "confidence": 0.5,
        }

    result = interpret_construction_request("连接两点形成线段", callback)

    assert result["status"] == "invalid"
    assert result["error"]["code"] == "low_confidence"
    assert result['diagnostic_trial_passed'] is True
    assert result['persisted'] is False
    assert result['rejected_plan']['steps']
    assert 'trial_result' not in result and 'geometries' not in result


def test_normalization_expands_mixed_units_and_connected_array_facts() -> None:
    source = (
        "创建3个相连的装卸位，每个宽2500毫米、深5米，相邻装卸位之间不留缝；"
        "再在它们后方50厘米处画一条贯穿全部装卸位的直线。"
    )

    normalized, facts = normalize_construction_request(source)

    assert normalized.startswith(source)
    assert "2500毫米 = 2.5米" in normalized
    assert "50厘米 = 0.5米" in normalized
    assert "数量=3" in normalized
    assert "列节距=2.5米" in normalized
    assert "总宽=7.5米" in normalized
    assert "长度=7.5米" in normalized
    assert len(facts) >= 5


def test_normalization_expands_open_u_topology_and_symmetric_columns() -> None:
    source = (
        "画一个开口朝上的U形厂房边界，左下角(-10,-6)，右下角(10,-6)，"
        "两侧墙顶端分别为(-10,8)和(10,8)；再在厂房内部沿左右两侧各布置"
        "3根半径0.3米的圆柱，左右对称且上下等距。"
    )

    normalized, facts = normalize_construction_request(source)

    assert "closed=false" in normalized
    assert "(-10,8) -> (-10,-6) -> (10,-6) -> (10,8)" in normalized
    assert "左列x=-9.7米" in normalized
    assert "右列x=9.7米" in normalized
    assert "共同y坐标=[-5.7, 1, 7.7]米" in normalized
    assert "共6个独立具名圆" in normalized
    assert len(facts) == 3


def test_model_receives_normalized_hints_but_evidence_stays_user_grounded() -> None:
    source = (
        "创建3个相连的装卸位，每个宽2500毫米、深5米，相邻装卸位之间不留缝。"
    )
    captured: dict[str, str] = {}

    def callback(model_text: str, _schema: dict) -> dict:
        captured["text"] = model_text
        return {
            "schema_version": "cad.construction-interpretation.v1",
            "is_construction_request": True,
            "plan": {
                "schema_version": "cad.construction-plan.v1", "units": "m",
                "steps": [{
                    "op": "add_rectangle", "step_id": "bay-1",
                    "output_ref": "bay-1", "layer_id": 1,
                    "semantic": {"object_type": "loading_bay", "label": "装卸位1"},
                    "origin": {"x": 0, "y": 0}, "width": 2.5, "height": 5,
                    "rotation_deg": 0,
                }],
            },
            "evidence_text": ["宽2500毫米、深5米"],
            "assumptions": [], "confidence": 0.9,
        }

    result = interpret_construction_request(source, callback)

    assert result["status"] == "ready"
    assert "[确定性需求规范化]" in captured["text"]
    assert "总宽=7.5米" in captured["text"]
    assert result["normalization_facts"]


def test_dangling_assertion_alias_is_repaired_once() -> None:
    payload = {
        "schema_version": "cad.construction-interpretation.v1",
        "is_construction_request": True,
        "plan": {
            "schema_version": "cad.construction-plan.v1", "units": "m",
            "steps": [{
                "op": "add_circle", "step_id": "center-circle-1",
                "output_ref": "center-circle-1", "layer_id": 1,
                "semantic": {
                    "object_id": "center-circle-1", "object_type": "circle",
                    "label": "中心圆",
                },
                "center": {"x": 0, "y": 0}, "radius": 1,
            }],
            "assertions": [{
                "kind": "closed", "assertion_id": "closed-center",
                "target_ref": "中心圆",
            }],
        },
        "evidence_text": ["中心圆"], "assumptions": [], "confidence": 0.9,
    }

    repaired, repairs = repair_construction_references_once(payload)

    assert repaired["plan"]["assertions"][0]["target_ref"] == "center-circle-1"
    assert repairs == [{
        "kind": "target_ref_alias", "from": "中心圆", "to": "center-circle-1",
        "assertion_id": "closed-center",
    }]
    assert payload["plan"]["assertions"][0]["target_ref"] == "中心圆"


def test_group_entity_count_alias_expands_only_when_total_is_proven() -> None:
    steps = [{
        "op": "add_rectangle", "step_id": f"aisle-{index}",
        "output_ref": f"aisle-{index}", "layer_id": 1,
        "semantic": {"object_type": "aisle", "label": f"通道{index}"},
        "origin": {"x": index * 4, "y": 0}, "width": 2, "height": 24,
        "rotation_deg": 0,
    } for index in range(1, 4)]
    payload = {
        "plan": {
            "steps": steps,
            "assertions": [{
                "kind": "entity_count", "assertion_id": "aisle-count",
                "target_ref": "aisle", "equals": 3,
            }],
        },
    }

    repaired, repairs = repair_construction_references_once(payload)

    assertions = repaired["plan"]["assertions"]
    assert [item["target_ref"] for item in assertions] == [
        "aisle-1", "aisle-2", "aisle-3",
    ]
    assert [item["equals"] for item in assertions] == [1, 1, 1]
    assert repairs[0]["kind"] == "target_ref_group_expansion"

    payload["plan"]["assertions"][0]["equals"] = 2
    unsafe, unsafe_repairs = repair_construction_references_once(payload)
    assert unsafe["plan"]["assertions"][0]["target_ref"] == "aisle"
    assert unsafe_repairs == []


def test_constraint_aliases_are_normalized_and_self_reference_is_removed() -> None:
    payload={"plan":{"steps":[{
        "op":"add_polyline","step_id":"star-outline","output_ref":"star_outline",
        "semantic":{"object_id":"star-outline","label":"五角星"},
        "vertices":[{"x":0,"y":0},{"x":1,"y":0},{"x":0,"y":1}],"closed":True,
    }],"constraints":[{
        "constraint_id":"invalid-self","kind":"concentric",
        "target_ref":"star-outline","reference_ref":"star_outline",
    }]}}

    repaired,repairs=repair_construction_references_once(payload)

    assert repaired["plan"]["constraints"]==[]
    assert any(item["kind"]=="constraint_ref_alias" for item in repairs)
    assert any(item["kind"]=="remove_self_referential_constraint" for item in repairs)
    assert payload["plan"]["constraints"]


def test_group_alias_can_match_hierarchical_output_refs_when_count_is_exact() -> None:
    payload = {
        "plan": {
            "steps": [
                {
                    "op": "add_circle", "step_id": f"column-{index}",
                    "output_ref": f"column.left.{index}", "layer_id": 1,
                    "semantic": {"object_type": "column", "label": f"柱{index}"},
                    "center": {"x": index, "y": 0}, "radius": 0.3,
                }
                for index in range(1, 4)
            ],
            "assertions": [{
                "kind": "entity_count", "assertion_id": "column-count",
                "target_ref": "column", "equals": 3,
            }],
        },
    }

    repaired, repairs = repair_construction_references_once(payload)

    assert [item["target_ref"] for item in repaired["plan"]["assertions"]] == [
        "column.left.1", "column.left.2", "column.left.3",
    ]
    assert repairs[0]["kind"] == "target_ref_group_expansion"


def test_global_entity_count_alias_repairs_only_exact_static_total() -> None:
    payload = {
        "plan": {
            "steps": [{
                "op": "add_rectangle", "step_id": f"parking-{index}",
                "output_ref": f"parking-{index}", "layer_id": 1,
                "semantic": {"object_type": "parking_space", "label": f"车位{index}"},
                "origin": {"x": index * 2.5, "y": 0}, "width": 2.5, "height": 5,
                "rotation_deg": 0,
            } for index in range(1, 4)],
            "assertions": [{
                "kind": "entity_count", "assertion_id": "all-count",
                "target_ref": "all", "equals": 3,
            }],
        },
    }

    repaired, repairs = repair_construction_references_once(payload)
    assert repaired["plan"]["assertions"][0]["target_ref"] is None
    assert repairs[0]["kind"] == "global_target_alias"

    payload["plan"]["assertions"][0]["equals"] = 4
    unsafe, unsafe_repairs = repair_construction_references_once(payload)
    assert unsafe["plan"]["assertions"][0]["target_ref"] == "all"
    assert unsafe_repairs == []


def test_wrong_single_target_assertions_are_repaired_only_from_exact_trial_facts() -> None:
    payload = {
        "plan": {
            "schema_version": "cad.construction-plan.v1", "units": "m",
            "steps": [
                {
                    "op": "add_rectangle", "step_id": f"rack-{index}",
                    "output_ref": f"rack-{index}", "layer_id": 1,
                    "semantic": {"object_type": "rack", "label": f"货架{index}"},
                    "origin": {"x": index * 2, "y": 0},
                    "width": 1.2, "height": 0.6, "rotation_deg": 0,
                }
                for index in range(2)
            ],
            "assertions": [
                {
                    "kind": "entity_count", "assertion_id": "all-count",
                    "target_ref": "rack-0", "equals": 2,
                },
                {
                    "kind": "bounds_size", "assertion_id": "all-bounds",
                    "target_ref": "rack-0", "width": 3.2, "height": 0.6,
                },
            ],
        },
    }

    repaired, repairs = repair_construction_references_once(payload)

    assert [item["target_ref"] for item in repaired["plan"]["assertions"]] == [
        None, None,
    ]
    assert [item["kind"] for item in repairs] == [
        "aggregate_assertion_scope", "aggregate_assertion_scope",
    ]


def test_open_target_closed_assertion_is_removed_and_rotated_bounds_are_normalized() -> None:
    payload = {
        "plan": {
            "schema_version": "cad.construction-plan.v1", "units": "m",
            "steps": [
                {
                    "op": "add_line", "step_id": "line", "output_ref": "line",
                    "layer_id": 1,
                    "semantic": {"object_type": "line", "label": "中心线"},
                    "start": {"x": 0, "y": 0}, "end": {"x": 2, "y": 0},
                },
                {
                    "op": "add_rectangle", "step_id": "base", "output_ref": "base",
                    "layer_id": 1,
                    "semantic": {"object_type": "base", "label": "旋转基础"},
                    "origin": {"x": 0, "y": 0}, "width": 12, "height": 8,
                    "rotation_deg": 30,
                },
            ],
            "assertions": [
                {
                    "kind": "closed", "assertion_id": "line-closed",
                    "target_ref": "line",
                },
                {
                    "kind": "bounds_size", "assertion_id": "base-size",
                    "target_ref": "base", "width": 12, "height": 8,
                },
            ],
        },
    }

    repaired, repairs = repair_construction_references_once(payload)

    assert len(repaired["plan"]["assertions"]) == 1
    bounds = repaired["plan"]["assertions"][0]
    assert round(bounds["width"], 4) == 14.3923
    assert round(bounds["height"], 4) == 12.9282
    assert [item["kind"] for item in repairs] == [
        "remove_inapplicable_closed_assertion", "rotated_bounds_normalization",
    ]


def test_global_bounds_use_single_centered_frame_when_children_are_inside() -> None:
    payload = {
        "plan": {
            "schema_version": "cad.construction-plan.v1", "units": "m",
            "steps": [
                {
                    "op": "add_centered_rectangle", "step_id": "base",
                    "output_ref": "base", "layer_id": 1,
                    "semantic": {"object_type": "base", "label": "旋转基础"},
                    "center": {"x": 0, "y": 0}, "width": 12, "height": 8,
                    "rotation_deg": 30,
                },
                {
                    "op": "add_circle", "step_id": "hole-1",
                    "output_ref": "hole-1", "layer_id": 1,
                    "semantic": {"object_type": "hole", "label": "孔1"},
                    "center": {"x": -5.299, "y": 2.232}, "radius": 0.25,
                },
                {
                    "op": "add_circle", "step_id": "hole-2",
                    "output_ref": "hole-2", "layer_id": 1,
                    "semantic": {"object_type": "hole", "label": "孔2"},
                    "center": {"x": 5.299, "y": -2.232}, "radius": 0.25,
                },
            ],
            "assertions": [{
                "kind": "bounds_size", "assertion_id": "global-bounds",
                "target_ref": None, "width": 13.723, "height": 13.723,
                "tolerance": 0.01,
            }],
        },
    }

    repaired, repairs = repair_construction_references_once(payload)

    bounds = repaired["plan"]["assertions"][0]
    assert bounds["width"] == pytest.approx(14.3923048454)
    assert bounds["height"] == pytest.approx(12.9282032303)
    assert [item["kind"] for item in repairs] == [
        "rotated_bounds_normalization",
    ]


def test_named_entity_count_binds_only_the_proven_output_group() -> None:
    payload = {
        "plan": {
            "schema_version": "cad.construction-plan.v1", "units": "m",
            "steps": [
                {
                    "op": "add_polyline", "step_id": f"room-{index}",
                    "output_ref": f"room_{index}_outline", "layer_id": 1,
                    "semantic": {
                        "object_type": "room_outline", "label": f"房间{index}",
                        "role": "room",
                    },
                    "vertices": [
                        {"x": index * 6, "y": 0}, {"x": index * 6 + 6, "y": 0},
                        {"x": index * 6 + 6, "y": 4}, {"x": index * 6, "y": 4},
                    ],
                    "closed": True,
                }
                for index in range(2)
            ] + [
                {
                    "op": "add_arc", "step_id": f"door-{index}",
                    "output_ref": f"{side}_door_arc", "layer_id": 1,
                    "semantic": {
                        "object_type": "door_swing_arc", "label": f"门弧{index}",
                        "role": "door",
                    },
                    "center": {"x": index * 6 + 1, "y": 0}, "radius": 1,
                    "start_angle": 0, "end_angle": 90,
                }
                for index, side in enumerate(("left", "right"))
            ],
            "assertions": [{
                "kind": "entity_count", "assertion_id": "door-arc-count",
                "target_ref": None, "equals": 2,
            }],
        },
    }

    repaired, repairs = repair_construction_references_once(payload)

    assertions = repaired["plan"]["assertions"]
    assert [item["target_ref"] for item in assertions] == [
        "left_door_arc", "right_door_arc",
    ]
    assert [item["equals"] for item in assertions] == [1, 1]
    assert [item["kind"] for item in repairs] == [
        "named_assertion_group_binding",
    ]


def _service(provider: str) -> RobotAgentService:
    service = object.__new__(RobotAgentService)
    service.mode = provider
    service.api_keys = {provider: "test-key"}
    service.model = "test-model"
    service.base_model = "test-model"
    service.advanced_model = "test-model"
    return service


def _factory_interpretation_json() -> str:
    return json.dumps({
        "schema_version": "cad.construction-interpretation.v1",
        "is_construction_request": True,
        "plan": {
            "schema_version": "cad.construction-plan.v1",
            "units": "m",
            "steps": [{
                "op": "add_rectangle", "step_id": "factory-main",
                "output_ref": "factory-main", "layer_id": 1,
                "semantic": {"object_type": "building", "label": "厂房主体"},
                "origin": {"x": 0, "y": 0}, "width": 20, "height": 10,
                "rotation_deg": 0,
            }],
            "assertions": [{
                "kind": "bounds_size", "assertion_id": "factory-size",
                "target_ref": "factory-main", "width": 20, "height": 10,
            }],
            "budgets": {"max_steps": 20, "max_entities": 100},
        },
        "evidence_text": ["厂房主体宽20米高10米"],
        "assumptions": [], "confidence": 0.93,
    }, ensure_ascii=False)


def test_service_rule_hit_does_not_call_provider() -> None:
    service = _service("deepseek")
    with patch.object(service, "_structured_review_text") as review:
        result = service._interpret_cad_construction_plan(
            "画一个宽5米高3米的矩形，左下角在(0,0)"
        )

    review.assert_not_called()
    assert result["status"] == "ready"
    assert result["provider_attempted"] is False
    assert result["persisted"] is False


def test_forced_structured_model_bypasses_rule_parser_for_path3_benchmark() -> None:
    service = _service("deepseek")
    command = "画一个矩形，厂房主体宽20米高10米，左下角在(0,0)"
    with patch.object(
        service,
        "_structured_review_text",
        return_value=_factory_interpretation_json(),
    ) as review:
        result = evaluate_construction_interpretation(
            service,
            command,
            force_structured_model=True,
        )

    review.assert_called_once()
    assert result["status"] == "ready"
    assert result["parser"] == "structured_model"
    assert result["provider"] == "deepseek"
    assert result["provider_attempted"] is True
    assert result["force_structured_model"] is True


def test_all_cloud_providers_share_construction_interpreter() -> None:
    providers = (
        "deepseek", "openai", "anthropic", "gemini",
        "qwen", "kimi", "glm", "minimax",
    )
    for provider in providers:
        service = _service(provider)
        with patch.object(
            service, "_structured_review_text",
            return_value=_factory_interpretation_json(),
        ) as review:
            result = service._interpret_cad_construction_plan(
                "创建厂房主体宽20米高10米，并预留后续内部隔断"
            )

        review.assert_called_once()
        assert result["status"] == "ready", provider
        assert result["provider"] == provider
        assert result["provider_attempted"] is True
        assert result["trial_result"]["feasibility"]["ok"] is True
        assert result["production_interpreter"] is True


def test_experimental_construction_does_not_retry_provider_failure() -> None:
    service = _service("qwen")
    with patch.object(
        service, "_structured_review_text",
        side_effect=RuntimeError("provider unavailable"),
    ) as review:
        result = evaluate_construction_interpretation(service, "创建复杂厂房总图")

    review.assert_called_once()
    assert result["status"] == "invalid"
    assert result["error"]["code"] == "invalid_model_output"
    assert result["provider_attempted"] is True


def test_experimental_construction_retries_unparseable_json_once() -> None:
    service = _service("deepseek")
    with patch.object(
        service, "_structured_review_text",
        side_effect=["这不是 JSON", _factory_interpretation_json()],
    ) as review:
        result = evaluate_construction_interpretation(
            service,
            "创建厂房主体宽20米高10米，并预留后续内部隔断"
        )

    assert review.call_count == 2
    assert result["status"] == "ready"
    assert result["request_attempts"] == 2
    assert result["structured_retry_used"] is True


def test_experimental_construction_stops_after_second_invalid_json() -> None:
    service = _service("deepseek")
    with patch.object(
        service, "_structured_review_text",
        side_effect=["第一次不是 JSON", "第二次仍不是 JSON"],
    ) as review:
        result = evaluate_construction_interpretation(service, "创建复杂厂房总图")

    assert review.call_count == 2
    assert result["status"] == "invalid"
    assert result["request_attempts"] == 2
    assert result["structured_retry_used"] is True
    assert "连续两次" in result["error"]["message"]


def test_local_mode_stays_rule_only_for_complex_request() -> None:
    service = _service("local")
    service.api_keys = {}
    with patch.object(service, "_structured_review_text") as review:
        result = service._interpret_cad_construction_plan("创建复杂厂房总图")

    review.assert_not_called()
    assert result["status"] == "clarification_required"
    assert result["provider_attempted"] is False


def _sketch_graph_interpretation_payload() -> dict:
    return {
        "schema_version": "cad.sketchgraph-interpretation.v1",
        "is_construction_request": True,
        "candidate_set": {
            "schema_version": "cad.sketchgraph-candidates.v1",
            "requirement": "将由解释器绑定到用户原文",
            "candidates": [
                {
                    "candidate_id": "single-hall",
                    "title": "单跨厂房",
                    "rationale": "一个连续矩形主体，内部不设分跨。",
                    "plan": {
                        "schema_version": "cad.construction-plan.v1",
                        "units": "m",
                        "steps": [{
                            "op": "add_rectangle", "step_id": "hall",
                            "output_ref": "hall", "layer_id": 1,
                            "semantic": {
                                "object_type": "building", "label": "单跨厂房",
                            },
                            "origin": {"x": 0, "y": 0},
                            "width": 20, "height": 10, "rotation_deg": 0,
                        }],
                        "assertions": [{
                            "kind": "bounds_size", "assertion_id": "hall-size",
                            "target_ref": "hall", "width": 20, "height": 10,
                        }],
                    },
                },
                {
                    "candidate_id": "two-halls",
                    "title": "双跨厂房",
                    "rationale": "两个并列矩形形成双跨结构。",
                    "plan": {
                        "schema_version": "cad.construction-plan.v1",
                        "units": "m",
                        "steps": [
                            {
                                "op": "add_rectangle", "step_id": "left",
                                "output_ref": "left", "layer_id": 1,
                                "semantic": {
                                    "object_type": "building", "label": "左跨",
                                },
                                "origin": {"x": 0, "y": 0},
                                "width": 9, "height": 10, "rotation_deg": 0,
                            },
                            {
                                "op": "add_rectangle", "step_id": "right",
                                "output_ref": "right", "layer_id": 1,
                                "semantic": {
                                    "object_type": "building", "label": "右跨",
                                },
                                "origin": {"x": 11, "y": 0},
                                "width": 9, "height": 10, "rotation_deg": 0,
                            },
                        ],
                        "assertions": [{
                            "kind": "entity_count", "assertion_id": "two-spans",
                            "target_ref": None, "equals": 2,
                        }],
                    },
                },
            ],
        },
        "evidence_text": ["厂房主体宽20米高10米"],
        "assumptions": [],
        "confidence": 0.91,
    }


def test_sketch_graph_schema_and_interpreter_return_two_ranked_candidates() -> None:
    schema = sketch_graph_interpretation_json_schema()
    assert schema["additionalProperties"] is False

    def callback(_text: str, supplied_schema: dict) -> dict:
        assert supplied_schema["properties"]["candidate_set"]
        return _sketch_graph_interpretation_payload()

    source = "创建厂房主体宽20米高10米，并比较单跨和双跨结构"
    result = interpret_sketch_graph_candidates(source, callback)

    assert result["status"] == "ready"
    assert result["candidate_set"]["requirement"] == source
    assert result["evaluation"]["candidate_count"] == 2
    assert result["evaluation"]["valid_candidate_count"] == 2
    assert result["evaluation"]["recommended_candidate_id"] in {
        "single-hall", "two-halls",
    }


def test_sketch_graph_rejects_model_that_returns_only_one_candidate() -> None:
    payload = _sketch_graph_interpretation_payload()
    payload["candidate_set"]["candidates"] = [
        payload["candidate_set"]["candidates"][0],
    ]

    result = interpret_sketch_graph_candidates(
        "创建厂房主体宽20米高10米", lambda _text, _schema: payload,
    )

    assert result["status"] == "invalid"
    assert result["error"]["code"] == "invalid_model_output"


def test_sketch_graph_keeps_valid_candidate_when_another_fails_execution() -> None:
    payload = _sketch_graph_interpretation_payload()
    payload["candidate_set"]["candidates"][0]["plan"] = {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [{
            "op": "add_composite_path", "step_id": "broken",
            "output_ref": "broken", "layer_id": 1,
            "semantic": {"object_type": "path", "label": "断开的轮廓"},
            "segments": [
                {
                    "kind": "line", "start": {"x": 0, "y": 0},
                    "end": {"x": 1, "y": 0},
                },
                {
                    "kind": "line", "start": {"x": 2, "y": 0},
                    "end": {"x": 3, "y": 0},
                },
            ],
        }],
    }

    result = interpret_sketch_graph_candidates(
        "创建厂房主体宽20米高10米", lambda _text, _schema: payload,
    )

    assert result["status"] == "ready"
    assert result["evaluation"]["invalid_candidate_count"] == 1
    assert result["evaluation"]["valid_candidate_count"] == 1
    assert result["evaluation"]["recommended_candidate_id"] == "two-halls"


def test_service_experimental_alternatives_uses_sketch_graph_schema() -> None:
    service = _service("deepseek")
    response = json.dumps(
        _sketch_graph_interpretation_payload(), ensure_ascii=False,
    )
    with patch.object(
        service, "_structured_review_text", return_value=response,
    ) as review:
        result = evaluate_construction_interpretation(
            service,
            "创建厂房主体宽20米高10米，并比较单跨和双跨结构",
            alternatives=True,
        )

    review.assert_called_once()
    assert result["status"] == "ready"
    assert result["candidate_mode"] is True
    assert result["evaluation"]["candidate_count"] == 2
    assert result["persisted"] is False
