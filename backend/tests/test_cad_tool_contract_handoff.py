"""Contract integration and independent geometric checks; no corpus-specific rules."""
from copy import deepcopy
import math

import pytest
from pydantic import ValidationError

from app.cad_construction import CadConstructionPlan, ConstructionPlanError, execute_construction_plan
from app.cad_construction_interpreter import repair_construction_references_once
from app.cad_path_relation_acceptance import assemble_closed_boundary
from app.cad_structure_contract import StructureContractError


def arch_plan():
    specs = [
        ('bottom', 'add_line', {'start': {'x': 0, 'y': 0}, 'end': {'x': 4, 'y': 0}}),
        ('right', 'add_line', {'start': {'x': 4, 'y': 0}, 'end': {'x': 4, 'y': 3}}),
        ('top', 'add_arc', {'center': {'x': 2, 'y': 3}, 'radius': 2, 'start_angle': 0, 'end_angle': 180}),
        ('left', 'add_line', {'start': {'x': 0, 'y': 3}, 'end': {'x': 0, 'y': 0}}),
    ]
    return {'units': 'm', 'steps': [
        {'step_id': name, 'output_ref': name, 'op': op, **values,
         'semantic': {'object_id': name + '-part', 'label': name, 'assembly_id': 'arch', 'assembly_label': 'arch'}}
        for name, op, values in specs], 'assertions': [
            {'kind': 'closed', 'assertion_id': 'closure', 'target_ref': 'assembly:arch'},
            {'kind': 'bounds_size', 'assertion_id': 'bounds', 'target_ref': 'assembly:arch', 'width': 4, 'height': 5},
            {'kind': 'entity_count', 'assertion_id': 'count', 'target_ref': 'assembly:arch', 'equals': 4},
        ]}


def test_native_composite_boundary_uses_same_identity_and_measurement_contract():
    plan = arch_plan()
    before = deepcopy(plan)
    fixed, _ = repair_construction_references_once({'plan': plan})
    assert fixed['plan']['assertions'] == before['assertions']
    result = execute_construction_plan(fixed['plan'])
    assert plan == before
    assert result['reference_table']['assembly:arch'] == [1, 2, 3, 4]
    assert result['reference_table']['object:top-part'] == result['symbol_table']['top'] == [3]
    assert len(result['symbol_table']) == 4
    assert len(result['logical_objects']) == 4  # identity and primitive segmentation are retained
    from evaluations.closed_boundary_oracle_v3 import single_closed_boundary
    assert single_closed_boundary(result['geometries'])['passed']


@pytest.mark.parametrize('mutation', ['gap', 'branch', 'duplicate', 'disconnected', 'crossing'])
def test_composite_closed_assertion_rejects_real_topology_errors(mutation):
    plan = arch_plan()
    if mutation == 'gap':
        plan['steps'][3]['start']['y'] += .01
    elif mutation in {'branch', 'duplicate', 'disconnected'}:
        extra = deepcopy(plan['steps'][0])
        extra.update(step_id='extra', output_ref='extra', semantic={'label': 'extra', 'assembly_id': 'arch', 'assembly_label': 'arch'})
        if mutation == 'branch':extra['end'] = {'x': -1, 'y': -1}
        if mutation == 'disconnected':extra.update(start={'x': 10, 'y': 10}, end={'x': 11, 'y': 10})
        plan['steps'].append(extra)
    else:
        points = [(0, 0), (4, 3), (0, 3), (4, 0)]
        for index, step in enumerate(plan['steps']):
            plan['steps'][index] = {k: step[k] for k in ('step_id', 'output_ref', 'semantic')}
            plan['steps'][index].update(op='add_line', start=dict(zip(('x', 'y'), points[index])),
                                       end=dict(zip(('x', 'y'), points[(index+1)%4])))
    with pytest.raises(ConstructionPlanError) as error:
        execute_construction_plan(plan)
    assert error.value.code == 'assertion_failed'
    assert error.value.assertion_id == 'closure'
    assert 'boundary_validation' in error.value.details


