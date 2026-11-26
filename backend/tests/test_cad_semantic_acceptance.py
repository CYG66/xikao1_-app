import math
import pytest

from app.cad_semantic_acceptance import verify_semantic_requirements,semantic_requirements
from app.cad_semantic_dispatch import validate_target_binding
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


# ---------------------------------------------------------------------------
# Round8 A-line: binding interface contract and payload validation (zero model)
# ---------------------------------------------------------------------------

HEART_TEXT='生成一个闭合爱心轮廓，宽度4米，高度4米'

_HEART_NORM=[(0.20,0.90),(0.50,0.62),(0.80,0.90),(0.95,0.50),
    (0.75,0.20),(0.50,0.00),(0.25,0.20),(0.05,0.50)]


def _heart(i=1,scale=2000.0,ox=0.0):
    return {'id':i,'type':'polyline','closed':True,'selected':True,
        'vertices':[{'x':round(x*scale+ox,3),'y':round(y*scale,3)} for x,y in _HEART_NORM]}


def _star(i=2,ox=3000.0,ro=1000.0,ri=400.0,cy=1000.0):
    pts=[]
    for k in range(10):
        r=ro if k%2==0 else ri
        ang=math.pi/2+k*math.pi/5
        pts.append({'x':round(r*math.cos(ang)+ox,3),'y':round(r*math.sin(ang)+cy,3)})
    return {'id':i,'type':'polyline','closed':True,'selected':True,'vertices':pts}


def _codes(validation):
    return [e['code'] for e in validation['errors']]


def test_bound_single_object_uses_backend_resolved_refs():
    geoms=[_heart(1)]
    logical=[{'object_id':'heart-1','geometry_refs':[1],'label':'爱心','confidence':1.0}]
    res=verify_semantic_requirements(HEART_TEXT,geoms,logical_objects=logical)
    assert res['review_required'] is False
    assert res['status']=='passed'
    assert res['checks'][-1]['name']=='heart_outline_requirements_complete'
    assert res['checks'][-1]['status']=='passed'
    assert res['binding_source']=='logical_objects.geometry_refs'
    assert res['binding_auxiliary'] is False
    entry=res['object_acceptance'][0]
    assert entry['target_ref']['geometry_ids']==[1]
    assert entry['target_ref']['identity_basis']=='backend_resolved_geometry_refs'
    assert entry['target_ref']['model_declared_object_id_trusted_as_identity'] is False


def test_bound_two_objects_are_kept_separate():
    geoms=[_heart(1,scale=2000.0),_star(2)]
    logical=[{'object_id':'heart-1','geometry_refs':[1],'label':'爱心'},
             {'object_id':'star-1','geometry_refs':[2],'label':'五角星'}]
    res=verify_semantic_requirements(HEART_TEXT,geoms,logical_objects=logical)
    assert res['status']=='partial'
    assert res['review_required'] is True
    refs=[o['target_ref']['geometry_ids'] for o in res['object_acceptance']]
    assert refs==[[1],[2]]
    statuses=[o['status'] for o in res['object_acceptance']]
    assert statuses==['passed','not_checked']


def test_dangling_geometry_ref_rejected_without_fuzzy_match():
    geoms=[_heart(1)]
    logical=[{'object_id':'heart-1','geometry_refs':[999]}]
    res=verify_semantic_requirements(HEART_TEXT,geoms,logical_objects=logical)
    assert res['status']=='unresolved'
    assert res['coverage']=='target_unresolved'
    assert res['review_required'] is True
    assert res['reason']=='invalid_target_binding'
    assert 'dangling_geometry_refs' in _codes(res['binding_validation'])
    assert res['status']!='passed'


def test_duplicate_refs_within_one_object_rejected():
    geoms=[_heart(1)]
    validation=validate_target_binding(geoms,[{'object_id':'o-1','geometry_refs':[1,1]}])
    assert validation['status']=='unresolved'
    assert 'duplicate_geometry_refs' in _codes(validation)
    assert validation['targets']==[]


