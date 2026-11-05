from __future__ import annotations


def test_rotational_arc_reports_wrong_wrap_direction_before_expansion():
    from copy import deepcopy
    import pytest
    from app.cad_construction import execute_construction_plan,ConstructionPlanError
    plan={'units':'m','steps':[{'op':'add_rotational_path','step_id':'ring','output_ref':'ring',
        'semantic':{'label':'周期圆弧'},'count':8,'center':{'x':0,'y':0},
        'direction':'counterclockwise','constrain_sector_end':True,
        'segments':[{'kind':'arc','center':{'x':0,'y':0},'radius':1,
                     'start_angle':0,'end_angle':45,'clockwise':True}]}]}
    with pytest.raises(ConstructionPlanError) as caught:execute_construction_plan(plan)
    assert caught.value.code=='rotational_arc_overlaps_period'
    assert caught.value.details['seed_segment_index']==0
    assert caught.value.details['arc_sweep_degrees']==315
    assert caught.value.details['period_degrees']==45
    assert caught.value.details['opposite_direction_sweep_degrees']==45
    correct=deepcopy(plan);correct['steps'][0]['segments'][0]['clockwise']=False
    assert execute_construction_plan(correct)['feasibility']['ok']


def test_rotational_crossing_reports_original_seed_segment_indices():
    from app.cad_construction import execute_construction_plan,ConstructionPlanError
    import math,pytest
    def p(radius,angle):return {'x':radius*math.cos(math.radians(angle)),'y':radius*math.sin(math.radians(angle))}
    plan={'units':'m','steps':[{'op':'add_rotational_path','step_id':'period','output_ref':'profile',
        'semantic':{'label':'周期边界'},'center':{'x':0,'y':0},'count':8,'direction':'auto',
        'constrain_sector_end':True,'segments':[
            {'kind':'line','start':p(.75,45),'end':p(.75,22.5)},
            {'kind':'line','start':p(.75,22.5),'end':p(1,15)},
            {'kind':'arc','center':{'x':0,'y':0},'radius':1,'start_angle':15,'end_angle':30},
            {'kind':'line','start':p(1,30),'end':p(.75,22.5)}]}]}
    with pytest.raises(ConstructionPlanError) as caught:execute_construction_plan(plan)
    assert caught.value.code=='self_intersecting_composite_path'
    details=caught.value.details
    assert details['seed_segment_count']==4 and details['rotation_count']==8
    assert len(details['conflicts'])==8
    assert all(pair['seed_segment_indices']==[1,3] for pair in details['conflicts'])


def test_zero_sweep_arc_is_distinct_from_an_explicit_full_circle():
    from app.cad_construction import execute_construction_plan,ConstructionPlanError
    from copy import deepcopy
    import pytest
    plan={'units':'m','steps':[{'op':'add_composite_path','step_id':'arc','output_ref':'arc',
        'semantic':{'label':'圆弧'},'closed':True,'segments':[{
            'kind':'arc','center':{'x':0,'y':0},'radius':1,'start_angle':22.5,'end_angle':22.5}]}]}
    with pytest.raises(ConstructionPlanError) as caught:execute_construction_plan(plan)
    assert caught.value.code=='zero_sweep_composite_arc'
    assert caught.value.details['segment_index']==0
    full=deepcopy(plan)
    full['steps'][0]['segments'][0]['end_angle']=382.5
    assert execute_construction_plan(full)['feasibility']['ok']


def test_rotational_arc_segments_execute_without_bezier_control_points():
    from app.cad_construction import execute_construction_plan
    plan={'units':'m','steps':[{'op':'add_rotational_path','step_id':'ring','output_ref':'ring',
        'semantic':{'label':'旋转圆弧'},'count':2,'constrain_sector_end':True,
        'center':{'x':0,'y':0},'segments':[{'kind':'arc','center':{'x':0,'y':0},
            'radius':1,'start_angle':0,'end_angle':180,'clockwise':False}]}]}
    result=execute_construction_plan(plan)
    assert result['geometries'][0]['closed']
    assert result['feasibility']['ok']
    import math
    assert all(abs(math.hypot(p['x'],p['y'])-1000)<.001 for p in result['geometries'][0]['vertices'])