def test_names_are_explicit_and_namespace_collisions_are_not_guessed():
    plan = arch_plan()
    plan['assertions'][0]['target_ref'] = 'arch'
    with pytest.raises(ValidationError, match='unknown_reference'):
        CadConstructionPlan.model_validate(plan)
    plan = arch_plan()
    plan['steps'][0]['output_ref'] = 'assembly:arch'
    with pytest.raises(ValidationError, match='ambiguous_reference'):
        CadConstructionPlan.model_validate(plan)


def test_group_is_not_silently_reduced_to_one_primitive_for_constraints():
    plan = arch_plan();plan['assertions'] = []
    plan['constraints'] = [{'kind': 'concentric', 'constraint_id': 'bad',
                            'target_ref': 'assembly:arch', 'reference_ref': 'object:top-part'}]
    with pytest.raises(ConstructionPlanError) as error:execute_construction_plan(plan)
    assert error.value.code == 'constraint_requires_single_geometry'


def test_area_does_not_treat_open_composite_edges_as_individually_closed_regions():
    plan = arch_plan()
    plan['assertions'] = [{'kind': 'area', 'assertion_id': 'area', 'target_ref': 'assembly:arch', 'area': 1}]
    with pytest.raises(ConstructionPlanError) as error:execute_construction_plan(plan)
    assert error.value.code == 'invalid_area_target'


def test_layout_reads_composite_bounds_but_only_mutates_closed_polyline():
    plan = arch_plan()
    plan['steps'].append({'op': 'add_rectangle', 'step_id': 'rect', 'output_ref': 'rect',
                          'origin': {'x': 0, 'y': 0}, 'width': 2, 'height': 1,
                          'semantic': {'label': 'rectangle', 'object_id': 'rect-part'}})
    plan['free_outline_layout'] = [{'target_ref': 'object:rect-part', 'right_of_ref': 'assembly:arch', 'gap': .7}]
    result = execute_construction_plan(plan)
    vertices = result['geometries'][-1]['vertices']
    assert min(p['x'] for p in vertices) == pytest.approx(4700)
    assert (min(p['y'] for p in vertices)+max(p['y'] for p in vertices))/2 == pytest.approx(2500)
    plan['free_outline_layout'][0]['target_ref'] = 'assembly:arch'
    with pytest.raises(ValidationError):CadConstructionPlan.model_validate(plan)


def test_endpoint_cluster_and_unsupported_bulge_are_rejected_without_geometry_rewrite():
    geoms = execute_construction_plan(arch_plan())['geometries']
    before = deepcopy(geoms)
    assert assemble_closed_boundary(geoms).area > 0
    assert geoms == before
    bad = [{'id': 1, 'type': 'polyline', 'closed': True,
            'vertices': [{'x': 0, 'y': 0, 'bulge': 1}, {'x': 2, 'y': 0}, {'x': 2, 'y': 2}]}]
    with pytest.raises(StructureContractError) as error:assemble_closed_boundary(bad)
    assert error.value.details['reason'] == 'unsupported_bulge'
    chain = [{'id': i+1, 'type': 'line', 'start': {'x': x, 'y': 0}, 'end': {'x': 10+i, 'y': 10}}
             for i, x in enumerate((0, .4, .8))]
    with pytest.raises(StructureContractError) as error:assemble_closed_boundary(chain)
    assert error.value.details['reason'] == 'ambiguous_endpoint_cluster'


def test_array_seed_identity_is_not_an_instance_object_reference():
    plan = endpoint_plan('line', 'start', 'end', 'm');plan['constraints'] = []
    plan['steps'].append({'op': 'rectangular_array', 'step_id': 'copies', 'output_ref': 'copies',
                          'source_ref': 'target', 'columns': 2, 'column_spacing': 10,
                          'semantic': {'object_id': 'copy-seed', 'label': 'copies'}})
    plan['assertions'] = [{'kind': 'entity_count', 'assertion_id': 'count', 'target_ref': 'object:copy-seed', 'equals': 1}]
    with pytest.raises(ValidationError, match='unknown_reference'):CadConstructionPlan.model_validate(plan)
    plan['assertions'][0]['target_ref'] = 'copies'
    assert execute_construction_plan(plan)['symbol_table']['copies'] == [3]


