"""Six exposed regression trials for the final bounded-repair delta."""
from datetime import datetime, timezone
import hashlib
import json
import os
import random
import sys

from evaluations import production_contract_pilot as base
from evaluations.frozen_release_validation import holdout_oracle, holdouts
from scripts.local_dev import ROOT, isolated_environment


def main():
    from evaluations.run_live_user_corpus import load_key
    load_key();env,state=isolated_environment('stale-assertion-live',True)
    os.environ.update({k:v for k,v in env.items() if k!='PATH'})
    output=base.prepare(state)
    cases=[next(c for c in base.cases() if c['id']=='R2'),next(c for c in holdouts() if c['id']=='L2')]
    source=base.tree_hashes(ROOT/'app');staged=base.tree_hashes(output/'versions/B')
    base.dump(output/'targeted-manifest.json',{'scope':'Exposed R2/L2 regression only, 3 repeats, unchanged run_trial; not a full 48-trial retest or new holdout.',
        'frozen_utc':datetime.now(timezone.utc).isoformat(),'source_files':source,'staged_files':staged,'cases':cases,
        'runner_sha256':hashlib.sha256(__import__('pathlib').Path(__file__).read_bytes()).hexdigest()})
    sys.path.insert(0,str(ROOT/'tests/manual'))
    from eval_budget_store import BudgetLedger
    os.environ.update(P12_MAX_REQUESTS='72',P12_MAX_INPUT_TOKENS='1600000',P12_MAX_OUTPUT_TOKENS='180000',P12_MAX_COST_USD='1')
    ledger=BudgetLedger(output/'budget.json');base.oracle=holdout_oracle;rows=[];rng=random.Random(241126)
    print('TARGETED OUTPUT '+str(output),flush=True)
    for repeat in range(1,4):
        order=cases.copy();rng.shuffle(order)
        for case in order:
            entry={'case':case['id'],'repeat':repeat,'arm':'B'}
            result=base.run_trial(output,entry,case);rows.append(result);base.dump(output/'results.json',rows)
            print(json.dumps({k:result[k] for k in ('trial','passed','failure_category','requests')},ensure_ascii=False),flush=True)
            assert not ledger.snapshot()['pending'] and not ledger.snapshot()['stopped']
    assert base.tree_hashes(ROOT/'app')==source and base.tree_hashes(output/'versions/B')==staged
    usage=[u for r in rows for u in r['usage']];book=ledger.snapshot()
    assert len(usage)==book['used']['requests']==len({u['request_id'] for u in usage})
    assert {(r['case'],r['repeat']) for r in rows}=={(c['id'],i) for c in cases for i in (1,2,3)}
    assert all(u['model']=='deepseek-flash' for u in usage)
    base.dump(output/'targeted-analysis.json',{'trials':6,'formal_passed':sum(r['passed'] for r in rows),
        'per_case':{c['id']:sum(r['passed'] for r in rows if r['case']==c['id']) for c in cases},
        'source_unchanged':True,'usage':book['used'],'finished_utc':datetime.now(timezone.utc).isoformat()})
    base.dump(output/'failure-details.json',[r for r in rows if not r['passed']])
    print('FINISHED '+(output/'targeted-analysis.json').read_text(encoding='utf-8'),flush=True)


if __name__=='__main__':main()