def test_empty_ref_list_rejected():
    geoms=[_heart(1)]
    validation=validate_target_binding(geoms,[{'object_id':'o-1','geometry_refs':[]}])
    assert validation['status']=='unresolved'
    assert 'missing_geometry_refs' in _codes(validation)


def test_non_list_logical_objects_payload_rejected():
    res=verify_semantic_requirements(HEART_TEXT,[_heart(1)],logical_objects='heart-1')
    assert res['status']=='unresolved'
    assert res['review_required'] is True
    assert 'invalid_logical_objects_payload' in _codes(res['binding_validation'])


def test_duplicate_object_id_rejected():
    geoms=[_heart(1),_star(2)]
    logical=[{'object_id':'same','geometry_refs':[1]},
             {'object_id':'same','geometry_refs':[2]}]
    validation=validate_target_binding(geoms,logical)
    assert validation['status']=='unresolved'
    assert 'duplicate_object_id' in _codes(validation)


def test_one_object_with_multiple_disconnected_geometries_stays_one_target():
    g1=_heart(1,scale=1000.0,ox=0.0)
    g2=_heart(2,scale=1000.0,ox=4000.0)
    logical=[{'object_id':'composite-1','geometry_refs':[1,2]}]
    validation=validate_target_binding([g1,g2],logical)
    assert validation['status']=='bound'
    assert len(validation['targets'])==1
    assert validation['targets'][0]['target_ref']['geometry_ids']==[1,2]


def test_touching_distinct_objects_are_not_merged():
    # Heart 2's left vertex coincides with heart 1's right vertex (950,500).
    g1=_heart(1,scale=1000.0,ox=0.0)
    g2=_heart(2,scale=1000.0,ox=900.0)
    logical=[{'object_id':'h-1','geometry_refs':[1]},
             {'object_id':'h-2','geometry_refs':[2]}]
    validation=validate_target_binding([g1,g2],logical)
    assert validation['status']=='bound'
    assert len(validation['targets'])==2
    assert [t['target_ref']['geometry_ids'] for t in validation['targets']]==[[1],[2]]
    assert any(w['code']=='contact_or_overlap_between_distinct_objects'
               for w in validation['warnings'])


def test_overlapping_distinct_objects_are_not_merged():
    g1=_heart(1,scale=1000.0,ox=0.0)
    g2=_heart(2,scale=1000.0,ox=500.0)
    logical=[{'object_id':'h-1','geometry_refs':[1]},
             {'object_id':'h-2','geometry_refs':[2]}]
    validation=validate_target_binding([g1,g2],logical)
    assert validation['status']=='bound'
    assert len(validation['targets'])==2
    relations=[w.get('relation') for w in validation['warnings']
               if w['code']=='contact_or_overlap_between_distinct_objects']
    assert relations and relations[0] in {'intersects','touching','bounds_overlap'}


def test_missing_logical_objects_falls_back_to_auxiliary_components_only():
    res=verify_semantic_requirements(HEART_TEXT,[_heart(1)])
    assert res['binding_source']=='connected_components'
    assert res['binding_auxiliary'] is True
    assert res['review_required'] is False
    assert res['status']=='passed'
    validation=validate_target_binding([_heart(1)])
    assert validation['auxiliary'] is True
    assert validation['targets'][0]['target_ref']['binding_source']=='connected_components'


def test_unowned_active_geometry_is_reported_not_silently_bound():
    g1=_heart(1,scale=1000.0,ox=0.0)
    g2=_star(2,ox=3000.0)
    logical=[{'object_id':'h-1','geometry_refs':[1]}]
    validation=validate_target_binding([g1,g2],logical)
    assert validation['status']=='bound'
    assert validation['unowned_geometry_ids']==[2]
    assert len(validation['targets'])==1