def test_rotational_arc_keeps_circle_constraints_and_rotates_centers():
    from app.cad_construction import AddRotationalPathStep,_expand_rotational_path,ConstructionPlanError
    import pytest
    data={'op':'add_rotational_path','step_id':'arcs','output_ref':'arcs',
        'semantic':{'label':'圆弧'},'count':4,'center':{'x':0,'y':0},
        'segments':[{'kind':'arc','center':{'x':1,'y':0},'radius':1,
                     'start_angle':0,'end_angle':90,'clockwise':False}]}
    step=AddRotationalPathStep.model_validate(data)
    expanded=_expand_rotational_path(step)
    assert expanded.segments[1].center.x==pytest.approx(0,abs=1e-10)
    assert expanded.segments[1].center.y==pytest.approx(1)
    assert expanded.segments[1].start_angle==90
    assert expanded.segments[1].radius==1
    data['constrain_sector_end']=True
    with pytest.raises(ConstructionPlanError) as error:
        _expand_rotational_path(AddRotationalPathStep.model_validate(data))
    assert error.value.code=='sector_arc_endpoint_conflict'


def test_parametric_sampling_accounts_for_final_layout_amplification():
    from app.cad_construction import execute_construction_plan
    plan={'units':'m','steps':[{'op':'add_parametric_curve','step_id':'curve','output_ref':'curve',
        'semantic':{'label':'自由周期曲线'},'x_expression':'2*cos(t)','y_expression':'sin(t)',
        't_start':'0','t_end':'2*pi','closed':True,'max_sampling_error':.001}],
        'free_outline_layout':[{'target_ref':'curve','width':5,'height':5}]}
    result=execute_construction_plan(plan)
    quality=result['curve_quality'][0]
    assert quality['pre_layout_sampling_tolerance']<.001
    assert quality['post_layout_sampling_error_bound']<=quality['max_sampling_error']==.001
    assert plan['steps'][0]['x_expression']=='2*cos(t)'


def test_safe_constant_expressions_are_supported_by_all_float_fields():
    plan = CadConstructionPlan.model_validate({
        "steps": [{
            "op": "add_rectangle", "step_id": "box", "output_ref": "box",
            "semantic": _semantic("矩形"), "origin": {"x": 0, "y": 0},
            "width": "2*sin(pi/2)", "height": "sqrt(4)",
        }],
        "assertions": [{
            "kind": "bounds_size", "assertion_id": "size", "target_ref": "box",
            "width": "2*sin(pi/2)", "height": "sqrt(4)", "tolerance": "1/1000",
        }],
    })
    assert plan.steps[0].width == 2
    assert plan.assertions[0].tolerance == .001
    with pytest.raises(ValidationError, match="不能依赖参数t"):
        CadConstructionPlan.model_validate({
            "steps": [{
                "op": "add_rectangle", "step_id": "box", "output_ref": "box",
                "semantic": _semantic("矩形"), "origin": {"x": 0, "y": 0},
                "width": "t+1", "height": 2,
            }],
        })

import math
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.cad_construction import (
    CadConstructionPlan,
    ConstructionPlanError,
    construction_plan_json_schema,
    execute_construction_plan,
)


def _semantic(label: str, object_type: str = "court_part") -> dict:
    return {"label": label, "object_type": object_type}


@pytest.mark.parametrize('bad_bounds',[False,True])
def test_duplicate_part_ids_report_all_members_even_when_bounds_also_fail(bad_bounds):
    plan={'units':'m','steps':[{'op':'add_line','step_id':f's{i}','output_ref':f'r{i}',
        'semantic':{'label':label,'object_id':'outline','assembly_id':'whole','assembly_label':'图案'},
        'start':{'x':i,'y':0},'end':{'x':i,'y':1}} for i,label in enumerate(['左笔画','右笔画'])]}
    if bad_bounds:plan['assertions']=[{'kind':'bounds_size','assertion_id':'size','width':2,'height':1}]
    original=deepcopy(plan)
    with pytest.raises(ConstructionPlanError) as error:execute_construction_plan(plan)
    exc=error.value
    assert exc.code==('assertion_failed' if bad_bounds else 'logical_graph_invalid')
    detail=exc.details['logical_graph_validation'] if bad_bounds else exc.details
    assert detail['identity_conflicts'][0]['object_id']=='outline'
    assert [m['source_steps'][0]['output_ref'] for m in detail['identity_conflicts'][0]['members']]==['r0','r1']
    assert plan==original
    # Repairing only identity preserves all geometry, labels and whole ownership.
    fixed=deepcopy(plan);fixed.pop('assertions',None)
    for step in fixed['steps']:step['semantic'].pop('object_id')
    result=execute_construction_plan(fixed)
    assert len({o['object_id'] for o in result['logical_objects']})==2
    assert {o['assembly_id'] for o in result['logical_objects']}=={'whole'}
    assert len(result['geometries'])==2


