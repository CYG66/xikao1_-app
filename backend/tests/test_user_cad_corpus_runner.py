import math
from copy import deepcopy
from tests.manual.run_user_cad_corpus import BASE,SUPPLEMENTS,corners,edit_checks,create_checks


def test_unspecified_branch_design_parameters_are_measured_without_inventing_fixed_values():
    source='生成一个雪花图案，6条对称分支，每条分支带2个侧枝，最大半径2米'
    geometries=[]
    for i in range(6):
        angle=i*math.pi/3
        def rotate(x,y):return {'x':x*math.cos(angle)-y*math.sin(angle),'y':x*math.sin(angle)+y*math.cos(angle)}
        for a,b in [((0,0),(2000,0)),((900,0),(1100,250)),((900,0),(1100,-250))]:
            geometries.append({'id':len(geometries)+1,'type':'line','start':rotate(*a),'end':rotate(*b)})
    result={'ok':True,'variant':{'geometries':geometries},'preview_paths':[{'points':[[0,0],[2,0]]}]}
    checks=create_checks('C22',result,[source])
    assert all(c['passed'] for c in checks),checks
    bad=deepcopy(result)
    bad['variant']['geometries'][-1]['end']['x']+=100
    measured=next(c for c in create_checks('C22',bad,[source]) if c['name']=='source_branch_connectivity_and_symmetry')
    assert not measured['passed']


def test_all_creation_and_edit_cases_have_explicit_setup():
    assert set(SUPPLEMENTS)==({f'A{i}' for i in range(1,13)}|{f'C{i}' for i in range(1,29)}|{'B18','C31','B4','B8','B13','B14','B15','D2','D6'})
    assert set(BASE)=={f'B{i}' for i in range(1,20)}|{f'D{i}' for i in range(1,7)}
    assert all(base in SUPPLEMENTS for base in BASE.values())


def test_renumbered_combination_keeps_correct_dependency_and_oracle():
    from tests.manual.run_user_cad_corpus import resolve_corpus_setup
    corpus={'A9':'生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米',
        'A10':'生成一个五角星轮廓','A11':'生成一个圆形和一个矩形，圆形在矩形正上方',
        'B14':'让矩形和圆形同心','B15':'让矩形和圆形一样大'}
    aliases,bases=resolve_corpus_setup(corpus,{'B14','B15'})
    assert aliases['A11']=='A12' and bases=={'B14':'A11','B15':'A11'}
    assert corpus['A11']=='生成一个圆形和一个矩形，圆形在矩形正上方'
    import pytest
    with pytest.raises(ValueError,match='expected one source case'):
        resolve_corpus_setup({'B14':'让矩形和圆形同心'}, {'B14'})


def test_polygon_oracle_ignores_straight_edge_subdivision():
    points=[{'x':1000*math.cos(i*math.pi/3),'y':1000*math.sin(i*math.pi/3)} for i in range(6)]
    divided=[]
    for a,b in zip(points,points[1:]+points[:1]):
        divided.extend([a,{'x':(a['x']+b['x'])/2,'y':(a['y']+b['y'])/2}])
    assert corners({'vertices':divided,'closed':True})==points


def test_translation_oracle_checks_non_target_parts():
    a={'id':1,'type':'circle','center':{'x':0,'y':0},'radius':1000}
    b={**a,'id':2,'center':{'x':3000,'y':0}}
    before={'id':'old','geometries':[a,b]}
    after={'id':'new','geometries':[{**a,'center':{'x':6000,'y':0}},b]}
    assert all(c['passed'] for c in edit_checks('B2',before,after,[1]))
    after['geometries'][1]={**b,'radius':2000}
    assert not next(c['passed'] for c in edit_checks('B2',before,after,[1]) if c['name']=='non_target_unchanged')


