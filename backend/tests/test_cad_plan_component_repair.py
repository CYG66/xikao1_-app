import json
from copy import deepcopy
from unittest.mock import patch

import pytest

from app.cad_plan_component_repair import ComponentRepairError, merge_component_repair


def test_identity_repair_cannot_change_geometry_or_assembly():
    plan={'units':'m','steps':[{'step_id':ref,'output_ref':ref,'op':'add_circle',
        'radius':radius,'center':{'x':0,'y':0},
        'semantic':{'object_id':'duplicate','assembly_id':'whole','label':ref}}
        for ref,radius in [('a',2),('b',1)]], 'assertions':[{'kind':'closed','assertion_id':'closed','target_ref':'a'}]}
    context={'plan':plan,'construction_error':{'details':{
        'identity_only_repair':True,'affected_output_refs':['a','b']}}}
    payload={'plan':deepcopy(plan)}
    for i,step in enumerate(payload['plan']['steps']):
        step['radius']=99
        step['semantic'].update(object_id=f'part-{i}',assembly_id='wrong')
    result=merge_component_repair(context,payload)['plan']
    for i,step in enumerate(result['steps']):
        expected=deepcopy(plan['steps'][i]);expected['semantic']['object_id']=f'part-{i}'
        assert step==expected
    assert result['assertions']==plan['assertions']


def test_executor_exposes_only_conflicting_step_refs_for_identity_repair():
    from app.cad_construction import execute_construction_plan, ConstructionPlanError
    plan={'units':'m','steps':[{'op':'add_circle','step_id':ref,'output_ref':ref,
        'center':{'x':x,'y':0},'radius':.2,
        'semantic':{'label':ref,'object_id':identity,'assembly_id':'whole','assembly_label':'完整对象'}}
        for ref,x,identity in [('a',0,'duplicate'),('b',1,'duplicate'),('c',2,'unique')]]}
    with pytest.raises(ConstructionPlanError) as caught:
        execute_construction_plan(plan)
    assert caught.value.code=='logical_graph_invalid'
    assert caught.value.details['identity_only_repair'] is True
    assert caught.value.details['affected_output_refs']==['a','b']


def test_only_failed_assertion_can_change_with_affected_component():
    old={'units':'m','steps':[{'step_id':'a','output_ref':'a','op':'add_polyline'},
        {'step_id':'b','output_ref':'b','op':'add_circle'}],
        'assertions':[{'assertion_id':'bad','target_ref':'a','width':3,'height':3},
                      {'assertion_id':'keep','target_ref':'b','radius':.8}]}
    context={'plan':old,'construction_error':{'assertion_id':'bad','details':{'affected_output_refs':['a']}}}
    proposed={'plan':{'units':'m','steps':[old['steps'][0]],'assertions':[
        {'assertion_id':'bad','target_ref':'a','width':3,'height':2.598},
        {'assertion_id':'keep','target_ref':'b','radius':9}]}}
    merged=merge_component_repair(context,proposed)['plan']
    assert merged['assertions'][0]['height']==2.598
    assert merged['assertions'][1]==old['assertions'][1]
    assert merged['steps'][1]==old['steps'][1]


def test_partial_repair_preserves_other_component_and_layout():
    plan = {'units': 'm', 'steps': [
        {'step_id': 'a', 'output_ref': 'a', 'op': 'add_polyline', 'vertices': [1]},
        {'step_id': 'b', 'output_ref': 'b', 'op': 'add_rotational_path', 'center': {'x': 6, 'y': 0}}],
        'assertions': [{'target_ref': 'b'}], 'free_outline_layout': [{'target_ref': 'b'}]}
    context = {'plan': plan, 'construction_error': {'details': {'affected_output_refs': ['a']}}}
    payload = {'plan': {'units': 'm', 'steps': [
        {'step_id': 'changed', 'output_ref': 'a', 'op': 'add_polyline', 'vertices': [2]}]}}
    before = deepcopy((context, payload))
    result = merge_component_repair(context, payload)['plan']
    assert result['steps'][0]['vertices'] == [2]
    assert result['steps'][0]['step_id'] == 'a'
    assert result['steps'][1] == plan['steps'][1]
    assert result['units'] == 'm'
    assert result['assertions'] == plan['assertions']
    assert result['free_outline_layout'] == plan['free_outline_layout']
    assert (context, payload) == before
    with pytest.raises(ValueError):
        merge_component_repair(context, {'plan': {'steps': []}})
    changed_units = deepcopy(payload)
    changed_units['plan']['units'] = 'mm'
    with pytest.raises(ValueError, match='单位'):
        merge_component_repair(context, changed_units)