def test_model_declared_label_does_not_promote_to_identity():
    geoms=[_heart(1)]
    logical=[{'object_id':'declared-by-model','assembly_id':'asm-1',
              'geometry_refs':[1],'label':'模型自报的爱心'}]
    validation=validate_target_binding(geoms,logical)
    ref=validation['targets'][0]['target_ref']
    assert ref['geometry_ids']==[1]
    assert ref['object_id']=='declared-by-model'
    assert ref['identity_basis']=='backend_resolved_geometry_refs'
    assert ref['model_declared_object_id_trusted_as_identity'] is False


def test_ref_to_role_excluded_geometry_is_rejected_and_diagnosed():
    active=_heart(1,scale=1000.0,ox=0.0)
    excluded=_heart(2,scale=1000.0,ox=4000.0);excluded['role']='annotation'
    res=verify_semantic_requirements(HEART_TEXT,[active,excluded],
        logical_objects=[{'object_id':'h-2','geometry_refs':[2]}])
    assert res['status']=='unresolved'
    assert res['review_required'] is True
    codes=_codes(res['binding_validation'])
    assert 'excluded_geometry_ref' in codes
    assert res['binding_validation']['excluded_geometry_ids']==[2]
    assert res['binding_validation']['excluded_geometries'][0]['role']=='annotation'


def test_shared_geometry_without_topology_declaration_rejected():
    g1=_heart(1,scale=1000.0,ox=0.0)
    logical=[{'object_id':'a','geometry_refs':[1]},
             {'object_id':'b','geometry_refs':[1]}]
    validation=validate_target_binding([g1],logical)
    assert validation['status']=='unresolved'
    assert 'undeclared_shared_geometry' in _codes(validation)


def test_shared_geometry_matching_topology_declaration_is_bound():
    g1=_heart(1,scale=1000.0,ox=0.0)
    logical=[{'object_id':'a','geometry_refs':[1]},
             {'object_id':'b','geometry_refs':[1]}]
    topology={'shared_geometries':[{'geometry_id':1,'object_ids':['a','b']}]}
    validation=validate_target_binding([g1],logical,topology=topology)
    assert validation['status']=='bound'
    assert len(validation['targets'])==2
    assert validation['shared_geometry_owners']=={'1':['a','b']}


def test_disconnected_members_are_warned_but_not_split():
    g1=_heart(1,scale=1000.0,ox=0.0)
    g2=_heart(2,scale=1000.0,ox=4000.0)
    logical=[{'object_id':'composite-1','geometry_refs':[1,2]}]
    validation=validate_target_binding([g1,g2],logical)
    assert validation['status']=='bound'
    assert len(validation['targets'])==1
    assert validation['targets'][0]['target_ref']['geometry_ids']==[1,2]
    member_warnings=[w for w in validation['warnings'] if w['code']=='disconnected_members']
    assert member_warnings and member_warnings[0]['component_count']==2


# ---------------------------------------------------------------------------
# Round9 A-line: semantic coverage completeness contract (zero model)
# ---------------------------------------------------------------------------

from app.cad_semantic_dispatch import (  # noqa: E402
    DECISION_AMBIGUOUS_UNRESOLVED,
    DECISION_APPLICABLE,
    DECISION_NO_SIGNAL,
    DECISION_RESOLVED_NON_STAR,
    STATE_FULLY_VERIFIED,
    STATE_NO_APPLICABLE_REQUIREMENT,
    STATE_UNVERIFIED_OR_PARTIAL,
    ambiguous_requirement_kinds_from_text,
    recognized_star_family_unsupported_kinds_from_text,
    recognized_unverifiable_kinds_from_text,
    semantic_requirement_state,
    state_allows_summary_passed,
)
import app.cad_semantic_acceptance as acceptance_mod  # noqa: E402

C10_TEXT='生成一个爱心和一个五角星，爱心在左，五角星在右'
STAR_ONLY_TEXT='生成一个五角星，外接圆半径2米，内外半径比0.381966，尖角朝上'


