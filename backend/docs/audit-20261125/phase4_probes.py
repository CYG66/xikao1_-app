"""Read-only differential probes of existing edit paths and preflight."""
from copy import deepcopy
import json
from pathlib import Path

from app.incremental_cad import (edit_candidate_geometries, parse_incremental_edit,
                                 resolve_incremental_followup)
from app.cad_edit_contract import build_cad_edit_contract
from app.cad_edit_gate import build_cad_edit_preflight
from app.cad_edit_plan import build_cad_edit_plan


def rectangle(instance=1):
    return [{'id': 1, 'type': 'polyline', 'template_instance': instance, 'layer_id': 1,
             'closed': True, 'vertices': [
                 {'x': x, 'y': y, 'z': 0.0}
                 for x, y in ((0, 0), (10000, 0), (10000, 2000), (0, 2000))]}]


def bounds(items):
    points = [p for g in items for p in g.get('vertices', [])]
    return {key: op(p[axis] for p in points) for key, axis, op in (
        ('min_x', 'x', min), ('max_x', 'x', max), ('min_y', 'y', min), ('max_y', 'y', max))}


def execute(source, edit, text=None):
    original = deepcopy(source)
    edit = deepcopy(edit)
    target, error = edit_candidate_geometries(source, edit)
    record = {'executor_ok': target is not None, 'error': error,
              'edit_after_execution': edit, 'source_unchanged': source == original}
    if target is not None:
        record['geometry_ids'] = [g['id'] for g in target]
        record['instance_ids'] = [g.get('template_instance') for g in target]
        additions = [g for g in target if g['id'] not in {g['id'] for g in source}]
        if additions:
            record['added_bounds_mm'] = bounds(additions)
        contract = build_cad_edit_contract(edit, source_text=text)
        preflight = build_cad_edit_preflight(source, target, contract)
        record['contract'] = contract
        record['edit_plan_verification'] = build_cad_edit_plan(source, target, contract)['verification']
        record['preflight'] = {key: preflight[key] for key in (
            'ready', 'requires_confirmation', 'checks', 'effect_validation', 'relation_validation')}
    return record


out = {'scope': 'Actual parser, continuation rewrite, executor, contract and preflight. '
                'No live model, HTTP finalizer, candidate save or device call.'}
out['offset_representation'] = []
for scope in ('instance', 'geometry'):
    edit = {'operation': 'offset', 'offset_side': 'outside', 'distance_mm': 1000}
    edit.update({'instance': 1} if scope == 'instance' else {'geometry_ids': [1]})
    out['offset_representation'].append({'scope': scope, **execute(rectangle(), edit)})

out['symmetric_mirror_representation'] = []
for scope in ('instance', 'geometry'):
    edit = {'operation': 'mirror', 'mirror_axis': 'vertical', 'keep_source': True}
    edit.update({'instance': 1} if scope == 'instance' else {'geometry_ids': [1]})
    out['symmetric_mirror_representation'].append({'scope': scope, **execute(rectangle(), edit)})

source_text = '将第2个图形做环形阵列，共6份，每60度。'
parsed = parse_incremental_edit(source_text)
out['polar_array_count'] = {'source': source_text, 'parsed': deepcopy(parsed),
                            'expected_count': 6, 'execution': execute(rectangle(2), parsed, source_text)}

source_text = '把它向右移动1米并向上移动2米'
previous = {'operation': 'translate', 'target_instance_id': 1,
            'coordinate_frame': 'drawing', 'parameters': {'dx_mm': 1000, 'dy_mm': 0}}
rewritten = resolve_incremental_followup(source_text, previous, [1])
out['followup_compound_translation'] = {
    'source': source_text, 'rewritten': rewritten,
    'direct_parse': parse_incremental_edit(source_text + ' 图形'),
    'rewritten_parse': parse_incremental_edit(rewritten),
    'previous': previous}

path = Path('.local-dev/code-capability-audit-20261125/phase4-probes.json')
path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({key: len(value) if isinstance(value, list) else 'recorded'
                  for key, value in out.items()}))