def _point(x, y):
    return {'x': x, 'y': y}


def _junction_constraints():
    return [
        {
            'junction_index': 0,
            'left_segment_index': 0,
            'right_segment_index': 1,
            'intent': 'smooth',
            'required_continuity': 'C1',
            'tangent_tolerance_deg': 0.01,
            'source_requirement_refs': ['user:0'],
        },
        {
            'junction_index': 1,
            'left_segment_index': 1,
            'right_segment_index': 2,
            'intent': 'smooth',
            'required_continuity': 'C1',
            'tangent_tolerance_deg': 0.01,
            'source_requirement_refs': ['user:0'],
        },
    ]


def _composite_plan(*, closed=False):
    return {
        'schema_version': 'cad.construction-plan.v1',
        'units': 'm',
        'steps': [{
            'op': 'add_composite_path',
            'step_id': 'composite-step',
            'output_ref': 'composite-curve',
            'layer_id': 1,
            'semantic': {
                'object_type': 'drawing_part',
                'label': 'generic composite fixture',
            },
            'segments': [
                {'kind': 'line', 'start': _point(0, 0), 'end': _point(1, 0)},
                {'kind': 'line', 'start': _point(1, 0), 'end': _point(2, 1)},
                {'kind': 'line', 'start': _point(2, 1), 'end': _point(3, 0)},
            ],
            'closed': closed,
            'samples_per_curve': 64,
            'connection_tolerance': 0.000001,
            'continuity': 'C1',
            'tangent_tolerance_deg': 0.01,
            'allow_self_intersection': False,
            'allow_duplicate_segments': False,
            'max_curvature': 1000.0,
            'max_sampling_error': 0.001,
            'junction_constraints': _junction_constraints(),
        }],
        'budgets': {'max_steps': 10, 'max_entities': 20},
    }


def _repair_context(plan, ref='composite-curve'):
    return {
        'plan': plan,
        'construction_error': {'details': {'affected_output_refs': [ref]}},
    }


def _replacement_from(plan, ref='composite-curve'):
    return {
        'plan': {
            'units': 'm',
            'steps': [deepcopy(plan['steps'][0])],
        }
    }


def _without_constraint_fields(step):
    for key in ('junction_constraints', 'continuity', 'tangent_tolerance_deg'):
        step.pop(key, None)
    return step


def test_replacement_omitting_local_constraints_preserves_original():
    plan = _composite_plan()
    replacement = _replacement_from(plan)
    _without_constraint_fields(replacement['plan']['steps'][0])

    merged = merge_component_repair(
        _repair_context(plan), replacement
    )['plan']['steps'][0]

    assert merged['junction_constraints'] == plan['steps'][0]['junction_constraints']
    assert merged['continuity'] == 'C1'
    assert merged['tangent_tolerance_deg'] == 0.01


def test_a9_junction_mock_no_longer_loses_constraints():
    """The original D0 junction mock was a two-segment path losing H3 fields."""
    plan = {
        'schema_version': 'cad.construction-plan.v1',
        'units': 'm',
        'steps': [{
            'op': 'add_composite_path',
            'step_id': 'junction-step',
            'output_ref': 'junction-curve',
            'layer_id': 1,
            'semantic': {'object_type': 'drawing_part', 'label': 'junction fixture'},
            'segments': [
                {'kind': 'line', 'start': _point(0, 0), 'end': _point(1, 0)},
                {'kind': 'line', 'start': _point(1, 0), 'end': _point(1, 1)},
            ],
            'closed': False,
            'continuity': 'C1',
            'tangent_tolerance_deg': 0.01,
            'junction_constraints': [{
                'junction_index': 0,
                'left_segment_index': 0,
                'right_segment_index': 1,
                'intent': 'smooth',
                'required_continuity': 'C1',
                'tangent_tolerance_deg': 0.01,
                'source_requirement_refs': ['user:0'],
            }],
        }],
    }
    replacement = deepcopy(plan['steps'][0])
    replacement.pop('junction_constraints', None)
    replacement.pop('continuity', None)
    replacement.pop('tangent_tolerance_deg', None)

    merged = merge_component_repair(
        _repair_context(plan, ref='junction-curve'),
        {'plan': {'units': 'm', 'steps': [replacement]}},
    )['plan']['steps'][0]

    assert merged['junction_constraints'] == plan['steps'][0]['junction_constraints']
    assert merged['continuity'] == 'C1'
    assert merged['tangent_tolerance_deg'] == 0.01



