"""Offline frozen-source comparison of tool contracts, not a live model score."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import sys


def verify(source_zip=None):
    if source_zip is not None:
        sys.path.insert(0, str(source_zip.resolve()))
    from app import cad_construction as construction
    from app.cad_shared_points import resolve_shared_points
    from pydantic import ValidationError
    fixtures = runpy.run_path(str(Path(__file__).resolve().parents[1]/'tests/test_cad_tool_contract_handoff.py'))
    arch = fixtures['arch_plan']()
    raw = {**arch, 'assertions': []}
    geometry = construction.execute_construction_plan(raw)['geometries']
    outcomes = {}
    def probe(name, function):
        try:
            function()
            outcomes[name] = {'passed': True}
        except (construction.ConstructionPlanError, ValidationError) as error:
            outcomes[name] = {'passed': False, 'error_type': type(error).__name__,
                              'code': getattr(error, 'code', 'schema_validation_failed'), 'message': str(error)[:300]}
    def composite():
        assertion = construction.ClosedAssertion(kind='closed', assertion_id='closure', target_ref='existing-selection')
        construction._run_single_assertion([assertion], geometry, {'existing-selection': [g['id'] for g in geometry]}, 1000)
    probe('same_native_geometry_closed_assertion', composite)
    from app.cad_path_relation_acceptance import assemble_closed_boundary
    probe('existing_source_boundary_measurement', lambda: assemble_closed_boundary(geometry))
    probe('explicit_assembly_reference', lambda: construction.execute_construction_plan(arch))
    for kind in ('line', 'arc', 'polyline'):
        probe('endpoint_relation_'+kind, lambda kind=kind: construction.execute_construction_plan(fixtures['endpoint_plan'](kind, 'start', 'end', 'm')))
    shared = resolve_shared_points({'shared_points': {'join': {'x': '2*cos(pi/6)', 'y': '2*sin(pi/6)'}},
                                    'steps': [{'end': {'x': '@join.x', 'y': '@join.y'}},
                                              {'start': {'x': '@join.x', 'y': '@join.y'}}]})
    outcomes['existing_shared_point_equality'] = {'passed': shared['steps'][0]['end'] == shared['steps'][1]['start']}
    # Controls prove support was not obtained by weakening real geometry checks.
    wrong = fixtures['arch_plan']();wrong['assertions'] = []
    wrong['steps'][3]['start']['y'] += .01
    wrong_geometry = construction.execute_construction_plan(wrong)['geometries']
    def gap():
        assertion = construction.ClosedAssertion(kind='closed', assertion_id='gap', target_ref='selection')
        construction._run_single_assertion([assertion], wrong_geometry, {'selection': [g['id'] for g in wrong_geometry]}, 1000)
    probe('gapped_boundary_accepted_negative_control', gap)
    return {'scope': 'Deterministic contract probes; no LLM, no formal delivery score',
            'construction_module': construction.__file__,
            'source_zip_sha256': hashlib.sha256(source_zip.read_bytes()).hexdigest() if source_zip else None,
            'outcomes': outcomes}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-zip', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.source_zip)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