def test_contract_no_applicable_requirement_resolves_to_state_one():
    report=verify_semantic_requirements('画一个花瓶',[_heart(1)])
    verdict=semantic_requirement_state(report,'画一个花瓶')
    assert verdict['state']==STATE_NO_APPLICABLE_REQUIREMENT
    assert verdict['applicable_requirement_kinds']==[]
    assert verdict['recognized_unknown_kinds']==[]
    assert state_allows_summary_passed(verdict) is True


def test_contract_fully_verified_passed_report_resolves_to_state_two():
    text='画一个嵌套正方形，外框边长3米，内框边长2米，内框居中'
    gs=[poly(1,[(-1500,-1500),(1500,-1500),(1500,1500),(-1500,1500)]),
        poly(2,[(-1000,-1000),(1000,-1000),(1000,1000),(-1000,1000)])]
    report=verify_semantic_requirements(text,gs)
    assert report['status']=='passed'
    verdict=semantic_requirement_state(report,text)
    assert verdict['state']==STATE_FULLY_VERIFIED
    assert state_allows_summary_passed(verdict) is True
    # Synthetic heart report whose every bound object passed: fully verified.
    heart_report={
        'status':'passed','review_required':False,
        'requirements':[{'kind':'heart_outline_features'}],
        'object_acceptance':[{'target_ref':{'object_id':'heart-1','geometry_ids':[1]},
            'status':'passed','reason':'heart_features_measured','profile':'heart_like'}],
    }
    v2=semantic_requirement_state(heart_report)
    assert v2['state']==STATE_FULLY_VERIFIED
    assert state_allows_summary_passed(v2) is True


def test_contract_c10_heart_star_is_unverified_or_partial():
    geoms=[_heart(1,scale=2000.0),_star(2)]
    logical=[{'object_id':'heart-1','geometry_refs':[1],'label':'爱心'},
             {'object_id':'star-1','geometry_refs':[2],'label':'五角星'}]
    report=verify_semantic_requirements(C10_TEXT,geoms,logical_objects=logical)
    verdict=semantic_requirement_state(report,C10_TEXT)
    assert verdict['state']==STATE_UNVERIFIED_OR_PARTIAL
    assert 'object_not_checked' in verdict['reasons']
    assert 'no_verifier' in verdict['reasons']
    affected={a['geometry_ids'][0]:a for a in verdict['affected']}
    assert 1 not in affected  # 爱心对象通过，不进入被拖累清单
    assert affected[2]['reason']=='no_verifier_for_star_profile'
    assert state_allows_summary_passed(verdict) is False


def test_contract_house_and_letter_partial_review_false_stay_state_three():
    house_report=verify_semantic_requirements(HOUSE,house())
    vh=semantic_requirement_state(house_report,HOUSE)
    assert vh['state']==STATE_UNVERIFIED_OR_PARTIAL
    assert 'partial_overall' in vh['reasons']
    assert house_report['review_required'] is False
    assert state_allows_summary_passed(vh) is False
    letter_triangle=poly(2,[(800,1400),(1200,1400),(1000,2400)])
    letter_report=verify_semantic_requirements(LETTER,[letter_outer(),letter_triangle])
    vl=semantic_requirement_state(letter_report,LETTER)
    assert vl['state']==STATE_UNVERIFIED_OR_PARTIAL
    assert 'partial_overall' in vl['reasons']
    assert letter_report['review_required'] is False
    assert state_allows_summary_passed(vl) is False


def test_contract_unknown_kind_resolves_to_state_three():
    orig=acceptance_mod.semantic_requirements
    acceptance_mod.semantic_requirements=lambda text:[{'kind':'mystery_contour','instruction':'未知轮廓'}]
    try:
        report=verify_semantic_requirements(HEART_TEXT,[_heart(1,4000.0)])
    finally:
        acceptance_mod.semantic_requirements=orig
    verdict=semantic_requirement_state(report,HEART_TEXT)
    assert verdict['state']==STATE_UNVERIFIED_OR_PARTIAL
    assert 'unknown_kind' in verdict['reasons']
    assert 'no_verifier' in verdict['reasons']
    assert 'mystery_contour' in verdict['recognized_unknown_kinds']
    assert state_allows_summary_passed(verdict) is False


