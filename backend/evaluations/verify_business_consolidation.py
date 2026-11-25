"""Capture public business-validation behavior for before/after comparison."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
def dump(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def worker(output):
    from app.cad_construction import execute_construction_plan
    from app.cad_rectangle_acceptance import verify_single_rectangle
    from app.cad_primitive_layout_acceptance import verify_primitive_layout
    from app.cad_path_relation_acceptance import verify_path_relations
    from app.cad_symmetric_divider_acceptance import verify_symmetric_divider_source
    from app.cad_source_acceptance import verify_final_source_contract,verify_scoped_primitives
    from app.drawing_store import _geometry_points
    cases=[]
    rectangle={'id':1,'type':'polyline','closed':True,'vertices':[
        {'x':0,'y':0},{'x':4000,'y':0},{'x':4000,'y':2000},{'x':0,'y':2000}]}
    for damage in ['normal','reversed','subdivided','open','crossed','bulge','wrong_size','nan','inf']:
        geometry=deepcopy(rectangle)
        if damage=='reversed':geometry['vertices'].reverse()
        elif damage=='subdivided':geometry['vertices'].insert(1,{'x':2000,'y':0})
        elif damage=='open':geometry['closed']=False
        elif damage=='crossed':geometry['vertices'][1],geometry['vertices'][2]=geometry['vertices'][2],geometry['vertices'][1]
        elif damage=='bulge':geometry['vertices'][0]['bulge']=.2
        elif damage=='wrong_size':geometry['vertices'][1]['x']+=100
        elif damage in {'nan','inf'}:geometry['vertices'][0]['x']=float(damage)
        for suffix,source in [('known','画一个矩形，宽4米高2米'),('unknown','画一个矩形，宽4米高2米，添加红色文字')]:
            cases.append(('rectangle-'+damage+'-'+suffix,verify_single_rectangle,source,[geometry]))
    row=json.loads((ROOT/'tests/fixtures/recorded_symmetric_divider.json').read_text(encoding='utf-8'))
    original=execute_construction_plan(row['plan'])['geometries']
    for damage in ['normal','symmetric_shift','asymmetric','disconnect','same_bend','dot_size','sampled_path']:
        gs=deepcopy(original);circles=sorted([g for g in gs if g['type']=='circle'],key=lambda g:g['radius']);arcs=[g for g in gs if g['type']=='arc']
        if damage=='symmetric_shift':circles[0]['center']['y']+=100;circles[1]['center']['y']-=100
        elif damage=='asymmetric':circles[0]['center']['x']+=100
        elif damage=='disconnect':arcs[0]['center']['y']+=100
        elif damage=='same_bend':arcs[1]['start_angle']=90;arcs[1]['end_angle']=270
        elif damage=='dot_size':circles[0]['radius']*=1.2
        elif damage=='sampled_path':
            gs=[g for g in gs if g['type']!='arc']+[
                {'id':g['id'],'type':'polyline','closed':False,'vertices':[{'x':p[0]*1000,'y':p[1]*1000} for p in _geometry_points(g)]} for g in arcs]
        for fn in [verify_path_relations,verify_symmetric_divider_source,verify_final_source_contract]:
            cases.append(('divider-'+damage+'-'+fn.__name__,fn,row['original'],gs))
    for case in ['A11','C15']:
        project=json.loads((ROOT/'.local-dev/live-corpus-acjm57j_/run'/case/'projects.json').read_text(encoding='utf-8'))['projects'][0]
        variant=project['variants'][-1];gs=execute_construction_plan(variant['construction_record']['plan'])['geometries']
        source='\n'.join([project['original_prompt'],*project['requirements'].get('source_followups',[])])
        for suffix in ['known','unknown','wrong_radius']:
            geometry=deepcopy(gs)
            if suffix=='wrong_radius':next(g for g in geometry if g['type']=='circle')['radius']*=.9
            text=source+('，添加红色文字' if suffix=='unknown' else '')
            for fn in [verify_primitive_layout,verify_final_source_contract,verify_scoped_primitives]:cases.append((case+'-'+suffix+'-'+fn.__name__,fn,text,geometry))
    results=[]
    for name,fn,source,geometry in cases:
        try:result={'returned':fn(source,deepcopy(geometry))}
        except Exception as exc:result={'exception':type(exc).__name__,'message':str(exc),'details':getattr(exc,'details',None)}
        results.append({'case':name,'result':result})
    dump(output/'results.json',results);print('Captured '+str(len(results))+' public validation cases',flush=True)

def main():
    from scripts.local_dev import isolated_environment,run
    env,state=isolated_environment('business-validation',False);env['PYTHONDONTWRITEBYTECODE']='1'
    print('OUTPUT: '+str(state),flush=True)
    code=run([sys.executable,str(Path(__file__).resolve()),'--worker',str(state)],env)
    if code==0 and len(sys.argv)>1:
        before=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'));after=json.loads((state/'results.json').read_text(encoding='utf-8'))
        a={v['case']:v['result'] for v in after}
        comparisons=[{'case':v['case'],'equal':v['result']==a.get(v['case'])} for v in before]
        dump(state/'comparison.json',comparisons);print('Equal: '+str(sum(v['equal'] for v in comparisons))+'/'+str(len(comparisons)),flush=True)
        if not all(v['equal'] for v in comparisons):return 1
    return code
if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--worker':worker(Path(sys.argv[2]))
    else:raise SystemExit(main())
