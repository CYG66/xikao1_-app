import math
from copy import deepcopy
import pytest
from app.cad_repetition_acceptance import verify_repetition_requirements
from app.cad_structure_contract import StructureContractError


def test_tooth_tops_are_not_single_star_peaks():
    text='生成一个齿轮轮廓，外径2米，8个齿，齿根圆直径1.5米，各齿齿顶角宽15度'
    points=[]
    for i in range(8):
        for delta,radius in [(-7.5,1000),(7.5,1000),(15,750),(30,750)]:
            angle=math.radians(i*45+delta)
            points.append({'x':radius*math.cos(angle),'y':radius*math.sin(angle)})
    geometry={'id':1,'type':'polyline','closed':True,'vertices':points}
    assert verify_repetition_requirements(text,[geometry])['checks']
    segments=[{'id':i+1,'type':'line','start':p,'end':points[(i+1)%len(points)]}
              for i,p in enumerate(points)]
    assert verify_repetition_requirements(text,segments)['checks']
    with pytest.raises(StructureContractError,match='闭合边界'):
        verify_repetition_requirements(text,segments[:-1])
    with pytest.raises(StructureContractError,match='闭合边界'):
        verify_repetition_requirements(text,segments+[dict(segments[0],id=100)])
    star=deepcopy(geometry)
    star['vertices']=[{'x':(1000 if i%2==0 else 750)*math.cos(i*math.pi/8),
        'y':(1000 if i%2==0 else 750)*math.sin(i*math.pi/8)} for i in range(16)]
    with pytest.raises(StructureContractError,match='齿顶'):
        verify_repetition_requirements(text,[star])


def test_arc_and_line_teeth_use_the_same_boundary_requirements():
    text='生成一个齿轮轮廓，外径2米，8个齿，齿根圆直径1.5米，各齿齿顶角宽15度'
    geometries=[]
    def point(radius,angle):
        return {'x':radius*math.cos(math.radians(angle)),'y':radius*math.sin(math.radians(angle))}
    for i in range(8):
        angle=i*45
        geometries.extend([
            {'type':'arc','center':{'x':0,'y':0},'radius':1000,'start_angle':angle-7.5,'end_angle':angle+7.5},
            {'type':'line','start':point(1000,angle+7.5),'end':point(750,angle+15)},
            {'type':'arc','center':{'x':0,'y':0},'radius':750,'start_angle':angle+15,'end_angle':angle+30},
            {'type':'line','start':point(750,angle+30),'end':point(1000,angle+37.5)}])
    for i,g in enumerate(geometries):g['id']=i+1
    assert verify_repetition_requirements(text,geometries)['checks']


def test_parallel_strip_local_dimensions_and_edge_vs_center_spacing():
    text='画6条平行横线，每条长4米宽0.4米，间距0.6米'
    gs=[{'id':i+1,'type':'polyline','closed':True,'vertices':[
        {'x':x,'y':y+i*1000} for x,y in [(0,0),(4000,0),(4000,400),(0,400)]]} for i in range(6)]
    assert verify_repetition_requirements(text,gs)['checks']
    with pytest.raises(StructureContractError,match='间距'):
        verify_repetition_requirements(text.replace('间距','中心距'),gs)
    with pytest.raises(StructureContractError,match='数量'):
        verify_repetition_requirements(text,gs[:-1])
    wrong=deepcopy(gs)
    for p in wrong[3]['vertices']:p['y']+=50
    with pytest.raises(StructureContractError,match='间距') as caught:
        verify_repetition_requirements(text,wrong)
    assert set(caught.value.details['geometry_ids'])=={3,4}


def test_branch_network_schema_is_not_a_closed_boundary_schema():
    from app.cad_construction_interpreter import _request_construction_schema
    from app.cad_repetition_acceptance import branch_structure_requirements
    text='生成一个雪花图案，6条对称分支，每条分支带2个侧枝，最大半径2米'
    schema=_request_construction_schema(text)
    props=schema['$defs']['CadConstructionPlan']['properties']
    assert props['steps']['minItems']==props['steps']['maxItems']==18
    assert props['steps']['items']=={'$ref':'#/$defs/AddLineStep'}
    assert props['assertions']['items']=={'$ref':'#/$defs/EntityCountAssertion'}
    assert branch_structure_requirements(text+'，侧枝使用圆弧') is None
    assert branch_structure_requirements('生成两个图案，3条对称分支，每条分支带2个侧枝') is None
    assert branch_structure_requirements('生成一个图案，3条对称分支，每条分支带2个侧枝')['entity_count']==9


