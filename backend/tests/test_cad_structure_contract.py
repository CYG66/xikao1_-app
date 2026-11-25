from copy import deepcopy
import math

import pytest

from app.cad_structure_contract import (
    StructureContractError, reference_contract, explicit_dimensions, validate_structure,
    explicit_composition, validate_explicit_composition, validate_plan_structure,
)
from app.cad_construction_interpreter import interpret_construction_request


def measured_fixture():
    # Independent 30x20 construction grid from the official source, 100mm/grid.
    geometries = [{"id":1,"type":"polyline","closed":True,"vertices":[
        {"x":0,"y":0},{"x":3000,"y":0},{"x":3000,"y":2000},{"x":0,"y":2000}]}]
    for i,(x,y,r) in enumerate([(5,15,3),(10,18,1),(12,16,1),(12,13,1),(10,11,1)]):
        theta=math.pi/2 if i==0 else math.atan2(15-y,5-x)
        points=[]
        for j in range(10):
            radius=r*100*(1 if j%2==0 else math.sin(math.pi/10)/math.sin(3*math.pi/10))
            points.append({"x":x*100+radius*math.cos(theta+j*math.pi/5),
                           "y":y*100+radius*math.sin(theta+j*math.pi/5)})
        geometries.append({"id":i+2,"type":"polyline","closed":True,"vertices":points})
    return geometries


def contract():
    return reference_contract("生成一个五星红旗")


def test_plan_preflight_rejects_missing_relation_branch_reference():
    plan={"steps":[{"output_ref":"main","op":"add_polyline"},
                   {"output_ref":"branch.1","op":"add_line"}],
          "constraints":[{"kind":"symmetric","refs":["branch.1","branch.2"]}]}
    with pytest.raises(StructureContractError,match="不存在"):
        validate_plan_structure({"kind":"named_components","names":["main","branch"]},plan)


def test_plan_preflight_rejects_relation_with_only_one_component():
    plan={"steps":[{"output_ref":"main","op":"add_polyline"}],
          "relations":[{"kind":"connected","target_ref":"main"}]}
    with pytest.raises(StructureContractError,match="两个独立组成"):
        validate_plan_structure({"kind":"named_components","names":["main"]},plan)


def test_plan_preflight_rejects_incomplete_declared_symmetry_count():
    plan={"steps":[{"output_ref":"b1","op":"add_line"},
                   {"output_ref":"b2","op":"add_line"}],
          "constraints":[{"kind":"symmetric","refs":["b1","b2"],"count":6}]}
    with pytest.raises(StructureContractError,match="少于声明数量"):
        validate_plan_structure({"kind":"named_components","names":["b1","b2"]},plan)


def test_independent_grid_matches_count_centers_radii_and_tip_directions():
    result=validate_structure(contract(),measured_fixture(),3,2)
    assert result["status"]=="passed"
    assert len(result["measurements"])==5
    assert result["reference_sha256"]


@pytest.mark.parametrize("defect", ["missing","extra","position","radius","direction","crossing","dimension","ratio"])
def test_rejects_incomplete_or_wrong_geometry_regardless_of_labels(defect):
    geometries=measured_fixture()
    if defect=="missing":geometries.pop()
    elif defect=="extra":geometries.append(deepcopy(geometries[-1]))
    elif defect=="position":
        for p in geometries[2]["vertices"]:p["x"]+=200
    elif defect=="radius":
        for p in geometries[2]["vertices"]:p["x"]=1000+(p["x"]-1000)*1.2
    elif defect=="direction":
        for p in geometries[2]["vertices"]:
            x,y=p["x"]-1000,p["y"]-1800
            p.update(x=1000+x*math.cos(.2)-y*math.sin(.2),y=1800+x*math.sin(.2)+y*math.cos(.2))
    elif defect=="crossing":
        points=geometries[2]["vertices"];points[0],points[2]=points[2],points[0]
    elif defect=="dimension":
        for g in geometries:
            for p in g["vertices"]:p["x"]*=2;p["y"]*=2
    elif defect=="ratio":geometries[0]["vertices"][1]["x"]+=100;geometries[0]["vertices"][2]["x"]+=100
    for g in geometries:g["label"]="五星红旗的全部正确组成"
    with pytest.raises(StructureContractError):
        validate_structure(contract(),geometries,3,2)


