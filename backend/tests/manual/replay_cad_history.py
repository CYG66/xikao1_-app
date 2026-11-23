"""Read-only historical output replay. Never contacts a model or rewrites history."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from app.cad_construction import CadConstructionPlan,execute_construction_plan
from app.agent_skills import check_drawing_feasibility
from app.cad_construction_interpreter import construction_acceptance_summary
from app.cad_constraint_solver import _single_geometry,_constraint_residual,ParallelConstraint,PerpendicularConstraint
from app.cad_source_acceptance import verify_scoped_primitives,verify_final_source_contract
from app.cad_semantic_acceptance import verify_semantic_requirements
from app.cad_path_relation_acceptance import verify_path_relations
from app.cad_repetition_acceptance import verify_repetition_requirements
from app.cad_structure_contract import StructureContractError
from pydantic import ValidationError
from run_user_cad_corpus import create_checks
from app.drawing_store import geometry_preview_paths


def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def write(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')


def corpus_geometry_checks(case,variant,messages):
    """Reuse the existing independent corpus oracle, never its old pass label."""
    try:
        checks=create_checks(case,{'ok':True,'variant':variant,
            'preview_paths':geometry_preview_paths({'lines':variant['geometries']})},messages)
        failures=[c for c in checks if not c['passed']]
        unknown=[c for c in failures if 'review' in c['name'] or 'independent_semantic_acceptance'==c['name']]
        return {'checks':checks,'concrete_failures':[c for c in failures if c not in unknown],
                'unknown_checks':unknown}
    except Exception as exc:return {'oracle_error':repr(exc)}


def verify(source,gs,record,trial=None):
    before=deepcopy(gs)
    if not gs:return {'classification':'not_available'}
    try:feasible=check_drawing_feasibility(gs)
    except Exception as exc:return {'classification':'geometry_invalid','error':repr(exc)}
    if not feasible['ok']:return {'classification':'geometry_invalid','feasibility':feasible}
    constraints=[];constraint_evidence='not_configured'
    plan=record.get('plan') or {}
    if plan.get('constraints'):
        symbols=(trial or {}).get('symbol_table') or record.get('symbol_table')
        if not symbols:constraint_evidence='insufficient_evidence'
        else:
            try:
                typed=CadConstructionPlan.model_validate(plan)
                for c in typed.constraints:
                    target=_single_geometry(gs,symbols,c.target_ref,c.constraint_id)
                    reference=_single_geometry(gs,symbols,c.reference_ref,c.constraint_id)
                    residual,metric=_constraint_residual(target,reference,c,1000 if typed.units=='m' else 1)
                    tolerance=c.angle_tolerance_deg if isinstance(c,(ParallelConstraint,PerpendicularConstraint)) else c.tolerance*(1000 if typed.units=='m' else 1)
                    constraints.append({'id':c.constraint_id,'residual':residual,'tolerance':tolerance,'metric':metric,'verified':residual<=tolerance})
                constraint_evidence='passed' if all(c['verified'] for c in constraints) else 'constraint_unsatisfied'
            except Exception as exc:constraint_evidence='insufficient_evidence';constraints.append({'error':repr(exc)})
    if gs!=before:raise AssertionError('Validation mutated history geometry')
    if constraint_evidence=='constraint_unsatisfied':return {'classification':'geometry_requirement_failed','constraints':constraints}
    reports={};source_failure=None
    for name,fn in [('final_source',verify_final_source_contract),('scoped',verify_scoped_primitives),('semantic',verify_semantic_requirements),('path',verify_path_relations),('repetition',verify_repetition_requirements)]:
        try:reports[name]=fn(source,gs)
        except StructureContractError as exc:source_failure={'module':fn.__module__,'message':str(exc),'details':exc.details};break
        except Exception as exc:return {'classification':'insufficient_evidence','validation_error':repr(exc),'module':fn.__module__}
    if gs!=before:raise AssertionError('Source validation mutated geometry')
    if source_failure:return {'classification':'geometry_requirement_failed','source_failure':source_failure,'reports':reports}
    # No original completeness inventory is invented. Current source checks
    # prove only their supported subset, even if all those checks succeed.
    source_report={'status':'partial','coverage':'partial','checks':[],
                   **{k+'_acceptance':v for k,v in reports.items()}}
    prior=record.get('acceptance_summary') or {}
    if prior.get('review_required'):source_report['review_required']=True
    summary=construction_acceptance_summary(preflight_structure=None,structure_contract=None,
        structure_validation=None,composition_contract=None,composition_validation=None,
        source_acceptance=source_report,trial_result=trial)
    return {'classification':'insufficient_evidence' if constraint_evidence=='insufficient_evidence' else
            'geometry_valid_review_required' if summary['review_required'] else 'geometry_valid_and_accepted',
            'source_coverage_rebuilt':'partial_supported_checks_only','reports':reports,'constraints':constraints,
            'constraint_evidence':constraint_evidence,'current_acceptance':summary,
            'historical_acceptance':prior,'permissions':{'formal_selectable':False,'construction_authorized':False},
            'geometry_unchanged':gs==before}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--history',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();history=args.history.resolve();out=args.output.resolve()
    if out==history or history in out.parents:raise ValueError('Output must be outside history')
    out.mkdir(parents=True,exist_ok=False)
    manifest=load(history/'manifest.json');inventory=[];l1=[];l2=[];l3=[]
    for folder in sorted(history.iterdir()):
        if not folder.is_dir() or not (folder/'corpus-report.json').exists():continue
        report=load(folder/'corpus-report.json');case=folder.name
        requests={p.stem:load(p) for p in sorted(folder.glob('request-*.json'))}
        messages=report.get('messages') or [manifest.get('original_prompts',{}).get(case,'')]
        # Follow-ups are retained verbatim, not inferred from final requirements.
        source='\n'.join(messages)
        projects=load(folder/'projects.json').get('projects',[]) if (folder/'projects.json').exists() else []
        variants=[v for p in projects for v in p.get('variants',[])]
        claimed=[]
        for p in sorted(folder.glob('step-*.json')):
            response=load(p)
            if isinstance(response.get('variant'),dict):claimed.append(response['variant'].get('id'))
        selected=next((v for vid in reversed(claimed) for v in variants if v.get('id')==vid),None)
        # Never guess a final candidate merely because the copied repository
        # contains a baseline. A failed edit must not inherit baseline success.
        if selected is None and report.get('has_candidate'):
            selected=next((load(p).get('variant') for p in reversed(sorted(folder.glob('step-*.json')))
                           if isinstance(load(p).get('variant'),dict)),None)
        if report.get('kind')=='edit' and report.get('has_candidate') is False and not report.get('passed'):
            selected=None  # A copied source is not the failed edit's new candidate.
        observed=[];plans=[];seen=set()
        log=folder/'model-responses.jsonl'
        if log.exists():
            for index,line in enumerate(log.read_text(encoding='utf-8').splitlines()):
                if not line.strip():continue
                event=json.loads(line);observed.append({'line':index+1,'step':event.get('step'),'response_hash':digest(event.get('response'))})
                try:payload=json.loads(event['response'])
                except (ValueError,TypeError):continue
                if isinstance(payload,dict) and isinstance(payload.get('plan'),dict):
                    plan=payload['plan'];key=(event.get('step'),digest(plan))
                    if key not in seen:plans.append({'origin':'raw_model_response','line':index+1,'step':event.get('step'),'plan':plan});seen.add(key)
        for v in variants:
            plan=(v.get('construction_record') or {}).get('plan')
            if isinstance(plan,dict):plans.append({'origin':'stored_candidate_plan','variant_id':v['id'],'plan':plan})
        initial=[]
        for req in requests.values():
            if req.get('project_id') or req.get('drawing_selection'):
                initial.append({'project_id':req.get('project_id'),'drawing_selection':req.get('drawing_selection'),
                                'pre_request_state_snapshot':'not_recorded'})
        entry={'case':case,'original_prompt':manifest.get('original_prompts',{}).get(case),'history_passed':report.get('passed'),
            'kind':report.get('kind'),'blocked_by':report.get('blocked_by'),'requests':requests,
            'historical_checks':report.get('checks',[]),'historical_error':report.get('error'),
            'final_variant':selected,
            'model_responses':observed,'plan_count':len(plans),'model_input_evidence_complete':False,
            'copied_baseline':report.get('base'),'initial_bindings':initial,
            'final_variant_id':(selected or {}).get('id'),'final_geometry_hash':digest(selected['geometries']) if selected else None,
            'L1_available':bool(selected),'L2_plan_evidence_available':bool(plans),'L3_available':False}
        inventory.append(entry)
        if report.get('blocked_by'):
            one={'classification':'not_available','reason':'historically_not_executed','blocked_by':report['blocked_by']}
        elif selected:
            one=verify(source,deepcopy(selected.get('geometries') or []),selected.get('construction_record') or {})
            if report.get('kind')=='edit' and one['classification']=='geometry_requirement_failed' and one.get('source_failure'):
                one.update(classification='insufficient_evidence',
                    reason='Creation-source checker cannot establish post-edit requirements; rotation/resize may intentionally supersede old shape pose/dimensions.')
        else:one={'classification':'not_available','reason':'no_identifiable_final_candidate'}
        if selected and report.get('kind')=='create':
            oracle=corpus_geometry_checks(report.get('oracle_case') or case,selected,messages)
            one['independent_corpus_oracle']=oracle
            if oracle.get('concrete_failures'):
                one['classification']='geometry_requirement_failed'
        l1.append({'case':case,**one})
        for item in plans:
            replay={'case':case,**item,'plan_hash':digest(item['plan'])}
            try:
                typed=CadConstructionPlan.model_validate(item['plan']);replay['schema']='passed'
                trial=execute_construction_plan(typed)
                replay.update(execution='passed',verification=verify(source,trial['geometries'],{'plan':item['plan']},trial))
                if report.get('kind')=='create':
                    oracle=corpus_geometry_checks(report.get('oracle_case') or case,
                        {'geometries':trial['geometries'],'logical_objects':trial.get('logical_objects',[])},messages)
                    replay['independent_corpus_oracle']=oracle
                    if oracle.get('concrete_failures'):replay['verification']['classification']='geometry_requirement_failed'
            except ValidationError as exc:replay.update(schema='failed',execution='not_run',error=str(exc))
            except Exception as exc:replay.update(execution='failed',error=str(exc),error_code=getattr(exc,'code',type(exc).__name__))
            l2.append(replay)
        if not plans:l2.append({'case':case,'execution':'not_run','reason':'no_recorded_construction_plan'})
        l3.append({'case':case,'status':'not_run','reason':'historically_not_executed' if report.get('blocked_by') else
            'full_model_call_inputs_missing; strict input matching cannot be established',
            'additional_evidence_gaps':[f'service-step-{n}.json' for n in [p.split('-')[-1] for p in requests]
                if not (folder/f'service-step-{n}.json').exists()]})
        print(case,one['classification'],len(plans),flush=True)
    write(out/'inventory.json',inventory);write(out/'L1.json',l1);write(out/'L2.json',l2);write(out/'L3.json',l3)
    counts=Counter(d['classification'] for d in l1)
    write(out/'summary.json',{'schema':'cad.history-replay.v1','timestamp':time.time(),'provider_calls':0,
        'historical_cases':len(inventory),'history_passed':sum(x['history_passed'] is True for x in inventory),
        'L1':dict(counts),'L2_records':len(l2),'L2_execution':dict(Counter(x['execution'] for x in l2)),
        'L3':dict(Counter(x['status'] for x in l3)),
        'limitations':['Not current model success rate','L1 source checks cover supported subset, not full requirement inventory',
            'L2 uses recorded plans and case text, not original missing model input or full per-turn state',
            'Copied records retained as provenance, never counted as new provider calls']})


if __name__=='__main__':main()
