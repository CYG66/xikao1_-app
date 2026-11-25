"""Preserve phase-four reading evidence and verify the original source baseline."""
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
            'read_ranges_this_phase': ranges or [[1, lines]],
            'full_module_complete': ranges is None}


full = [record('app/' + name + '.py') for name in (
    'incremental_cad', 'cad_selected_operations', 'cad_edit_contract', 'cad_edit_gate',
    'cad_edit_plan', 'cad_edit_intent', 'cad_edit_chain')]
test_full = [record('tests/' + name + '.py') for name in (
    'test_cad_selected_operations', 'test_mirror_offset_array_constraint')]
ledger = {'date': '2026-11-25', 'phase': 4,
    'meaning': 'Human reading of tool-presented complete source. Includes rereads; '
               'not novel-line count, whole-repository completion, or formal delivery proof.',
    'full_modules_completed': full, 'production_module_lines': sum(r['lines'] for r in full),
    'full_test_files_read': test_full, 'test_file_lines': sum(r['lines'] for r in test_full),
    'partial_modules': [record('app/agent_service.py', [[8261, 8470]]),
                        record('app/agent_http_service.py', [[371, 450]]),
                        record('tests/test_incremental_cad.py', [[494, 550]])],
    'new_evidence': ['phase4-probes.json', 'phase4-integrity.json'],
    'prior_reading_ledgers_preserved': True,
    'whole_repository_manual_read_complete': False,
    'remaining': ['agent_service.py remaining branches', 'logical_topology.py remaining branches',
        'ros_adapter.py remaining branches', 'other partially/unread production, tools, evaluation and test files']}
integrity = {'date': '2026-11-25', 'baseline_file_count': len(baseline),
    'production_python_file_count': sum(i['file'].replace('\\', '/').startswith('app/') for i in baseline),
    'changed_files': changed, 'missing_files': missing,
    'meaning': 'Existence and hash check only; not reading completion.'}
for name, value in (('manual-reading-log-phase4.json', ledger), ('phase4-integrity.json', integrity)):
    (audit / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'integrity': integrity, 'production_lines_read': ledger['production_module_lines'],
                  'test_lines_read': ledger['test_file_lines']}))
assert len(baseline) == 471 and not changed and not missing