def test_contract_star_only_not_checked_is_state_three_not_one():
    report=verify_semantic_requirements(STAR_ONLY_TEXT,[_star(1,ox=0.0)])
    assert report['status']=='not_checked'
    assert 'star_profile' in report['applicable_requirement_kinds']
    verdict=semantic_requirement_state(report,STAR_ONLY_TEXT)
    assert verdict['state']==STATE_UNVERIFIED_OR_PARTIAL
    assert 'report_unchecked_applicable' in verdict['reasons']
    assert state_allows_summary_passed(verdict) is False


def test_contract_missing_report_is_state_three_not_state_one():
    verdict=semantic_requirement_state(None)
    assert verdict['state']==STATE_UNVERIFIED_OR_PARTIAL
    assert 'report_unavailable' in verdict['reasons']
    assert state_allows_summary_passed(verdict) is False


# ---------------------------------------------------------------------------
# Round11 R-04: explicit / ambiguous / not-applicable star scope (zero model)
# ---------------------------------------------------------------------------

def _regular_poly(i, n, r=1000.0, cy=1000.0):
    pts=[{'x':round(r*math.cos(k*math.tau/n),3),
          'y':round(cy+r*math.sin(k*math.tau/n),3)} for k in range(n)]
    return {'id':i,'type':'polyline','closed':True,'selected':True,'vertices':pts}


def _rect(i):
    return {'id':i,'type':'polyline','closed':True,'selected':True,
            'vertices':[{'x':-1000,'y':0},{'x':1000,'y':0},
                        {'x':1000,'y':2000},{'x':-1000,'y':2000}]}


def _circle(i):
    return {'id':i,'type':'circle','center':{'x':0,'y':1000},'radius':1000}


@pytest.mark.parametrize('word', ['五角星', '五芒星', '星形轮廓'])
def test_r04_explicit_star_vocabulary_applicable_not_checked(word):
    text=f'画一个{word}'
    report=verify_semantic_requirements(text, [])
    assert report['status']=='not_checked'
    assert report['review_required'] is True
    assert 'star_profile' in report['applicable_requirement_kinds']
    verdict=semantic_requirement_state(report, text)
    assert verdict['state']==STATE_UNVERIFIED_OR_PARTIAL
    assert state_allows_summary_passed(verdict) is False


def test_r04_ambiguous_word_with_star_geometry_is_applicable_unverified():
    text='画一个五角形'
    report=verify_semantic_requirements(text, [_star(1, ox=0.0)])
    verdict=semantic_requirement_state(report, text)
    assert 'star_profile' in verdict['applicable_requirement_kinds']
    assert verdict['state']==STATE_UNVERIFIED_OR_PARTIAL
    assert 'no_verifier' in verdict['reasons']
    assert 'object_not_checked' in verdict['reasons']
    assert state_allows_summary_passed(verdict) is False
    star_entry=[o for o in report['object_acceptance'] if o['profile']=='star']
    assert star_entry and star_entry[0]['reason']=='no_verifier_for_star_profile'


def test_r04_ambiguous_word_with_convex_pentagon_is_released():
    text='画一个五角形'
    report=verify_semantic_requirements(text, [_regular_poly(1, 5)])
    verdict=semantic_requirement_state(report, text)
    assert verdict['applicable_requirement_kinds']==[]
    assert verdict['state']==STATE_NO_APPLICABLE_REQUIREMENT
    assert state_allows_summary_passed(verdict) is True
    assert report.get('ambiguity_resolution')=='resolved_non_star'


