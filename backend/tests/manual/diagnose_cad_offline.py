"""No provider/network calls. Diagnostic coverage is not end-to-end success."""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from app.cad_construction_interpreter import interpret_construction_request
from app.incremental_cad import parse_incremental_edit,edit_candidate_geometries


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    creation=json.loads((ROOT/'evaluations/cad_construction_model_benchmark_extended.json').read_text(encoding='utf-8'))
    editing=json.loads((ROOT/'evaluations/cad_edit_chinese_commands.json').read_text(encoding='utf-8'))
    corpus=[];results=[]
    for c in creation['cases']:
        corpus.append({'id':c['id'],'kind':'create','category':c['category'],
            'messages':[c['command']],'initial_state':{'geometries':[]},'expected':c['expected'],
            'oracle_limit':'Existing oracle covers execution structure, not full natural-language semantics.'})
    for c in editing['cases']:
        corpus.append({'id':c['id'],'kind':'edit','category':c['category'],
            'messages':[c['message']] if 'message' in c else [c['base_message'],c['variant_message']] if 'base_message' in c else [],
            'source_kind':c['kind'],'initial_state':{'geometries':editing['fixtures'].get(c.get('source_fixture'),[])},
            'expected':c['expected']})
    for c in corpus:
        started=time.monotonic()
        stages={k:'not_run' for k in ['requirement_extraction','unrequested_requirements','planning',
            'target_resolution','execution','independent_geometry','preservation','automatic_acceptance','preview','persistence']}
        try:
            if c['kind']=='create':
                observed=interpret_construction_request(c['messages'][0])
                ready=observed.get('status')=='ready'
                stages['planning']='passed' if ready else observed.get('status','failed')
                stages['execution']='passed' if observed.get('trial_result') else 'not_run'
                error_code=(observed.get('error') or {}).get('code')
                outcome=('acceptance_unknown' if ready else 'requirement_missing'
                    if error_code=='missing_coordinate_units' else 'planning_failed')
            else:
                if c.get('source_kind')!='cad_edit':
                    results.append({'id':c['id'],'kind':'edit','category':c['category'],
                        'outcome':'not_run','stages':stages,
                        'reason':'Counterfactual pair requires its existing dedicated oracle; not a sequential edit.'})
                    continue
                parsed=parse_incremental_edit(c['messages'][0])
                if parsed is None:
                    results.append({'id':c['id'],'kind':'edit','category':c['category'],
                        'outcome':'target_resolution_failed','stages':stages,
                        'observed':{'parsed_command':None},'note':'Rule parser declined; model fallback not exercised.'})
                    continue
                source=deepcopy(c['initial_state']['geometries'])
                after,error=edit_candidate_geometries(source,parsed)
                observed={'parsed_command':parsed,'geometry':after,'error':error}
                stages['execution']='passed' if after is not None else 'failed'
                checks=[];expected=c['expected'];byid={g['id']:g for g in after or []}
                for gid in expected.get('non_target_ids',[]):
                    checks.append(byid.get(gid)==next(g for g in source if g['id']==gid))
                if 'result_entity_count' in expected:checks.append(len(after or [])==expected['result_entity_count'])
                if 'expected_end' in expected:
                    p=byid.get(expected.get('end_geometry_id'),{}).get('end',{})
                    checks.append(all(abs(p.get(k,float('inf'))-v)<1e-6 for k,v in expected['expected_end'].items()))
                stages['independent_geometry']=('passed' if all(checks) else 'failed') if checks and after is not None else 'not_run'
                # Even successful local execution is not a model, project or UI result.
                outcome='geometry_execution_failed' if after is None else 'verified_geometry_mismatch' if checks and not all(checks) else 'acceptance_unknown'
            results.append({'id':c['id'],'kind':c['kind'],'category':c['category'],'outcome':outcome,
                'stages':stages,'observed':observed,'elapsed_seconds':time.monotonic()-started})
        except Exception as exc:
            results.append({'id':c['id'],'kind':c['kind'],'outcome':'diagnostic_error','error':repr(exc),'stages':stages})
    try:revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:revision='unknown'
    args.output.mkdir(parents=True,exist_ok=True)
    manifest={'version':'cad.offline-diagnostic.v1','cases':corpus}
    raw=json.dumps(manifest,ensure_ascii=False,indent=2)
    (args.output/'dataset.json').write_text(raw,encoding='utf-8')
    from collections import Counter
    report={'mode':'offline_without_model','model':None,'provider_calls':0,'code_revision':revision,
        'source_hashes':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
            ['app/cad_construction_interpreter.py','app/incremental_cad.py','app/cad_target_resolver.py']},
        'dataset_sha256':hashlib.sha256(raw.encode()).hexdigest(),'timestamp':time.time(),
        'limitations':['No model planning, HTTP, project persistence, multi-turn or App success measured.',
                      'Local execution and partial oracles must not be reported as full requirement satisfaction.'],
        'case_count':len(results),'outcomes':dict(Counter(r['outcome'] for r in results)),
        'results':results}
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['mode','provider_calls','case_count','outcomes']},ensure_ascii=False))


if __name__=='__main__':main()
