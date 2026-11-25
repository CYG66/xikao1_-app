from copy import deepcopy
import json
from pathlib import Path
import pytest
from evaluations.heart_acceptance_candidate_v5 import compare,compatibility_decision
ROWS=json.loads((Path(__file__).parent/'fixtures/recorded_legacy_heart_regressions.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('row',ROWS)
def test_actual_legacy_success_is_not_downgraded_for_an_unsupported_new_formula(row):
    result=compare(row['source'],row['payload'])
    assert result['legacy_passed'] and result['v4_decision']=='undetermined'
    assert result['decision']=='passed'
    assert result['decision_origin']=='legacy_acceptance_retained'
    assert not result['formal_candidate_accepted']


def test_real_new_rejection_is_not_hidden_by_legacy_compatibility():
    previous={'legacy_passed':True,'decision':'rejected','candidate_passed':False,'reason':'source_has_lowest_flat_interval'}
    before=deepcopy(previous);result=compatibility_decision(previous)
    assert previous==before
    assert result['decision']=='undetermined' and not result['candidate_passed']
    assert result['decision_origin']=='legacy_new_rule_conflict'


def test_legacy_failure_does_not_gain_a_pass_from_missing_evidence():
    result=compatibility_decision({'legacy_passed':False,'decision':'undetermined','candidate_passed':False,'reason':'source_extremum_not_resolved'})
    assert result['decision']=='undetermined' and not result['candidate_passed']
