from copy import deepcopy

import pytest

from app.cad_path_relation_acceptance import verify_path_relations
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_structure_contract import StructureContractError


TEXT='生成一个轮廓，外圆半径2米，S形分割线，两个对称小圆'


def test_free_lines_share_exact_analytic_arc_endpoints_but_user_points_are_fixed():
    from app.cad_construction_interpreter import normalize_composite_path_connections_once
    import math
    payload={'plan':{'steps':[{'op':'add_composite_path','step_id':'path','closed':False,
        'segments':[{'kind':'line','start':{'x':0,'y':0},'end':{'x':1,'y':.083333}},
            {'kind':'arc','center':{'x':0,'y':0},'radius':1,'start_angle':5,'end_angle':40},
            {'kind':'line','start':{'x':1,'y':.083333},'end':{'x':0,'y':1}}]}]}}
    before=deepcopy(payload)
    result,changes=normalize_composite_path_connections_once(payload,'生成连续自由轮廓')
    segments=result['plan']['steps'][0]['segments']
    assert segments[0]['end']['x']==pytest.approx(math.cos(math.radians(5)))
    assert segments[2]['start']['y']==pytest.approx(math.sin(math.radians(40)))
    assert segments[1]==before['plan']['steps'][0]['segments'][1]
    assert len([c for c in changes if c['kind']=='bind_free_line_to_arc_endpoint'])==2
    assert payload==before
    for fixed in ['指定端点(1,0.083333)，不得移动','线段长1米','顶点(1,0.083333)']:
        protected,_=normalize_composite_path_connections_once(payload,fixed)
        assert protected==before


def test_connected_zero_arc_is_removed_without_joining_a_real_gap():
    from app.cad_construction_interpreter import normalize_composite_path_connections_once
    payload={'plan':{'steps':[{'op':'add_composite_path','step_id':'path','closed':False,
        'segments':[{'kind':'line','start':{'x':0,'y':0},'end':{'x':1,'y':0}},
            {'kind':'arc','center':{'x':0,'y':0},'radius':1,'start_angle':0,'end_angle':0},
            {'kind':'line','start':{'x':1,'y':0},'end':{'x':1,'y':1}}]}]}}
    result,changes=normalize_composite_path_connections_once(payload,'连续开放路径')
    assert result['plan']['steps'][0]['segments']==[payload['plan']['steps'][0]['segments'][i] for i in (0,2)]
    assert any(c['kind']=='remove_connected_zero_sweep_arc' for c in changes)
    gap=deepcopy(payload);gap['plan']['steps'][0]['segments'][1]['center']['x']=2
    result,changes=normalize_composite_path_connections_once(gap,'连续开放路径')
    assert result==gap
    full=deepcopy(payload);full['plan']['steps'][0]['segments'][1]['end_angle']=360
    result,changes=normalize_composite_path_connections_once(full,'连续开放路径')
    assert result==full


def test_connection_normalization_uses_safe_point_expressions():
    from app.cad_construction_interpreter import normalize_composite_path_connections_once
    point={'x':'0.92*cos(pi/8)','y':'0.92*sin(pi/8)'}
    payload={'plan':{'steps':[{'op':'add_composite_path','step_id':'curve','closed':False,
        'segments':[{'kind':'line','start':{'x':0,'y':0},'end':point},
                    {'kind':'bezier','control_points':[{'x':1,'y':1},{'x':2,'y':1},{'x':2,'y':0}]}]}]}}
    before=deepcopy(payload)
    normalized,changes=normalize_composite_path_connections_once(payload,'生成一条连续曲线')
    points=normalized['plan']['steps'][0]['segments'][1]['control_points']
    import math
    assert points[0]['x']==pytest.approx(.92*math.cos(math.pi/8))
    assert points[0]['y']==pytest.approx(.92*math.sin(math.pi/8))
    assert len(points)==4
    assert payload==before
    assert any(c['kind']=='complete_composite_bezier_start' for c in changes)


def test_semicircle_orientation_accepts_safe_scalar_expressions():
    from app.cad_construction_interpreter import normalize_composite_path_connections_once
    payload={'plan':{'steps':[{'op':'add_composite_path','step_id':'arc',
        'segments':[{'kind':'arc','center':{'x':'cos(0)','y':0},'radius':'sqrt(1)',
                     'start_angle':0,'end_angle':'90*2','clockwise':True}]}]}}
    result,changes=normalize_composite_path_connections_once(payload,'生成上半圆')
    assert result['plan']['steps'][0]['segments'][0]['clockwise'] is False
    assert any(c['kind']=='bind_semicircle_orientation' for c in changes)


def test_arc_chain_orientation_preserves_arcs_and_respects_explicit_direction():
    from app.cad_construction_interpreter import normalize_composite_path_connections_once
    payload={'plan':{'steps':[{'op':'add_composite_path','step_id':'chain','closed':False,
        'segments':[{'kind':'arc','center':{'x':0,'y':1},'radius':1,'start_angle':270,'end_angle':90,'clockwise':False},
                    {'kind':'arc','center':{'x':0,'y':-1},'radius':1,'start_angle':90,'end_angle':270,'clockwise':False}]}]}}
    normalized,changes=normalize_composite_path_connections_once(payload,'生成一条连续开放曲线')
    segments=normalized['plan']['steps'][0]['segments']
    assert segments[0]['start_angle']==90 and segments[0]['end_angle']==270
    assert segments[0]['clockwise'] is True
    assert segments[1]==payload['plan']['steps'][0]['segments'][1]
    assert any(c['kind']=='orient_existing_arc_chain' for c in changes)
    protected,_=normalize_composite_path_connections_once(payload,'所有圆弧逆时针')
    assert protected['plan']['steps'][0]['segments']==payload['plan']['steps'][0]['segments']


