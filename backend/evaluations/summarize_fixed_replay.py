"""Compare two recorded audits without executing plans or calling a model."""
import argparse
from collections import Counter
import json
from pathlib import Path


def write_comparison(before_path, after_path):
    before = json.loads(before_path.read_text(encoding='utf-8'))
    after = json.loads(after_path.read_text(encoding='utf-8'))
    if before['inputs_sha256'] != after['inputs_sha256'] or before['chain'] != after['chain']:
        raise ValueError('Input hash and execution chain must match for comparison.')
    previous = {row['case']: row for row in before['cases']}
    if set(previous) != {row['case'] for row in after['cases']}:
        raise ValueError('Case inventories differ.')
    changes = []
    failures = []
    for row in after['cases']:
        old = previous[row['case']]
        if (old['status'], old['acceptance']) != (row['status'], row['acceptance']):
            changes.append({'case': row['case'],
                            'before': [old['status'], old['acceptance']],
                            'after': [row['status'], row['acceptance']]})
        if row['acceptance'] == 'passed':
            continue
        record = json.loads(Path(row['record']).read_text(encoding='utf-8'))
        source = record.get('source_acceptance') or {}
        proofs = {}
        for name, value in source.items():
            if isinstance(value, dict):
                proofs[name] = {key: value[key] for key in (
                    'status', 'coverage', 'review_required', 'unknown_requirements',
                    'checks', 'measurement_scope', 'unconsumed_text') if key in value}
        failures.append({
            **row, 'source_coverage': source.get('coverage', 'unknown'),
            'execution_failure_details': record.get('construction_error'),
            'failed_checks': (record.get('acceptance_summary') or {}).get('failed_checks', []),
            'source_unknown_requirements': source.get('unknown_requirements', []),
            'measurement_details': proofs,
            'geometry_validity': (record.get('acceptance_summary') or {}).get('geometry_validity'),
            'constraint_satisfaction': (record.get('acceptance_summary') or {}).get('constraint_satisfaction'),
            'diagnosis': ('执行或独立验收失败，具体错误及定位见 error 和 record。'
                          if row['status'] != 'ready' else
                          '几何已执行，但缺少完整来源覆盖证据；已有局部测量不能代替其余要求的证明。'),
        })
    counts = lambda rows: dict(Counter(row.get('acceptance') or row['status'] for row in rows))
    report = {'scope': after['scope'], 'chain': after['chain'],
              'inputs_sha256': after['inputs_sha256'],
              'before': counts(before['cases']), 'after': counts(after['cases']),
              'changes': changes, 'remaining': len(failures),
              'model_calls': 0}
    output = after_path.parent
    for name, data in (('comparison.json', report), ('failure-details.json', failures)):
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    args = parser.parse_args()
    write_comparison(args.before, args.after)
