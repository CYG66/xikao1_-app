"""Recorded geometry exercises acceptance dispatch, never shape generation."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.cad_construction import CadConstructionPlan, execute_construction_plan
from app.cad_semantic_acceptance import verify_semantic_requirements
from app.cad_structure_contract import StructureContractError


def recorded():
    data = json.loads((Path(__file__).parent / 'fixtures' /
                       'recorded_semantic_dispatch.json').read_text(encoding='utf-8'))
    return data, execute_construction_plan(CadConstructionPlan.model_validate(data['plan']))


def test_recorded_profile_does_not_fall_through_to_letter_checker():
    data, result = recorded()
    report = verify_semantic_requirements(data['source'], result['geometries'])
    assert report['review_required'] is False
    assert [c['name'] for c in report['checks']] == [
        'heart_bilateral_lobes_notch_and_lower_tip']
    assert report['status'] == 'partial'


def test_existing_lower_tip_requirement_is_still_enforced():
    data, result = recorded()
    # Reflect the recorded boundary: the original bottom feature is now at top.
    for geometry in result['geometries']:
        for p in geometry['vertices']:
            p['y'] = -p['y']
    with pytest.raises(StructureContractError, match='双侧上凸'):
        verify_semantic_requirements(data['source'], result['geometries'])


def test_unknown_profile_is_unverified_instead_of_assuming_a_letter():
    with patch('app.cad_semantic_acceptance.semantic_requirements',
               return_value=[{'kind': 'future_profile'}]):
        report = verify_semantic_requirements('已有明确尺寸的轮廓', [])
    assert report['status'] == 'unverified'
    assert report['review_required'] is True
    assert not report['checks']


def test_non_letter_geometry_still_fails_when_user_actually_requests_letter():
    _, result = recorded()
    with pytest.raises(StructureContractError, match='大写A'):
        verify_semantic_requirements('生成一个大写字母A的轮廓，高3米宽2米',
                                     result['geometries'])


def test_recorded_model_plan_passes_full_interpreter_without_new_model_call():
    from app.cad_construction_interpreter import interpret_construction_request
    data, _ = recorded()
    result = interpret_construction_request(data['source'], lambda *_: {
        'schema_version': 'cad.construction-interpretation.v1',
        'is_construction_request': True, 'confidence': .86,
        'evidence_text': [data['source']], 'plan': data['plan'],
    }, force_structured_model=True)
    assert result['status'] == 'ready', result.get('error')
    assert result['trial_result']['geometries']