def test_arm_dimensions_and_duplicate_boundaries_are_measured():
    from app.agent_skills import analyze_geometry_topology
    source='画一个L形走廊，宽1米，两条臂分别长3米和2米，直角连接'
    points=[(0,0),(3000,0),(3000,1000),(1000,1000),(1000,2000),(0,2000)]
    geometry={'id':1,'type':'polyline','closed':True,'layer_id':1,
        'vertices':[{'x':x,'y':y,'z':0} for x,y in points]}
    assert verify_path_relations(source,[geometry])['status']=='passed'
    wrong=deepcopy(geometry)
    wrong['vertices'][-2]['y']=wrong['vertices'][-1]['y']=3000
    with pytest.raises(StructureContractError):
        verify_path_relations(source,[wrong])
    duplicate=deepcopy(geometry);duplicate['id']=2
    ring=duplicate['vertices']
    duplicate['vertices']=list(reversed(ring[2:]+ring[:2]))
    assert analyze_geometry_topology([geometry,duplicate])['duplicate_geometry_count']==1
    with pytest.raises(StructureContractError):
        verify_path_relations(source,[geometry,duplicate])


def scene(correct=True):
    circles=[{'id':i,'type':'circle','center':{'x':0,'y':y,'z':0},'radius':r,'layer_id':1}
             for i,y,r in [(1,0,2000),(4,1000,300),(5,-1000,300)]]
    arcs=[{'id':2,'type':'arc','center':{'x':0 if correct else -1000,'y':1000 if correct else 0,'z':0},
           'radius':1000,'start_angle':-90 if correct else 90,'end_angle':90 if correct else 270,'layer_id':1},
          {'id':3,'type':'arc','center':{'x':0 if correct else 1000,'y':-1000 if correct else 0,'z':0},
           'radius':1000,'start_angle':90 if correct else -90,'end_angle':270 if correct else 90,'layer_id':1}]
    return circles+arcs


def test_screenshot_disconnected_arcs_are_rejected():
    with pytest.raises(StructureContractError,match='端点'):
        verify_path_relations(TEXT,scene(False))


def test_connected_s_with_independent_circles_passes_without_mutation():
    gs=scene();before=deepcopy(gs)
    result=verify_path_relations(TEXT,gs)
    assert result['checks'][0]['geometry_ids']==[2,3]
    assert gs==before


def test_symmetric_circles_cannot_duplicate_divider_semicircles():
    gs=scene()
    result=verify_path_relations(TEXT,gs)
    assert any(c['name']=='symmetric_contained_circles' for c in result['checks'])
    for geometry in gs:
        if geometry['id'] in {4,5}:geometry['radius']=1000
    with pytest.raises(StructureContractError,match='分割区域'):
        verify_path_relations(TEXT,gs)


def test_generic_s_without_taiji_or_outer_circle_is_verified():
    assert verify_path_relations('画一条S形曲线',scene()[3:])['checks']


def test_unrequested_disconnected_arcs_are_not_implicitly_connected():
    assert verify_path_relations('画两个独立半圆弧',scene(False))['status']=='not_checked'


def test_wrong_arc_sweep_is_rejected():
    gs=scene();gs[-1].update(start_angle=-90,end_angle=90)
    with pytest.raises(StructureContractError):verify_path_relations(TEXT,gs)


def test_interior_chain_cannot_claim_to_split_outer_circle():
    gs=scene()
    for g in gs[3:]:
        g['center']['y']/=2;g['radius']/=2
    with pytest.raises(StructureContractError,match='外圆'):
        verify_path_relations(TEXT,gs)


def test_same_direction_bends_and_extra_branch_are_rejected():
    gs=[{'id':1,'type':'polyline','closed':False,'vertices':[
        {'x':0,'y':0},{'x':1000,'y':0},{'x':1000,'y':1000},{'x':0,'y':1000}]}]
    with pytest.raises(StructureContractError,match='相反弯曲'):
        verify_path_relations('S形曲线',gs)
    gs=scene()+[{'id':6,'type':'line','start':{'x':0,'y':0},'end':{'x':1000,'y':0}}]
    with pytest.raises(StructureContractError,match='无分叉'):
        verify_path_relations(TEXT,gs)


def test_interpreter_rejects_invalid_relations_before_candidate_commit():
    def callback(text,schema):
        steps=[]
        for g in scene(False):
            g=deepcopy(g);kind=g.pop('type');g.pop('id');g.pop('layer_id')
            g['center'].pop('z')
            steps.append({'op':'add_'+kind,'step_id':f's{len(steps)}','output_ref':f'p{len(steps)}',
                'semantic':{'label':'部件'},**g})
        return {'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
            'confidence':1,'evidence_text':[TEXT],'plan':{'units':'mm','steps':steps}}
    result=interpret_construction_request(TEXT,callback,force_structured_model=True)
    assert result['status']=='invalid'
    assert result['construction_error']['code']=='structure_requirement_failed'
    assert result['construction_error']['details']['required_relation']=='continuous_open_s_path'
