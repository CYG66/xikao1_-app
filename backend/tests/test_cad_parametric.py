import math

import pytest

from app.cad_parametric import ParametricError, expression, sample_curve
from app.cad_construction import ConstructionPlanError, execute_construction_plan
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_parametric import polar_requirements, verify_polar_requirements


def plan(x="t*cos(t)/(3*pi)", y="t*sin(t)/(3*pi)", **extra):
    return {"units": "m", "steps": [{"op": "add_parametric_curve", "step_id": "curve",
        "output_ref": "curve", "semantic": {"label": "参数曲线"}, "x_expression": x,
        "y_expression": y, "t_start": "0", "t_end": "6*pi", **extra}]}


@pytest.mark.parametrize("source", [
    "__import__('os')", "t.__class__", "[t][0]", "(lambda: 0)()", "sin(t, t)",
    "sin(x=t)", "[x for x in t]", "True", "1e999", "unknown(t)", "t if t else 0",
])
def test_rejects_non_arithmetic_syntax(source):
    with pytest.raises(ParametricError):
        expression(source)


@pytest.mark.parametrize("source", ["1/0", "sqrt(-1)", "(-1)**0.5", "2**1000000", "exp(1000)"])
def test_rejects_nonfinite_or_unbounded_evaluation(source):
    with pytest.raises(ParametricError):
        expression(source)(0)


def test_schema_failure_also_reports_both_undefined_curve_parameters():
    broken=plan('a*cos(t)','b*sin(t)',closed=True)
    broken['free_outline_layout']=[{'target_ref':'curve','width':3}]
    result=interpret_construction_request('画一个闭合参数轮廓，最大宽度3米',lambda *_:{
        'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
        'plan':broken,'confidence':.99,'evidence_text':[],'assumptions':['a=1.5,b=1']},
        force_structured_model=True)
    assert result['status']=='invalid'
    detail=result['construction_error']['details']
    assert any('free_outline_layout' in e['path'] for e in detail['field_errors'])
    assert {e['path'][-1] for e in detail['expression_errors']}=={'x_expression','y_expression'}
    assert 'a' in detail['expression_errors'][0]['message']
    assert result['rejected_plan']['steps'][0]['x_expression']=='a*cos(t)'


def test_expression_failure_reports_all_invalid_steps_without_running_code():
    from copy import deepcopy
    broken=plan('a*cos(t)','b*sin(t)')
    second=deepcopy(broken['steps'][0]);second.update(step_id='other',output_ref='other',x_expression='c*cos(t)',y_expression='sin(t)')
    broken['steps'].append(second)
    with pytest.raises(ConstructionPlanError) as failure:
        execute_construction_plan(broken)
    assert failure.value.code=='invalid_parametric_curve'
    details=failure.value.details
    assert details['affected_output_refs']==['curve','other']
    assert len(details['expression_errors'])==3
    assert all(e['path'][-1] in {'x_expression','y_expression'} for e in details['expression_errors'])


def test_spiral_formula_computes_three_turns_with_linear_radial_growth():
    result = execute_construction_plan(plan())
    points = result["geometries"][0]["vertices"]
    assert len(points) <= 500
    assert points[0]["x"] == points[0]["y"] == 0
    angles = []
    for p in points[1:]:
        a = math.atan2(p["y"], p["x"])
        if angles:
            while a < angles[-1]-math.pi:
                a += math.tau
        angles.append(a)
        assert math.hypot(p["x"], p["y"]) == pytest.approx(a/(3*math.pi)*1000, abs=1e-6)
    assert angles[-1] == pytest.approx(6*math.pi)
    assert math.hypot(points[-1]["x"], points[-1]["y"]) == pytest.approx(2000)


@pytest.mark.parametrize('gap_reference,expected_x',[('center',6000),('edge',9000)])
def test_relative_curve_translation_preserves_size_and_sampling(gap_reference,expected_x):
    from copy import deepcopy
    base=plan('2*cos(t)','sin(t)',closed=True)
    base['steps'][0]['t_end']='2*pi'
    second=deepcopy(base['steps'][0]);second.update(step_id='second',output_ref='second',x_expression='cos(t)')
    base['steps'].append(second)
    unchanged=execute_construction_plan(base)
    base['free_outline_layout']=[{'target_ref':'second','right_of_ref':'curve','gap':6,'gap_reference':gap_reference}]
    result=execute_construction_plan(base)
    before=unchanged['geometries'][1]['vertices'];after=result['geometries'][1]['vertices']
    assert result['geometries'][0]==unchanged['geometries'][0]
    assert len(before)==len(after)
    assert all(p['x']-q['x']==pytest.approx(expected_x,abs=1e-8) and p['y']==q['y'] for q,p in zip(before,after))
    assert result['curve_quality'][1]['post_layout_sampling_error_bound']==result['curve_quality'][1]['observed_sampling_error']