def test_translation_and_reversed_paths_do_not_change_contract():
    geometries=measured_fixture()
    for g in geometries:
        g["vertices"].reverse()
        for p in g["vertices"]:p["x"]-=800;p["y"]+=400
    assert validate_structure(contract(),geometries,3,2)["status"]=="passed"


def test_reference_is_not_a_generator_and_missing_size_does_not_call_model():
    def forbidden(*_):raise AssertionError("不应在没有尺寸时调用构造模型")
    result=interpret_construction_request("生成一个五星红旗，大小按照目前标准的中国红旗",forbidden)
    assert result["clarification"]["question_key"]=="size"
    assert "plan" not in result and "trial_result" not in result
    assert explicit_dimensions("宽度300厘米、高度2000毫米")==(3,2)


def test_rule_rectangle_cannot_swallow_compound_reference_request():
    text="生成五星红旗，旗面矩形宽3米高2米"
    payload={"schema_version":"cad.construction-interpretation.v1","is_construction_request":True,
             "evidence_text":[text],"confidence":.99,"plan":{"units":"m","steps":[{
                 "op":"add_rectangle","step_id":"field","output_ref":"field","semantic":{"label":"旗面"},
                 "origin":{"x":0,"y":0},"width":3,"height":2}]}}
    calls=[]
    result=interpret_construction_request(text,lambda *args: calls.append(args) or payload)
    assert len(calls)==1
    assert result["construction_error"]["code"]=="structure_requirement_failed"
    assert "6" in result["construction_error"]["message"]


@pytest.mark.parametrize("text,expected", [
    ("矩形四个角各放一个半径0.5米的圆", {"rectangle":1,"circle":4}),
    ("生成3行4列矩形阵列", {"rectangle":12}),
    ("生成两个相交圆组成的轮廓", {"circle":2}),
])
def test_explicit_counts_are_independent_of_model_labels(text,expected):
    contract=explicit_composition(text)
    assert contract["counts"]==expected
    with pytest.raises(StructureContractError):validate_explicit_composition(contract,measured_fixture()[:1])


def test_line_inventory_measures_count_orientation_and_overall_bounds():
    contract=explicit_composition("画两条竖直线，整体宽2米高1米，坐标单位米")
    assert contract["counts"]=={"line":2}
    lines=[
        {"id":1,"type":"line","start":{"x":0,"y":0},"end":{"x":0,"y":1000}},
        {"id":2,"type":"line","start":{"x":2000,"y":0},"end":{"x":2000,"y":1000}},
    ]
    report=validate_explicit_composition(contract,lines)
    assert report["status"]=="passed"
    assert report["orientation"]=="vertical"
    assert report["measured_dimensions"]=={"width_m":2,"height_m":1}
    wrong=deepcopy(lines);wrong[1]["end"]["x"]+=10
    with pytest.raises(StructureContractError,match="竖直"):
        validate_explicit_composition(contract,wrong)
    with pytest.raises(StructureContractError,match="数量"):
        validate_explicit_composition(contract,lines[:1])


def test_line_count_in_mixed_drawing_is_not_promoted_to_complete_inventory():
    assert explicit_composition("画两条竖直线和一个圆") is None


def test_corner_positions_cannot_be_replaced_by_four_coincident_circles():
    frame=measured_fixture()[0]
    circles=[{"id":i+2,"type":"circle","center":{"x":0,"y":0},"radius":.5} for i in range(4)]
    req=explicit_composition("矩形四个角各放一个圆")
    with pytest.raises(StructureContractError,match="一一对应"):
        validate_explicit_composition(req,[frame,*circles])


def test_point_expression_preserves_exact_geometry_without_shape_generator():
    from app.cad_construction import ConstructionPoint
    p=ConstructionPoint(x="1+0.1*cos(atan2(3,4))",y="2+sqrt(4)/10")
    assert p.x==pytest.approx(1.08)
    assert p.y==pytest.approx(2.2)
    for x in ("__import__('os')", "t+1", "100001", "2**1000000"):
        with pytest.raises(ValueError):ConstructionPoint(x=x,y=0)


