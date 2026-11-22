from copy import deepcopy
import pytest
from app.cad_source_acceptance import verify_final_source_contract
from app.cad_structure_contract import StructureContractError


def rectangle(x=0,y=0,width=4000,height=3000):
    return {'id':1,'type':'polyline','closed':True,'vertices':[
        {'x':x,'y':y},{'x':x+width,'y':y},{'x':x+width,'y':y+height},{'x':x,'y':y+height}]}


def test_center_is_measured_not_taken_from_model():
    with pytest.raises(StructureContractError):
        verify_final_source_contract('画一个矩形，宽4米高3米，中心在(2,3)',[rectangle()])
    gs=[rectangle(y=1500)];before=deepcopy(gs)
    result=verify_final_source_contract('画一个矩形，宽4米高3米，中心在(2,3)',gs)
    assert any(c['field']=='center' for c in result['checks'])
    assert gs==before and result['coverage']=='partial'


def test_overall_size_includes_all_printing_parts_but_not_annotations():
    gs=[rectangle(),{'id':2,'type':'line','start':{'x':0,'y':4500},'end':{'x':4000,'y':4500}}]
    with pytest.raises(StructureContractError):
        verify_final_source_contract('画一个房子轮廓，整体宽4米高3米，屋顶是三角形，中间有一个门',gs)
    gs[1]['role']='annotation'
    assert verify_final_source_contract('画一个房子轮廓，整体宽4米高3米',gs)['checks']


def test_upper_bound_not_equality_and_local_size_not_whole_size():
    assert verify_final_source_contract('画一个矩形，最大宽度5米',[rectangle()])['checks']
    result=verify_final_source_contract('画两个矩形，左边矩形宽1米，右边矩形宽2米',[rectangle()])
    assert not result['checks']


def test_spline_degree_never_inferred_from_shape_name():
    assert not verify_final_source_contract('画一条闭合样条曲线，平滑闭合',[rectangle()])['checks']


def test_named_component_radius_is_bound_only_to_verified_logical_ids():
    gs=[{'id':1,'type':'circle','center':{'x':0,'y':0},'radius':1000},
        {'id':2,'type':'circle','center':{'x':4000,'y':0},'radius':2000}]
    source='内圆：半径1米；外圆：半径2米'
    objects=[{'label':'内圆','geometry_ids':[1]},{'label':'外圆','geometry_ids':[2]}]
    result=verify_final_source_contract(source,gs,objects)
    assert [c['geometry_ids'] for c in result['checks']]==[[1],[2]]
    gs[1]['radius']=3000
    with pytest.raises(StructureContractError) as failure:verify_final_source_contract(source,gs,objects)
    assert failure.value.details['geometry_ids']==[2]


def test_executor_geometry_refs_are_consumed_and_wrong_dimension_still_fails():
    gs=[{'id':1,'type':'circle','center':{'x':0,'y':0},'radius':1000},
        {'id':2,'type':'polyline','closed':True,'vertices':[
            {'x':3000,'y':0},{'x':5000,'y':0},{'x':5000,'y':2000},{'x':3000,'y':2000}]}]
    source='画一个圆和一个矩形，圆半径1米，矩形宽2米，矩形高2米'
    objects=[{'label':'圆','geometry_refs':[1]},{'label':'矩形','geometry_refs':[2]}]
    result=verify_final_source_contract(source,gs,objects)
    assert len(result['checks'])==3
    assert not result['unknown_requirements']
    gs[0]['radius']=2000
    with pytest.raises(StructureContractError) as failure:
        verify_final_source_contract(source,gs,objects)
    assert failure.value.details['geometry_ids']==[1]


def test_conflicting_or_duplicate_object_refs_stay_unresolved():
    gs=[{'id':1,'type':'circle','center':{'x':0,'y':0},'radius':1000},
        {'id':2,'type':'circle','center':{'x':4000,'y':0},'radius':2000}]
    source='内圆：半径1米；外圆：半径2米'
    for inner in ({'label':'内圆','geometry_refs':[1],'geometry_ids':[2]},
                  {'label':'内圆','geometry_refs':[1,1]},
                  {'label':'内圆','geometry_refs':[1.5]},
                  {'label':'内圆','geometry_refs':['1.0']}):
        result=verify_final_source_contract(source,gs,[inner,{'label':'外圆','geometry_refs':[2]}])
        assert not any(c['field']=='radius' and c['geometry_ids']==[1] for c in result['checks'])
        assert result['unknown_requirements']


