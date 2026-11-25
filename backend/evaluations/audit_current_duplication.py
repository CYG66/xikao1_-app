"""Static clone candidates and isolated validator-call evidence; no app edits."""
import ast
from collections import defaultdict,Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]

def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def scan():
    functions=defaultdict(list);blocks=defaultdict(list);files={};units=[];calls=[]
    for path in sorted((ROOT/'app').rglob('*.py')):
        if '__pycache__' in path.parts:continue
        rel=path.relative_to(ROOT).as_posix();raw=path.read_bytes();files[rel]=hashlib.sha256(raw).hexdigest()
        tree=ast.parse(raw.decode('utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                body=list(node.body)
                if body and isinstance(body[0],ast.Expr) and isinstance(body[0].value,ast.Constant) and isinstance(body[0].value.value,str):body=body[1:]
                if len(body)>=2 and node.end_lineno-node.lineno>=4:
                    key='\n'.join(ast.dump(s,include_attributes=False) for s in body)
                    functions[key].append({'file':rel,'function':node.name,'line':node.lineno,'end':node.end_lineno})
            for field in ('body','orelse','finalbody'):
                body=getattr(node,field,None)
                if not isinstance(body,list) or not all(isinstance(s,ast.stmt) for s in body):continue
                for i in range(max(0,len(body)-3)):
                    chunk=body[i:i+4]
                    if chunk[-1].end_lineno-chunk[0].lineno<9:continue
                    key='\n'.join(ast.dump(s,include_attributes=False) for s in chunk)
                    blocks[key].append({'file':rel,'line':chunk[0].lineno,'end':chunk[-1].end_lineno})
            if isinstance(node,ast.Dict):
                values={k.value:v.value for k,v in zip(node.keys,node.values)
                    if isinstance(k,ast.Constant) and isinstance(k.value,str) and isinstance(v,ast.Constant)}
                if {'毫米','厘米','米'}<=values.keys():units.append({'file':rel,'line':node.lineno,'values':values})
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id.startswith(('verify_','validate_')):
                calls.append({'file':rel,'line':node.lineno,'callee':node.func.id})
    def groups(source):
        result=[]
        for key,sites in source.items():
            sites=list({(s['file'],s['line']):s for s in sites}.values())
            if len({s['file'] for s in sites})<2:continue
            result.append({'ast_sha256':hashlib.sha256(key.encode()).hexdigest(),'sites':sites})
        return sorted(result,key=lambda r:-len(r['sites']))
    return {'file_hashes':files,'exact_body_candidates':groups(functions),
            'exact_four_statement_candidates':groups(blocks),'unit_tables':units,'validator_call_sites':calls}

def worker(output):
    from app.cad_construction_interpreter import interpret_construction_request
    history=ROOT/'.local-dev/live-corpus-acjm57j_/run'
    selected={'verify_symmetric_divider_source','verify_path_relations','verify_radial_attachment_source',
              'verify_repetition_requirements','verify_final_source_contract','verify_single_rectangle',
              'verify_primitive_layout','verify_named_relations','_frame','verify_semantic_requirements',
              'rectangle_frame','path_geometry_facts','circle_facts','arc_facts'}
    cases=[]
    for case in ['A2','A3','A11','C5','C15','C18','C22','C22_valid_recorded','C24','C31']:
        folder=history/case.split('_')[0];store=folder/'projects.json'
        projects=json.loads(store.read_text(encoding='utf-8')).get('projects',[])
        project=next((p for p in projects if p.get('variants')),None)
        if not project:continue
        variant=next((v for v in reversed(project['variants']) if (v.get('construction_record') or {}).get('plan')),None)
        if not variant:continue
        plan=variant['construction_record']['plan'];source='\n'.join([project['original_prompt'],*(project['requirements'].get('source_followups') or [])])
        if case=='C22_valid_recorded':
            fixture=json.loads((ROOT/'tests/fixtures/recorded_source_proof_gaps.json').read_text(encoding='utf-8'))
            row=next(r for r in fixture['rows'] if r['case']=='C22')
            plan=row['plan'];source=row['source']
        seen={}
        def profile(frame,event,arg):
            if event!='call' or frame.f_code.co_name not in selected:return
            path=Path(frame.f_code.co_filename)
            if path.parent!=ROOT/'app':return
            names=frame.f_code.co_varnames[:frame.f_code.co_argcount]
            argument_hash=digest({n:frame.f_locals.get(n) for n in names})
            key=(path.name,frame.f_code.co_name,argument_hash)
            item=seen.setdefault(key,{'file':str(path),'function':frame.f_code.co_name,
                'input_sha256':argument_hash,'count':0,'callers':[]})
            item['count']+=1
            parent=frame.f_back
            caller={'file':parent.f_code.co_filename,'function':parent.f_code.co_name,'line':parent.f_lineno}
            if caller not in item['callers']:item['callers'].append(caller)
        sys.setprofile(profile)
        try:
            result=interpret_construction_request(source,lambda *_:{
                'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
                'plan':plan,'confidence':.99,'evidence_text':[project['original_prompt']],'assumptions':[]},force_structured_model=True)
        finally:sys.setprofile(None)
        cases.append({'case':case,'scope':'Recorded-plan validator trace, not real LLM generation or corpus score',
            'status':result.get('status'),'validator_calls':list(seen.values()),
            'same_input_repeated_calls':[v for v in seen.values() if v['count']>1]})
    dump(output/'runtime-validation-traces.json',cases)

def main():
    from scripts.local_dev import isolated_environment,run
    env,state=isolated_environment('current-duplication-audit',False);env['PYTHONDONTWRITEBYTECODE']='1'
    before=scan();dump(state/'static-evidence.json',before)
    print('AUDIT OUTPUT: '+str(state),flush=True)
    code=run([sys.executable,str(Path(__file__).resolve()),'--worker',str(state)],env)
    after=scan();summary={'worker_exit_code':code,'app_source_unchanged':before['file_hashes']==after['file_hashes'],
        'python_files':len(before['file_hashes']),'exact_function_body_candidate_groups':len(before['exact_body_candidates']),
        'exact_statement_candidate_groups':len(before['exact_four_statement_candidates']),
        'unit_table_locations':len(before['unit_tables']),'real_model_calls':0}
    dump(state/'summary.json',summary);print(json.dumps(summary),flush=True)
    return code

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--worker':worker(Path(sys.argv[2]))
    else:raise SystemExit(main())
