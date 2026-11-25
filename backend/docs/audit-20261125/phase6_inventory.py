"""Record reading ranges and compare source hashes with the original audit."""
import hashlib
import json
from pathlib import Path

root = Path.cwd()
audit = root / '.local-dev/code-capability-audit-20261125'
baseline = []
for name in ('inventory.json', 'root-entrypoints.json'):
    baseline.extend(json.loads((audit / name).read_text(encoding='utf-8-sig')))
changed, missing = [], []
for item in baseline:
    path = root / item['file']
    if not path.is_file():
        missing.append(item['file'])
    elif hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
        changed.append(item['file'])


def record(name, ranges=None):
    path = root / name
    lines = len(path.read_text(encoding='utf-8-sig').splitlines())
    return {'file': name, 'lines': lines,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'read_ranges_this_phase': ranges or [[1, lines]], 'full_module_complete': ranges is None}


current = [[1,613], [1258,1385], [1618,2252], [2406,2656],
           [2806,2995], [3128,4970], [11281,11566]]
ranges = list(current)
for name in ('manual-reading-log.json', 'manual-reading-log-phase4.json', 'manual-reading-log-phase5.json'):
    prior = json.loads((audit / name).read_text(encoding='utf-8-sig'))
    for item in prior.get('partial_modules', []):
        if item['file'].replace('\\', '/') == 'app/agent_service.py':
            ranges.extend(item.get('read_ranges') or item.get('read_ranges_this_phase') or [])
merged = []
for start, end in sorted(ranges):
    if merged and start <= merged[-1][1] + 1:
        merged[-1][1] = max(merged[-1][1], end)
    else:
        merged.append([start, end])
covered = sum(end - start + 1 for start, end in merged)
full = [record('app/' + name + '.py') for name in (
    'model_request_gateway', 'deepseek_transport', 'structured_usage')]
tests = [record('tests/' + name + '.py') for name in (
    'test_deepseek_transport', 'test_cad_model_strategy',
    'test_deepseek_flash_compatibility', 'test_deepseek_flash_budget')]
ledger = {'date': '2026-11-25', 'phase': 6,
    'meaning': 'Human reading of tool-presented source, including rereads. Cumulative ranges '
               'are conservatively merged from preserved ledgers; no whole-repository completion claim.',
    'partial_modules': [record('app/agent_service.py', current)],
    'service_lines_presented_this_phase_including_rereads': sum(b-a+1 for a,b in current),
    'service_cumulative_read_ranges': merged, 'service_cumulative_covered_lines': covered,
    'service_uncompleted_ranges': [[5886,7410],[7901,8260],[8471,10573],[11180,11280]],
    'full_modules_completed': full, 'production_module_lines': sum(r['lines'] for r in full),
    'full_test_files_read': tests, 'test_file_lines': sum(r['lines'] for r in tests),
    'new_evidence': ['phase6-probes.json', 'phase6-integrity.json'],
    'prior_reading_ledgers_preserved': True, 'whole_repository_manual_read_complete': False}
integrity = {'date': '2026-11-25', 'baseline_file_count': len(baseline),
    'production_python_file_count': sum(i['file'].replace('\\', '/').startswith('app/') for i in baseline),
    'changed_files': changed, 'missing_files': missing,
    'meaning': 'Existence/hash verification only; not reading or runtime correctness proof.'}
for name, value in (('manual-reading-log-phase6.json', ledger), ('phase6-integrity.json', integrity)):
    (audit / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'integrity': integrity, 'current_service_lines': ledger['service_lines_presented_this_phase_including_rereads'],
    'cumulative_service_lines': covered, 'cumulative_service_ranges': merged,
    'other_production_lines': ledger['production_module_lines'], 'test_lines': ledger['test_file_lines']}))
assert len(baseline) == 471 and not changed and not missing
assert covered == 7477