def test_r04_ambiguous_word_without_geometry_stays_unresolved():
    for text in ('画一个星星', '画一个星形'):
        report=verify_semantic_requirements(text, [])
        verdict=semantic_requirement_state(report, text)
        assert verdict['applicable_requirement_kinds']==[]
        assert verdict['ambiguous_requirement_kinds']==['star_profile']
        assert verdict['state']==STATE_UNVERIFIED_OR_PARTIAL
        assert 'ambiguous_requirement' in verdict['reasons']
        assert verdict['review_required'] is True
        assert state_allows_summary_passed(verdict) is False


@pytest.mark.parametrize('label,text,geometry', [
    ('hexagon', '画一个六边形', _regular_poly(1, 6)),
    ('circle', '画一个圆', _circle(1)),
    ('rectangle', '画一个矩形', _rect(1)),
    ('plain_pentagon', '画一个五边形', _regular_poly(1, 5)),
])
def test_r04_ordinary_shapes_are_not_intercepted(label, text, geometry):
    report=verify_semantic_requirements(text, [geometry])
    verdict=semantic_requirement_state(report, text)
    assert verdict['applicable_requirement_kinds']==[]
    assert verdict['ambiguous_requirement_kinds']==[]
    assert verdict['state']==STATE_NO_APPLICABLE_REQUIREMENT
    assert state_allows_summary_passed(verdict) is True


def test_r04_astroid_is_not_treated_as_star():
    text='星形线 astroid 具有四个内禀尖点'
    assert semantic_requirements(text)[0]['kind']=='astroid_identity'
    assert recognized_unverifiable_kinds_from_text(text)==[]
    assert ambiguous_requirement_kinds_from_text(text)==[]


def test_r04_c10_heart_passes_star_not_checked_partial():
    geoms=[_heart(1, scale=2000.0), _star(2)]
    logical=[{'object_id':'heart-1','geometry_refs':[1],'label':'爱心'},
             {'object_id':'star-1','geometry_refs':[2],'label':'五角星'}]
    report=verify_semantic_requirements(C10_TEXT, geoms, logical_objects=logical)
    verdict=semantic_requirement_state(report, C10_TEXT)
    assert report['status']=='partial'
    assert report['review_required'] is True
    by_id={o['target_ref']['object_id']: o for o in report['object_acceptance']}
    assert by_id['heart-1']['status']=='passed'
    assert by_id['star-1']['status']=='not_checked'
    assert by_id['star-1']['reason']=='no_verifier_for_star_profile'
    assert verdict['state']==STATE_UNVERIFIED_OR_PARTIAL
    assert state_allows_summary_passed(verdict) is False


# ---------------------------------------------------------------------------
# Round11 R-04 second round: authorization boundary + explicit decision field
# ---------------------------------------------------------------------------

def test_r04_round2_w1_star_like_geometry_without_source_signal_is_released():
    # W1: wording carries no star / ambiguous signal; a star-like backend
    # profile must NOT fabricate an applicable star requirement.
    text='画一个圆和一个矩形'
    report=verify_semantic_requirements(text, [_star(1, ox=0.0)])
    assert report['applicable_requirement_kinds']==[]
    assert report['ambiguous_requirement_kinds']==[]
    assert report.get('applicability_decision')==DECISION_NO_SIGNAL
    assert all(o['reason']!='no_verifier_for_star_profile'
               for o in report.get('object_acceptance') or [])
    verdict=semantic_requirement_state(report, text)
    assert verdict['applicability_decision']==DECISION_NO_SIGNAL
    assert verdict['state']==STATE_NO_APPLICABLE_REQUIREMENT
    assert state_allows_summary_passed(verdict) is True


def test_r04_round2_m1_ambiguous_pentagon_carries_resolved_non_star_decision():
    # M1: ambiguous wording resolved against a convex pentagon must survive
    # the gate as an explicit resolved_non_star decision and release.
    text='生成一个五角形'
    report=verify_semantic_requirements(text, [_regular_poly(1, 5)])
    assert report.get('ambiguity_resolution')=='resolved_non_star'
    assert report.get('applicability_decision')==DECISION_RESOLVED_NON_STAR
    verdict=semantic_requirement_state(report, text)
    assert verdict['applicability_decision']==DECISION_RESOLVED_NON_STAR
    assert verdict['applicable_requirement_kinds']==[]
    assert verdict['state']==STATE_NO_APPLICABLE_REQUIREMENT
    assert state_allows_summary_passed(verdict) is True