def test_center_only_parametric_translation_does_not_require_resize_dimensions():
    base=plan('cos(t)','sin(t)',closed=True)
    base['steps'][0]['t_end']='2*pi'
    base['free_outline_layout']=[{'target_ref':'curve','center':{'x':3,'y':4}}]
    result=execute_construction_plan(base)
    assert max(p['x'] for p in result['geometries'][0]['vertices'])==pytest.approx(4000)
    assert max(p['y'] for p in result['geometries'][0]['vertices'])==pytest.approx(5000)


def test_layout_still_rejects_partial_resize_and_conflicting_placement():
    from app.cad_construction import FreeOutlineLayout
    for layout in ({'target_ref':'curve','width':3},
                   {'target_ref':'curve','center':{'x':0,'y':0},'right_of_ref':'other'},
                   {'target_ref':'curve'}):
        with pytest.raises(ValueError):
            FreeOutlineLayout.model_validate(layout)


def test_same_executor_handles_sinusoid_and_closed_circle():
    points, error = sample_curve("t", "0.5*sin(2*pi*t)", 0, 5, .001)
    assert error <= .001
    assert max(p[1] for p in points) == pytest.approx(.5, abs=.001)
    result = execute_construction_plan(plan("cos(t)", "sin(t)", t_end="2*pi", closed=True))
    assert result["geometries"][0]["closed"] is True


@pytest.mark.parametrize("extra", [{"t_end": "t+1"}, {"t_end": "-1"}, {"closed": True},
                                   {"max_sampling_error": 1e-12}])
def test_invalid_interval_closure_and_unattainable_accuracy_fail(extra):
    with pytest.raises(ConstructionPlanError):
        execute_construction_plan(plan(**extra))


def test_adaptive_result_matches_dense_independent_reference():
    points, _ = sample_curve("t*cos(t)/(3*pi)", "t*sin(t)/(3*pi)", 0, 6*math.pi, .001)
    for i in range(1001):
        t = 6*math.pi*i/1000
        p = (t*math.cos(t)/(3*math.pi), t*math.sin(t)/(3*math.pi))
        def distance(a, b):
            dx, dy = b[0]-a[0], b[1]-a[1]
            u = max(0, min(1, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
            return math.dist(p, (a[0]+u*dx, a[1]+u*dy))
        assert min(distance(a,b) for a,b in zip(points,points[1:])) <= .0011


@pytest.mark.parametrize("phase,direction", [(0,1), (1.2,1), (-2,-1)])
def test_source_checks_accept_arbitrary_initial_orientation(phase, direction):
    payload = plan(f"t*cos({direction}*t+{phase})/(3*pi)",
                   f"t*sin({direction}*t+{phase})/(3*pi)")
    req = polar_requirements("生成阿基米德螺旋线，从(0,0)出发，旋转3圈，最大半径2米")
    verify_polar_requirements(req, execute_construction_plan(payload)["geometries"])


def test_source_requirement_check_rejects_model_self_consistent_wrong_turn_count():
    text = "生成一个阿基米德螺旋线，从(0,0)出发，旋转3圈，最大半径2米"
    wrong = plan("t*cos(t)/pi", "t*sin(t)/pi", t_end="2*pi")
    payload = {"schema_version": "cad.construction-interpretation.v1",
               "is_construction_request": True, "plan": wrong,
               "evidence_text": [text], "assumptions": [], "confidence": .99}
    result = interpret_construction_request(text, model_callback=lambda *_: payload)
    assert result["status"] == "invalid"
    assert result["construction_error"]["code"] == "source_requirement_mismatch"
    assert "1圈" in result["construction_error"]["message"]


def test_high_frequency_curve_cannot_hide_between_uniform_sample_points():
    with pytest.raises(ParametricError, match="预算"):
        sample_curve("t", "sin(512*pi*t)", 0, 1, .001)
