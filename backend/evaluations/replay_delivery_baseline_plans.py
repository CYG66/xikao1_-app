"""Exploratory offline replay of A's independently correct stored plans in B.

Never changes the live score, requests additional model output or saves CAD.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from evaluations.production_contract_pilot import dump,oracle


def replay(root):
    from app.cad_construction_interpreter import interpret_construction_request
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    manifest=read(root/'manifest.json');specs={r['id']:r for r in manifest['cases']}
    budget_before=(root/'budget.json').read_bytes();records=[]
    for trial in read(root/'results.json'):
        if trial['arm']!='A' or not trial['geometry_any_stored']:continue
        folder=root/trial['trial'];projects=read(folder/'projects.json').get('projects',[])
        good={v['id'] for v in trial['saved_variants'] if v['geometry']['passed']}
        original=next(v for p in projects for v in p.get('variants',[]) if v['id'] in good)
        plan=(original.get('construction_record') or {}).get('plan')
        record={'trial':trial['trial'],'original_variant_id':original['id'],'original_live_passed':trial['passed']}
        try:
            source=read(folder/'request-1.json')['message']
            result=interpret_construction_request(source,lambda *_:{'schema_version':'cad.construction-interpretation.v1',
                'is_construction_request':True,'confidence':.99,'evidence_text':[source],'assumptions':[],
                'plan':deepcopy(plan)},force_structured_model=True)
            geometry=(result.get('trial_result') or {}).get('geometries',[])
            record.update(status=result['status'],acceptance_summary=result.get('acceptance_summary'),
                error=result.get('construction_error') or result.get('error'),
                independent_geometry=oracle(specs[trial['case']],geometry) if geometry else None)
            record['accepted_and_geometry_passed']=bool((result.get('acceptance_summary') or {}).get('status')=='passed'
                and (record.get('independent_geometry') or {}).get('passed'))
        except Exception as exc:record.update(error=str(exc),accepted_and_geometry_passed=False)
        records.append(record)
    assert (root/'budget.json').read_bytes()==budget_before
    result={'scope':'Offline fixed-A-plan replay in current B; not new live results or score correction',
        'model_calls':0,'budget_unchanged':True,'trials':len(records),
        'accepted_and_geometry_passed':sum(r['accepted_and_geometry_passed'] for r in records),'records':records}
    dump(root/'baseline-plan-replay.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='records'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    replay(p.parse_args().run.resolve())
