"""Audit fixed source/plan pairs against this backend, with no model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from scripts.local_dev import ROOT, isolated_environment, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--force-structured', action='store_true')
    args = parser.parse_args()
    inputs = args.inputs.resolve()
    if not args.worker:
        env, state = isolated_environment('audit', False)
        print('Output:', state, flush=True)
        command = [sys.executable, '-m', 'evaluations.replay_fixed_plans',
                   '--inputs', str(inputs), '--worker']
        if args.force_structured:
            command.append('--force-structured')
        return run(command, env)
    import os
    from app.cad_construction_interpreter import interpret_construction_request
    data = json.loads(inputs.read_text(encoding='utf-8'))
    output = Path(os.environ['XLINE_CAD_DIR']).parent
    cases = []
    for index, row in enumerate(data['cases']):
        representative = row.get('representative_plan')
        if not representative:
            continue
        source = row['fixed_source']
        plan = representative['plan']
        result = interpret_construction_request(source, lambda *_: {
            'schema_version': 'cad.construction-interpretation.v1',
            'is_construction_request': True, 'confidence': .99,
            'evidence_text': [row['original_prompt']], 'plan': plan,
        }, force_structured_model=args.force_structured)
        record = output / f'case-{index:03d}.json'
        record.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        acceptance = result.get('acceptance_summary') or {}
        cases.append({
            'case': row['case'], 'source': source, 'status': result['status'],
            'acceptance': acceptance.get('status'), 'error': result.get('error'),
            'unknown_requirements': acceptance.get('unknown_requirements'),
            'record': str(record), 'plan_provenance': representative.get('provenance'),
        })
        print(row['case'], result['status'], acceptance.get('status'), flush=True)
    summary = {
        'scope': 'Fixed historical plans; not live corpus pass rate',
        'backend': str(ROOT), 'inputs': str(inputs),
        'inputs_sha256': hashlib.sha256(inputs.read_bytes()).hexdigest(),
        'model_calls': 0, 'cases': cases,
        'chain': 'forced_structured' if args.force_structured else 'production_rule_first',
    }
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Summary:', output / 'summary.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
