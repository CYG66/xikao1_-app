import json
from tests.manual.cad_acceptance_metrics import summarize


def test_unobserved_metrics_are_unknown_not_zero(tmp_path):
    result=summarize(tmp_path,[{'case':'missing','passed':False}])
    assert result['end_to_end_pass_rate']==0
    for key in ('first_plan_success_rate','cost','reported_total_tokens','omission_rate','false_acceptance_rate'):
        assert result[key] is None


def test_actual_timing_usage_and_retries_are_counted(tmp_path):
    folder=tmp_path/'case';folder.mkdir()
    (folder/'timing-1.json').write_text(json.dumps({'elapsed_seconds':2.5}))
    (folder/'step-1.json').write_text(json.dumps({'usage':{'total_tokens':12},'construction_commit':{'recovery':{
        'attempts':[{'status':'invalid','category':'model_plan_invalid'},{'status':'ready','category':None}]}}}))
    result=summarize(tmp_path,[{'case':'case','passed':True}])
    assert result['total_elapsed_seconds']==2.5
    assert result['reported_total_tokens']==12
    assert result['first_plan_success_rate']==0
    assert result['failure_categories']=={'model_plan_invalid':1}
