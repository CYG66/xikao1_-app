"""Read-only exploratory failure attribution, never changes pilot scores."""
from collections import Counter
import argparse
import json
from pathlib import Path

from evaluations.production_contract_pilot import dump, oracle


def native_design(plan):
    """Read explicit line/arc design only, before production tessellation.

    No fitting, missing edge construction or inference from the expected CAD.
    This is a secondary diagnostic, never the delivered-geometry score.
    """
    if plan.get('constraints') or plan.get('free_outline_layout'):
        return None  # do not mistake a later transform for tessellation error
    scale=1000 if plan.get('units','m')=='m' else 1
    result=[]
    point=lambda p:{'x':p['x']*scale,'y':p['y']*scale}
    for step in plan.get('steps',[]):
        if step['op']!='add_composite_path':return None
        for segment in step.get('segments',[]):
            if segment['kind']=='line':
                g={'type':'line','start':point(segment['start']),'end':point(segment['end'])}
            elif segment['kind']=='arc' and not segment.get('clockwise'):
                g={'type':'arc','center':point(segment['center']),'radius':segment['radius']*scale,
                   'start_angle':segment['start_angle'],'end_angle':segment['end_angle']}
            else:return None
            result.append({'id':len(result)+1,**g})
    return result or None


def diagnose(root):
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    m=read(root/'manifest.json');specs={c['id']:c for c in m['cases']};rows=[]
    for trial in read(root/'results.json'):
        folder=root/trial['trial'];record={'trial':trial['trial'],'arm':trial['arm'],'original_passed':trial['passed'],
            'failure_category':trial['failure_category'],'audited_backend_failures':[],
            'http_failures':[],'variants':[]}
        audit=folder/'audit.jsonl'
        if audit.exists():
            record['audited_backend_failures']=[d for d in (json.loads(s) for s in audit.read_text(encoding='utf-8').splitlines())
                if d.get('ok') is False or 'failed' in str(d.get('event',''))]
        for p in sorted(folder.glob('step-*.json')):
            d=read(p)
            if d.get('ok') is False:record['http_failures'].append({'step':p.name,'message':d.get('message'),
                'failure_category':d.get('failure_category'),'error_code':d.get('error_code')})
        projects=read(folder/'projects.json').get('projects',[]) if (folder/'projects.json').exists() else []
        for project in projects:
            for variant in project.get('variants',[]):
                saved=next(v for v in trial['saved_variants'] if v['id']==variant['id'])
                construction=variant.get('construction_record') or {};plan=construction.get('plan') or {}
                source=construction.get('source_acceptance') or {}
                evidence=source.get('final_source_acceptance') or {}
                info={'id':variant['id'],'parser':construction.get('parser'),'ops':[s['op'] for s in plan.get('steps',[])],
                    'delivered_geometry':saved['geometry'],'acceptance_summary':variant.get('acceptance_summary'),
                    'source_final':evidence,'typed_references':[],
                    'endpoint_constraints':[c for c in plan.get('constraints',[]) if c['kind']=='endpoint_coincident']}
                for group in ('assertions','constraints','free_outline_layout'):
                    for item in plan.get(group,[]):
                        for key in ('target_ref','reference_ref','right_of_ref'):
                            ref=item.get(key)
                            if isinstance(ref,str) and ref.startswith(('object:','assembly:')):
                                info['typed_references'].append({'group':group,'field':key,'reference':ref})
                if not saved['geometry']['passed']:
                    try:
                        design=native_design(plan)
                        info['ideal_explicit_design_oracle']=oracle(specs[trial['case']],design) if design else None
                    except Exception as exc:info['ideal_design_diagnostic_error']=str(exc)
                record['variants'].append(info)
        rows.append(record)
    summary={}
    for arm in ('A','B'):
        group=[r for r in rows if r['arm']==arm]
        summary[arm]={
            'trials_with_audited_backend_failures':sum(bool(r['audited_backend_failures']) for r in group),
            'trials_with_geometry_correct_but_review_required':sum(any(v['delivered_geometry']['passed'] and (v['acceptance_summary'] or {}).get('status')=='review_required' for v in r['variants']) for r in group),
            'trials_with_correct_explicit_design_but_delivered_sampling_fails':sum(any((v.get('ideal_explicit_design_oracle') or {}).get('passed') for v in r['variants']) for r in group),
            'trials_with_saved_typed_references':sum(any(v['typed_references'] for v in r['variants']) for r in group),
            'trials_with_saved_endpoint_constraints':sum(any(v['endpoint_constraints'] for v in r['variants']) for r in group),
            'backend_failure_messages':dict(Counter(d.get('message','') for r in group for d in r['audited_backend_failures']))}
    report={'scope':'Exploratory attribution only, does not modify original pass/fail or budget. Categories overlap.',
            'summary':summary,'rows':rows}
    dump(root/'failure-diagnostics.json',report)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    diagnose(p.parse_args().run.resolve())