def test_circle_size_is_checked_against_source_not_model_assertions():
    frame=measured_fixture()[0]
    circles=[{"id":i+2,"type":"circle","center":p.copy(),"radius":500} for i,p in enumerate(frame["vertices"])]
    req=explicit_composition("矩形宽3米高2米，四个角各放一个半径0.5米的圆")
    assert validate_explicit_composition(req,[frame,*circles])["status"]=="passed"
    circles[0]["radius"]=600
    with pytest.raises(StructureContractError,match="半径"):
        validate_explicit_composition(req,[frame,*circles])


def test_array_pitch_is_checked_even_with_correct_row_column_counts():
    req=explicit_composition("生成2行3列矩形阵列，每个矩形宽1米高0.6米，行距1.2米列距1.5米")
    rectangles=[]
    for row in range(2):
        for col in range(3):
            x,y=col*1500,row*1200
            rectangles.append({"type":"polyline","closed":True,"vertices":[
                {"x":x,"y":y},{"x":x+1000,"y":y},{"x":x+1000,"y":y+600},{"x":x,"y":y+600}]})
    assert validate_explicit_composition(req,rectangles)["status"]=="passed"
    for g in rectangles:
        for p in g["vertices"]:p["x"]+=1000 if p["x"]>=3000 else 0
    with pytest.raises(StructureContractError,match="间距"):
        validate_explicit_composition(req,rectangles)


def test_sentence_local_compound_dimensions_are_per_component():
    text="生成一个爱心和一个五角星，爱心在左，五角星在右，它们的长宽均为5米，间距为8米"
    for source in (text,"新建 CAD 图纸："+text):
        contract=explicit_composition(source)
        assert contract["names"]==["爱心","五角星"]
        assert contract["dimensions"]["width_m"]==contract["dimensions"]["height_m"]==5
        assert contract["gap_m"]==8 and contract["left_to_right"]


def test_mixed_component_sizes_are_not_promoted_to_shared_bounds():
    original='生成一个爱心和一个五角星，爱心在左，五角星在右'
    supplement='爱心宽4米高4米；五角星外接圆半径2米；两者中心水平相距6米。'
    source='新建 CAD 图纸：'+original+'\n最新已确认要求（覆盖原描述中同名参数）：\n{"dimensions":{"width_m":99,"height_m":99}}\n用户逐轮补充的原文约束（按时间排序，后文覆盖同名约束；必须保留全部组成）：\n'+supplement
    contract=explicit_composition(source)
    assert contract['dimensions']=={}
    assert contract['component_dimensions']=={'爱心':{'width_m':4,'height_m':4},'五角星':{'circumradius_m':2}}
    assert contract['gap_reference']=='center' and contract['gap_m']==6
    from app.agent_service import RobotAgentService
    project={'original_prompt':original,'requirements':{'dimensions':{'width_m':4,'height_m':4,'radius_m':2},'source_followups':[supplement]}}
    before=deepcopy(project)
    prompt=RobotAgentService._project_construction_prompt(project)
    assert '宽度4米' not in prompt and '半径2米\n' not in prompt
    assert 'component_dimensions' in prompt and project==before


def test_different_component_size_and_circumradius_are_measured_independently():
    text='生成一个甲形和一个乙形，甲形在左，乙形在右；甲形宽4米高4米；乙形外接圆半径2米；两者中心水平相距6米。'
    contract=explicit_composition(text)
    geometries=[{'id':1,'type':'polyline','closed':True,'vertices':[{'x':x,'y':y} for x,y in [(-2000,-2000),(2000,-2000),(2000,2000),(-2000,2000)]]},
        {'id':2,'type':'polyline','closed':True,'vertices':[{'x':6000+2000*math.cos(a),'y':2000*math.sin(a)} for a in (math.pi/2,7*math.pi/6,11*math.pi/6)]}]
    assert validate_explicit_composition(contract,geometries)['status']=='passed'
    for point in geometries[1]['vertices']:point['x']+=1000
    with pytest.raises(StructureContractError,match='间距'):
        validate_explicit_composition(contract,geometries)


