"""In-memory merge feasibility probes; never rewrite production modules."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import sys
from functools import wraps

ROOT=Path(__file__).resolve().parents[1]
def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def source_hashes():return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'app').rglob('*.py')}
def capture(call):
    try:return {'returned':call()}
    except Exception as exc:return {'exception':type(exc).__name__,'message':str(exc),'details':getattr(exc,'details',None)}

def worker(output):
    from app.cad_construction_interpreter import interpret_construction_request
    targets=[('cad_symmetric_divider_acceptance','verify_symmetric_divider_source'),
             ('cad_radial_attachment_acceptance','verify_radial_attachment_source'),
             ('cad_repetition_acceptance','verify_repetition_requirements'),
             ('cad_projection_acceptance','verify_projection_requirements')]
    originals={(module,name):getattr(importlib.import_module('app.'+module),name) for module,name in targets}
    cases=[]
    for filename in ['recorded_symmetric_divider.json','recorded_radial_attachments.json']:
        row=json.loads((ROOT/'tests/fixtures'/filename).read_text(encoding='utf-8'))
        cases.append({'label':filename,'source':'\n'.join([row['original'],*row.get('followups',[])]),'plan':row['plan']})
    rows=json.loads((ROOT/'tests/fixtures/recorded_source_proof_gaps.json').read_text(encoding='utf-8'))['rows']
    cases.extend({'label':r['case'],'source':r['source'],'plan':r['plan']} for r in rows)
    expanded=[]
    for case in cases:
        expanded.append(case)
        expanded.append({**case,'label':case['label']+'-unknown','source':case['source']+'，另外绘制红色文字'})
        wrong=deepcopy(case);wrong['label']+='-wrong-dimension'
        first=wrong['plan']['steps'][0]
        if 'radius' in first:first['radius']*=.9
        elif 'end' in first:first['end']['x']+=.2
        elif 'x_expression' in first:first['x_expression']='0.9*('+first['x_expression']+')'
        expanded.append(wrong)
    results=[];full_results=[]
    for case in expanded:
        observations=[]
        for memoized in (False,True):
            cache={};counts={};hits={}
            for key,original in originals.items():
                def make_wrapper(key,original):
                    @wraps(original)
                    def wrapped(*args,**kwargs):
                        owner=kwargs.get('evidence_context')
                        semantic_kwargs={k:v for k,v in kwargs.items() if k!='evidence_context'}
                        digest=hashlib.sha256(json.dumps([args,semantic_kwargs],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                        cache_key=(key,digest,id(owner) if owner is not None else None)
                        if memoized and cache_key in cache:
                            hits[key]=hits.get(key,0)+1
                            return deepcopy(cache[cache_key])
                        counts[key]=counts.get(key,0)+1
                        result=original(*args,**kwargs)
                        if memoized:cache[cache_key]=deepcopy(result)
                        return result
                    return wrapped
                setattr(importlib.import_module('app.'+key[0]),key[1],make_wrapper(key,original))
            try:
                source=case['source'];plan=deepcopy(case['plan'])
                result=capture(lambda:interpret_construction_request(source,lambda *_:{
                    'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
                    'plan':plan,'confidence':.99,'evidence_text':[source],'assumptions':[]},force_structured_model=True))
                observations.append({'result':result,'raw_calls':{'.'.join(k):v for k,v in counts.items()},
                                     'cache_hits':{'.'.join(k):v for k,v in hits.items()}})
            finally:
                for key,original in originals.items():setattr(importlib.import_module('app.'+key[0]),key[1],original)
        results.append({'case':case['label'],'entire_result_equal':observations[0]['result']==observations[1]['result'],
            'baseline_calls':observations[0]['raw_calls'],'reuse_calls':observations[1]['raw_calls'],
            'reuse_hits':observations[1]['cache_hits'],
            'status':observations[0]['result'].get('returned',{}).get('status')})
        full_results.append({'case':case['label'],'result':observations[0]['result']})
    dump(output/'validator-reuse-equivalence.json',results)
    dump(output/'full-results.json',full_results)
    # Verify the prototype's scope and ownership rules explicitly. This
    # remains local to this worker and is never installed in production.
    cache.clear();counts.clear();hits.clear()
    key=('cad_radial_attachment_acceptance','verify_radial_attachment_source')
    wrapped=make_wrapper(key,originals[key])
    row=json.loads((ROOT/'tests/fixtures/recorded_radial_attachments.json').read_text(encoding='utf-8'))

    divider=json.loads((ROOT/'tests/fixtures/recorded_symmetric_divider.json').read_text(encoding='utf-8'))
    from app.cad_construction import execute_construction_plan,construction_geometry_bounds
    geo=execute_construction_plan(row['plan'])['geometries'];text=row['original']
    first=wrapped(text,geo);first['checks'][0]['status']='failed'
    again=wrapped(text,geo)
    damaged=deepcopy(geo);damaged[0]['radius']*=.9
    damaged_result=capture(lambda:wrapped(text,damaged))
    changed_source=wrapped(text+'，增加红色文字',geo)
    before_new_request=counts[key];cache.clear();wrapped(text,geo)
    dump(output/'reuse-isolation-checks.json',{
        'returned_evidence_is_not_shared_mutable_state':again['checks'][0]['status']=='passed',
        'changed_geometry_is_revalidated':bool(damaged_result.get('exception')),
        'changed_source_does_not_receive_complete_proof':changed_source['coverage']!='complete',
        'next_request_recomputes':counts[key]==before_new_request+1})
    from app.cad_path_relation_acceptance import verify_path_relations
    from app.cad_symmetric_divider_acceptance import verify_symmetric_divider_source
    geometry=execute_construction_plan(divider['plan'])['geometries']
    pairs=[]
    for name,geometries in [('recorded',geometry),('symmetric-dot-shift',deepcopy(geometry))]:
        if name=='symmetric-dot-shift':
            dots=sorted([g for g in geometries if g['type']=='circle'],key=lambda g:g['radius'])[:2]
            dots[0]['center']['y']+=100;dots[1]['center']['y']-=100
        source=divider['original']
        pairs.append({'case':name,'path_validator':capture(lambda:verify_path_relations(source,geometries)),
                      'native_divider_validator':capture(lambda:verify_symmetric_divider_source(source,geometries))})
    dump(output/'divider-contract-differences.json',pairs)
    from app.cad_target_resolver import _bounds
    arc={'id':1,'type':'arc','center':{'x':0,'y':0},'radius':1000,'start_angle':0,'end_angle':90}
    dump(output/'bounds-contract-differences.json',{'input':arc,'exact':construction_geometry_bounds([arc]),'selector_approximate':_bounds([arc])})

    from app.cad_assertions import _fingerprint as assertions_hash
    from app.cad_edit_preview import _fingerprint as preview_hash
    from app.cad_edit_gate import geometry_fingerprint,geometry_entity_fingerprint
    from app.cad_local_repair import fingerprint
    functions=[assertions_hash,preview_hash,geometry_fingerprint,geometry_entity_fingerprint,fingerprint]
    values=[None,True,False,0,1,1.0,-0.0,'中文',[],{},float('nan'),float('inf'),{'标签':'爱心','x':1.0}]
    values += [{'id':i,'center':{'x':i/3,'y':-i},'label':'图元','vertices':[{'x':i,'y':i*.2}]} for i in range(100)]
    hashes=[{'sample':i,'all_equal':all(capture(lambda f=f:f(value))==capture(lambda:assertions_hash(value)) for f in functions)} for i,value in enumerate(values)]
    dump(output/'fingerprint-equivalence.json',hashes)
    from evaluations.audit_current_duplication import scan
    unit_checks=[]
    for table in scan()['unit_tables']:
        values=table['values'];scale=values['米']
        unit_checks.append({'file':table['file'],'line':table['line'],
            'target_scale':scale,'relative_factors_consistent':all(abs(values[u]/scale-expected)<1e-12
                for u,expected in [('毫米',.001),('厘米',.01),('米',1)])})
    dump(output/'unit-factor-consistency.json',unit_checks)
    print(json.dumps({'validator_cases':len(results),'entire_results_equal':sum(r['entire_result_equal'] for r in results),
        'fingerprint_samples':len(hashes),'fingerprint_equivalent':all(r['all_equal'] for r in hashes)},ensure_ascii=False),flush=True)

def main():
    from scripts.local_dev import isolated_environment,run
    env,state=isolated_environment('merge-feasibility',False);env['PYTHONDONTWRITEBYTECODE']='1'
    before=source_hashes();print('OUTPUT: '+str(state),flush=True)
    code=run([sys.executable,str(Path(__file__).resolve()),'--worker',str(state)],env)
    dump(state/'integrity.json',{'app_source_unchanged':before==source_hashes(),'worker_exit_code':code,'real_model_calls':0})
    return code
if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--worker':worker(Path(sys.argv[2]))
    else:raise SystemExit(main())
