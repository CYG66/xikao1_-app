"""Honest metrics from recorded runs; missing usage/cost stays unknown."""
import json
from pathlib import Path


def summarize(root,reports):
    durations=[];tokens=[];categories={};first_success=[]
    for report in reports:
        folder=Path(root)/report['case']
        for path in sorted(folder.glob('timing-*.json')):
            durations.append(json.loads(path.read_text(encoding='utf-8'))['elapsed_seconds'])
        for path in sorted(folder.glob('step-*.json')):
            result=json.loads(path.read_text(encoding='utf-8'))
            usage=result.get('usage') or {}
            if usage.get('total_tokens',0)>0:tokens.append(usage['total_tokens'])
            recovery=(result.get('construction_commit') or result.get('construction_interpretation') or {}).get('recovery')
            if recovery:
                first_success.append(recovery['attempts'][0]['status']=='ready')
                for attempt in recovery['attempts']:
                    if attempt.get('category'):categories[attempt['category']]=categories.get(attempt['category'],0)+1
    count=len(reports)
    return {'schema':'cad.acceptance-metrics.v1','case_count':count,
        'end_to_end_pass_rate':sum(bool(r['passed']) for r in reports)/count if count else None,
        'first_plan_success_rate':sum(first_success)/len(first_success) if first_success else None,
        'measured_request_count':len(durations),'total_elapsed_seconds':sum(durations) if durations else None,
        'reported_total_tokens':sum(tokens) if tokens else None,'cost':None,
        'failure_categories':categories,'omission_rate':None,'false_acceptance_rate':None,
        'limitations':['No inferred zero cost or zero omissions. Labeled negative cases are required to estimate false acceptance.']}