def endpoint_plan(kind, target_end, reference_end, units):
    factor = 1 if units == 'm' else 1000
    p = lambda x, y: {'x': x*factor, 'y': y*factor}
    shape = {'line': {'op': 'add_line', 'start': p(-3, 7), 'end': p(-1, 8)},
             'polyline': {'op': 'add_polyline', 'vertices': [p(-3, 7), p(-2, 9), p(-1, 8)], 'closed': False},
             'arc': {'op': 'add_arc', 'center': p(-3, 7), 'radius': 1.7*factor, 'start_angle': 23, 'end_angle': 137}}[kind]
    return {'units': units, 'constraint_backend': 'builtin', 'steps': [
        {'op': 'add_line', 'step_id': 'reference', 'output_ref': 'reference', 'start': p(2, -4), 'end': p(5, -1),
         'semantic': {'label': 'fixed', 'object_id': 'fixed'}},
        {'step_id': 'target', 'output_ref': 'target', **shape, 'semantic': {'label': 'moving', 'object_id': 'moving'}}],
        'constraints': [{'kind': 'endpoint_coincident', 'constraint_id': 'join',
                         'target_ref': 'object:moving', 'reference_ref': 'object:fixed',
                         'target_endpoint': target_end, 'reference_endpoint': reference_end}]}


@pytest.mark.parametrize('units', ['m', 'mm'])
@pytest.mark.parametrize('kind', ['line', 'arc', 'polyline'])
@pytest.mark.parametrize('target_end,reference_end', [('start', 'start'), ('start', 'end'), ('end', 'start'), ('end', 'end')])
def test_endpoint_join_is_measured_and_preserves_shape_and_reference(kind, target_end, reference_end, units):
    plan = endpoint_plan(kind, target_end, reference_end, units);before = deepcopy(plan)
    unconstrained = deepcopy(plan);unconstrained['constraints'] = []
    original = execute_construction_plan(unconstrained)['geometries']
    result = execute_construction_plan(plan)
    assert plan == before
    assert result['geometries'][0] == original[0]
    target = result['geometries'][1];source = original[1]
    if kind == 'arc':
        assert (target['radius'], target['start_angle'], target['end_angle']) == (source['radius'], source['start_angle'], source['end_angle'])
        angle = math.radians(target[target_end+'_angle'])
        point = (target['center']['x']+target['radius']*math.cos(angle), target['center']['y']+target['radius']*math.sin(angle))
    else:
        points = ([target['start'], target['end']] if kind == 'line' else target['vertices'])
        previous = ([source['start'], source['end']] if kind == 'line' else source['vertices'])
        assert [math.dist((a['x'], a['y']), (b['x'], b['y'])) for a, b in zip(points, points[1:])] == pytest.approx(
            [math.dist((a['x'], a['y']), (b['x'], b['y'])) for a, b in zip(previous, previous[1:])])
        chosen = points[0 if target_end == 'start' else -1];point = (chosen['x'], chosen['y'])
    expected = original[0][reference_end]
    assert math.dist(point, (expected['x'], expected['y'])) < 1e-8
    report = result['constraint_solve']['constraints'][0]
    assert report['verified'] and report['metric'] == 'endpoint_distance_mm'
    assert execute_construction_plan(plan)['geometries'] == result['geometries']


def test_aliases_of_same_geometry_do_not_create_fake_binary_relation():
    plan = endpoint_plan('line', 'start', 'end', 'm')
    plan['constraints'][0]['reference_ref'] = 'target'
    with pytest.raises(ConstructionPlanError) as error:execute_construction_plan(plan)
    assert error.value.code == 'constraint_overlapping_references'


def test_endpoint_relation_survives_production_interpretation_without_becoming_delivery_proof():
    from app.cad_construction_interpreter import interpret_construction_request
    source = '绘制两条首尾相接的线段，坐标单位米'
    result = interpret_construction_request(source, lambda *_: {
        'schema_version': 'cad.construction-interpretation.v1', 'is_construction_request': True,
        'confidence': .99, 'evidence_text': [source], 'assumptions': [],
        'plan': endpoint_plan('line', 'start', 'end', 'm')}, force_structured_model=True)
    assert result['status'] == 'ready', result.get('error')
    gs = result['trial_result']['geometries']
    assert gs[0]['end'] == gs[1]['start']
    assert result['trial_result']['constraint_solve']['verified']


