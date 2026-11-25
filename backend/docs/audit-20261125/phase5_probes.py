"""Read-only topology evolution, revision and partition boundary probes."""
from copy import deepcopy
import json
from pathlib import Path

from app.incremental_cad import edit_candidate_geometries
from app.cad_edit_contract import build_cad_edit_contract
from app.cad_construction import construction_geometry_bounds
from app.cad_target_resolver import resolve_logical_object_target
from app.cad_revision import build_cad_revision_contract
from app.logical_topology import evolve_logical_graph_for_edit, validate_logical_object_graph
from app.spatial_partition import build_spatial_partition, MAX_SEGMENT_PRINTING_LENGTH_M
from app.cad_project_candidates import normalize_model_geometry_units, scale_factor_from_message
from app.incremental_cad import _scale_factor


def execute_graph(source, objects, topology, edit):
    before = deepcopy((source, objects, topology))
    target, error = edit_candidate_geometries(source, edit)
    if target is None:
        return {'executor_ok': False, 'error': error}
    contract = build_cad_edit_contract(edit)
    evolved, graph = evolve_logical_graph_for_edit(source, target, objects, topology, contract)
    revision = build_cad_revision_contract(source, target,
        parent_variant_id='review-parent', variant_id='review-child', edit_contract=contract,
        source_logical_objects=objects, target_logical_objects=evolved,
        source_topology=topology, target_topology=graph)
    return {'executor_ok': True, 'error': error, 'contract': contract,
        'target': target, 'objects': evolved, 'topology': graph,
        'graph_validation': validate_logical_object_graph(target, evolved, graph),
        'revision_status': revision['status'],
        'revision_logical_validation': revision['logical_object_validation'],
        'source_inputs_unchanged': before == (source, objects, topology)}


out = {'scope': 'Actual deterministic edit, graph evolution, revision, target resolver and '
                'partition functions. No HTTP finalization, candidate store, model or hardware calls.'}
source = [{'id': 1, 'type': 'circle', 'layer_id': 1, 'template_instance': 1,
           'center': {'x': 0, 'y': 0, 'z': 0}, 'radius': 500}]
objects = [{'object_id': 'circle-1', 'object_type': 'circle', 'label': '圆形',
    'geometry_refs': [1], 'bounds': {'min_x': -500, 'max_x': 500, 'min_y': -500, 'max_y': 500},
    'assembly_id': 'drawing', 'assembly_label': '图形', 'confirmed': True}]
record = execute_graph(source, objects, {}, {'operation': 'duplicate', 'geometry_ids': [1],
    'direction': '右', 'distance_mm': 3000, 'placement': 'offset'})
record['actual_copy_bounds_mm'] = construction_geometry_bounds([record['target'][-1]])
record['rightmost_resolution'] = resolve_logical_object_target(
    {'position': 'right', 'object_type': 'circle'}, record['objects'])
out['copy_bounds'] = record


def rect(gid, x):
    return {'id': gid, 'type': 'polyline', 'closed': True, 'layer_id': 1, 'template_instance': 1,
        'vertices': [{'x': a + x, 'y': b, 'z': 0} for a, b in ((0,0),(1000,0),(1000,1000),(0,1000))]}


source = [rect(1, 0), rect(2, 3000)]
objects = [{'object_id': 'pair', 'object_type': 'drawing', 'label': '组合',
    'geometry_refs': [1, 2], 'confirmed': True,
    'bounds': {'min_x': 0, 'max_x': 4000, 'min_y': 0, 'max_y': 1000}}]
record = execute_graph(source, objects, {}, {'operation': 'delete', 'geometry_ids': [2]})
record['actual_remaining_bounds_mm'] = construction_geometry_bounds(record['target'])
out['delete_bounds'] = record

source = [{'id': i + 1, 'type': 'line', 'layer_id': 1, 'template_instance': 1,
    'start': {'x': i * 1000, 'y': 0, 'z': 0},
    'end': {'x': i * 1000, 'y': 1000, 'z': 0}} for i in range(3)]
objects = [{'object_id': name, 'object_type': 'room', 'label': name, 'geometry_refs': refs,
    'assembly_id': 'whole', 'assembly_label': '组合', 'confirmed': True,
    'bounds': {'min_x': x, 'max_x': x + 1000, 'min_y': 0, 'max_y': 1000}}
    for name, refs, x in (('room-a', [1, 2], 0), ('room-b', [2, 3], 1000))]
topology = {'shared_geometries': [{'geometry_id': 2, 'object_ids': ['room-a', 'room-b'],
                                 'relation': 'shared_boundary'}], 'relations': []}
out['shared_boundary_copy'] = []
for scope in ('instance', 'geometry'):
    edit = {'operation': 'duplicate', 'direction': '右', 'distance_mm': 4000, 'placement': 'offset'}
    edit.update({'instance': 1} if scope == 'instance' else {'geometry_ids': [1,2,3]})
    out['shared_boundary_copy'].append({'scope': scope, **execute_graph(source, objects, topology, edit)})

points = []
for row in range(61):
    points.extend({'x': x, 'y': row * 300, 'z': 0} for x in
                  ((0, 10000) if row % 2 == 0 else (10000, 0)))
partition = build_spatial_partition('partition-review',
    [{'id': 1, 'type': 'polyline', 'layer_id': 1, 'closed': False, 'vertices': points}], [], {},
    {'suggested_rows': 1, 'suggested_columns': 1, 'work_zone_size_m': 50})
segments = [s for z in partition['zones'] for s in z['execution_segments']]
out['partition_single_long_path'] = {'footprint_mm': [10000, 18000],
    'partition_status': partition['status'], 'coverage': partition['coverage'],
    'coordinate_validation': partition['coordinate_validation'],
    'segment_budget_m': MAX_SEGMENT_PRINTING_LENGTH_M,
    'segment_lengths_m': [s['printing_length_m'] for s in segments],
    'segment_count': len(segments)}

line = [{'id': 1, 'type': 'line', 'start': {'x': 0, 'y': 0}, 'end': {'x': 1, 'y': 0}}]
normalized, note = normalize_model_geometry_units(line, None, explicit_units='m')
out['compatibility_helper_boundaries'] = {
    'scope': 'Function-only findings; current app caller supplies explicit mm. '
             'Whole-design scale helpers have no app call sites found.',
    'explicit_m_horizontal_line': {'note': note, 'actual_endpoint': normalized[0]['end'],
                                  'expected_endpoint_mm': {'x': 1000, 'y': 0}},
    'scale_parser_differential': [{
        'text': text, 'incremental_parser': _scale_factor(text),
        'whole_design_helper': scale_factor_from_message(text)}
        for text in ('缩小到0.5倍', '缩小到原来的0.5倍')]}

path = Path('.local-dev/code-capability-audit-20261125/phase5-probes.json')
path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'copy_revision': out['copy_bounds']['revision_status'],
    'copy_target_resolution': out['copy_bounds']['rightmost_resolution']['status'],
    'delete_revision': out['delete_bounds']['revision_status'],
    'shared_copy': [{'scope': r['scope'], 'graph': r['graph_validation']['verified'],
                     'revision': r['revision_status'],
                     'errors': [e['code'] for e in r['revision_logical_validation']['errors']]}
                    for r in out['shared_boundary_copy']],
    'partition': out['partition_single_long_path']}, ensure_ascii=True))
