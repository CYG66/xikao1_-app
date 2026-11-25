import pytest

from app.cad_semantic_acceptance import verify_semantic_requirements,semantic_requirements
from app.cad_structure_contract import StructureContractError

HOUSE='生成一个房子轮廓，宽4米高3米，屋顶是三角形，下面加一个门'
LETTER='生成一个大写字母A的轮廓，高3米宽2米'


def test_nested_frames_bind_local_dimensions_and_only_report_displaced_inner():
    from copy import deepcopy
    text='画一个嵌套正方形，外框边长3米，内框边长2米，内框居中'
    gs=[poly(1,[(-1500,-1500),(1500,-1500),(1500,1500),(-1500,1500)]),
        poly(2,[(-1000,-1000),(1000,-1000),(1000,1000),(-1000,1000)])]
    assert verify_semantic_requirements(text,gs)['status']=='passed'
    wrong=deepcopy(gs)
    for p in wrong[1]['vertices']:p['x']+=50
    with pytest.raises(StructureContractError) as caught:verify_semantic_requirements(text,wrong)
    assert caught.value.details['geometry_ids']==[2]
    assert caught.value.details['center_error_mm']==50
    wrong=deepcopy(gs)
    for p in wrong[1]['vertices']:p['x']*=1.1;p['y']*=1.1
    with pytest.raises(StructureContractError,match='边长'):verify_semantic_requirements(text,wrong)


def test_regular_polygon_is_not_a_radial_lobed_contour():
    import math
    from copy import deepcopy
    text='画一个六角螺母轮廓，外六角外接圆半径1.5米，中心圆孔半径0.8米'
    outline=poly(1,[(1500*math.cos(i*math.pi/3),1500*math.sin(i*math.pi/3)) for i in range(6)])
    hole={'id':2,'type':'circle','center':{'x':0,'y':0},'radius':800}
    assert verify_semantic_requirements(text,[outline,hole])['status']=='passed'
    wrong=deepcopy(outline)
    wrong['vertices'][1]['x']+=10
    with pytest.raises(StructureContractError):verify_semantic_requirements(text,[wrong,hole])
    wrong=deepcopy(hole);wrong['center']['x']=10
    with pytest.raises(StructureContractError):verify_semantic_requirements(text,[outline,wrong])
    wrong=poly(1,[(r*math.cos(i*math.pi/6),r*math.sin(i*math.pi/6)) for i in range(12) for r in [1500 if i%2==0 else 1300]])
    with pytest.raises(StructureContractError):verify_semantic_requirements(text,[wrong,hole])


def poly(i,points):
    return {'id':i,'type':'polyline','closed':True,'vertices':[{'x':x,'y':y} for x,y in points]}


def house():
    return [poly(1,[(0,0),(4000,0),(4000,2000),(2000,3000),(0,2000)]),
        poly(2,[(1500,0),(2500,0),(2500,1500),(1500,1500)])]


@pytest.mark.parametrize('separate',[False,True])
def test_house_accepts_shared_outer_boundary_or_separate_wall_roof(separate):
    gs=house()
    if separate:
        gs=[poly(1,[(0,0),(4000,0),(4000,2000),(0,2000)]),
            poly(3,[(0,2000),(4000,2000),(2000,3000)]),gs[1]]
    assert verify_semantic_requirements(HOUSE,gs)['checks'][-1]['status']=='passed'


def test_house_linework_and_subdivisions_share_same_semantic_acceptance():
    gs=[]
    for polygon in house():
        points=polygon['vertices']
        for a,b in zip(points,points[1:]+points[:1]):
            midpoint={'x':(a['x']+b['x'])/2,'y':(a['y']+b['y'])/2}
            for start,end in [(a,midpoint),(midpoint,b)]:
                gs.append({'id':len(gs)+1,'type':'line','start':start,'end':end})
    assert verify_semantic_requirements(HOUSE,gs)['checks'][-1]['status']=='passed'


@pytest.mark.parametrize('mutation',['no_door','floating_door','roof_rectangle','door_above_eave','detached_roof'])
def test_house_wrong_semantics_rejected_even_with_correct_overall_bounds(mutation):
    gs=house()
    if mutation=='no_door':gs.pop()
    elif mutation=='floating_door':
        for p in gs[1]['vertices']:p['y']+=100
    elif mutation=='roof_rectangle':gs[0]=poly(1,[(0,0),(4000,0),(4000,3000),(0,3000)])
    elif mutation=='door_above_eave':
        for p in gs[1]['vertices']:
            if p['y']:p['y']=2500
    else:
        gs=[poly(1,[(0,0),(4000,0),(4000,1900),(0,1900)]),
            poly(3,[(0,2000),(4000,2000),(2000,3000)]),gs[1]]
    with pytest.raises(StructureContractError):verify_semantic_requirements(HOUSE,gs)


def letter_outer():
    return poly(1,[(0,0),(850,3000),(1150,3000),(2000,0),(1550,0),(1350,750),(650,750),(450,0)])


def test_filled_letter_requires_real_internal_triangle_not_model_label():
    outer=letter_outer();outer['label']='正确的字母A，结构已验证'
    with pytest.raises(StructureContractError,match='三角区域'):verify_semantic_requirements(LETTER,[outer])
    triangle=poly(2,[(800,1400),(1200,1400),(1000,2400)])
    assert verify_semantic_requirements(LETTER,[outer,triangle])['checks'][-1]['status']=='passed'
    # A disconnected triangle in the gap between the feet is not the counter.
    for p in triangle['vertices']:p['y']-=1400
    with pytest.raises(StructureContractError):verify_semantic_requirements(LETTER,[outer,triangle])