def test_replacement_explicit_empty_local_constraints_is_rejected():
    plan = _composite_plan()
    replacement = _replacement_from(plan)
    replacement['plan']['steps'][0]['junction_constraints'] = []

    with pytest.raises(ComponentRepairError) as caught:
        merge_component_repair(_repair_context(plan), replacement)

    assert caught.value.code == 'junction_constraints_clear_rejected'
    assert caught.value.details['output_ref'] == 'composite-curve'


def test_replacement_explicit_null_local_constraints_is_rejected():
    plan = _composite_plan()
    replacement = _replacement_from(plan)
    replacement['plan']['steps'][0]['junction_constraints'] = None

    with pytest.raises(ComponentRepairError) as caught:
        merge_component_repair(_repair_context(plan), replacement)

    assert caught.value.code == 'junction_constraints_null_rejected'


def test_replacement_partial_local_constraints_is_rejected_when_structure_is_unchanged():
    plan = _composite_plan()
    replacement = _replacement_from(plan)
    replacement['plan']['steps'][0]['junction_constraints'] = [
        deepcopy(plan['steps'][0]['junction_constraints'][0])
    ]

    with pytest.raises(ComponentRepairError) as caught:
        merge_component_repair(_repair_context(plan), replacement)

    assert caught.value.code == 'junction_constraints_partial_replacement_rejected'


def test_exact_segment_reorder_without_new_constraints_is_rejected():
    plan = _composite_plan()
    replacement = _replacement_from(plan)
    replacement['plan']['steps'][0]['segments'] = list(reversed(
        replacement['plan']['steps'][0]['segments']
    ))
    _without_constraint_fields(replacement['plan']['steps'][0])

    with pytest.raises(ComponentRepairError) as caught:
        merge_component_repair(_repair_context(plan), replacement)

    assert caught.value.code == 'junction_constraint_mapping_unsafe'
    assert caught.value.details['reason'] == 'segment_identity_order_changed'


def test_segment_count_change_without_new_constraints_is_rejected():
    plan = _composite_plan()
    replacement = _replacement_from(plan)
    replacement['plan']['steps'][0]['segments'].append(
        {'kind': 'line', 'start': _point(3, 0), 'end': _point(4, 1)}
    )
    _without_constraint_fields(replacement['plan']['steps'][0])

    with pytest.raises(ComponentRepairError) as caught:
        merge_component_repair(_repair_context(plan), replacement)

    assert caught.value.code == 'junction_constraint_mapping_unsafe'
    assert caught.value.details['reason'] == 'segment_count_changed'


def test_segment_count_change_with_valid_new_constraints_is_accepted():
    plan = _composite_plan()
    replacement = _replacement_from(plan)
    replacement['plan']['steps'][0]['segments'] = [
        {'kind': 'line', 'start': _point(0, 0), 'end': _point(1, 0)},
        {'kind': 'line', 'start': _point(1, 0), 'end': _point(2, 1)},
        {'kind': 'line', 'start': _point(2, 1), 'end': _point(3, 0)},
        {'kind': 'line', 'start': _point(3, 0), 'end': _point(4, 1)},
    ]
    replacement['plan']['steps'][0]['junction_constraints'] = [
        {
            'junction_index': 0,
            'left_segment_index': 0,
            'right_segment_index': 1,
            'intent': 'smooth',
            'required_continuity': 'C1',
            'tangent_tolerance_deg': 0.01,
            'source_requirement_refs': ['user:0'],
        },
        {
            'junction_index': 2,
            'left_segment_index': 2,
            'right_segment_index': 3,
            'intent': 'smooth',
            'required_continuity': 'C1',
            'tangent_tolerance_deg': 0.01,
            'source_requirement_refs': ['user:0'],
        },
    ]

    merged = merge_component_repair(
        _repair_context(plan), replacement
    )['plan']['steps'][0]

    assert merged['junction_constraints'] == replacement['plan']['steps'][0]['junction_constraints']


def test_explicit_tolerance_weakening_is_rejected():
    plan = _composite_plan()
    replacement = _replacement_from(plan)
    replacement['plan']['steps'][0]['tangent_tolerance_deg'] = 1.0

    with pytest.raises(ComponentRepairError) as caught:
        merge_component_repair(_repair_context(plan), replacement)

    assert caught.value.code == 'tangent_tolerance_weakened'


