"""Summarize one frozen corpus run without importing old hard-coded outcomes."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))


def audit(root):
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    requested=set(manifest['requested']);records=[];auxiliary=[]
    for path in sorted(root.glob('*/corpus-report.json')):
        original=json.loads(path.read_text(encoding='utf-8'))
        if path.parent.name!=original.get('case'):
            auxiliary.append(str(path.relative_to(root)))
            continue
        if original['case'] not in requested:continue
        record=dict(original);checks=record.get('checks') or []
        if record.get('kind')=='create' and record.get('candidate_step'):
            from tests.manual.run_user_cad_corpus import create_checks
            response=json.loads((path.parent/f"step-{record['candidate_step']}.json").read_text(encoding='utf-8'))
            record['original_checks']=checks
            checks=[c for c in checks if c['name']=='same_project']+create_checks(record.get('oracle_case') or record['case'],response,record['messages'])
            record['checks']=checks
            record['passed']=all(c.get('passed') for c in checks)
        failed=[c for c in checks if not c.get('passed')]
        if record.get('runner_error'):outcome='runner_error'
        elif record.get('blocked_by'):outcome='blocked_by_creation'
        elif record.get('kind')=='edit' and (not record.get('has_candidate') or any(c['name']=='new_saved_version' and not c['passed'] for c in checks)):outcome='edit_not_saved_or_clarification'
        elif not record.get('has_candidate'):outcome='no_candidate'
        elif any(c['name']=='new_saved_version' and not c['passed'] for c in checks):outcome='edit_not_saved'
        elif failed and all('review' in c['name'] or c['name'] in {'independent_semantic_acceptance','heart_visual_semantics'} for c in failed):outcome='requires_review'
        elif failed:outcome='measured_check_failed'
        else:outcome='measured_checks_passed'
        record['outcome']=outcome
        record['failed_checks']=[c['name'] for c in failed]
        record['trace_conflicts']=[]
        for step in path.parent.glob('step-*.json'):
            response=json.loads(step.read_text(encoding='utf-8'))
            plan=response.get('execution_plan') or {}
            pending=bool(response.get('pending_action'))
            clarification=bool(response.get('clarification_required') or response.get('clarification_question')
                or isinstance(response.get('clarification'),dict)
                and response['clarification'].get('status')=='clarification_required')
            if plan.get('status')=='completed' and (pending or clarification):
                record['trace_conflicts'].append({'step':step.name,'pending_action':pending,'clarification':clarification})
        records.append(record)
    app_path=root/'app-replays.json'
    app=json.loads(app_path.read_text(encoding='utf-8')) if app_path.exists() else None
    return {'schema':'cad.corpus-run-audit.v1','input_manifest':manifest,
        'complete':{r['case'] for r in records}==requested,'completed_cases':len(records),
        'requested_cases':len(requested),'outcomes':dict(Counter(r['outcome'] for r in records)),
        'auxiliary_report_paths':auxiliary,
        'trace_conflict_cases':[r['case'] for r in records if r['trace_conflicts']],
        'app_replays':app,
        'app_replay_counts':dict(Counter(app['cases'].values())) if app else {},
        'scope':['Real DeepSeek through production strategy selection; deterministic hits do not force a model call',
                 'Original prompts and bounded supplement/confirmation turns retained',
                 'Candidate presence alone is not geometric or business acceptance',
                 'Some corpus oracles remain partial; review outcomes are not passes',
                 'App response replay and installed APK are separate acceptance levels'],
        'records':records}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);args=parser.parse_args()
    root=Path(args.root);report=audit(root)
    (root/'run-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('complete','completed_cases','requested_cases','outcomes','trace_conflict_cases')},ensure_ascii=False))
