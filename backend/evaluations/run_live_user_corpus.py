"""Fresh DeepSeek corpus run through the current streaming/confirmation handlers.

Reuses frozen corpus oracles without changing production CAD behavior. Raw
legacy checks and formal candidate acceptance are both reported explicitly.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import traceback
import time

from scripts.local_dev import ROOT, isolated_environment, run


def dump(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def load_key():
    if os.environ.get('DEEPSEEK_API_KEY','').strip():return
    credential=ROOT/'.local-ai-test/deepseek-api-key.clixml'
    if not credential.exists():raise RuntimeError('DEEPSEEK_API_KEY or local credential is required')
    command="$s=Import-Clixml -LiteralPath '"+str(credential).replace("'","''")+"'; [Console]::Write(([System.Net.NetworkCredential]::new('', $s)).Password)"
    value=subprocess.check_output(['powershell','-NoProfile','-NonInteractive','-Command',command],text=True).strip()
    if not value or value=='System.Security.SecureString':raise RuntimeError('Local credential could not be decoded')
    os.environ['DEEPSEEK_API_KEY']=value


def characterize(case,report,output):
    from app.cad_candidate_state import candidate_is_accepted
    folder=output/case
    steps=sorted(folder.glob('step-*.json'),key=lambda p:int(p.stem.split('-')[-1]))
    response=json.loads(steps[-1].read_text(encoding='utf-8')) if steps else {}
    store_path=folder/'projects.json'
    projects=json.loads(store_path.read_text(encoding='utf-8')).get('projects',[]) if store_path.exists() else []
    variants=[v for p in projects for v in p.get('variants',[])]
    variant=response.get('variant') or {}
    if not variant and isinstance(response.get('project'),dict):
        candidates=response['project'].get('variants') or []
        variant=candidates[-1] if candidates else {}
    # Edit returns may already satisfy the requested relation; in that case
    # use the retained source version named by the real production response.
    if not variant and response.get('cad_edit_outcome')=='already_satisfied':
        variant=next((v for v in variants if v['id']==response.get('source_variant_id')), {})
    accepted=candidate_is_accepted(variant)
    checks=report.get('checks') or []
    # This legacy entry is a constant manual-review marker, not a geometric
    # test. Keep it in raw results; report it separately in the formal score.
    markers=[c for c in checks if c['name']=='template_semantics_review']
    substantive=[c for c in checks if c['name']!='template_semantics_review']
    if report.get('blocked_by'):category='blocked_by_generation'
    elif report.get('runner_error'):category='runner_error'
    elif accepted and substantive and all(c['passed'] for c in substantive):category='passed'
    elif variant and not accepted:category='review_required_candidate'
    elif variant:category='independent_check_failed'
    elif any((v.get('acceptance_summary') or {}).get('status')=='review_required' for v in variants):category='review_required_draft'
    elif any(token in str(response.get('message') or '') for token in ('补充','请提供','请说明','请确认','尺寸','参数','不支持')):category='clarification_or_no_delivery'
    else:category='no_delivery'
    return {**report,'legacy_passed':bool(report.get('passed')),'category':category,
            'formal_passed':category=='passed','accepted_candidate':accepted,
            'manual_review_markers':markers,'failed_checks':[c for c in substantive if not c['passed']],
            'last_message':response.get('message'),'last_response':str(steps[-1]) if steps else None,
            'acceptance_summary':variant.get('acceptance_summary'),
            'stored_candidate_summaries':[{'id':v.get('id'),'acceptance_summary':v.get('acceptance_summary')} for v in variants]}


def worker(corpus_path,output,cases=None,shadow_heart=False,resume=False):
    sys.path.insert(0,str(ROOT/'tests/manual'))
    from tests.manual import run_user_cad_corpus as corpus_runner
    from eval_budget_store import BudgetLedger
    raw=corpus_path.read_bytes()
    corpus=dict(re.findall(r'^\| (?:⭐)?([ABCD]\d+) \| ([^|]+) \|',raw.decode('utf-8'),re.M))
    if len(corpus)!=70:raise ValueError(f'Expected exactly 70 prompts, got {len(corpus)}')
    wanted=set(cases or corpus)
    unknown=wanted-set(corpus)
    if unknown:raise ValueError(f'Unknown corpus cases: {sorted(unknown)}')
    aliases,bases=corpus_runner.resolve_corpus_setup(corpus,wanted)
    needed=wanted|set(bases.values())
    code=hashlib.sha256()
    for path in sorted((ROOT/'app').rglob('*.py')):
        code.update(path.relative_to(ROOT).as_posix().encode());code.update(path.read_bytes())
    manifest={'started_utc':datetime.now(timezone.utc).isoformat(),
        'backend':str(ROOT),'python':sys.executable,'source':str(corpus_path),
        'source_sha256':hashlib.sha256(raw).hexdigest(),'backend_code_sha256':code.hexdigest(),
        'model_configuration':{key:os.environ[key] for key in ('DEEPSEEK_MODEL','DEEPSEEK_BASE_MODEL','DEEPSEEK_ADVANCED_MODEL','DEEPSEEK_CAD_PLANNING_MODEL')},
        'prompts':corpus,'supplements':corpus_runner.SUPPLEMENTS,'aliases':aliases,'edit_bases':bases,
        'scope':'Real DeepSeek; current production streaming and confirmation handlers; virtual hardware; no Flutter/APK rendering',
        'protocol':'Original prompts, existing fixed supplements, existing confirmation; no historical plans or synthetic seed geometry',
        'requested_cases':sorted(wanted),'workers':1,'shadow_heart_v5':shadow_heart,
        'legacy_runner_sha256':hashlib.sha256(Path(corpus_runner.__file__).read_bytes()).hexdigest()}
    if resume:
        prior=json.loads((output/'manifest.json').read_text(encoding='utf-8'))
        for key in ('backend_code_sha256','source_sha256','model_configuration','prompts','supplements','aliases','edit_bases','requested_cases','shadow_heart_v5','legacy_runner_sha256'):
            if prior[key]!=manifest[key]:raise ValueError('Resume mismatch: '+key)
    else:dump(output/'manifest.json',manifest)
    ledger=BudgetLedger(os.environ['P12_EVAL_BUDGET_PATH'])
    reports={};detailed={};shadow_reports=[]
    if resume:
        saved=json.loads((output/'summary.json').read_text(encoding='utf-8'))
        for row in saved['reports']:
            case=row['case'];detailed[case]=row
            reports[case]=json.loads((output/case/'corpus-report.json').read_text(encoding='utf-8'))
        shadow_reports=json.loads((output/'heart-shadow-summary.json').read_text(encoding='utf-8'))['cases'] if shadow_heart else []
    order=[c for c in corpus if c in needed and c not in corpus_runner.BASE]+[c for c in corpus if c in needed and c in corpus_runner.BASE]
    for case in order:
        if case in detailed:continue
        if ledger.snapshot().get('stopped'):
            raise RuntimeError('Evaluation ledger stopped; see budget.json. Remaining cases were not executed.')
        print('START '+case,flush=True)
        formal_started=time.perf_counter()
        try:
            report=(corpus_runner.make_creation(case,corpus[case].strip(),output,aliases[case])
                    if case not in corpus_runner.BASE else
                    corpus_runner.make_edit(case,corpus[case].strip(),output,reports,bases[case]))
        except Exception as exc:
            report={'case':case,'kind':'edit' if case in corpus_runner.BASE else 'create',
                    'passed':False,'runner_error':str(exc),'traceback':traceback.format_exc()}
            dump(output/case/'corpus-report.json',report)
        reports[case]=report
        interrupted_usage=output/'interrupted-evidence'/case/'model-usage.jsonl'
        if resume and interrupted_usage.exists():
            current=output/case/'model-usage.jsonl'
            current.write_text(interrupted_usage.read_text(encoding='utf-8')+(current.read_text(encoding='utf-8') if current.exists() else ''),encoding='utf-8')
        detailed[case]=characterize(case,report,output)
        dump(output/case/'result.json',detailed[case])
        if shadow_heart:
            from evaluations.live_heart_shadow import sidecar
            budget_before=ledger.snapshot().get('used')
            shadow=sidecar(output/case,(time.perf_counter()-formal_started)*1000)
            shadow['budget_usage_unchanged']=budget_before==ledger.snapshot().get('used')
            dump(output/case/'heart-shadow-sidecar.json',shadow)
            shadow_reports.append({'case':case,**shadow})
            dump(output/'heart-shadow-summary.json',{'scope':'Separate post-delivery shadow audit; not a corpus score',
                'cases':shadow_reports})
            print(json.dumps({'case':case,'shadow':shadow['status'],'formal_files_unchanged':shadow['formal_files_unchanged'],
                'budget_usage_unchanged':shadow['budget_usage_unchanged']},ensure_ascii=False),flush=True)
        result={'completed':len(detailed),'requested':len(needed),
                'formal_passed':sum(r['formal_passed'] for r in detailed.values()),
                'legacy_passed':sum(r['legacy_passed'] for r in detailed.values()),
                'categories':dict(Counter(r['category'] for r in detailed.values())),
                'reports':list(detailed.values()),'budget':ledger.snapshot().get('used')}
        dump(output/'summary.json',result)
        dump(output/'failure-details.json',[r for r in detailed.values() if not r['formal_passed']])
        print(json.dumps({'completed':len(detailed),'case':case,'category':detailed[case]['category'],
                          'formal_passed':result['formal_passed'],'legacy_passed':result['legacy_passed']},ensure_ascii=False),flush=True)
    dump(output/'completed.json',{'finished_utc':datetime.now(timezone.utc).isoformat(),'completed':len(detailed)})
    print('FINISHED '+str(output/'summary.json'),flush=True)
    return 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus',type=Path,required=True)
    parser.add_argument('--worker',action='store_true')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--cases',nargs='+',help='Run a subset plus its real creation prerequisites')
    parser.add_argument('--shadow-heart-v5',action='store_true',help='Post-delivery shadow replay; never changes scores')
    args=parser.parse_args()
    if args.worker:return worker(args.corpus.resolve(),args.output.resolve(),args.cases,args.shadow_heart_v5)
    load_key()
    env,state=isolated_environment('live-corpus',True)
    output=state/'run';output.mkdir()
    env.update(P12_EVAL_MODE='1',P12_EVAL_RUN_ID=state.name,P12_EVAL_BUDGET_PATH=str(output/'budget.json'),
               P12_MAX_REQUESTS='600',P12_MAX_INPUT_TOKENS='20000000',P12_MAX_OUTPUT_TOKENS='2000000',P12_MAX_COST_USD='5',
               PYTHONDONTWRITEBYTECODE='1')
    env.pop('P12_EVAL_MOCK_PROVIDER',None)
    print('LIVE OUTPUT: '+str(output),flush=True)
    return run([sys.executable,'-m','evaluations.run_live_user_corpus','--worker',
                '--corpus',str(args.corpus.resolve()),'--output',str(output),
                *(['--cases',*args.cases] if args.cases else []),
                *(['--shadow-heart-v5'] if args.shadow_heart_v5 else [])],env)


if __name__=='__main__':raise SystemExit(main())
