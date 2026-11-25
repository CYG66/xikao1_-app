from copy import deepcopy
import pytest
from app.cad_construction import execute_construction_plan,ConstructionPlanError

def test_duplicate_failure_reports_pairs_and_step_binding_without_editing_plan():
    plan={'units':'m','steps':[{'op':'add_line','step_id':str(i),'output_ref':'edge'+str(i),
        'semantic':{'label':'边'+str(i)},'start':{'x':0,'y':0},'end':{'x':2,'y':1}} for i in range(2)]}
    before=deepcopy(plan)
    with pytest.raises(ConstructionPlanError) as caught:execute_construction_plan(plan)
    assert caught.value.code=='drawing_infeasible'
    details=caught.value.details
    assert details['duplicate_line_pairs']==[[1,2]]
    assert details['geometry_refs']=={'edge0':[1],'edge1':[2]}
    assert len(details['measured_geometries'])==2
    assert plan==before

def test_assertion_failure_includes_real_target_and_reference():
    plan={'units':'m','steps':[{'op':'add_circle','step_id':str(i),'output_ref':'circle'+str(i),
        'semantic':{'label':'圆'+str(i)},'center':{'x':i*3,'y':0},'radius':1} for i in range(2)],
        'assertions':[{'kind':'center_distance','assertion_id':'distance','target_ref':'circle0',
            'reference_ref':'circle1','distance':2}]}
    before=deepcopy(plan)
    with pytest.raises(ConstructionPlanError) as caught:execute_construction_plan(plan)
    assert caught.value.code=='assertion_failed'
    details=caught.value.details
    assert details['failed_model_assertion']['distance']==2
    assert details['assertion_target_geometry'][0]['center']['x']==0
    assert details['assertion_reference_geometry'][0]['center']['x']==3000
    assert plan==before
