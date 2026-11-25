"""Labeled mutations of real geometry; measure false acceptance, not model claims."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app.cad_source_acceptance import verify_scoped_primitives


def evaluate(root,output):
    corpus=json.loads((Path(__file__).resolve().parents[2]/'evaluations/cad_product_acceptance_v1.json').read_text(encoding='utf-8'))
    results=[]
    for case in corpus['cases']:
        path=root/case['id']/'step-3.json'
        if not path.exists():continue
        variant=json.loads(path.read_text(encoding='utf-8'))['variant']
        source=variant['geometries'];objects=variant['logical_objects'];text=case['messages'][1]
        mutations=[]
        gs=deepcopy(source)
        extra=deepcopy(source[0]);extra['id']=max(g['id'] for g in gs)+1
        gs.append(extra)
        extra_objects=deepcopy(objects)
        extra_objects.append({'object_id':'unexpected-extra','geometry_refs':[extra['id']],
            'assembly_id':'unexpected','assembly_label':'多余部件'})
        mutations.append(('extra-component-partial-inventory',gs,extra_objects))
        mutations.append(('extra-component-complete-inventory',gs,extra_objects))
        for i,g in enumerate(source):
            gs=deepcopy(source);gs.pop(i);mutations.append((f'missing-{i}',gs,objects))
            gs=deepcopy(source);gs[i]['selected']=False;mutations.append((f'hidden-{i}',gs,objects))
            gs=deepcopy(source)
            points=[gs[i][k] for k in ('center','start','end') if k in gs[i]]+list(gs[i].get('vertices') or [])
            for p in points:p['x']+=100
            mutations.append((f'displaced-{i}',gs,objects))
            if 'radius' in g:
                gs=deepcopy(source);gs[i]['radius']*=2;mutations.append((f'radius-{i}',gs,objects))
            os=deepcopy(objects)
            for o in os:
                if g['id'] in o['geometry_refs']:o.pop('assembly_id',None)
            mutations.append((f'unowned-{i}',source,os))
        for name,gs,os in mutations:
            expected='review' if name=='extra-component-partial-inventory' else 'reject'
            # This is a labeled synthetic closed-inventory variant, not a change
            # to the frozen user corpus. Keep partial-inventory evidence separate.
            request_text=('完整部件清单：\n'+text) if name=='extra-component-complete-inventory' else text
            review=False
            try:
                report=verify_scoped_primitives(request_text,gs,os)
                accepted=len(report['checks'])==case['expected_preview_count']
                review=bool(report.get('review_required'))
            except ValueError:accepted=False
            visible=[g for g in gs if g.get('selected') is not False and g.get('role') not in {'reference','annotation','ignored'}]
            results.append({'case':case['id'],'mutation':name,'expected':expected,'accepted':accepted,
                'review_required':review,
                'full_corpus_gate_accepted':accepted and len(visible)==case['expected_preview_count']})
    negatives=[r for r in results if r['expected']=='reject']
    false=sum(r['accepted'] for r in negatives)
    missed_review=sum(not r['review_required'] for r in results if r['expected']=='review')
    report={'schema':'cad.negative-acceptance.v2','negative_samples':len(negatives),'false_acceptances':false,
        'partial_inventory_samples':len(results)-len(negatives),'missed_reviews':missed_review,
        'false_acceptance_rate':false/len(negatives) if negatives else None,'results':results,
        'full_corpus_gate_false_acceptances':sum(r['full_corpus_gate_accepted'] for r in results),
        'scope':'Deterministic labeled mutations of explicit scoped primitives. Not arbitrary semantic false acceptance.'}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False))
    return bool(results) and false==0 and missed_review==0


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    sys.exit(0 if evaluate(Path(a.root),Path(a.output)) else 1)
