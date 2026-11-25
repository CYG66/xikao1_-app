"""Read-only review probes; run with scripts.local_dev isolated environment."""
from pathlib import Path
import json
import math
import runpy

from app.cad_construction_interpreter import interpret_construction_request, construction_acceptance_summary
from app.drawing_store import _geometry_points
from app.cad_precision import ACCEPTANCE_MM, SAMPLING_MM
from app.cad_source_acceptance import verify_final_source_contract
from evaluations.bezier_layout_minimum_v1 import measure
from app.cad_construction import execute_construction_plan
from app.cad_target_resolver import resolve_cad_target, resolve_logical_object_target

out = {}
corpus = json.loads(Path('evaluations/cad_construction_chinese_commands.json').read_text(encoding='utf-8'))
case = next(c for c in corpus['cases'] if c['id'] == 'circle_centimeters')
out['circle_centimeters'] = {'case': case, 'actual': interpret_construction_request(case['command'])}
out['explicit_coordinate_units'] = {}
for unit, coordinate, radius in [('米', 2, 1.5), ('厘米', 200, 150), ('毫米', 2000, 1500)]:
    source = f'画一个圆，圆心({coordinate},{coordinate})，半径{radius}{unit}，坐标单位为{unit}'
    out['explicit_coordinate_units'][unit] = {'source': source, 'result': interpret_construction_request(source)}

arc = {'id': 1, 'type': 'arc', 'center': {'x': 0, 'y': 0},
       'radius': 5000, 'start_angle': 0, 'end_angle': 180}
points = _geometry_points(arc)
a, b = points[0], points[1]
midpoint = [(a[i] + b[i])/2 for i in (0, 1)]
out['arc_preview_precision'] = {
    'geometry': arc, 'segment_count': len(points)-1,
    'first_chord_sag_mm': arc['radius']-math.hypot(*midpoint)*1000,
    'construction_sampling_budget_mm': SAMPLING_MM,
    'source_acceptance_tolerance_mm': ACCEPTANCE_MM,
    'scope': 'Renderer samples reused by measure_path_geometry; not an HTTP false-acceptance reproduction.'}

geometries = [{'id': 1, 'type': 'circle', 'center': {'x': 0, 'y': 0}, 'radius': 1000},
              {'id': 2, 'type': 'circle', 'center': {'x': 4000, 'y': 0}, 'radius': 2000}]
out['named_inner_outer_test_fixture'] = verify_final_source_contract(
    '内圆：半径1米；外圆：半径2米', geometries,
    [{'label': '内圆', 'geometry_ids': [1]}, {'label': '外圆', 'geometry_ids': [2]}])

out['generic_preflight_review_resolution'] = construction_acceptance_summary(
    preflight_structure={'review_required': True}, structure_contract={'id': 'source'},
    structure_validation={'status': 'passed'}, composition_contract=None,
    composition_validation=None,
    source_acceptance={'coverage': 'complete', 'checks': [{'status': 'passed'}]})

out['middle_target_representation'] = {}
for positions in [(-2000, 2000), (0, 10000, 5000)]:
    gs = [{'id': i, 'type': 'circle', 'center': {'x': x, 'y': 0}, 'radius': 100,
           'template_instance': i, 'template_type': 'circle'} for i,x in enumerate(positions,1)]
    objects = [{'object_id': f'circle-{g["id"]}', 'object_type': 'circle', 'label': f'circle-{g["id"]}',
                'confirmed': True, 'geometry_refs': [g['id']],
                'bounds': {'min_x': g['center']['x']-100, 'max_x': g['center']['x']+100,
                           'min_y': -100, 'max_y': 100}} for g in gs]
    out['middle_target_representation'][str(positions)] = {
        'centers_by_instance_id': {g['id']: g['center']['x'] for g in gs},
        'instance_untyped': resolve_cad_target({'position': 'middle'}, gs),
        'instance_typed': resolve_cad_target({'position': 'middle', 'object_type': 'circle'}, gs),
        'logical_object': resolve_logical_object_target({'position': 'middle', 'object_type': 'circle'}, objects)}

fixture = runpy.run_path('tests/test_bezier_layout_minimum_v1.py')['plan']
out['offline_minimum_trace'] = {}
for unit in ('m', 'mm'):
    for flat in (False, True):
        result = measure(fixture(flat=flat, unit=unit))
        try:
            execute_construction_plan(fixture(flat=flat, unit=unit))
        except Exception as exc:
            result['direct_execution_error'] = exc.as_dict() if hasattr(exc, 'as_dict') else str(exc)
        out['offline_minimum_trace'][f'{unit},flat={flat}'] = result

destination = Path('.local-dev/code-capability-audit-20261125/additional-probes.json')
destination.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
for key, value in out.items():
    if key == 'explicit_coordinate_units':
        value = {unit: {'source': v['source'], 'status': v['result'].get('status'),
                       'error': v['result'].get('construction_error')} for unit,v in value.items()}
    if key == 'circle_centimeters':
        value = {'command': value['case']['command'], 'expected': value['case']['expected_status'],
                 'actual': value['actual'].get('status'), 'error': value['actual'].get('error'),
                 'construction_error': value['actual'].get('construction_error')}
    print(key, json.dumps(value, ensure_ascii=False))