@pytest.mark.parametrize("count", [3, 5, 7])
@pytest.mark.parametrize("clockwise", [False, True])
def test_rotational_path_reuses_one_sector_and_validates_completed_boundary(count, clockwise):
    angle = math.pi / count
    start = {"x": math.cos(angle), "y": -math.sin(angle)}
    end = {"x": start["x"], "y": -start["y"]}
    step = {"op": "add_rotational_path", "step_id": "periodic", "output_ref": "outline",
            "semantic": _semantic("周期边界"), "count": count, "center": {"x": 0, "y": 0},
            "fit_width": 5, "fit_height": 5, "continuity": "C1", "segments": [
        {"kind": "bezier", "control_points": [start,
            {"x": start["x"]+.5*math.sin(angle), "y": start["y"]+.5*math.cos(angle)},
            {"x": 2, "y": -.5}, {"x": 2, "y": 0}]},
        {"kind": "bezier", "control_points": [{"x": 2, "y": 0}, {"x": 2, "y": .5},
            {"x": end["x"]+.5*math.sin(angle), "y": end["y"]-.5*math.cos(angle)}, end]},
    ]}
    if clockwise:
        for segment in step["segments"]:
            for point in segment["control_points"]:
                point["y"] = -point["y"]
    plan = {"steps": [step], "assertions": [
        {"kind": "entity_count", "assertion_id": "one", "equals": 1},
        {"kind": "bounds_size", "assertion_id": "size", "width": 5, "height": 5},
        {"kind": "radial_pattern", "assertion_id": "repeat", "target_ref": "outline", "lobes": count},
    ]}
    source = deepcopy(plan)
    result = execute_construction_plan(plan)
    assert plan == source
    assert len(result["geometries"]) == 1
    assert result["curve_quality"][0]["c1"] is True
    assert len(result["geometries"][0]["vertices"]) <= 500
    plan["steps"][0]["segments"][1]["control_points"][-1]["x"] += .1
    with pytest.raises(ConstructionPlanError, match="端点未连接"):
        execute_construction_plan(plan)
    plan["steps"][0]["constrain_sector_end"] = True
    constrained = execute_construction_plan(plan)
    assert constrained["curve_quality"][0]["c1"] is True
    assert constrained["assertions"]["ok"] is True


def test_polygonal_radial_failure_reports_peak_valley_topology():
    plan = {
        "steps": [{
            "op": "add_rotational_path", "step_id": "regular-polygon", "output_ref": "outline",
            "semantic": _semantic("径向多边形"), "center": {"x": 0, "y": 0}, "count": 5,
            "closed": True, "direction": "counterclockwise", "constrain_sector_end": True,
            "segments": [
                {"kind": "line", "start": {"x": 0, "y": 2}, "end": {"x": -1.1755705, "y": 1.618034}},
                {"kind": "line", "start": {"x": -1.1755705, "y": 1.618034}, "end": {"x": -1.902113, "y": .618034}},
            ],
        }],
        "assertions": [{
            "kind": "radial_pattern", "assertion_id": "peaks", "target_ref": "outline",
            "lobes": 5, "profile": "polygonal",
        }],
    }

    with pytest.raises(ConstructionPlanError) as failure:
        execute_construction_plan(plan)

    assert failure.value.code == "assertion_failed"
    assert failure.value.details["observed_radial_peaks"] != 5
    assert "外峰" in failure.value.details["required_topology"]


