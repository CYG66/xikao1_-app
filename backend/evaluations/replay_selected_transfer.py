"""Replay selected exposed transfer cases without editing their original texts."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import sys
from scripts.local_dev import ROOT, isolated_environment
from evaluations import production_contract_pilot as base
from evaluations.frozen_release_validation import holdout_oracle


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run',type=Path,required=True)
    parser.add_argument('--cases',nargs='+',required=True)
    parser.add_argument('--protocol',required=True)
    args=parser.parse_args()
    prior=args.source_run.resolve()
    old=json.loads((prior/'holdout-manifest.json').read_text(encoding='utf-8'))
    assert len(args.cases)==len(set(args.cases))
    data=[c for c in old['cases'] if c['id'] in args.cases]
    assert {c['id'] for c in data}==set(args.cases)
    from evaluations.run_live_user_corpus import load_key
    load_key()
    _,freeze=isolated_environment('selected-transfer-freeze',False)
    shutil.copytree(ROOT/'app',freeze/'app',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    frozen={'frozen_utc':datetime.now(timezone.utc).isoformat(),'source_files':base.tree_hashes(freeze/'app')}
    base.dump(freeze/'freeze.json',frozen)
    env,state=isolated_environment('selected-transfer-live',True)
    os.environ.update({k:v for k,v in env.items() if k!='PATH'})
    output=base.prepare(state);staged=base.tree_hashes(output/'versions/B')
    names=['evaluations/replay_selected_transfer.py','evaluations/production_contract_pilot.py',
        'evaluations/frozen_release_validation.py','evaluations/relation_pilot/oracle.py',
        'evaluations/relation_pilot/cases.py','evaluations/audit_transfer_holdout.py',args.protocol]
    base.dump(output/'holdout-manifest.json',{
        'scope':'Selected exposed-case regression, two repeats; not a new holdout.',
        'replay_of':str(prior),'prior_manifest_sha256':hashlib.sha256((prior/'holdout-manifest.json').read_bytes()).hexdigest(),
        'cases':data,'source_files':frozen['source_files'],'frozen_source':str(freeze),
        'source_frozen_utc':frozen['frozen_utc'],'staged_files':staged,
        'hashes':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}})
    sys.path.insert(0,str(ROOT/'tests/manual'))
    from eval_budget_store import BudgetLedger
    os.environ.update(P12_MAX_REQUESTS=str(len(data)*24),P12_MAX_INPUT_TOKENS='1600000',P12_MAX_OUTPUT_TOKENS='180000',P12_MAX_COST_USD='1')
    ledger=BudgetLedger(output/'budget.json');base.oracle=holdout_oracle;rows=[];rng=random.Random(2411242)
    print('REPLAY OUTPUT '+str(output),flush=True)
    for repeat in (1,2):
        order=data.copy();rng.shuffle(order)
        for case in order:
            row=base.run_trial(output,{'case':case['id'],'repeat':repeat,'arm':'B'},case)
            rows.append(row);base.dump(output/'results.json',rows)
            print(json.dumps({k:row[k] for k in ('trial','passed','first_turn_passed','failure_category','requests')}),flush=True)
            assert not ledger.snapshot()['pending'] and not ledger.snapshot()['stopped']
    assert base.tree_hashes(ROOT/'app')==frozen['source_files']==base.tree_hashes(freeze/'app')
    assert base.tree_hashes(output/'versions/B')==staged
    base.dump(output/'holdout-analysis.json',{'trials':len(rows),'formal_passed':sum(r['passed'] for r in rows),
        'first_turn_passed':sum(r['first_turn_passed'] for r in rows),'geometry_any_stored':sum(r['geometry_any_stored'] for r in rows),
        'per_case':{c['id']:{'formal':sum(r['passed'] for r in rows if r['case']==c['id']),
            'geometry':sum(r['geometry_any_stored'] for r in rows if r['case']==c['id'])} for c in data},
        'source_unchanged':True,'usage':ledger.snapshot()['used']})
    base.dump(output/'failure-details.json',[r for r in rows if not r['passed']])
    from evaluations.audit_transfer_holdout import audit
    audit(output)


if __name__=='__main__':main()
