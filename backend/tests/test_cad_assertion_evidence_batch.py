from copy import deepcopy
import pytest
from app.cad_construction import execute_construction_plan,ConstructionPlanError


def test_independent_assertion_failures_are_reported_together():
    plan={'units':'m','steps':[{'op':'add_circle','step_id':'circle','output_ref':'circle',
        'semantic':{'label':'圆'},'center':{'x':0,'y':0},'radius':1}],
        'assertions':[{'kind':'entity_count','assertion_id':'count','target_ref':'circle','equals':2},
                      {'kind':'bounds_size','assertion_id':'size','target_ref':'circle','width':4,'height':4}]}
    before=deepcopy(plan)
    with pytest.raises(ConstructionPlanError) as failure:execute_construction_plan(plan)
    assert len(failure.value.details['failures'])==2
    assert failure.value.details['affected_output_refs']==['circle']
    assert plan==before