def test_translated_polygon_sector_rejects_wrong_rotation_center():
    angle = math.pi / 5
    outer = 2.0
    inner = 0.76
    plan = {"steps": [{
        "op": "add_rotational_path", "step_id": "translated", "output_ref": "outline",
        "semantic": _semantic("平移后的径向多边形"), "center": {"x": 0, "y": 0},
        "count": 5, "direction": "counterclockwise", "constrain_sector_end": True,
        "segments": [
            {"kind": "line", "start": {"x": 6, "y": outer},
             "end": {"x": 6 + inner * math.cos(math.pi / 2 + angle),
                     "y": inner * math.sin(math.pi / 2 + angle)}},
            {"kind": "line",
             "start": {"x": 6 + inner * math.cos(math.pi / 2 + angle),
                       "y": inner * math.sin(math.pi / 2 + angle)},
             "end": {"x": 6 + outer * math.cos(math.pi / 2 + 2 * angle),
                     "y": outer * math.sin(math.pi / 2 + 2 * angle)}},
        ],
    }]}
    with pytest.raises(ConstructionPlanError) as failure:
        execute_construction_plan(plan)
    assert failure.value.code in {"self_intersecting_composite_path", "drawing_infeasible"}
    plan["steps"][0]["center"] = {"x": 6, "y": 0}
    assert len(execute_construction_plan(plan)["geometries"]) == 1


def test_center_distance_assertion_measures_final_layout_geometry():
    plan = {
        "steps": [
            {"op": "add_circle", "step_id": "left", "output_ref": "left",
             "semantic": _semantic("左圆"), "center": {"x": 0, "y": 0}, "radius": 1},
            {"op": "add_circle", "step_id": "right", "output_ref": "right",
             "semantic": _semantic("右圆"), "center": {"x": 6, "y": 0}, "radius": 1},
        ],
        "assertions": [{
            "kind": "center_distance", "assertion_id": "spacing",
            "target_ref": "left", "reference_ref": "right", "distance": "3*2",
        }],
    }
    result = execute_construction_plan(plan)
    assert result["assertions"]["ok"] is True
    plan["assertions"][0]["distance"] = 5
    with pytest.raises(ConstructionPlanError, match="实际中心距 6"):
        execute_construction_plan(plan)


def test_executor_allocates_sampling_budget_and_still_enforces_accuracy() -> None:
    step = {
        "step_id": "boundary", "output_ref": "boundary", "op": "add_composite_path",
        "samples_per_curve": 128, "semantic": _semantic("连续曲线"),
        "segments": [{"kind": "bezier", "control_points": [
            {"x": i, "y": 0}, {"x": i + .25, "y": .2},
            {"x": i + .75, "y": .2}, {"x": i + 1, "y": 0},
        ]} for i in range(4)],
    }
    result = execute_construction_plan({"steps": [step]})
    quality = result["curve_quality"][0]
    assert quality["requested_samples_per_curve"] == 128
    assert quality["effective_samples_per_curve"] == 124
    assert quality["sampled_point_count"] == 497
    assert result["geometries"][0]["vertices"][-1]["x"] == 4000
    step["max_sampling_error"] = 1e-10
    with pytest.raises(ConstructionPlanError) as failure:
        execute_construction_plan({"steps": [step]})
    assert failure.value.code == "sampling_error_exceeded"


@pytest.mark.parametrize("units,factor", [("m",1),("mm",1000)])
def test_executor_refines_under_sampled_curve_without_relaxing_error(units, factor):
    step={"step_id":"curve","output_ref":"curve","op":"add_composite_path",
          "samples_per_curve":8,"max_sampling_error":.001*factor,
          "semantic":_semantic("曲线"),"segments":[{"kind":"bezier","control_points":[
              {"x":x*factor,"y":y*factor} for x,y in [(0,0),(0,4),(4,4),(4,0)]]}]}
    source=deepcopy(step)
    result=execute_construction_plan({"units":units,"steps":[step]})
    quality=result["curve_quality"][0]
    assert quality["effective_samples_per_curve"] > 8
    assert quality["maximum_sampling_error"] <= .001*factor
    assert quality["sampled_point_count"] <= 500
    assert step==source
    # Check the persisted mm polyline against independent analytic points.
    points=result["geometries"][0]["vertices"]
    for i in range(1001):
        t=i/1000
        x,y=4000*(3*t*t-2*t*t*t),12000*t*(1-t)
        distances=[]
        for a,b in zip(points,points[1:]):
            dx,dy=b["x"]-a["x"],b["y"]-a["y"]
            u=max(0,min(1,((x-a["x"])*dx+(y-a["y"])*dy)/(dx*dx+dy*dy)))
            distances.append(math.hypot(x-a["x"]-u*dx,y-a["y"]-u*dy))
        assert min(distances)<=1.001


