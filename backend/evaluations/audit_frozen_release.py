"""Read-only post-run integrity audit; does not alter evaluation decisions."""
import hashlib
import json
from collections import Counter
from pathlib import Path

from evaluations import production_contract_pilot as base
from scripts.local_dev import ROOT


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def audit(output):
    manifest = read(output / 'release-manifest.json')
    assert (output / 'release-completed.json').exists()
    frozen = Path(manifest['frozen_source'])
    assert base.tree_hashes(ROOT / 'app') == manifest['source_files'] == base.tree_hashes(frozen / 'app')
    for field, name in [('runner_sha256', 'evaluations/frozen_release_validation.py'),
                        ('base_runner_sha256', 'evaluations/production_contract_pilot.py'),
                        ('protocol_sha256', 'docs/FROZEN_RELEASE_AND_HOLDOUT_PROTOCOL_20261124.md')]:
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == manifest[field]
    old_manifest = read(output / 'manifest.json')
    for name, digest in old_manifest['oracle_source_sha256'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    provider_ids, request_ids = [], []
    report = {'source_unchanged': True, 'app_file_count': len(manifest['source_files']),
              'app_digest': hashlib.sha256(json.dumps(manifest['source_files'], sort_keys=True).encode()).hexdigest(),
              'stages': {}}
    for stage, cases in manifest['datasets'].items():
        folder = output / stage
        stage_manifest = read(folder / 'manifest.json')
        assert cases == stage_manifest['cases']
        assert base.tree_hashes(folder / 'versions/B') == stage_manifest['versions']['B']
        assert base.tree_hashes(folder / 'versions/B/app') == manifest['source_files']
        rows, ledger = read(folder / 'results.json'), read(folder / 'budget.json')
        assert len(rows) == 24
        assert {(r['case'], r['repeat'], r['arm']) for r in rows} == {(c['id'], i, 'B') for c in cases for i in (1, 2, 3)}
        assert not ledger['pending'] and not ledger['stopped']
        usage = [u for row in rows for u in row['usage']]
        reserved = [e for e in ledger['events'] if e['event'] == 'reserved']
        settled = [e for e in ledger['events'] if e['event'] == 'settled']
        ids = {u['request_id'] for u in usage}
        assert len(ids) == len(usage) == len(reserved) == len(settled) == ledger['used']['requests']
        assert ids == {e['request_id'] for e in reserved} == {e['request_id'] for e in settled}
        assert sum(u['usage']['prompt_tokens'] for u in usage) == ledger['used']['input_tokens']
        assert sum(u['usage']['completion_tokens'] for u in usage) == ledger['used']['output_tokens']
        assert abs(sum(e['cost_usd'] for e in settled) - ledger['used']['cost_usd']) < 1e-9
        request_ids.extend(ids)
        details = []
        for row in rows:
            trial = folder / row['trial']
            case = next(c for c in cases if c['id'] == row['case'])
            allowed = {case['text'] + '只生成预览，不执行小车。', base.CONFIRM}
            requests = list(trial.glob('api-request-*.json'))
            responses = list(trial.glob('api-response-*.json'))
            assert len(requests) == len(responses) == row['requests']
            for path in requests:
                assert read(path)['model'] == 'deepseek-flash'
            for path in responses:
                payload = read(path)
                assert payload.get('id')
                provider_ids.append(payload['id'])
            steps = []
            for path in sorted(trial.glob('request-*.json')):
                payload = read(path)
                if 'message' in payload:
                    assert payload['message'] in allowed
                else:
                    assert payload.get('action_id') and payload['approved'] is True
            for path in sorted(trial.glob('step-*.json')):
                payload = read(path)
                steps.append({'file': path.name, 'ok': payload.get('ok'), 'message': payload.get('message'),
                              'error_code': payload.get('error_code'), 'api_attempted': payload.get('api_attempted')})
            errors = []
            if (trial / 'audit.jsonl').exists():
                for line in (trial / 'audit.jsonl').read_text(encoding='utf-8').splitlines():
                    entry = json.loads(line)
                    if entry.get('ok') is False:
                        errors.append({k: entry.get(k) for k in ('event', 'tool', 'message')})
            if not row['passed']:
                details.append({'trial': row['trial'], 'category': row['failure_category'],
                                'requests': row['requests'], 'runner_error': row['error'],
                                'steps': steps, 'audit_failures': errors, 'variants': row['saved_variants']})
        categories = {}
        for category in sorted({c.get('category', 'regression') for c in cases}):
            members = {c['id'] for c in cases if c.get('category', 'regression') == category}
            sample = [r for r in rows if r['case'] in members]
            categories[category] = {'trials': len(sample), 'formal': sum(r['passed'] for r in sample),
                                    'geometry': sum(r['geometry_any_stored'] for r in sample)}
        report['stages'][stage] = {
            **read(folder / 'analysis.json'), 'first_turn_passed': sum(r['first_turn_passed'] for r in rows),
            'stable_cases': [c['id'] for c in cases if all(r['passed'] for r in rows if r['case'] == c['id'])],
            'categories': categories, 'failure_counts': dict(Counter(r['failure_category'] for r in rows if not r['passed'])),
            'ledger_reserved': len(reserved), 'ledger_settled': len(settled), 'failures': details}
    assert len(set(provider_ids)) == len(provider_ids) == len(request_ids) == len(set(request_ids))
    report['all_request_ids_unique'] = True
    report['all_provider_response_ids_unique'] = True
    report['total_requests'] = len(request_ids)
    base.dump(output / 'independent-integrity-audit.json', report)
    return report


if __name__ == '__main__':
    import sys
    result = audit(Path(sys.argv[1]))
    print(json.dumps({k: v for k, v in result.items() if k != 'stages'}, ensure_ascii=False))
    for name, value in result['stages'].items():
        print(name, json.dumps({k: v for k, v in value.items() if k != 'failures'}, ensure_ascii=False))
