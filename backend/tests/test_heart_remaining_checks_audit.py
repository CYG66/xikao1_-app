from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from app import cad_semantic_acceptance as semantic
from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import interpret_construction_request
from evaluations.audit_heart_remaining_checks import diagnostic_verifier

ROWS={r['response_index']:r for r in json.loads((Path(__file__).parent/'fixtures/recorded_shallow_notch_audit.json').read_text(encoding='utf-8'))}


def interpret(row,extra=''):
    return interpret_construction_request(row['source']+extra,lambda *_:deepcopy(row['payload']),force_structured_model=True)


@pytest.mark.parametrize('index',[3,5])
def test_only_counterfactual_notch_relation_unblocks_remaining_existing_checks(index):
    row=ROWS[index];original=semantic.verify_semantic_requirements
    baseline=interpret(row)
    assert baseline['status']=='invalid'
    assert baseline['construction_error']['details']['failed_features']==['center_notch']
    before=execute_construction_plan(baseline['plan'])['geometries']
    with patch.object(semantic,'verify_semantic_requirements',diagnostic_verifier()):
        diagnostic=interpret(row)
    assert semantic.verify_semantic_requirements is original
    assert interpret(row)['status']=='invalid'
    assert diagnostic['acceptance_summary']['status']=='passed'
    assert before==diagnostic['trial_result']['geometries']
    source=diagnostic['source_acceptance']
    facts=source['final_source_acceptance']['checks']
    assert {f['field'] for f in facts}=={'width','height','center'}
    assert all(f['status']=='passed' for f in facts)
    measurements=source['semantic_acceptance']['checks'][0]['measurements']
    assert measurements['simple_closed_outline']
    assert measurements['left_right_symmetry_error_mm']<=.5
    assert measurements['maximum_sample_turn_degrees']<=60


def test_central_peak_is_still_rejected_by_counterfactual_relation():
    with patch.object(semantic,'verify_semantic_requirements',diagnostic_verifier()):
        result=interpret(ROWS[7])
    assert result['status']=='invalid'
    assert result['construction_error']['details']['failed_features']==['center_notch']


@pytest.mark.parametrize('index',[3,5])
def test_unknown_source_requirement_is_not_bypassed(index):
    with patch.object(semantic,'verify_semantic_requirements',diagnostic_verifier()):
        result=interpret(ROWS[index],'，面积为123平方米')
    assert result.get('acceptance_summary',{}).get('status')!='passed'
