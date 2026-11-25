"""Offline replay of actual provider plans, preserving each turn's user sources."""
from collections import Counter
import hashlib
import json
from pathlib import Path
from evaluations.heart_acceptance_candidate_v4 import compare


def collect(folder):
    records=[];skipped=[];response_file=folder/'model-responses.jsonl'
    for index,line in enumerate(response_file.read_text(encoding='utf-8').splitlines(),1):
        raw=json.loads(line);turn=raw['step']
        request=json.loads((folder/f'request-{turn}.json').read_text(encoding='utf-8'))
        sources=[h['content'] for h in request.get('history',[]) if h.get('role')=='user']
        # Corpus confirmation is a fixed protocol command, not shape evidence.
        if request['message']!='确认需求并生成CAD候选，只预览，不执行小车。':sources.append(request['message'])
        source='\n'.join(sources)
        try:payload=json.loads(raw['response'])
        except (ValueError,TypeError):
            skipped.append({'response_index':index,'reason':'not_json'});continue
        if not isinstance(payload,dict) or not isinstance(payload.get('plan'),dict):
            skipped.append({'response_index':index,'reason':'no_plan'});continue
        fingerprint=hashlib.sha256(json.dumps({'source':source,'payload':payload},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        records.append({'folder':str(folder.resolve()),'response_index':index,'turn':turn,
            'source':source,'payload':payload,'fingerprint':fingerprint,
            'request_sha256':hashlib.sha256((folder/f'request-{turn}.json').read_bytes()).hexdigest(),
            'responses_sha256':hashlib.sha256(response_file.read_bytes()).hexdigest()})
    return records,skipped


def replay(folders,output):
    unique={};skipped=[]
    for folder in folders:
        rows,excluded=collect(folder);skipped.extend({'folder':str(folder),**r} for r in excluded)
        for row in rows:
            key=row['fingerprint']
            occurrence={k:row[k] for k in ('folder','response_index','turn','request_sha256','responses_sha256')}
            if key not in unique:unique[key]={'source':row['source'],'payload':row['payload'],'occurrences':[]}
            unique[key]['occurrences'].append(occurrence)
    results=[]
    for index,(key,row) in enumerate(unique.items(),1):
        try:result=compare(row['source'],row['payload'])
        except Exception as error:result={'decision':'audit_error','candidate_passed':False,'reason':str(error)}
        results.append({'fingerprint':key,'source':row['source'],'occurrences':row['occurrences'],'result':result})
        print(index,len(unique),result['decision'],flush=True)
    regressions=[r['fingerprint'] for r in results if r['result'].get('legacy_passed') and r['result']['decision']!='passed']
    report={'scope':'Historical plan replay only; not fresh model success or original session rescoring',
        'summary':dict(Counter(r['result']['decision'] for r in results)),
        'unique_plans_with_sources':len(results),'plan_occurrences':sum(len(r['occurrences']) for r in results),
        'legacy_passed_now_not_passed_v4':regressions,'skipped':skipped,'rows':results,
        'replay_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'rows','skipped'}},ensure_ascii=False))


if __name__=='__main__':
    import sys
    replay([Path(f)/'A9' for f in sys.argv[2:]],Path(sys.argv[1]))