def test_inverted_counter_failure_reports_actual_orientation_for_bounded_repair():
    triangle=poly(2,[(800,2400),(1200,2400),(1000,1400)])
    with pytest.raises(StructureContractError) as caught:
        verify_semantic_requirements(LETTER,[letter_outer(),triangle])
    measured=caught.value.details['measurements']
    assert measured['required_relation']=='triangle_tip_above_horizontal_base'
    observed=measured['observed_triangular_regions']
    assert observed and any(p.get('tip_above_base') is False for p in observed)
    assert '尖点朝上' in semantic_requirements(LETTER)[0]['instruction']


def test_structural_counter_schema_preserves_multiple_paths_without_coordinates():
    from app.cad_construction_interpreter import _request_construction_schema
    contract=semantic_requirements(LETTER)[0]['representation_contract']
    assert contract['minimum_path_count']==2
    assert 'vertices' not in contract and 'coordinates' not in contract
    schema=_request_construction_schema(LETTER)
    steps=schema['$defs']['CadConstructionPlan']['properties']['steps']
    assert steps['minItems']==2 and steps.get('maxItems',100)>=2
    simple=_request_construction_schema('生成一个平滑闭合爱心轮廓，宽4米高4米')
    assert simple['$defs']['CadConstructionPlan']['properties']['steps']['maxItems']==1


def test_closed_bottom_failure_identifies_measured_contact_and_affected_path():
    outer=poly(1,[(0,0),(1000,3000),(2000,0)])
    inner=poly(2,[(800,1400),(1200,1400),(1000,2400)])
    with pytest.raises(StructureContractError,match='支脚') as caught:
        verify_semantic_requirements(LETTER,[outer,inner])
    observed=caught.value.details['measurements']
    assert observed['required_bottom_components']==2 and observed['actual_bottom_components']==1
    assert observed['probe_y_mm']==0
    assert observed['affected_geometries']==[{'geometry_id':1,'intersection_bounds_mm':[0.0,0.0,2000.0,0.0]}]
    assert observed['previously_passed_checks'] and observed['repair_guidance']


def test_centerline_letter_accepts_actual_intersections_and_rejects_disconnected_crossbar():
    gs=[{'id':i,'type':'line','start':{'x':a[0],'y':a[1]},'end':{'x':b[0],'y':b[1]}}
        for i,(a,b) in enumerate([((0,0),(1000,3000)),((1000,3000),(2000,0)),((500,1500),(1500,1500))],1)]
    assert verify_semantic_requirements(LETTER,gs)['checks'][0]['status']=='passed'
    gs[2]['start']['x']+=100;gs[2]['end']['x']-=100
    with pytest.raises(StructureContractError,match='三角区域'):verify_semantic_requirements(LETTER,gs)


def test_triangle_with_continuous_bottom_is_not_letter_a():
    gs=[poly(1,[(0,0),(2000,0),(1000,3000)]),poly(2,[(800,1400),(1200,1400),(1000,2400)])]
    with pytest.raises(StructureContractError,match='支脚'):verify_semantic_requirements(LETTER,gs)


def test_unsupported_styles_and_multiple_objects_are_not_falsely_fully_verified():
    assert not semantic_requirements('生成一个手写艺术字大写字母A')
    assert not semantic_requirements('生成一个爱心和一个大写字母A')
    gs=[{'id':1,'type':'circle','center':{'x':0,'y':0},'radius':1000}]
    assert verify_semantic_requirements(LETTER,gs)['status']=='unverified'
    assert not verify_semantic_requirements('不要生成一个大写字母A',gs)['checks']


def test_generated_metadata_does_not_inject_structural_requirements():
    source='生成一个圆\n最新已确认要求（摘要）：大写字母A，房子轮廓，屋顶是三角形，下面加门'
    assert not semantic_requirements(source)


def test_source_profile_rejects_missing_counter_in_production_interpreter():
    from app.cad_construction_interpreter import interpret_construction_request
    def callback(text,schema):
        assert 'straight_capital_a' in text
        return {'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
            'confidence':.99,'evidence_text':[LETTER],'plan':{'units':'mm','steps':[
                {'op':'add_polyline','step_id':'outline','output_ref':'outline','semantic':{'label':'字母A'},
                 'vertices':letter_outer()['vertices'],'closed':True}]}}
    result=interpret_construction_request(LETTER,callback,force_structured_model=True)
    assert result['status']=='invalid'
    assert '三角区域' in result['error']['message']


def test_closed_profile_schema_allows_internal_contours_and_parts():
    from app.cad_construction_interpreter import _request_construction_schema
    schema=_request_construction_schema(LETTER+'，闭合')
    assert schema['$defs']['CadConstructionPlan']['properties']['steps']['maxItems']>1


def test_unsized_profile_cannot_let_a_confident_model_invent_actual_dimensions():
    from unittest.mock import Mock
    from app.cad_construction_interpreter import interpret_construction_request
    callback=Mock(side_effect=AssertionError('Missing scale must be clarified before model construction'))
    result=interpret_construction_request('生成一个大写字母A的轮廓',callback,force_structured_model=True)
    callback.assert_not_called()
    assert result['error']['code']=='missing_dimensions'
    assert result['status']=='clarification_required'
    assert result['clarification']['recognized_shape']=='大写字母A的轮廓'