def test_layout_cannot_silently_amplify_curve_error_past_limit():
    plan={"steps":[{"step_id":"curve","output_ref":"curve","op":"add_composite_path",
          "closed":True,"samples_per_curve":8,"max_sampling_error":.001,
          "semantic":_semantic("曲线"),"segments":[
              {"kind":"bezier","control_points":[{"x":x,"y":y} for x,y in [(0,0),(0,4),(4,4),(4,0)]]},
              {"kind":"line","start":{"x":4,"y":0},"end":{"x":0,"y":0}}]}]}
    execute_construction_plan(plan)
    plan["free_outline_layout"]=[{"target_ref":"curve","width":400,"height":300}]
    with pytest.raises(ConstructionPlanError) as failure:
        execute_construction_plan(plan)
    assert failure.value.code=="sampling_error_exceeded"
    assert failure.value.details["sampling_error_bound"]>.001


def test_constructs_existing_cad_ir_with_symbols_and_logical_objects() -> None:
    result = execute_construction_plan({
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [
            {
                "step_id": "boundary", "op": "add_rectangle",
                "output_ref": "court.boundary", "origin": {"x": 0, "y": 0},
                "width": 28, "height": 15,
                "semantic": _semantic("篮球场外框", "court_boundary"),
            },
            {
                "step_id": "center-line", "op": "add_line",
                "output_ref": "court.center_line",
                "start": {"x": 14, "y": 0}, "end": {"x": 14, "y": 15},
                "semantic": _semantic("中线", "center_line"),
            },
            {
                "step_id": "center-circle", "op": "add_circle",
                "output_ref": "court.center_circle",
                "center": {"x": 14, "y": 7.5}, "radius": 1.8,
                "semantic": _semantic("中心圆", "center_circle"),
            },
        ],
        "assertions": [
            {"kind": "entity_count", "assertion_id": "count", "equals": 3},
            {
                "kind": "bounds_size", "assertion_id": "size",
                "target_ref": "court.boundary", "width": 28, "height": 15,
            },
            {"kind": "closed", "assertion_id": "closed", "target_ref": "court.boundary"},
        ],
    })

    assert result["schema"] == "cad.construction-result.v1"
    assert [item["type"] for item in result["geometries"]] == ["polyline", "line", "circle"]
    assert result["symbol_table"]["court.center_circle"] == [3]
    assert [item["label"] for item in result["logical_objects"]] == ["篮球场外框", "中线", "中心圆"]
    assert result["graph_validation"]["verified"] is True
    assert result["feasibility"]["ok"] is True


def test_centered_rectangle_rotates_around_declared_center() -> None:
    result = execute_construction_plan({
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [{
            "step_id": "foundation",
            "op": "add_centered_rectangle",
            "output_ref": "foundation",
            "center": {"x": 10, "y": -2},
            "width": 6,
            "height": 4,
            "rotation_deg": 30,
            "semantic": _semantic("设备基础", "equipment_foundation"),
        }],
        "assertions": [{
            "kind": "closed", "assertion_id": "closed",
            "target_ref": "foundation",
        }],
    })

    geometry = result["geometries"][0]
    vertices = geometry["vertices"]
    center_x = sum(value["x"] for value in vertices) / len(vertices)
    center_y = sum(value["y"] for value in vertices) / len(vertices)
    assert center_x == pytest.approx(10000)
    assert center_y == pytest.approx(-2000)
    bounds = result["logical_objects"][0]["bounds"]
    assert bounds["max_x"] - bounds["min_x"] == pytest.approx(
        (6 * math.cos(math.radians(30)) + 4 * math.sin(math.radians(30))) * 1000
    )
    assert bounds["max_y"] - bounds["min_y"] == pytest.approx(
        (6 * math.sin(math.radians(30)) + 4 * math.cos(math.radians(30))) * 1000
    )


def test_bezier_and_bspline_preserve_curve_ir() -> None:
    result = execute_construction_plan({
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [
            {
                "step_id": "quadratic", "op": "add_bezier",
                "output_ref": "curve.quadratic",
                "control_points": [
                    {"x": 0, "y": 0}, {"x": 2, "y": 3}, {"x": 4, "y": 0},
                ],
                "semantic": _semantic("二次贝塞尔曲线", "bezier_curve"),
            },
            {
                "step_id": "spline", "op": "add_spline",
                "output_ref": "curve.spline", "degree": 3,
                "control_points": [
                    {"x": 5, "y": 0}, {"x": 6, "y": 2},
                    {"x": 8, "y": 2}, {"x": 9, "y": 0},
                ],
                "semantic": _semantic("三次样条曲线", "spline_curve"),
            },
        ],
    })

    assert [item["type"] for item in result["geometries"]] == ["spline", "spline"]
    assert result["geometries"][0]["degree"] == 2
    assert result["geometries"][1]["degree"] == 3
    assert result["geometries"][0]["control_points"][1] == {
        "x": 2000.0, "y": 3000.0, "z": 0.0,
    }


