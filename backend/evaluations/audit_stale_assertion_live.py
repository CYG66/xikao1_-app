"""Read-only integrity checks for the final six exposed regression trials."""
import hashlib
import json
from pathlib import Path
import sys

from evaluations import production_contract_pilot as base
from scripts.local_dev import ROOT


def audit(folder):
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    manifest=read(folder/'targeted-manifest.json');rows=read(folder/'results.json');ledger=read(folder/'budget.json')
    assert len(rows)==6 and len({r['trial'] for r in rows})==6
    assert base.tree_hashes(ROOT/'app')==manifest['source_files']==base.tree_hashes(folder/'versions/B/app')
    assert base.tree_hashes(folder/'versions/B')==manifest['staged_files']
    assert hashlib.sha256((ROOT/'evaluations/stale_assertion_live_check.py').read_bytes()).hexdigest()==manifest['runner_sha256']
    assert not ledger['pending'] and not ledger['stopped']
    usage=[u for row in rows for u in row['usage']]
    ids=[u['request_id'] for u in usage];responses=[]
    reserved=[e for e in ledger['events'] if e['event']=='reserved'];settled=[e for e in ledger['events'] if e['event']=='settled']
    assert len(ids)==len(set(ids))==len(reserved)==len(settled)==ledger['used']['requests']
    assert set(ids)=={e['request_id'] for e in settled}=={e['request_id'] for e in reserved}
    assert sum(u['usage']['prompt_tokens'] for u in usage)==ledger['used']['input_tokens']
    assert sum(u['usage']['completion_tokens'] for u in usage)==ledger['used']['output_tokens']
    assert abs(sum(e['cost_usd'] for e in settled)-ledger['used']['cost_usd'])<1e-9
    failures=[]
    for row in rows:
        trial=folder/row['trial'];case=next(c for c in manifest['cases'] if c['id']==row['case'])
        allowed={case['text']+'只生成预览，不执行小车。',base.CONFIRM}
        reqs=list(trial.glob('api-request-*.json'));replies=list(trial.glob('api-response-*.json'))
        assert len(reqs)==len(replies)==row['requests']
        assert all(read(p)['model']=='deepseek-flash' for p in reqs)
        responses.extend(read(p)['id'] for p in replies)
        for p in trial.glob('request-*.json'):
            body=read(p)
            assert body['message'] in allowed if 'message' in body else body.get('action_id') and body.get('approved') is True
        if not row['passed']:
            errors=[json.loads(line) for line in (trial/'audit.jsonl').read_text(encoding='utf-8').splitlines()]
            failures.append({'trial':row['trial'],'last_message':row['last_message'],
                'audit_failures':[e for e in errors if e.get('ok') is False],'error':row['error']})
    assert len(responses)==len(set(responses))==len(ids)
    result={'source_unchanged':True,'trials':6,'usage':ledger['used'],'all_ids_unique':True,
            'app_digest':hashlib.sha256(json.dumps(manifest['source_files'],sort_keys=True).encode()).hexdigest(),
            'failures':failures}
    base.dump(folder/'targeted-integrity-audit.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':audit(Path(sys.argv[1]))
