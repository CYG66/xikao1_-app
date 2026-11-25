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