def test_composite_bezier_path_builds_closed_heart_outline() -> None:
    result = execute_construction_plan({
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [{
            "step_id": "heart", "op": "add_composite_path",
            "output_ref": "heart.outline", "closed": True,
            "samples_per_curve": 32,
            "segments": [
                {
                    "kind": "bezier",
                    "control_points": [
                        {"x": 0, "y": 2}, {"x": -4, "y": 5},
                        {"x": -5, "y": -1}, {"x": 0, "y": -4},
                    ],
                },
                {
                    "kind": "bezier",
                    "control_points": [
                        {"x": 0, "y": -4}, {"x": 5, "y": -1},
                        {"x": 4, "y": 5}, {"x": 0, "y": 2},
                    ],
                },
            ],
            "semantic": _semantic("爱心轮廓", "heart_outline"),
        }],
        "assertions": [{
            "kind": "closed", "assertion_id": "heart-closed",
            "target_ref": "heart.outline",
        }],
    })

    geometry = result["geometries"][0]
    assert geometry["type"] == "polyline"
    assert geometry["closed"] is True
    assert len(geometry["vertices"]) == 64
    assert min(point["y"] for point in geometry["vertices"]) == pytest.approx(-4000)
    assert result["assertions"] == {"ok": True, "count": 1}
    quality = result["curve_quality"][0]
    assert quality["verified"] is True
    assert quality["c0"] is True
    assert quality["self_intersection_count"] == 0
    assert quality["duplicate_segment_count"] == 0
    assert quality["maximum_sampling_error"] > 0


def test_composite_path_rejects_disconnected_segments_atomically() -> None:
    plan = {
        "schema_version": "cad.construction-plan.v1",
        "steps": [{
            "step_id": "broken", "op": "add_composite_path",
            "output_ref": "broken.path",
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
            "semantic": _semantic("断开的复合路径"),
        }],
    }
    with pytest.raises(ConstructionPlanError) as caught:
        execute_construction_plan(plan)
    assert caught.value.code == "disconnected_composite_path"
    assert caught.value.step_id == "broken"


def test_composite_path_rejects_self_intersection_by_default() -> None:
    plan = {
        "schema_version": "cad.construction-plan.v1",
        "steps": [{
            "step_id": "bow", "op": "add_composite_path",
            "output_ref": "bow.path", "closed": True,
            "segments": [
                {"kind": "line", "start": {"x": 0, "y": 0}, "end": {"x": 2, "y": 2}},
                {"kind": "line", "start": {"x": 2, "y": 2}, "end": {"x": 0, "y": 2}},
                {"kind": "line", "start": {"x": 0, "y": 2}, "end": {"x": 2, "y": 0}},
                {"kind": "line", "start": {"x": 2, "y": 0}, "end": {"x": 0, "y": 0}},
            ],
            "semantic": _semantic("交叉轮廓"),
        }],
    }
    with pytest.raises(ConstructionPlanError) as caught:
        execute_construction_plan(plan)
    assert caught.value.code == "self_intersecting_composite_path"
    assert caught.value.step_id == "bow"
    conflict=caught.value.details['conflicts'][0]
    assert conflict['expanded_segment_indices']==[0,2]
    assert conflict['edge_indices']==[0,2]
    assert conflict['edges'][0]==[{'x':0.0,'y':0.0},{'x':2.0,'y':2.0}]


def test_composite_path_requires_explicit_duplicate_segment_opt_in() -> None:
    plan = {
        "schema_version": "cad.construction-plan.v1",
        "steps": [{
            "step_id": "repeat", "op": "add_composite_path",
            "output_ref": "repeat.path",
            "segments": [
                {"kind": "line", "start": {"x": 0, "y": 0}, "end": {"x": 2, "y": 0}},
                {"kind": "line", "start": {"x": 2, "y": 0}, "end": {"x": 0, "y": 0}},
            ],
            "semantic": _semantic("重复线段"),
        }],
    }
    with pytest.raises(ConstructionPlanError) as caught:
        execute_construction_plan(plan)
    assert caught.value.code == "duplicate_composite_segment"
    assert caught.value.details['conflicts'][0]['expanded_segment_indices']==[0,1]


