"""Read-only integrity audit of internal transfer cases, each repeated twice."""
import hashlib
import json
from pathlib import Path
import sys
from evaluations import production_contract_pilot as base
from scripts.local_dev import ROOT


def audit(root):
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    m=read(root/'holdout-manifest.json');rows=read(root/'results.json');book=read(root/'budget.json')
    assert len(rows)==2*len(m['cases']) and {(r['case'],r['repeat'],r['arm']) for r in rows}=={(c['id'],i,'B') for c in m['cases'] for i in (1,2)}
    assert base.tree_hashes(ROOT/'app')==m['source_files']==base.tree_hashes(Path(m['frozen_source'])/'app')==base.tree_hashes(root/'versions/B/app')
    assert base.tree_hashes(root/'versions/B')==m['staged_files']
    for name,digest in m['hashes'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
    assert not book['pending'] and not book['stopped']
    usage=[u for r in rows for u in r['usage']];ids=[u['request_id'] for u in usage];response_ids=[]
    reserved=[e for e in book['events'] if e['event']=='reserved'];settled=[e for e in book['events'] if e['event']=='settled']
    assert len(ids)==len(set(ids))==len(reserved)==len(settled)==book['used']['requests']
    assert set(ids)=={e['request_id'] for e in reserved}=={e['request_id'] for e in settled}
    assert sum(u['usage']['prompt_tokens'] for u in usage)==book['used']['input_tokens']
    assert sum(u['usage']['completion_tokens'] for u in usage)==book['used']['output_tokens']
    assert abs(sum(e['cost_usd'] for e in settled)-book['used']['cost_usd'])<1e-9
    failures=[]
    for r in rows:
        f=root/r['trial'];case=next(c for c in m['cases'] if c['id']==r['case'])
        allowed={case['text']+'只生成预览，不执行小车。',base.CONFIRM}
        req=list(f.glob('api-request-*.json'));replies=list(f.glob('api-response-*.json'))
        assert len(req)==len(replies)==r['requests']
        assert all(read(p)['model']=='deepseek-flash' for p in req)
        response_ids.extend(read(p)['id'] for p in replies)
        steps=[]
        for p in sorted(f.glob('request-*.json')):
            b=read(p)
            assert b['message'] in allowed if 'message' in b else b.get('action_id') and b.get('approved') is True
        for p in sorted(f.glob('step-*.json')):
            d=read(p);steps.append({k:d.get(k) for k in ('ok','message','error_code','project_id')})
        if not r['passed']:
            errors=[json.loads(line) for line in (f/'audit.jsonl').read_text(encoding='utf-8').splitlines()] if (f/'audit.jsonl').exists() else []
            failures.append({'trial':r['trial'],'category':r['failure_category'],'steps':steps,
                             'audit_failures':[e for e in errors if e.get('ok') is False],
                             'variants':r['saved_variants'],'runner_error':r['error']})
    assert len(response_ids)==len(set(response_ids))==len(ids)
    report={'source_unchanged':True,'app_files':len(m['source_files']),
        'app_digest':hashlib.sha256(json.dumps(m['source_files'],sort_keys=True).encode()).hexdigest(),
        'first_turn':sum(r['first_turn_passed'] for r in rows),'formal':sum(r['passed'] for r in rows),
        'stable_cases':[c['id'] for c in m['cases'] if all(r['passed'] for r in rows if r['case']==c['id'])],
        'usage':book['used'],'failures':failures}
    base.dump(root/'holdout-integrity-audit.json',report)
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':audit(Path(sys.argv[1]))