def test_explicit_self_intersection_permission_is_rejected():
    plan = _composite_plan()
    replacement = _replacement_from(plan)
    replacement['plan']['steps'][0]['allow_self_intersection'] = True

    with pytest.raises(ComponentRepairError) as caught:
        merge_component_repair(_repair_context(plan), replacement)

    assert caught.value.code == 'allow_self_intersection_weakened'


def test_explicit_stricter_tolerance_is_accepted_and_constraints_preserved():
    plan = _composite_plan()
    replacement = _replacement_from(plan)
    _without_constraint_fields(replacement['plan']['steps'][0])
    replacement['plan']['steps'][0]['tangent_tolerance_deg'] = 0.001

    merged = merge_component_repair(
        _repair_context(plan), replacement
    )['plan']['steps'][0]

    assert merged['tangent_tolerance_deg'] == 0.001
    assert merged['junction_constraints'] == plan['steps'][0]['junction_constraints']


def test_explicit_legitimate_continuity_change_is_kept():
    plan = _composite_plan()
    plan['steps'][0]['junction_constraints'] = []
    replacement = _replacement_from(plan)
    replacement['plan']['steps'][0]['continuity'] = 'C0'

    merged = merge_component_repair(
        _repair_context(plan), replacement
    )['plan']['steps'][0]

    assert merged['continuity'] == 'C0'


def test_missing_execution_policy_fields_are_preserved():
    plan = _composite_plan(closed=True)
    replacement = _replacement_from(plan)
    for key in (
        'closed', 'samples_per_curve', 'connection_tolerance',
        'allow_self_intersection', 'allow_duplicate_segments',
        'max_curvature', 'max_sampling_error',
    ):
        replacement['plan']['steps'][0].pop(key, None)
    _without_constraint_fields(replacement['plan']['steps'][0])

    merged = merge_component_repair(
        _repair_context(plan), replacement
    )['plan']['steps'][0]

    for key in (
        'closed', 'samples_per_curve', 'connection_tolerance',
        'allow_self_intersection', 'allow_duplicate_segments',
        'max_curvature', 'max_sampling_error',
    ):
        assert merged[key] == plan['steps'][0][key]


def test_unconstrained_primitive_repair_keeps_existing_behavior():
    plan = {
        'units': 'm',
        'steps': [{
            'step_id': 'circle', 'output_ref': 'circle', 'op': 'add_circle',
            'center': _point(0, 0), 'radius': 2,
            'semantic': {'label': '普通圆'},
        }],
    }
    replacement = {
        'plan': {
            'units': 'm',
            'steps': [{
                'step_id': 'circle', 'output_ref': 'circle', 'op': 'add_circle',
                'center': _point(0, 0), 'radius': 1.5,
                'semantic': {'label': '普通圆'},
            }],
        }
    }

    merged = merge_component_repair(
        _repair_context(plan, ref='circle'), replacement
    )['plan']['steps'][0]

    assert merged['radius'] == 1.5


@pytest.mark.parametrize('segment_kind,segments', [
    ('line', [
        {'kind': 'line', 'start': _point(0, 0), 'end': _point(1, 0)},
        {'kind': 'line', 'start': _point(1, 0), 'end': _point(2, 1)},
        {'kind': 'line', 'start': _point(2, 1), 'end': _point(3, 0)},
    ]),
    ('bezier', [
        {'kind': 'bezier', 'control_points': [
            _point(0, 0), _point(0.4, 0.5), _point(0.8, 0.8), _point(1, 0)]},
        {'kind': 'bezier', 'control_points': [
            _point(1, 0), _point(1.3, -0.4), _point(1.7, 0.2), _point(2, 1)]},
        {'kind': 'bezier', 'control_points': [
            _point(2, 1), _point(2.4, 1.3), _point(2.8, 0.2), _point(3, 0)]},
    ]),
    ('spline', [
        {'kind': 'spline', 'degree': 3, 'control_points': [
            _point(0, 0), _point(0.5, 0.4), _point(1.0, 0.2), _point(1.5, 0.3)]},
        {'kind': 'spline', 'degree': 3, 'control_points': [
            _point(1.5, 0.3), _point(2.0, 0.4), _point(2.5, 0.5), _point(3.0, 0.6)]},
        {'kind': 'spline', 'degree': 3, 'control_points': [
            _point(3.0, 0.6), _point(3.5, 0.7), _point(4.0, 0.8), _point(4.5, 0.9)]},
    ]),
    ('arc', [
        {'kind': 'arc', 'center': _point(0, 0), 'radius': 1,
         'start_angle': 0, 'end_angle': 90, 'clockwise': False},
        {'kind': 'arc', 'center': _point(1, 1), 'radius': 1,
         'start_angle': 180, 'end_angle': 270, 'clockwise': False},
        {'kind': 'arc', 'center': _point(2, 0), 'radius': 1,
         'start_angle': 0, 'end_angle': -90, 'clockwise': True},
    ]),
])
def test_constraint_preservation_is_independent_of_segment_kind(segment_kind, segments):
    plan = _composite_plan()
    plan['steps'][0]['segments'] = deepcopy(segments)
    replacement = _replacement_from(plan)
    _without_constraint_fields(replacement['plan']['steps'][0])

    merged = merge_component_repair(
        _repair_context(plan), replacement
    )['plan']['steps'][0]

    assert merged['junction_constraints'] == plan['steps'][0]['junction_constraints'], segment_kind



