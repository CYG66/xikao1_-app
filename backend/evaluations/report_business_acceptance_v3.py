"""Separate boundary-representation calibration; never rewrite previous scores."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from evaluations.closed_boundary_oracle_v3 import single_closed_boundary


def report(root):
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    previous=root/'business-results-v2.json'
    if not previous.exists():
        from evaluations.report_business_acceptance_v2 import report as report_v2
        report_v2(root)
    baseline=read(previous);summary=read(root/'summary.json')
    protected={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (previous,root/'summary.json',root/'manifest.json')}
    actual={r['case']:r for r in summary['reports']};rows=deepcopy(baseline['rows'])
    for row in rows:
        row['v3_passed']=row['v2_passed'];row['v3_rule_change']=None
        if row['case']!='C3':continue
        raw=actual[row['case']]
        response=read(Path(raw['last_response'])) if raw.get('last_response') else {}
        proof=single_closed_boundary((response.get('variant') or {}).get('geometries') or [])
        others=[c for c in raw.get('checks',[]) if c['name']!='single_closed_boundary']
        row['closed_boundary_proof']=proof
        if (proof['passed'] and raw.get('accepted_candidate') and response.get('ok') is True
                and others and all(c['passed'] for c in others)):
            row['v3_passed']=True
            if not row['v2_passed']:row['v3_rule_change']='single_physical_boundary_replaces_single_entity_check'
    unchanged=all(hashlib.sha256((root/name).read_bytes()).hexdigest()==value for name,value in protected.items())
    if not unchanged:raise RuntimeError('Protected score evidence changed')
    result={'schema':'cad.business-oracles.v3','scope':'Separate evaluation calibration, not a production capability increase or new live run',
        'total':len(rows),'v2_passed':baseline['v2_passed'],'v3_passed':sum(r['v3_passed'] for r in rows),
        'previous_scores_unchanged':unchanged,'source_v2_sha256':protected[previous.name],
        'source_summary_sha256':protected['summary.json'],'source_run':str(root.resolve()),
        'oracle_source_sha256':hashlib.sha256(Path(__file__).with_name('closed_boundary_oracle_v3.py').read_bytes()).hexdigest(),
        'rows':rows}
    (root/'business-results-v3.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,required=True)
    result=report(parser.parse_args().run)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False,indent=2))
