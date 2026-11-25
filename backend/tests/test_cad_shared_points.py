from copy import deepcopy
import pytest
from app.cad_construction import CadConstructionPlan,execute_construction_plan

def plan():
    return {'units':'m','shared_points':{'origin':{'x':1,'y':2},
        'tip':{'x':'@origin.x+2*cos(pi/6)','y':'@origin.y+2*sin(pi/6)'},
        'top':{'x':'@tip.x','y':'@tip.y+1'}},'steps':[
        {'op':'add_line','step_id':'a','output_ref':'a','semantic':{'label':'第一段'},
         'start':{'x':'@origin.x','y':'@origin.y'},'end':{'x':'@tip.x','y':'@tip.y'}},
        {'op':'add_line','step_id':'b','output_ref':'b','semantic':{'label':'第二段'},
         'start':{'x':'@tip.x','y':'@tip.y'},'end':{'x':'@top.x','y':'@top.y'}}]}

def test_shared_endpoint_evaluated_once_without_changing_input_or_geometry_protocol():
    p=plan();before=deepcopy(p);result=execute_construction_plan(p)
    assert p==before
    gs=result['geometries'];assert gs[0]['end']==gs[1]['start']
    assert gs[0]['start']=={'x':1000,'y':2000,'z':0}
    assert gs[0]['end']['y']==pytest.approx(3000)
    assert execute_construction_plan(result['plan'])['geometries']==gs


def test_shared_points_work_through_the_production_interpreter():
    from app.cad_construction_interpreter import interpret_construction_request
    source='绘制两条首尾相接的线段，坐标单位米'
    result=interpret_construction_request(source,lambda *_:{
        'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
        'plan':plan(),'confidence':.99,'evidence_text':[source],'assumptions':[]},force_structured_model=True)
    assert result['status']=='ready',result.get('error')
    assert result['trial_result']['geometries'][0]['end']==result['trial_result']['geometries'][1]['start']


def test_complete_edge_inventory_schema_requires_shared_endpoint_references():
    from app.cad_construction_interpreter import _request_construction_schema
    schema=_request_construction_schema('绘制框架，只画7条直线段，边长2米')
    defs=schema['$defs'];props=defs['CadConstructionPlan']['properties']
    assert props['steps']['minItems']==props['steps']['maxItems']==7
    assert 'shared_points' in defs['CadConstructionPlan']['required']
    assert defs['AddLineStep']['properties']['start']=={'$ref':'#/$defs/SharedEndpointReference'}


@pytest.mark.parametrize('source,has_equal_box',[
    ('画一个立方体的透视轮廓，边长2米',False),
    ('生成3列2行蜂窝六边形阵列，边长0.5米，无缝拼接',False),
    ('画一个正六边形，边长1米',False),
    ('画一个正方形，边长2米',True),
    ('画一个矩形，长宽均为3米',True),
])
def test_local_side_length_is_not_promoted_to_whole_drawing_dimensions(source,has_equal_box):
    from app.cad_construction_interpreter import normalize_construction_request
    _,facts=normalize_construction_request(source)
    assert any(f.startswith('等尺寸约束：') for f in facts)==has_equal_box


def test_component_patch_resolves_its_points_without_changing_protected_components():
    from app.cad_plan_component_repair import merge_component_repair
    original=CadConstructionPlan.model_validate(plan()).model_dump(mode='json')
    context={'plan':original,'construction_error':{'details':{'affected_output_refs':['b']}}}
    patch={'plan':{'units':'m','shared_points':{'tip':{'x':4,'y':5}},'steps':[
        {'op':'add_line','step_id':'b','output_ref':'b','semantic':{'label':'第二段'},
         'start':{'x':'@tip.x','y':'@tip.y'},'end':{'x':'@top.x','y':'@top.y'}}]}}
    before=deepcopy(patch);old=deepcopy(context)
    merged=merge_component_repair(context,patch)['plan']
    assert merged['steps'][0]==original['steps'][0]
    assert merged['shared_points']==original['shared_points']
    assert merged['steps'][1]['start']=={'x':4,'y':5}
    assert patch==before and context==old
    CadConstructionPlan.model_validate(merged)

@pytest.mark.parametrize('damage',['cycle','missing','unsafe','range','t','extra','many','invalid_name'])
def test_invalid_references_remain_rejected(damage):
    p=plan()
    if damage=='cycle':p['shared_points']['origin']['x']='@tip.x'
    elif damage=='missing':p['steps'][0]['start']['x']='@missing.x'
    elif damage=='unsafe':p['shared_points']['origin']['x']="__import__('os').getcwd()"
    elif damage=='range':p['shared_points']['origin']['x']=100001
    elif damage=='t':p['shared_points']['origin']['x']='sin(t)'
    elif damage=='extra':p['shared_points']['origin']['z']=0
    elif damage=='many':p['shared_points'].update({f'p{i}':{'x':i,'y':0} for i in range(65)})
    else:p['shared_points']['bad-name']={'x':0,'y':0}
    with pytest.raises(ValueError):CadConstructionPlan.model_validate(p)