def test_r04_round2_m1b_ambiguous_word_with_star_geometry_still_blocked():
    # The original defect must stay closed: ambiguous wording + star outline.
    text='画一个五角形'
    report=verify_semantic_requirements(text, [_star(1, ox=0.0)])
    assert report.get('applicability_decision')==DECISION_APPLICABLE
    verdict=semantic_requirement_state(report, text)
    assert verdict['applicability_decision']==DECISION_APPLICABLE
    assert 'star_profile' in verdict['applicable_requirement_kinds']
    assert verdict['state']==STATE_UNVERIFIED_OR_PARTIAL
    assert state_allows_summary_passed(verdict) is False


def test_r04_round2_unresolved_ambiguity_carries_ambiguous_unresolved_decision():
    for text in ('画一个星星', '画一个星形'):
        report=verify_semantic_requirements(text, [])
        assert report.get('applicability_decision')==DECISION_AMBIGUOUS_UNRESOLVED
        verdict=semantic_requirement_state(report, text)
        assert verdict['applicability_decision']==DECISION_AMBIGUOUS_UNRESOLVED
        assert verdict['state']==STATE_UNVERIFIED_OR_PARTIAL
        assert 'ambiguous_requirement' in verdict['reasons']
        assert state_allows_summary_passed(verdict) is False


def test_r04_round2_explicit_star_words_carry_applicable_decision():
    for word in ('五角星', '五芒星', '星形轮廓'):
        text=f'画一个{word}'
        report=verify_semantic_requirements(text, [])
        assert report.get('applicability_decision')==DECISION_APPLICABLE
        verdict=semantic_requirement_state(report, text)
        assert verdict['applicability_decision']==DECISION_APPLICABLE
        assert verdict['state']==STATE_UNVERIFIED_OR_PARTIAL
        assert state_allows_summary_passed(verdict) is False


@pytest.mark.parametrize('label,text,geometry', [
    ('hexagon', '画一个六边形', _regular_poly(1, 6)),
    ('circle', '画一个圆', _circle(1)),
    ('rectangle', '画一个矩形', _rect(1)),
    ('plain_pentagon', '画一个五边形', _regular_poly(1, 5)),
])
def test_r04_round2_ordinary_shapes_carry_no_signal_decision(label, text, geometry):
    report=verify_semantic_requirements(text, [geometry])
    assert report.get('applicability_decision')==DECISION_NO_SIGNAL
    verdict=semantic_requirement_state(report, text)
    assert verdict['applicability_decision']==DECISION_NO_SIGNAL
    assert verdict['state']==STATE_NO_APPLICABLE_REQUIREMENT
    assert state_allows_summary_passed(verdict) is True


def test_r04_round2_c10_decision_is_applicable():
    geoms=[_heart(1, scale=2000.0), _star(2)]
    logical=[{'object_id':'heart-1','geometry_refs':[1],'label':'爱心'},
             {'object_id':'star-1','geometry_refs':[2],'label':'五角星'}]
    report=verify_semantic_requirements(C10_TEXT, geoms, logical_objects=logical)
    assert report.get('applicability_decision')==DECISION_APPLICABLE
    verdict=semantic_requirement_state(report, C10_TEXT)
    assert verdict['applicability_decision']==DECISION_APPLICABLE
    assert verdict['state']==STATE_UNVERIFIED_OR_PARTIAL
    assert state_allows_summary_passed(verdict) is False


