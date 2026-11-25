from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.cad_construction_interpreter import bind_outline_requirements, interpret_construction_request

ROWS = json.loads((Path(__file__).parent / 'fixtures' /
                   'recorded_outline_binding.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('row', ROWS, ids=lambda row: row['case'])
def test_replaying_a_bound_historical_plan_reaches_real_geometry_validation(row):
    result = interpret_construction_request(row['source'], lambda *_: {
        'schema_version': 'cad.construction-interpretation.v1',
        'is_construction_request': True, 'confidence': .99,
        'evidence_text': [row['original']], 'plan': deepcopy(row['plan']),
    })
    assert result['status'] == 'ready', result.get('error')
    if row['case'] == 'C6':
        assert result['source_acceptance']['periodic_source_acceptance']['coverage'] == 'complete'
        assert result['acceptance_summary']['status'] == 'passed'
    elif row['case']=='A10':
        proof=result['source_acceptance']['polygonal_source_acceptance']
        assert proof['coverage']=='complete'
        assert proof['checks'][0]['outer_tip_count']==5
        assert result['acceptance_summary']['status']=='passed'
    else:
        assert result['acceptance_summary']['status'] == 'review_required'


def test_outline_binding_is_idempotent_including_serialized_plan_defaults():
    from app.cad_construction import CadConstructionPlan
    row = ROWS[0]
    payload = {'plan': CadConstructionPlan.model_validate(row['plan']).model_dump(mode='json')}
    first = deepcopy(bind_outline_requirements(payload, row['source']))
    assert bind_outline_requirements(payload, row['source']) == first
    ids = [a['assertion_id'] for a in payload['plan']['assertions']]
    assert len(ids) == len(set(ids))


def test_colliding_id_preserves_the_original_assertion_and_uses_unique_new_id():
    row = ROWS[0]
    payload = {'plan': deepcopy(row['plan'])}
    original = {'kind': 'entity_count', 'assertion_id': 'required-outline-count',
                'target_ref': None, 'equals': 2}
    payload['plan']['assertions'] = [deepcopy(original)]
    bound = bind_outline_requirements(payload, row['source'])
    assertions = bound['plan']['assertions']
    assert original in assertions
    assert any(a['kind'] == 'entity_count' and a['equals'] == 1 for a in assertions)
    ids = [a['assertion_id'] for a in assertions]
    assert len(ids) == len(set(ids))
    first = deepcopy(bound)
    assert bind_outline_requirements(bound, row['source']) == first
    from app.cad_construction import execute_construction_plan, ConstructionPlanError
    with pytest.raises(ConstructionPlanError):
        execute_construction_plan(bound['plan'])


def test_scoped_count_is_not_mistaken_for_the_required_whole_drawing_count():
    row = ROWS[0]
    payload = {'plan': deepcopy(row['plan'])}
    payload['plan']['assertions'] = [{
        'kind': 'entity_count', 'assertion_id': 'local-count',
        'target_ref': payload['plan']['steps'][0]['output_ref'], 'equals': 1,
    }]
    bound = bind_outline_requirements(payload, row['source'])
    assert any(a['kind'] == 'entity_count' and a.get('target_ref') is None
               and a['equals'] == 1 for a in bound['plan']['assertions'])
