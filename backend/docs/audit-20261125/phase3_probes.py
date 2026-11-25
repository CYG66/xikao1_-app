"""Read-only normalization boundary probes; no model, store or device calls."""
from copy import deepcopy
import json
import math
from pathlib import Path

from app.cad_construction_interpreter import normalize_composite_path_connections_once
from app.cad_construction import execute_construction_plan, construction_geometry_bounds
from app.drawing_store import geometry_preview_paths


def trial(plan):
    try:
        result = execute_construction_plan(plan)
        return {'ok': True, 'geometry_count': len(result['geometries'])}
    except Exception as exc:
        return {'ok': False, 'exception': type(exc).__name__,
                'code': getattr(exc, 'code', None), 'message': str(exc)}


out = {'scope': 'Existing normalizer plus real deterministic executor only; '
                'no HTTP delivery or live model claim.'}
out['three_control_points'] = []
for kind in ('bezier', 'spline'):
    first = {'kind': kind, 'control_points': [
        {'x': 0, 'y': 0}, {'x': 1, 'y': 1}, {'x': 2, 'y': 0}]}
    second = {'kind': kind, 'control_points': [
        {'x': 3, 'y': 0}, {'x': 4, 'y': 1}, {'x': 5, 'y': 0}]}
    if kind == 'spline':
        first['degree'] = second['degree'] = 2
    payload = {'plan': {'units': 'm', 'steps': [{
        'op': 'add_composite_path', 'step_id': 'path', 'output_ref': 'path',
        'semantic': {'label': '曲线'}, 'closed': False,
        'segments': [first, second]}]}}
    source = ('两段二次曲线，保留控制点：第一段(0,0),(1,1),(2,0)；'
              '第二段(3,0),(4,1),(5,0)，坐标单位米。')
    before = deepcopy(payload)
    normalized, repairs = normalize_composite_path_connections_once(payload, source)
    out['three_control_points'].append({
        'kind': kind, 'source': source,
        'original_control_points': before['plan']['steps'][0]['segments'][1]['control_points'],
        'normalized_control_points': normalized['plan']['steps'][0]['segments'][1]['control_points'],
        'repairs': repairs, 'before_executor': trial(before['plan']),
        'after_executor': trial(normalized['plan']), 'input_unchanged': before == payload})

source = '画两个独立圆弧：中心(0,0)半径1米的上半圆；中心(5,0)半径1米的下半圆，坐标单位米。'
payload = {'plan': {'units': 'm', 'steps': []}}
for name, x, clockwise in (('upper', 0, False), ('lower', 5, True)):
    payload['plan']['steps'].append({
        'op': 'add_composite_path', 'step_id': name, 'output_ref': name,
        'semantic': {'label': name}, 'closed': False, 'segments': [{
            'kind': 'arc', 'center': {'x': x, 'y': 0}, 'radius': 1,
            'start_angle': 0, 'end_angle': 180, 'clockwise': clockwise}]})
before = deepcopy(payload)
normalized, repairs = normalize_composite_path_connections_once(payload, source)
out['scoped_semicircles'] = {
    'source': source, 'before': before, 'after': normalized, 'repairs': repairs,
    'before_executor': trial(before['plan']), 'after_executor': trial(normalized['plan']),
    'input_unchanged': before == payload}

out['local_tangent_tolerance'] = []
for global_tol, local_tol in ((5, 1), (1, 5)):
    plan = {'units': 'm', 'steps': [{
        'op': 'add_composite_path', 'step_id': 'joint', 'output_ref': 'joint',
        'semantic': {'label': '连接'}, 'closed': False, 'continuity': 'C0',
        'tangent_tolerance_deg': global_tol, 'junction_constraints': [{
            'junction_index': 0, 'left_segment_index': 0, 'right_segment_index': 1,
            'intent': 'smooth', 'required_continuity': 'G1',
            'tangent_tolerance_deg': local_tol}], 'segments': [
                {'kind': 'line', 'start': {'x': 0, 'y': 0}, 'end': {'x': 1, 'y': 0}},
                {'kind': 'line', 'start': {'x': 1, 'y': 0},
                 'end': {'x': 1 + math.cos(math.radians(2)), 'y': math.sin(math.radians(2))}}]}]}
    out['local_tangent_tolerance'].append({
        'global_tolerance_deg': global_tol, 'local_tolerance_deg': local_tol,
        'actual_angle_deg': 2, 'expected_pass_under_local_contract': 2 <= local_tol,
        'executor': trial(plan)})

controls = [{'x': 0, 'y': 0}, {'x': 1, 'y': 2}, {'x': 2, 'y': 0}]
out['equivalent_bezier_bounds'] = []
for representation in ('native', 'composite'):
    step = {'step_id': 'curve', 'output_ref': 'curve', 'semantic': {'label': '二次曲线'}}
    if representation == 'native':
        step.update(op='add_bezier', control_points=deepcopy(controls))
    else:
        step.update(op='add_composite_path', segments=[{'kind': 'bezier',
                    'control_points': deepcopy(controls)}], closed=False)
    plan = {'units': 'm', 'steps': [step]}
    result = execute_construction_plan(plan)
    preview = geometry_preview_paths({'lines': result['geometries']})
    checked = deepcopy(plan)
    checked['assertions'] = [{'kind': 'bounds_size', 'assertion_id': 'bounds',
                             'target_ref': 'curve', 'width': 2, 'height': 2}]
    out['equivalent_bezier_bounds'].append({
        'representation': representation, 'analytic_curve_bounds_mm': {
            'min_x': 0, 'max_x': 2000, 'min_y': 0, 'max_y': 1000},
        'construction_bounds_mm': construction_geometry_bounds(result['geometries']),
        'preview_bounds_mm': {key: value * 1000 for key, value in preview[0]['bounds'].items()},
        'incorrect_two_metre_height_assertion': trial(checked)})

destination = Path('.local-dev/code-capability-audit-20261125/phase3-probes.json')
destination.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(out, ensure_ascii=False, indent=2))
