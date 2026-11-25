from copy import deepcopy
from unittest.mock import Mock, patch

import pytest

from app.agent_service import robot_agent, _REQUEST_EXECUTION_CONTEXT
from app.agent_http_service import _chat_stream_with_execution_context
from app.cad_template_plan import template_plan_for_project
from app.cad_construction import execute_construction_plan, construction_geometry_bounds


@pytest.mark.parametrize('terminal', ['completed', 'error', 'close'])
def test_stream_binds_request_snapshot_and_resets_context(terminal):
    snapshot = {'request_id': 'stream-test', 'source_variant_id': 'v1'}
    previous = _REQUEST_EXECUTION_CONTEXT.get()

    def stream(*args, **kwargs):
        assert _REQUEST_EXECUTION_CONTEXT.get() == snapshot
        yield {'type': 'progress'}
        assert _REQUEST_EXECUTION_CONTEXT.get() == snapshot
        if terminal == 'error':
            raise RuntimeError('stream interrupted')
        yield {'type': 'result'}

    with patch('app.agent_http_service.robot_agent.chat_stream', side_effect=stream):
        events = _chat_stream_with_execution_context('edit', [], mode='advanced',
                    route={'execution_context': snapshot}, user_id=None)
        assert next(events)['type'] == 'progress'
        assert _REQUEST_EXECUTION_CONTEXT.get() == previous
        if terminal == 'close':
            events.close()
        elif terminal == 'error':
            with pytest.raises(RuntimeError, match='interrupted'):
                list(events)
        else:
            assert list(events) == [{'type': 'result'}]
    assert _REQUEST_EXECUTION_CONTEXT.get() == previous


def test_stream_can_resume_in_different_threadpool_contexts():
    from contextvars import copy_context
    snapshot = {'request_id': 'cross-context'}
    def stream(*args, **kwargs):
        for _ in range(2):
            assert _REQUEST_EXECUTION_CONTEXT.get() == snapshot
            yield {'type': 'progress'}
    with patch('app.agent_http_service.robot_agent.chat_stream', side_effect=stream):
        events = _chat_stream_with_execution_context('edit', [], mode='advanced',
                    route={'execution_context': snapshot}, user_id=None)
        assert copy_context().run(next, events)['type'] == 'progress'
        assert copy_context().run(next, events)['type'] == 'progress'
        with pytest.raises(StopIteration):
            copy_context().run(next, events)
    assert _REQUEST_EXECUTION_CONTEXT.get() is None


@pytest.mark.parametrize('status', ['review_required', 'passed'])
def test_confirmed_non_template_never_uses_legacy_shape_generator(status):
    project = {'id': 'p1', 'original_prompt': '生成一个半径2米的圆形',
               'requirements': {'shape': 'circle', 'dimensions': {'radius_m': 2}},
               'variants': [{'id': 'v1', 'acceptance_summary': {'status': status}}]}
    store = Mock()
    store.get.return_value = project
    with patch('app.agent_service.get_creative_project_store', return_value=store), \
         patch('app.agent_service.design_geometries_for_project',
               side_effect=AssertionError('legacy geometry producer called')):
        assert robot_agent._confirm_parameterized_project('确认需求并生成CAD候选',
                    {'selected_project_id': 'p1'}) is None
    assert project['variants'][0]['id'] == 'v1'
    store.add_variant.assert_not_called()


@pytest.mark.parametrize('dimensions', [
    {'length_m': 28, 'width_m': 15},
    {'length_m': 28, 'width_m': 15, 'height_m': 15},
])
def test_template_tool_length_width_reaches_executor_without_square_alias(dimensions):
    project = {'name': '篮球场', 'original_prompt': '标准篮球场',
               'requirements': {'dimensions': dimensions}}
    original = deepcopy(project)
    plan = template_plan_for_project(project, {})
    gs = execute_construction_plan(plan)['geometries']
    b = construction_geometry_bounds(gs)
    assert sorted([b['max_x']-b['min_x'], b['max_y']-b['min_y']]) == [15000, 28000]
    assert project == original


def test_conflicting_template_axes_require_clarification_instead_of_silent_override():
    with pytest.raises(ValueError, match='冲突'):
        template_plan_for_project({'name': '篮球场', 'original_prompt': '标准篮球场',
            'requirements': {'dimensions': {'length_m': 28, 'width_m': 15,
                                             'height_m': 20}}}, {})
