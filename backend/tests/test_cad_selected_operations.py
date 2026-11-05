from copy import deepcopy
import pytest
from app.incremental_cad import parse_incremental_edit,edit_candidate_geometries
from app.cad_edit_contract import build_cad_edit_contract
from app.cad_edit_intent import build_cad_edit_intent
from app.cad_edit_gate import build_cad_edit_preflight


@pytest.mark.parametrize('unit,expected',[('米',6000),('mm',6),('cm',60),('毫米',6)])
def test_direction_before_copy_verb_preserves_supplied_distance(unit,expected):
    edit=parse_incremental_edit('将选中的完整图形向右复制6'+unit)
    assert edit['operation']=='duplicate' and edit['direction']=='右' and edit['distance_mm']==expected


def test_arc_mirror_is_not_discarded_as_identical_circle():
    arc={'id':1,'type':'arc','center':{'x':0,'y':0},'radius':1000,'start_angle':0,'end_angle':90}
    edit={**parse_incremental_edit('把图形关于Y轴镜像复制'),'geometry_ids':[1]}
    changed,error=edit_candidate_geometries([arc],edit)
    assert error is None and len(changed)==2
    assert changed[-1]['start_angle']==90 and changed[-1]['end_angle']==180


@pytest.mark.parametrize('text,axis,position',[
    ('把图形关于x=5米镜像复制','vertical',5000),
    ('把图形关于y=-20厘米镜像复制','horizontal',-200),
    ('把图形关于Y轴镜像复制','vertical',0),
    ('把图形关于X轴镜像复制','horizontal',0)])
def test_explicit_mirror_axis_reaches_normalized_intent(text,axis,position):
    edit=parse_incremental_edit(text)
    assert edit['mirror_axis']==axis and edit['mirror_coordinate_mm']==position
    intent=build_cad_edit_intent(text,edit)
    assert intent['parameters']['mirror_coordinate_mm']==position


def test_complete_disconnected_selection_is_mirrored_without_changing_non_target():
    source=[{'id':1,'type':'line','start':{'x':0,'y':0},'end':{'x':1000,'y':0}},
        {'id':2,'type':'circle','center':{'x':500,'y':700},'radius':100},
        {'id':3,'type':'circle','center':{'x':-5000,'y':0},'radius':200}]
    old=deepcopy(source)
    edit={**parse_incremental_edit('把图形关于x=5米镜像复制'),'geometry_ids':[1,2]}
    changed,error=edit_candidate_geometries(source,edit)
    assert error is None and source==old
    assert changed[:3]==source and len(changed)==5
    assert changed[3]['start']['x']==10000 and changed[3]['end']['x']==9000
    assert changed[4]['center']['x']==9500
    contract=build_cad_edit_contract(edit)
    assert contract['parameters']['mirror_coordinate_mm']==5000
    assert build_cad_edit_preflight(source,changed,contract)['ready']
    tampered=deepcopy(changed);tampered[-1]['center']['x']+=100
    assert not build_cad_edit_preflight(source,tampered,contract)['ready']


def test_array_copies_all_parts_and_preserves_separate_assembly_ownership():
    from app.logical_topology import evolve_logical_graph_for_edit,validate_logical_object_graph
    source=[{'id':1,'type':'circle','center':{'x':0,'y':0},'radius':100},
        {'id':2,'type':'circle','center':{'x':400,'y':0},'radius':50}]
    objects=[{'object_id':f'part-{i}','label':f'部件{i}','geometry_refs':[i],
        'assembly_id':'whole','assembly_label':'完整对象'} for i in (1,2)]
    edit={**parse_incremental_edit('将选中的图形阵列成2行2列，行间距2米，列间距3米'),
        'geometry_ids':[1,2]}
    changed,error=edit_candidate_geometries(source,edit)
    assert error is None and len(changed)==8
    assert [(g['center']['x'],g['center']['y']) for g in changed]==[
        (0,0),(400,0),(3000,0),(3400,0),(0,2000),(400,2000),(3000,2000),(3400,2000)]
    contract=build_cad_edit_contract(edit)
    assert build_cad_edit_preflight(source,changed,contract)['ready']
    evolved,topology=evolve_logical_graph_for_edit(source,changed,objects,{},contract)
    groups={o['assembly_id'] for o in evolved}
    assert len(groups)==4 and all(sum(o['assembly_id']==group for o in evolved)==2 for group in groups)
    assert validate_logical_object_graph(changed,evolved,topology)['verified']
