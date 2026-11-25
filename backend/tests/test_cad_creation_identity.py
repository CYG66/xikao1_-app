from copy import deepcopy
from app.incremental_cad import edit_candidate_geometries


def circles():return [{'id':1,'type':'circle','template_instance':1,'center':{'x':0,'y':0},'radius':1000},
                      {'id':2,'type':'circle','template_instance':2,'center':{'x':6000,'y':0},'radius':2000}]


def test_copy_emits_source_identity_and_keeps_original_unchanged():
    source=circles();before=deepcopy(source)
    edit={'operation':'duplicate','instance':2,'direction':'上','distance_mm':6000}
    result,error=edit_candidate_geometries(source,edit)
    assert error is None
    assert len({g['id'] for g in result})==3
    assert result[:2]==before and source==before
    assert edit['execution_identity']['members'][-1]['source_geometry_id']==2
    assert edit['execution_identity']['members'][-1]['operation_id']


def test_consecutive_copy_keeps_unique_ids_and_distinct_operations():
    edit1={'operation':'duplicate','instance':2,'direction':'上','distance_mm':6000}
    one,error=edit_candidate_geometries(circles(),edit1)
    edit2={'operation':'duplicate','instance':3,'direction':'上','distance_mm':6000}
    two,error=edit_candidate_geometries(one,edit2)
    assert error is None and len({g['id'] for g in two})==4
    assert edit2['execution_identity']['members'][-1]['source_geometry_id']==one[-1]['id']
    assert edit2['execution_identity']['members'][-1]['operation_id']!=edit1['execution_identity']['members'][-1]['operation_id']


def test_multigeometry_copy_records_every_source_and_ambiguity_is_not_guessed():
    from app.cad_candidate_state import bind_creation_history
    from app.cad_target_resolver import resolve_created_target,recent_creation_selector
    source=circles();source[1]['template_instance']=1
    edit={'operation':'duplicate','instance':1,'direction':'上','distance_mm':6000}
    result,error=edit_candidate_geometries(source,edit)
    assert error is None
    assert {m['source_geometry_id'] for m in edit['execution_identity']['members']}=={1,2}
    parent={'id':'base','geometries':source}
    variant={'id':'new','parent_variant_id':'base','geometries':result}
    variant['reference_mapping']=bind_creation_history(parent,variant,'project',{'execution_identity':edit['execution_identity']})
    resolution=resolve_created_target(variant,'project',recent_creation_selector('把刚才复制的圆半径改为0.5米'))
    assert resolution['status']=='needs_clarification' and resolution['candidate_count']==2
