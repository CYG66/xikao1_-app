"""Record phase-five manual reading and verify unchanged baseline sources."""
import hashlib
import json
from pathlib import Path

root = Path.cwd()
audit = root / '.local-dev/code-capability-audit-20261125'
baseline = []
for name in ('inventory.json', 'root-entrypoints.json'):
    baseline += json.loads((audit / name).read_text(encoding='utf-8-sig'))
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


full = [record('app/' + name + '.py') for name in (
    'logical_topology', 'spatial_partition', 'cad_revision', 'cad_candidate_state',
    'cad_plan_references', 'cad_candidate_orchestrator', 'cad_project_candidates')]
ledger = {'date': '2026-11-25', 'phase': 5,
    'meaning': 'Human reading of tool-presented source, including rereads; not '
               'whole-repository completion or HTTP/hardware delivery proof.',
    'full_modules_completed': full, 'production_module_lines': sum(r['lines'] for r in full),
    'full_test_files_read': [record('tests/test_logical_topology.py')],
    'partial_modules': [record('app/agent_service.py', [[7411, 7900]]),
                        record('app/creative_projects.py', [[451, 540], [851, 935]])],
    'new_evidence': ['phase5-probes.json', 'phase5-integrity.json'],
    'prior_reading_ledgers_preserved': True, 'whole_repository_manual_read_complete': False,
    'remaining': ['agent_service.py remaining branches', 'ros_adapter.py remaining branches',
                  'other partially/unread production, tools, evaluations and test files']}
integrity = {'date': '2026-11-25', 'baseline_file_count': len(baseline),
    'production_python_file_count': sum(i['file'].replace('\\', '/').startswith('app/') for i in baseline),
    'changed_files': changed, 'missing_files': missing,
    'meaning': 'Existence and hash verification only; not manual reading completion.'}
for name, value in (('manual-reading-log-phase5.json', ledger), ('phase5-integrity.json', integrity)):
    (audit / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'integrity': integrity, 'production_lines': ledger['production_module_lines'],
                  'test_lines': ledger['full_test_files_read'][0]['lines']}))
assert len(baseline) == 471 and not changed and not missing