def _s1_plan_with_local_constraints():
    segments = [
        [_point(0.0, 0.0), _point(0.8, 0.6), _point(1.4, 1.2), _point(2.0, 1.0)],
        [_point(2.0, 1.0), _point(2.2, 0.9333333333333333), _point(3.6, -0.9), _point(4.0, -1.0)],
        [_point(4.0, -1.0), _point(4.4, -1.1), _point(5.2, -0.6), _point(6.0, 0.0)],
    ]
    return {
        'schema_version': 'cad.construction-plan.v1',
        'units': 'm',
        'steps': [{
            'op': 'add_composite_path',
            'step_id': 's1-service-step',
            'output_ref': 's1-s-curve',
            'layer_id': 1,
            'semantic': {'object_type': 'drawing_part', 'label': 'S1 service fixture'},
            'segments': [{'kind': 'bezier', 'control_points': item} for item in segments],
            'closed': False,
            'samples_per_curve': 64,
            'connection_tolerance': 0.000001,
            'continuity': 'C1',
            'tangent_tolerance_deg': 0.01,
            'allow_self_intersection': False,
            'allow_duplicate_segments': False,
            'junction_constraints': _junction_constraints(),
        }],
        'budgets': {'max_steps': 10, 'max_entities': 20},
    }


def _service(provider='deepseek'):
    from app.agent_service import RobotAgentService
    service = object.__new__(RobotAgentService)
    service.mode = provider
    service.api_keys = {provider: 'test-key'}
    service.model = 'test-model'
    service.base_model = 'test-model'
    service.advanced_model = 'test-model'
    service._cad_planning_model = 'deepseek-chat'
    return service


S1_PROMPT = (
    '新建一条开放、平滑的三段三次 Bezier 曲线，使用 3 段三次 Bezier 曲线连接。'
    '起点为 (0,0) 米，依次经过 (2,1) 米、(4,-1) 米，终点为 (6,0) 米。'
    '两处内部连接点必须满足 C1 连续和切向平滑，不允许尖点或自交，曲线不闭合。'
)


def _service_model_payload(plan):
    return json.dumps({
        'schema_version': 'cad.construction-interpretation.v1',
        'is_construction_request': True,
        'plan': plan,
        'confidence': 0.95,
        'evidence_text': [S1_PROMPT],
        'assumptions': [],
    }, ensure_ascii=False)


def test_service_component_repair_chain_preserves_local_constraints():
    plan = _s1_plan_with_local_constraints()
    replacement_plan = deepcopy(plan)
    _without_constraint_fields(replacement_plan['steps'][0])

    service = _service()
    with patch.object(
        service,
        '_structured_review_text',
        return_value=_service_model_payload(replacement_plan),
    ) as review:
        result = service._interpret_cad_construction_plan(
            S1_PROMPT,
            component_repair_context=_repair_context(plan, ref='s1-s-curve'),
        )

    review.assert_called_once()
    assert result['status'] == 'ready', json.dumps(result, ensure_ascii=False)[:3000]
    assert result['provider_attempted'] is True
    assert result['persisted'] is False
    assert result['plan']['steps'][0]['junction_constraints'] == plan['steps'][0]['junction_constraints']


def test_service_component_repair_chain_returns_explicit_clear_error():
    plan = _s1_plan_with_local_constraints()
    replacement_plan = deepcopy(plan)
    replacement_plan['steps'][0]['junction_constraints'] = []

    service = _service()
    with patch.object(
        service,
        '_structured_review_text',
        return_value=_service_model_payload(replacement_plan),
    ):
        result = service._interpret_cad_construction_plan(
            S1_PROMPT,
            component_repair_context=_repair_context(plan, ref='s1-s-curve'),
        )

    assert result['status'] == 'invalid'
    assert result['construction_error']['code'] == 'junction_constraints_clear_rejected'