# ---------------------------------------------------------------------------
# Round11 R-04 third round: recognized-but-unverifiable star-family intent
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('text,kind', [
    ('画一个四角星', 'four_pointed_star'),
    ('画一个六角星', 'six_pointed_star'),
    ('画一个六芒星', 'six_pointed_star'),
    ('画一个星号', 'asterisk'),
    ('draw a star', 'star_family_generic'),
    ('a five-pointed star', 'star_family_generic'),
    ('一个star', 'star_family_generic'),
])
def test_r04_round3_star_family_intent_recorded_and_blocked(text, kind):
    assert recognized_star_family_unsupported_kinds_from_text(text)==[kind]
    report=verify_semantic_requirements(text, [])
    assert report['status']=='unverified'
    assert report['coverage']=='unsupported_semantic_kind'
    assert report['review_required'] is True
    assert report['unsupported_kind']==kind
    assert kind in report['applicable_requirement_kinds']
    assert 'star_profile' not in report['applicable_requirement_kinds']
    verdict=semantic_requirement_state(report, text)
    assert verdict['applicability_decision']==DECISION_APPLICABLE
    assert verdict['recognized_unknown_kinds']==[]
    assert verdict['state']==STATE_UNVERIFIED_OR_PARTIAL
    assert 'no_verifier' in verdict['reasons']
    assert state_allows_summary_passed(verdict) is False


def test_r04_round3_english_word_start_is_not_star_family():
    text='start here'
    assert recognized_star_family_unsupported_kinds_from_text(text)==[]
    report=verify_semantic_requirements(text, [])
    verdict=semantic_requirement_state(report, text)
    assert verdict['state']==STATE_NO_APPLICABLE_REQUIREMENT
    assert state_allows_summary_passed(verdict) is True


def test_r04_round3_ordinary_shapes_and_w1_boundary_still_released():
    controls=[
        ('画一个圆和一个矩形', _star(1, ox=0.0)),
        ('画一个六边形', _regular_poly(1, 6)),
        ('画一个圆', _circle(1)),
        ('画一个矩形', _rect(1)),
        ('画一个五边形', _regular_poly(1, 5)),
    ]
    for text, geometry in controls:
        report=verify_semantic_requirements(text, [geometry])
        verdict=semantic_requirement_state(report, text)
        assert verdict['applicability_decision']==DECISION_NO_SIGNAL, text
        assert verdict['state']==STATE_NO_APPLICABLE_REQUIREMENT, text
        assert state_allows_summary_passed(verdict) is True, text


def test_r04_round3_ambiguous_pentagon_still_resolved_non_star():
    report=verify_semantic_requirements('生成一个五角形', [_regular_poly(1, 5)])
    verdict=semantic_requirement_state(report, '生成一个五角形')
    assert verdict['applicability_decision']==DECISION_RESOLVED_NON_STAR
    assert verdict['state']==STATE_NO_APPLICABLE_REQUIREMENT
    assert state_allows_summary_passed(verdict) is True


def test_r04_round3_ambiguous_star_geometry_still_blocked():
    report=verify_semantic_requirements('画一个五角形', [_star(1, ox=0.0)])
    verdict=semantic_requirement_state(report, '画一个五角形')
    assert verdict['applicability_decision']==DECISION_APPLICABLE
    assert verdict['state']==STATE_UNVERIFIED_OR_PARTIAL
    assert state_allows_summary_passed(verdict) is False


def test_r04_round3_c10_still_partial_rejected():
    geoms=[_heart(1, scale=2000.0), _star(2)]
    logical=[{'object_id':'heart-1','geometry_refs':[1],'label':'爱心'},
             {'object_id':'star-1','geometry_refs':[2],'label':'五角星'}]
    report=verify_semantic_requirements(C10_TEXT, geoms, logical_objects=logical)
    by_id={o['target_ref']['object_id']: o for o in report['object_acceptance']}
    assert by_id['heart-1']['status']=='passed'
    assert by_id['star-1']['status']=='not_checked'
    verdict=semantic_requirement_state(report, C10_TEXT)
    assert verdict['state']==STATE_UNVERIFIED_OR_PARTIAL
    assert state_allows_summary_passed(verdict) is False