def test_composite_path_c1_continuity_is_machine_checked() -> None:
    smooth = execute_construction_plan({
        "schema_version": "cad.construction-plan.v1",
        "steps": [{
            "step_id": "smooth", "op": "add_composite_path",
            "output_ref": "smooth.path", "continuity": "C1",
            "segments": [
                {
                    "kind": "bezier", "control_points": [
                        {"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 2, "y": 1},
                    ],
                },
                {
                    "kind": "bezier", "control_points": [
                        {"x": 2, "y": 1}, {"x": 3, "y": 2}, {"x": 4, "y": 2},
                    ],
                },
            ],
            "semantic": _semantic("连续曲线"),
        }],
    })
    assert smooth["curve_quality"][0]["c1"] is True

    broken = deepcopy(smooth["plan"])
    broken["steps"][0]["step_id"] = "corner"
    broken["steps"][0]["segments"][1]["control_points"][1] = {"x": 2, "y": 2}
    with pytest.raises(ConstructionPlanError) as caught:
        execute_construction_plan(broken)
    assert caught.value.code == "c1_continuity_failed"
    evidence = caught.value.as_dict()["details"]
    assert evidence["failed_joints"]
    assert evidence["failed_joints"][0]["angle_degrees"] > evidence["tolerance_degrees"]


def test_composite_path_enforces_curvature_and_sampling_error_limits() -> None:
    base_step = {
        "step_id": "curve", "op": "add_composite_path",
        "output_ref": "curve.path", "samples_per_curve": 8,
        "segments": [{
            "kind": "bezier", "control_points": [
                {"x": 0, "y": 0}, {"x": 0, "y": 4},
                {"x": 4, "y": 4}, {"x": 4, "y": 0},
            ],
        }],
        "semantic": _semantic("高曲率曲线"),
    }
    with pytest.raises(ConstructionPlanError) as caught:
        execute_construction_plan({
            "schema_version": "cad.construction-plan.v1",
            "steps": [{**base_step, "max_curvature": 0.01}],
        })
    assert caught.value.code == "curvature_limit_exceeded"

    with pytest.raises(ConstructionPlanError) as caught:
        execute_construction_plan({
            "schema_version": "cad.construction-plan.v1",
            "steps": [{**base_step, "max_sampling_error": 0.000001}],
        })
    assert caught.value.code == "sampling_error_exceeded"


def test_rectangular_array_references_prior_symbol_and_assigns_stable_ids() -> None:
    result = execute_construction_plan({
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [
            {
                "step_id": "space", "op": "add_rectangle", "output_ref": "parking.seed",
                "origin": {"x": 0, "y": 0}, "width": 2.5, "height": 5,
                "semantic": _semantic("第一个车位", "parking_space"),
            },
            {
                "step_id": "array", "op": "rectangular_array", "output_ref": "parking.copies",
                "source_ref": "parking.seed", "rows": 1, "columns": 4,
                "column_spacing": 2.5,
                "semantic": _semantic("其余三个车位", "parking_space_array"),
            },
        ],
        "assertions": [
            {"kind": "entity_count", "assertion_id": "all", "equals": 4},
            {"kind": "entity_count", "assertion_id": "copies", "target_ref": "parking.copies", "equals": 3},
        ],
    })

    assert [item["id"] for item in result["geometries"]] == [1, 2, 3, 4]
    assert result["symbol_table"] == {"parking.seed": [1], "parking.copies": [2, 3, 4]}


def test_array_include_source_does_not_duplicate_origin_and_creates_independent_objects() -> None:
    result = execute_construction_plan({
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [
            {
                "step_id": "rack", "op": "add_rectangle", "output_ref": "rack.seed",
                "origin": {"x": 0, "y": 0}, "width": 1.2, "height": 0.6,
                "semantic": _semantic("货架1", "rack"),
            },
            {
                "step_id": "array", "op": "rectangular_array",
                "output_ref": "rack.array", "source_ref": "rack.seed",
                "rows": 4, "columns": 5, "row_spacing": 2,
                "column_spacing": 2, "include_source": True,
                "semantic": _semantic("货架", "rack"),
            },
        ],
        "assertions": [{
            "kind": "entity_count", "assertion_id": "rack-count",
            "target_ref": "rack.array", "equals": 20,
        }],
    })

    assert len(result["geometries"]) == 20
    assert len(result["logical_objects"]) == 20
    assert result["symbol_table"]["rack.array"] == list(range(1, 21))
    first_vertices = result["geometries"][0]["vertices"]
    assert sum(item["vertices"] == first_vertices for item in result["geometries"]) == 1


def test_rejects_unknown_fields_and_forward_references() -> None:
    with pytest.raises(ValidationError):
        CadConstructionPlan.model_validate({
            "schema_version": "cad.construction-plan.v1",
            "units": "m",
            "steps": [{
                "step_id": "bad", "op": "add_circle", "output_ref": "circle",
                "center": {"x": 0, "y": 0}, "radius": 1,
                "semantic": _semantic("圆"), "unexpected": True,
            }],
        })

    with pytest.raises(ValidationError, match="unavailable source_ref"):
        CadConstructionPlan.model_validate({
            "schema_version": "cad.construction-plan.v1",
            "steps": [{
                "step_id": "array", "op": "rectangular_array", "output_ref": "copies",
                "source_ref": "missing", "columns": 2, "column_spacing": 2,
                "semantic": _semantic("复制"),
            }],
        })


def test_failed_assertion_returns_no_partial_result() -> None:
    plan = {
        "schema_version": "cad.construction-plan.v1",
        "steps": [{
            "step_id": "rect", "op": "add_rectangle", "output_ref": "rect",
            "origin": {"x": 0, "y": 0}, "width": 5, "height": 3,
            "semantic": _semantic("矩形"),
        }],
        "assertions": [{
            "kind": "bounds_size", "assertion_id": "wrong-size",
            "target_ref": "rect", "width": 6, "height": 3,
        }],
    }

    with pytest.raises(ConstructionPlanError) as caught:
        execute_construction_plan(plan)
    assert caught.value.code == "assertion_failed"
    assert caught.value.assertion_id == "wrong-size"


def test_entity_budget_stops_array_expansion() -> None:
    plan = {
        "schema_version": "cad.construction-plan.v1",
        "steps": [
            {
                "step_id": "seed", "op": "add_circle", "output_ref": "seed",
                "center": {"x": 0, "y": 0}, "radius": 1,
                "semantic": _semantic("种子圆"),
            },
            {
                "step_id": "array", "op": "rectangular_array", "output_ref": "copies",
                "source_ref": "seed", "rows": 3, "columns": 3,
                "row_spacing": 3, "column_spacing": 3,
                "semantic": _semantic("圆阵列"),
            },
        ],
        "budgets": {"max_steps": 10, "max_entities": 5},
    }
    with pytest.raises(ConstructionPlanError) as caught:
        execute_construction_plan(plan)
    assert caught.value.code == "entity_budget_exceeded"


def test_schema_is_provider_ready_and_array_budget_is_checked_before_expansion() -> None:
    schema = construction_plan_json_schema()
    assert schema["additionalProperties"] is False
    assert "steps" in schema["properties"]

    plan = {
        "schema_version": "cad.construction-plan.v1",
        "steps": [
            {
                "step_id": "seed", "op": "add_circle", "output_ref": "seed",
                "center": {"x": 0, "y": 0}, "radius": 1,
                "semantic": _semantic("种子圆"),
            },
            {
                "step_id": "first", "op": "rectangular_array", "output_ref": "first",
                "source_ref": "seed", "rows": 10, "columns": 10,
                "row_spacing": 3, "column_spacing": 3,
                "semantic": _semantic("第一层阵列"),
            },
            {
                "step_id": "second", "op": "rectangular_array", "output_ref": "second",
                "source_ref": "first", "rows": 10, "columns": 10,
                "row_spacing": 30, "column_spacing": 30,
                "semantic": _semantic("第二层阵列"),
            },
        ],
        "budgets": {"max_steps": 10, "max_entities": 200},
    }
    with pytest.raises(ConstructionPlanError) as caught:
        execute_construction_plan(plan)
    assert caught.value.code == "entity_budget_exceeded"
    assert caught.value.step_id == "second"