def test_rectangular_array_oracle_rejects_wrong_pitch_even_with_twelve_circles():
    circle={'id':1,'type':'circle','center':{'x':0,'y':0},'radius':2000}
    before={'id':'old','geometries':[circle]}
    after={'id':'new','geometries':[
        {**circle,'id':row*4+column+1,'center':{'x':column*1500,'y':row*1000}}
        for row in range(3) for column in range(4)]}
    assert all(c['passed'] for c in edit_checks('B11',before,after,[1]))
    after['geometries'][-1]['center']['x']+=100
    assert not all(c['passed'] for c in edit_checks('B11',before,after,[1]))


def test_stair_oracle_accepts_base_closure_but_rejects_shrunken_steps():
    points=[{'x':0,'y':0}]
    for i in range(5):points.extend([{'x':i*400,'y':(i+1)*300},{'x':(i+1)*400,'y':(i+1)*300}])
    points.append({'x':2000,'y':0})
    response={'variant':{'geometries':[{'id':1,'type':'polyline','closed':True,'vertices':points}]},'preview_paths':[{'points':[[0,0],[2,1.5]]}]}
    checks=create_checks('C23',response,[])
    assert next(c['passed'] for c in checks if c['name']=='five_stair_steps')
    for point in points:point['x']/=5;point['y']/=5
    assert not next(c['passed'] for c in create_checks('C23',response,[]) if c['name']=='five_stair_steps')


def test_cube_oracle_does_not_require_unsent_twelve_edge_supplement():
    response={'variant':{'geometries':[{'id':1,'type':'line','start':{'x':0,'y':0},'end':{'x':1000,'y':1000}}]},'preview_paths':[{'points':[[0,0],[1,1]]}]}
    checks=create_checks('C27',response,['画一个立方体的透视轮廓，边长2米'])
    assert not any(c['name']=='twelve_edges' for c in checks)
    assert any(c['name']=='projection_topology_review' and not c['passed'] for c in checks)
    assert any(c['name']=='twelve_edges' and not c['passed'] for c in create_checks('C27',response,[SUPPLEMENTS['C27']]))


def test_astroid_oracle_rejects_straight_edges_even_when_vertices_satisfy_equation():
    points=[[2,0],[2**-.5,2**-.5],[0,2],[-2**-.5,2**-.5],[-2,0],[-2**-.5,-2**-.5],[0,-2],[2**-.5,-2**-.5],[2,0]]
    response={'ok':True,'variant':{'geometries':[{'id':1,'type':'polyline','closed':True,
        'vertices':[{'x':1000*x,'y':1000*y} for x,y in points[:-1]]}]},'preview_paths':[{'points':points}]}
    assert all(abs((abs(x)/2)**(2/3)+(abs(y)/2)**(2/3)-1)<1e-9 for x,y in points)
    assert not next(c['passed'] for c in create_checks('C18',response) if c['name']=='astroid_equation_radius_2m')
    points=[[2*math.cos(t)**3,2*math.sin(t)**3] for t in [i*math.tau/256 for i in range(257)]]
    response['preview_paths']=[{'points':points}]
    assert next(c['passed'] for c in create_checks('C18',response) if c['name']=='astroid_equation_radius_2m')


def test_house_combined_outer_boundary_is_not_missing_a_separate_roof_entity():
    gs=[{'id':1,'type':'polyline','closed':True,'vertices':[{'x':x,'y':y} for x,y in [(0,0),(4000,0),(4000,2000),(2000,3000),(0,2000)]]},
        {'id':2,'type':'polyline','closed':True,'vertices':[{'x':x,'y':y} for x,y in [(1500,0),(2500,0),(2500,1500),(1500,1500)]]}]
    response={'ok':True,'variant':{'geometries':gs,'logical_objects':[{'geometry_refs':[1]},{'geometry_refs':[2]}]},'preview_paths':[{'points':[[0,0],[4,3]]}]}
    checks=create_checks('C16',response)
    assert next(c['passed'] for c in checks if c['name']=='outline_and_door_candidates_present')
    assert not next(c['passed'] for c in checks if c['name']=='house_part_geometry_review')
