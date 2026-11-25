"""Bounded CAD recovery evidence; no implicit background jobs."""
from copy import deepcopy
import hashlib
import json


def recovery_category(result):
    details=(result.get('construction_error') or {}).get('details') or {}
    if details.get('reason')=='unverified_geometry' and details.get('inventory_scope')=='partial':
        return 'requirements_unverified'
    code=str((result.get('construction_error') or {}).get('code') or (result.get('error') or {}).get('code') or '')
    if result.get('clarification') or result.get('status')=='clarification_required':return 'requirements_missing'
    if any(t in code for t in ('budget','too_dense','sampling')):return 'sampling_budget'
    if any(t in code for t in ('constraint','continuity','intersect')):return 'constraint_conflict'
    if any(t in code for t in ('timeout','network','transport','provider','connection')):return 'network_failure'
    if code=='persistence_failed':return 'persistence_failure'
    return 'model_plan_invalid'


def should_repair(result):
    return (result.get('status')=='invalid' and bool(result.get('provider_attempted'))
            and recovery_category(result) in {'model_plan_invalid','constraint_conflict','sampling_budget'})


def bounded_repair_available(attempts, max_repairs=2):
    """Permit a second repair only when the first repair made real progress.

    A compound plan can expose failures sequentially: repairing component A may
    allow independent acceptance to reach component B.  Repeating the same
    failure or returning the same plan is model oscillation, not progress.
    """
    repairs=max(0,len(attempts)-1)
    if repairs>=max_repairs:
        return False
    if len(attempts)<2:
        return True
    previous,current=attempts[-2],attempts[-1]
    current_error=current.get('construction_error') or current.get('error') or {}
    # A repaired plan that still misses the confidence gate has supplied no
    # new geometric failure to act on.  Retrying it would only ask the model
    # to inflate a score, which is explicitly forbidden.
    if str(current_error.get('code') or '') in {'low_confidence','confidence_only_repair'}:
        return False
    def signature(result):
        error=result.get('construction_error') or result.get('error') or {}
        return (recovery_category(result),str(error.get('code') or ''),
                str(error.get('message') or ''),
                json.dumps(error.get('details'),sort_keys=True,ensure_ascii=False,default=str))
    before=previous.get('plan') or previous.get('rejected_plan')
    after=current.get('plan') or current.get('rejected_plan')
    return signature(previous)!=signature(current) and before!=after


def confidence_only_repair(before,after):
    """A confidence number alone is not a plan correction or new user evidence."""
    return (before.get('diagnostic_trial_passed') is True
            and (before.get('error') or {}).get('code')=='low_confidence'
            and after.get('status')=='ready'
            and bool(before.get('rejected_plan'))
            and before['rejected_plan']==after.get('plan'))


def recovery_record(source,attempts,max_repairs=1):
    records=[]
    for index,result in enumerate(attempts):
        plan=deepcopy(result.get('plan') or result.get('rejected_plan'))
        records.append({'attempt':index+1,'status':result.get('status'),
            'confidence':result.get('confidence'),
            'category':None if result.get('status')=='ready' else recovery_category(result),
            'error':deepcopy(result.get('construction_error') or result.get('error')),
            'plan':plan,'plan_sha256':hashlib.sha256(json.dumps(plan,sort_keys=True,ensure_ascii=False).encode()).hexdigest()})
        if result.get('local_repair_validation'):
            records[-1]['local_repair_validation']=deepcopy(result['local_repair_validation'])
        if result.get('coordinate_patch'):
            records[-1]['coordinate_patch']=deepcopy(result['coordinate_patch'])
        if index:
            before=records[index-1]['plan'] or {}
            after=plan or {}
            records[-1]['changed_plan_fields']=sorted(k for k in set(before)|set(after) if before.get(k)!=after.get(k)) if isinstance(before,dict) and isinstance(after,dict) else ['plan']
            if isinstance(before,dict) and isinstance(after,dict):
                def steps_by_ref(plan):
                    return {str(s.get('output_ref') or s.get('step_id') or i):s
                            for i,s in enumerate(plan.get('steps') or []) if isinstance(s,dict)}
                old,new=steps_by_ref(before),steps_by_ref(after)
                records[-1]['step_diff']={
                    'added_refs':sorted(set(new)-set(old)),
                    'removed_refs':sorted(set(old)-set(new)),
                    'modified_refs':sorted(k for k in set(old)&set(new) if old[k]!=new[k]),
                    'unchanged_refs':sorted(k for k in set(old)&set(new) if old[k]==new[k]),
                    'comparison':'exact_plan_steps_not_geometric_equivalence'}
    return {'schema':'cad.generation-recovery.v1','source_sha256':hashlib.sha256(source.encode('utf-8')).hexdigest(),
            'max_repairs':max_repairs,'repair_count':max(0,len(records)-1),'attempts':records,
            'background_job':None,'source_preserved':True}
