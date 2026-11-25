"""Build a conservative per-case status report from the frozen markdown corpus."""
import argparse, json, re
from pathlib import Path

def parse(path):
    rows=[]; group=None
    for line in path.read_text(encoding='utf-8').splitlines():
        m=re.match(r'\|\s*([ABCD]\d+)\s*\|\s*(.*?)\s*\|', line)
        if m:
            rows.append({'id':m.group(1),'message':m.group(2),'status':'not_run','evidence':None})
    return rows

def main():
    p=argparse.ArgumentParser(); p.add_argument('--corpus',required=True); p.add_argument('--output',required=True)
    a=p.parse_args(); rows=parse(Path(a.corpus))
    evidence={
        'house': 'evaluations/reports/cad-final-live-20261030-r2/house/validation.json',
        'heart_star': 'evaluations/reports/cad-final-live-20261030-r3/heart_star/validation.json',
        'edit_context': 'evaluations/reports/cad-edit-context-20261030-r3/context-acceptance.json',
    }
    for row in rows:
        if row['id']=='C16': row.update(status='passed', evidence=evidence['house'])
        elif row['id']=='C10': row.update(status='passed', evidence=evidence['heart_star'])
        elif row['id'] in {'B4','D1','D3'}: row.update(status='passed', evidence=evidence['edit_context'])
    grouped={k:[r for r in rows if r['id'].startswith(k)] for k in 'ABCD'}
    report={'corpus':str(Path(a.corpus).resolve()),'groups':grouped,
            'summary':{k:{s:sum(r['status']==s for r in v) for s in ('passed','clarified','failed','not_run')} for k,v in grouped.items()}}
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report['summary'],ensure_ascii=False))
if __name__=='__main__': main()
