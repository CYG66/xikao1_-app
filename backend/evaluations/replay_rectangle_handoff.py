"""Replay historical plans through the current interpreter and commit gate.

Run under scripts.local_dev.isolated_environment; no model/API calls are made.
The callback supplies an unchanged historical plan, not generated geometry.
"""
import json
import os
from pathlib import Path

from app.cad_construction_interpreter import interpret_construction_request
from app.cad_construction_commit import commit_construction_interpretation
from app.creative_projects import CreativeProjectStore


def main():
    root = Path(__file__).resolve().parents[1]
    output = Path(os.environ['XLINE_CAD_DIR']).parent / 'rectangle-handoff'
    output.mkdir(parents=True, exist_ok=True)
    rows = json.loads((root / 'tests' / 'fixtures' /
                       'recorded_rectangle_handoff.json').read_text(encoding='utf-8'))
    store = CreativeProjectStore(output / 'projects.json')
    reports = []
    for row in rows:
        result = interpret_construction_request(row['source'], lambda *_: {
            'schema_version': 'cad.construction-interpretation.v1',
            'is_construction_request': True, 'confidence': .99,
            'evidence_text': [row['original']], 'plan': row['plan'],
        }, force_structured_model=True)
        (output / f'{row["case"]}-record.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        report = {
            'case': row['case'], 'source': row['source'],
            'plan_provenance': row['provenance'], 'status': result['status'],
            'acceptance_summary': result.get('acceptance_summary'),
            'source_acceptance': result.get('source_acceptance'),
            'error': result.get('error'), 'saved': False,
        }
        if result.get('acceptance_summary', {}).get('status') == 'passed':
            saved = commit_construction_interpretation(row['source'], result, store=store)
            report.update(saved=True, commit=saved)
        reports.append(report)
        print(row['case'], result['status'],
              (result.get('acceptance_summary') or {}).get('status'),
              'saved:', report['saved'])
    (output / 'summary.json').write_text(json.dumps({
        'scope': 'Historical-plan offline replay, not live 70-case success rate',
        'backend': str(root), 'model_calls': 0, 'cases': reports,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Report:', output / 'summary.json')


if __name__ == '__main__':
    main()