def test_scoped_layout_fits_free_part_without_stretching_radius_constrained_part():
    from app.cad_construction_interpreter import bind_component_layout
    from app.cad_construction import execute_construction_plan
    text='生成一个甲形和一个乙形，甲形在左，乙形在右；甲形宽4米高4米；乙形外接圆半径2米；两者中心水平相距6米。'
    steps=[{'op':'add_polyline','step_id':'a','output_ref':'a','semantic':{'label':'甲形'},'closed':True,
        'vertices':[{'x':x,'y':y} for x,y in [(0,0),(1,0),(1,1),(0,1)]]},
        {'op':'add_polyline','step_id':'b','output_ref':'b','semantic':{'label':'乙形'},'closed':True,
        'vertices':[{'x':2*math.cos(a),'y':2*math.sin(a)} for a in (math.pi/2,7*math.pi/6,11*math.pi/6)]}]
    payload={'plan':{'units':'m','steps':steps,'free_outline_layout':[
        {'target_ref':'a','width':4,'height':4},{'target_ref':'b','width':4,'height':4}]}}
    repaired,changes=bind_component_layout(payload,explicit_composition(text),text)
    assert changes[0]['kind']=='bind_scoped_component_layout'
    result=execute_construction_plan(repaired['plan'])
    assert validate_explicit_composition(explicit_composition(text),result['geometries'])['status']=='passed'


@pytest.mark.parametrize("units", ["m", "mm"])
def test_component_constraints_fit_and_place_model_outlines_without_synthesizing(units):
    from app.cad_construction import execute_construction_plan
    from app.cad_construction_interpreter import bind_component_layout
    text="生成一个甲形和一个乙形，甲形在左，乙形在右，它们的长宽均为5米，间距为8米"
    steps=[{"op":"add_polyline","step_id":f"s{i}","output_ref":f"r{i}","semantic":{"label":name},
            "closed":True,"vertices":[{"x":0,"y":0},{"x":1,"y":0},{"x":1,"y":1},{"x":0,"y":1}]}
           for i,name in enumerate(("甲形","乙形"))]
    source={"plan":{"units":units,"steps":steps}}
    payload,repairs=bind_component_layout(deepcopy(source),explicit_composition(text),text)
    result=execute_construction_plan(payload["plan"])
    assert repairs and len(result["geometries"])==2
    assert validate_explicit_composition(explicit_composition(text),result["geometries"])["status"]=="passed"
    assert source["plan"]["steps"][0]["vertices"][1]["x"]==1
    assert "free_outline_layout" not in source["plan"]
    # Missing output is rejected; the constraint binder never invents it.
    source["plan"]["steps"].pop()
    unchanged,repairs=bind_component_layout(source,explicit_composition(text),text)
    assert not repairs
    with pytest.raises(StructureContractError):
        validate_explicit_composition(explicit_composition(text),execute_construction_plan(unchanged["plan"])["geometries"])


def test_fixed_coordinate_request_is_not_fitted_as_free_layout():
    from app.cad_construction_interpreter import bind_component_layout
    text="生成一个甲形和一个乙形，坐标固定，长宽均为5米，间距8米"
    payload={"plan":{"steps":[]}}
    assert bind_component_layout(payload,explicit_composition(text),text)==(payload,[])


def test_mixed_primitive_inventory_does_not_reject_required_frame():
    source="一个竖直矩形灯箱，内部三个等大的圆。宽1米高3米"
    contract=explicit_composition(source)
    assert contract["counts"]=={"rectangle":1,"circle":3}
    frame={"type":"polyline","closed":True,"vertices":[{"x":x,"y":y} for x,y in [(0,0),(1000,0),(1000,3000),(0,3000)]]}
    circles=[{"type":"circle","center":{"x":500,"y":y},"radius":350} for y in (600,1500,2400)]
    assert validate_explicit_composition(contract,[frame,*circles])["status"]=="passed"
    with pytest.raises(StructureContractError):
        validate_explicit_composition(contract,[frame,*circles[:2]])
    assert explicit_composition("矩形外框，三个圆") is None


@pytest.mark.parametrize("text", [
    "生成一个笑脸图案，圆半径1米，两个圆点眼睛，一个圆弧嘴巴",
    "生成一个面板，两个圆孔，外框宽3米高2米",
    "画两个圆和一个圆弧，半径1米",
])
def test_component_subset_is_not_a_whole_drawing_inventory(text):
    assert explicit_composition(text) is None