def test_step_dimensions_are_local_and_cannot_be_replaced_by_total_dimensions():
    source='生成一段楼梯轮廓，5级台阶，每级宽0.4米高0.3米'
    points=[{'x':0,'y':0}]
    for i in range(5):points.extend([{'x':(i+1)*400,'y':i*300},{'x':(i+1)*400,'y':(i+1)*300}])
    gs=[{'id':1,'type':'polyline','closed':False,'vertices':points}]
    assert verify_repetition_requirements(source,gs)['checks']
    closed=deepcopy(gs);closed[0]['closed']=True
    closed[0]['vertices'].append({'x':2000,'y':0})
    assert verify_repetition_requirements(source,closed)['checks']
    smaller=deepcopy(gs)
    for point in smaller[0]['vertices']:point['x']/=5;point['y']/=5
    with pytest.raises(StructureContractError):verify_repetition_requirements(source,smaller)


def test_rotational_correspondence_rejects_one_side_branch_with_wrong_length():
    source='生成一个图案，6条对称分支，每条分支带2个侧枝'
    gs=[]
    for i in range(6):
        angle=i*math.pi/3
        def turn(x,y):return {'x':x*math.cos(angle)-y*math.sin(angle),'y':x*math.sin(angle)+y*math.cos(angle)}
        for a,b in [((0,0),(2000,0)),((1200,0),(1450,433.0127019)),((1200,0),(1450,-433.0127019))]:
            gs.append({'id':len(gs)+1,'type':'line','start':turn(*a),'end':turn(*b)})
    assert verify_repetition_requirements(source,gs)['checks']
    specified=source+'，侧枝长度0.5米，在半径1.2米处，与主枝夹角60度'
    assert verify_repetition_requirements(specified,gs)['checks']
    uniformly_wrong=deepcopy(gs)
    for g in uniformly_wrong:
        if math.hypot(g['start']['x'],g['start']['y'])<1:continue
        for axis in ('x','y'):g['end'][axis]=g['start'][axis]+2*(g['end'][axis]-g['start'][axis])
    with pytest.raises(StructureContractError,match='侧枝原文长度'):
        verify_repetition_requirements(specified,uniformly_wrong)
    gs[-1]['end']['x']+=250
    with pytest.raises(StructureContractError):verify_repetition_requirements(source,gs)


def test_tiling_rejects_overlapping_or_disconnected_regular_cells():
    source='生成2列1行六边形阵列，边长0.5米，无缝拼接'
    def cell(cx,cy,gid):return {'id':gid,'type':'polyline','closed':True,'vertices':[
        {'x':cx+500*math.cos(i*math.pi/3),'y':cy+500*math.sin(i*math.pi/3)} for i in range(6)]}
    assert verify_repetition_requirements(source,[cell(0,0,1),cell(750,math.sqrt(3)*250,2)])['checks']
    for distance in (100,2000):
        with pytest.raises(StructureContractError):verify_repetition_requirements(source,[cell(0,0,1),cell(distance,0,2)])


def test_tiling_reports_all_conflicts_in_one_bounded_repair():
    source='生成3列1行六边形阵列，边长0.5米，无缝拼接'
    geometries=[{'id':j+1,'type':'polyline','closed':True,'vertices':[
        {'x':j*100+500*math.cos(i*math.pi/3),'y':500*math.sin(i*math.pi/3)}
        for i in range(6)]} for j in range(3)]
    before=deepcopy(geometries)
    with pytest.raises(StructureContractError) as caught:
        verify_repetition_requirements(source,geometries)
    assert caught.value.details['geometry_ids']==[1,2,3]
    assert len(caught.value.details['measurements']['overlap_pairs'])==3
    assert geometries==before


def test_wrong_local_dimensions_are_rejected_by_production_interpreter():
    from app.cad_construction_interpreter import interpret_construction_request
    source='生成一段楼梯轮廓，5级台阶，每级宽0.4米高0.3米'
    vertices=[{'x':0,'y':0}]
    for i in range(5):vertices.extend([{'x':(i+1)*.08,'y':i*.06},{'x':(i+1)*.08,'y':(i+1)*.06}])
    payload={'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
        'plan':{'units':'m','steps':[{'op':'add_polyline','step_id':'stairs','output_ref':'stairs',
            'semantic':{'label':'阶梯'},'closed':False,'vertices':vertices}]},
        'confidence':.99,'evidence_text':[source],'assumptions':[]}
    result=interpret_construction_request(source,lambda *_:payload,force_structured_model=True)
    assert result['status']!='ready'
    assert result['construction_error']['code']=='structure_requirement_failed'
