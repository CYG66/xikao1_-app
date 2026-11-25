"""Secondary read-only geometry audit of failed recorded model plans.

Model assertions are removed for this diagnostic only. No model requests or
formal score changes; execution/schema failures remain explicit unknowns.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys


def main(folder):
    from app.cad_construction import execute_construction_plan
    from evaluations import production_contract_pilot as base
    from evaluations.frozen_release_validation import holdout_oracle
    manifest=json.loads((folder/'release-manifest.json').read_text(encoding='utf-8'))
    report=[]
    for stage,cases in manifest['datasets'].items():
        results=json.loads((folder/stage/'results.json').read_text(encoding='utf-8'))
        for row in results:
            if row['passed']:continue
            case=next(c for c in cases if c['id']==row['case'])
            for path in sorted((folder/stage/row['trial']).glob('api-response-*.json')):
                response=json.loads(path.read_text(encoding='utf-8'))
                try:payload=json.loads(response['choices'][0]['message']['content'])
                except (ValueError,KeyError):continue
                if not isinstance(payload,dict) or not isinstance(payload.get('plan'),dict):continue
                plan=deepcopy(payload['plan']);plan['assertions']=[]
                item={'stage':stage,'trial':row['trial'],'response':path.name,'model_assertions_removed':True}
                try:
                    result=execute_construction_plan(plan)
                    item['independent_geometry']=(base.oracle if stage=='regression' else holdout_oracle)(case,result['geometries'])
                except Exception as exc:item['execution_error']=str(exc)
                report.append(item)
    base.dump(folder/'failed-recorded-plan-geometry.json',report)
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main(Path(sys.argv[1]))