def test_endpoint_native_backend_is_explicitly_unsupported_not_silently_faked(monkeypatch):
    from app import cad_constraint_solver as solver
    monkeypatch.setattr(solver, 'available_constraint_backends', lambda: {
        'builtin': {'available': True}, 'solvespace': {'available': True, 'executable': 'unused'},
        'planegcs': {'available': False}})
    monkeypatch.setattr(solver, '_run_native_solver', lambda *a, **k: pytest.fail('must reject before native invocation'))
    plan = endpoint_plan('line', 'start', 'end', 'm');plan['constraint_backend'] = 'solvespace'
    with pytest.raises(ConstructionPlanError) as error:execute_construction_plan(plan)
    assert error.value.code == 'constraint_backend_kind_unsupported'


def test_long_explicit_ids_and_repeated_identity_remain_unambiguous():
    plan = endpoint_plan('line', 'start', 'end', 'm')
    identity = 'x'*128
    plan['steps'][1]['semantic']['object_id'] = identity
    plan['constraints'][0]['target_ref'] = 'object:'+identity
    assert execute_construction_plan(plan)['constraint_solve']['verified']
    plan['steps'][0]['semantic']['object_id'] = identity
    with pytest.raises(ValidationError, match='ambiguous_reference'):CadConstructionPlan.model_validate(plan)


def test_layout_alias_cannot_bypass_post_scaling_sampling_accuracy():
    plan = {'steps': [{'op': 'add_parametric_curve', 'step_id': 'curve', 'output_ref': 'curve',
                      'semantic': {'label': 'curve', 'object_id': 'curve-part'},
                      'x_expression': 'cos(t)', 'y_expression': 'sin(t)', 't_end': '2*pi', 'closed': True,
                      'max_sampling_error': .001}],
            'free_outline_layout': [{'target_ref': 'object:curve-part', 'width': 10, 'height': 10}]}
    result = execute_construction_plan(plan)
    quality = result['curve_quality'][0]
    assert quality['post_layout_sampling_error_bound'] <= quality['max_sampling_error']


def test_layout_detects_physical_overlap_even_with_distinct_output_symbols():
    plan = {'steps': [
        {'op': 'add_rectangle', 'step_id': 'seed', 'output_ref': 'seed', 'semantic': {'label': 'seed'},
         'origin': {'x': 0, 'y': 0}, 'width': 2, 'height': 1},
        {'op': 'rectangular_array', 'step_id': 'array', 'output_ref': 'array', 'semantic': {'label': 'array'},
         'source_ref': 'seed', 'columns': 2, 'column_spacing': 5, 'include_source': True}],
        'free_outline_layout': [{'target_ref': 'seed', 'right_of_ref': 'array', 'gap': 1}]}
    with pytest.raises(ConstructionPlanError) as error:execute_construction_plan(plan)
    assert error.value.code == 'invalid_layout_target'


def test_incompatible_endpoint_constraints_are_rechecked_after_all_moves():
    plan = endpoint_plan('line', 'start', 'start', 'm')
    conflict = deepcopy(plan['constraints'][0]);conflict.update(constraint_id='conflict', reference_endpoint='end')
    plan['constraints'].append(conflict)
    with pytest.raises(ConstructionPlanError) as error:execute_construction_plan(plan)
    assert error.value.code == 'constraint_residual_exceeded'


@pytest.mark.parametrize('replacement', [
    {'op': 'add_circle', 'center': {'x': 0, 'y': 0}, 'radius': 1},
    {'op': 'add_arc', 'center': {'x': 0, 'y': 0}, 'radius': 1, 'start_angle': 0, 'end_angle': 360},
    {'op': 'add_polyline', 'vertices': [{'x': 0, 'y': 0}, {'x': 1, 'y': 0}, {'x': 1, 'y': 1}], 'closed': True},
])
def test_endpoint_relation_rejects_objects_without_unique_open_endpoints(replacement):
    plan = endpoint_plan('line', 'start', 'end', 'm')
    old = plan['steps'][1]
    plan['steps'][1] = {k: old[k] for k in ('step_id', 'output_ref', 'semantic')}
    plan['steps'][1].update(replacement)
    with pytest.raises(ConstructionPlanError) as error:execute_construction_plan(plan)
    assert error.value.code == 'constraint_geometry_type_unsupported'
