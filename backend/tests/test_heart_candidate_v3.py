import json
from pathlib import Path
import pytest
from evaluations.heart_acceptance_candidate_v3 import compare
from evaluations.stress_heart_candidate_v1 import scenarios

ROWS={r['response_index']:r for r in json.loads((Path(__file__).parent/'fixtures/recorded_shallow_notch_audit.json').read_text(encoding='utf-8'))}


def test_parametric_source_does_not_pass_from_sampled_minimum_alone():
    row=ROWS[3];result=compare(row['source'],row['payload'])
    assert result['v2_result']['candidate_passed']
    assert result['decision']=='undetermined' and not result['candidate_passed']
    assert not result['formal_candidate_accepted']


def test_supported_bezier_with_agreeing_evidence_can_pass_offline():
    row=ROWS[5];result=compare(row['source'],row['payload'])
    assert result['decision']=='passed'
    assert result['geometry_unchanged']
    assert result['source_minimum']['minimum_kind']=='isolated_point'
    assert not result['legacy_passed'] and not result['formal_candidate_accepted']


@pytest.mark.parametrize('name',['rounded_u_160','rounded_u_400'])
def test_literal_flat_boundary_remains_rejected(name):
    row=ROWS[3];result=compare(row['source'],dict(scenarios(row))[name])
    assert result['decision']=='rejected'


def test_central_peak_is_not_promoted_by_a_bottom_point():
    row=ROWS[7];result=compare(row['source'],row['payload'])
    assert result['decision']=='rejected'


def test_unsupported_explicit_requirement_is_not_a_pass():
    row=ROWS[5];result=compare(row['source']+'，凹口深度10厘米',row['payload'])
    assert result['decision']=='undetermined'
    assert not result['candidate_passed']
