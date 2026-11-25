"""Record manual reading ranges and verify the unchanged review baseline."""
import hashlib
import json
from pathlib import Path

root = Path.cwd()
audit = root / '.local-dev/code-capability-audit-20261125'
baseline = json.loads((audit / 'inventory.json').read_text(encoding='utf-8-sig'))
baseline += json.loads((audit / 'root-entrypoints.json').read_text(encoding='utf-8-sig'))
changed, missing = [], []
for item in baseline:
    path = root / item['file']
    if not path.is_file():
        missing.append(item['file'])
    elif hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
        changed.append(item['file'])
records = []
for name, read_now, carry in (
    ('app/cad_construction_interpreter.py', [[341, 3190]], [[1, 340], [3191, 3434]]),
    ('app/cad_construction.py', [[1, 2111]], []),
):
    path = root / name
    records.append({'file': name, 'lines': len(path.read_text(encoding='utf-8-sig').splitlines()),
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'read_ranges_this_phase': read_now, 'unchanged_prior_read_carry_forward': carry,
        'full_module_complete': True})
integrity = {'date': '2026-11-25', 'baseline_file_count': len(baseline),
    'production_python_file_count': sum(item['file'].replace('\\', '/').startswith('app/') for item in baseline),
    'changed_files': changed, 'missing_files': missing,
    'meaning': 'Hash verification only; does not establish manual reading or passing runtime paths.'}
ledger = {'date': '2026-11-25', 'phase': 3, 'prior_ledger_preserved': 'manual-reading-log.json',
    'meaning': 'Human reading of tool-presented source with unchanged-source carry-forward; '
               'not whole-repository manual completion or production delivery verification.',
    'full_modules_completed': records, 'module_lines_total': sum(r['lines'] for r in records),
    'lines_presented_this_phase_including_rereads': 4961,
    'new_evidence': ['phase3-probes.json', 'phase3-integrity.json'],
    'whole_repository_manual_read_complete': False,
    'remaining': ['agent_service.py remaining branches', 'incremental_cad.py remaining branches',
        'ros_adapter.py remaining branches', 'other partially/unread modules, tools, evaluations and tests']}
for filename, value in (('phase3-integrity.json', integrity), ('manual-reading-log-phase3.json', ledger)):
    (audit / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(integrity))
assert len(baseline) == 471 and not changed and not missing