def _two_rectangles():
    return [
        {'id':1,'type':'polyline','closed':True,'vertices':[
            {'x':0,'y':0},{'x':2000,'y':0},{'x':2000,'y':2000},{'x':0,'y':2000}]},
        {'id':2,'type':'polyline','closed':True,'vertices':[
            {'x':3000,'y':0},{'x':5000,'y':0},{'x':5000,'y':2000},{'x':3000,'y':2000}]},
    ]


def test_multi_object_single_subject_size_is_not_measured_as_overall():
    objects=[{'object_id':'rect-1','label':'矩形','geometry_refs':[1]},
             {'object_id':'rect-2','label':'矩形','geometry_refs':[2]}]
    result=verify_final_source_contract('画两个矩形并排，宽2米高2米',_two_rectangles(),objects)
    assert result['status']=='unverified' and not result['checks']
    assert len(result['unknown_requirements'])==2
    assert all('多对象尺寸范围不明确' in item['reason']
               for item in result['unknown_requirements'])


def test_explicit_overall_size_still_measures_all_objects():
    objects=[{'object_id':'rect-1','label':'矩形','geometry_refs':[1]},
             {'object_id':'rect-2','label':'矩形','geometry_refs':[2]}]
    result=verify_final_source_contract(
        '画两个矩形并排，整体宽5米，整体高2米',_two_rectangles(),objects)
    assert len(result['checks'])==2
    assert not result['unknown_requirements']


def test_explicit_overall_size_on_rectangle_count_is_validated_as_bounds():
    from app.cad_structure_contract import explicit_composition, validate_explicit_composition
    contract=explicit_composition('画两个矩形并排，整体宽5米，整体高2米')
    assert contract['kind']=='component_count'
    assert contract['dimension_scope']=='overall'
    validate_explicit_composition(contract,_two_rectangles())
    with pytest.raises(StructureContractError):
        validate_explicit_composition(
            explicit_composition('画两个矩形并排，整体宽6米，整体高2米'),
            _two_rectangles())


def test_ambiguous_rectangle_size_is_not_enforced_per_component():
    from app.cad_structure_contract import explicit_composition, validate_explicit_composition
    contract=explicit_composition('画两个矩形并排，宽2米高2米')
    assert contract['dimension_scope']=='ambiguous'
    # Same phrase, another legal reading: each rectangle 1m wide, overall 4m.
    alternate=[
        {'id':1,'type':'polyline','closed':True,'vertices':[
            {'x':0,'y':0},{'x':1000,'y':0},{'x':1000,'y':2000},{'x':0,'y':2000}]},
        {'id':2,'type':'polyline','closed':True,'vertices':[
            {'x':3000,'y':0},{'x':4000,'y':0},{'x':4000,'y':2000},{'x':3000,'y':2000}]},
    ]
    validate_explicit_composition(contract,alternate)


def test_explicit_per_component_size_is_still_enforced():
    from app.cad_structure_contract import explicit_composition, validate_explicit_composition
    contract=explicit_composition('画两个矩形并排，每个矩形宽2米高2米')
    assert contract['dimension_scope']=='component'
    validate_explicit_composition(contract,_two_rectangles())
    with pytest.raises(StructureContractError):
        validate_explicit_composition(
            explicit_composition('画两个矩形并排，每个矩形宽1米高2米'),
            _two_rectangles())


def test_explicit_overall_size_mismatch_still_fails():
    objects=[{'object_id':'rect-1','label':'矩形','geometry_refs':[1]},
             {'object_id':'rect-2','label':'矩形','geometry_refs':[2]}]
    with pytest.raises(StructureContractError):
        verify_final_source_contract(
            '画两个矩形并排，整体宽6米，整体高2米',_two_rectangles(),objects)
