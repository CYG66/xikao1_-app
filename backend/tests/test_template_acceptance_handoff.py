from copy import deepcopy
from unittest.mock import Mock, patch

import pytest

from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_template_plan import (interpret_template_project, template_plan_from_text,
                                   template_trial_acceptance)


def test_fresh_and_confirmed_template_share_measured_acceptance():
    source = '画一个标准篮球场'
    model = Mock(side_effect=AssertionError('registered template called model'))
    fresh = interpret_construction_request(source, model)
    confirmed = interpret_template_project(
        {'name': source, 'original_prompt': source, 'requirements': {}}, {})
    assert fresh['acceptance_summary'] == confirmed['acceptance_summary']
    assert fresh['acceptance_summary']['status'] == 'passed'
    assert fresh['acceptance_summary']['requirement_coverage'] == 'registered_template_scope'
    # Generic prose coverage remains partial: the scope is not fabricated.
    assert fresh['source_acceptance']['coverage'] != 'complete'
    model.assert_not_called()


@pytest.mark.parametrize('field,key', [('assertions', 'ok'), ('feasibility', 'ok'),
                                      ('constraint_solve', 'verified'),
                                      ('graph_validation', 'verified')])
def test_template_authority_rejects_each_unverified_execution_gate(field, key):
    trial = execute_construction_plan(template_plan_from_text('画一个标准篮球场'))
    assert template_trial_acceptance(trial)['status'] == 'passed'
    changed = deepcopy(trial)
    changed[field][key] = False
    assert template_trial_acceptance(changed)['review_required'] is True


def test_template_authority_does_not_override_unresolved_source_measurement():
    unresolved = {'status': 'partial', 'coverage': 'partial', 'checks': [],
                  'unknown_requirements': [{'reason': 'source target ambiguous'}],
                  'review_required': True}
    with patch('app.cad_source_acceptance.verify_final_source_contract',
               return_value=unresolved):
        result = interpret_construction_request('画一个标准篮球场')
    assert result['acceptance_summary']['review_required'] is True


def test_template_with_additional_object_is_not_claimed_as_fully_covered():
    assert template_plan_from_text('画一个标准篮球场，另外添加一个半径2米的圆') is None


@pytest.mark.parametrize('source,dimensions', [
    ('画一个标准篮球场', [15000, 28000]),
    ('生成一个羽毛球场', [6100, 13400]),
    ('画两个并排的停车位', [5000, 5000]),
])
def test_template_creation_and_repeated_confirmation_reuse_same_saved_version(
        tmp_path, source, dimensions):
    from app.agent_service import robot_agent
    from app.creative_projects import CreativeProjectStore
    from app.cad_construction import construction_geometry_bounds
    store = CreativeProjectStore(tmp_path / 'projects.json')
    with patch('app.agent_service.get_creative_project_store', return_value=store), \
         patch.object(robot_agent, '_structured_review_text',
                      side_effect=AssertionError('template used provider')):
        first = robot_agent._formal_cad_construction(source,
            {'name': 'drawing_design', 'operation': 'create'}, mode='advanced')
        assert first['ok'] and first['variant']['acceptance_summary']['status'] == 'passed'
        bounds = construction_geometry_bounds(first['variant']['geometries'])
        assert sorted([bounds['max_x']-bounds['min_x'],
                       bounds['max_y']-bounds['min_y']]) == dimensions
        project_id = first['project_id']
        for _ in range(2):
            confirmed = robot_agent.generate_project_candidate(project_id)
            assert confirmed['ok']
            assert confirmed['variant']['id'] == first['variant']['id']
        assert len(store.get(project_id)['variants']) == 1
