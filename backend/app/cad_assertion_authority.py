"""Resolve model bounds only through complete independent source evidence."""
from copy import deepcopy


def reconcile_model_bounds(payload, source, *, eligible_ids=None):
    from .cad_construction import BoundsSizeAssertion, construction_geometry_bounds
    from .cad_construction_interpreter import _trial_plan_without_assertions
    from .cad_source_acceptance import verify_final_source_contract
    from .cad_structure_contract import StructureContractError
    raw=payload.get('plan')
    if not isinstance(raw,dict):return payload,[]
    assertions=raw.get('assertions',[])
    eligible=[a for a in assertions if a.get('kind')=='bounds_size'
              and (eligible_ids is None or a.get('assertion_id') in eligible_ids)]
    if not eligible:return payload,[]
    trial=_trial_plan_without_assertions(raw)
    if not trial:return payload,[]
    try:proof=verify_final_source_contract(source,trial['geometries'],trial.get('logical_objects'))
    except StructureContractError:return payload,[]
    if proof.get('status')!='passed' or proof.get('coverage')!='complete':return payload,[]
    ids={g['id'] for g in trial['geometries']}
    if not ids:return payload,[]
    refs=trial.get('reference_table',trial['symbol_table'])
    bounds=construction_geometry_bounds(trial['geometries'])
    actual=[bounds['max_x']-bounds['min_x'],bounds['max_y']-bounds['min_y']]
    scale=1000 if raw.get('units','m')=='m' else 1
    removed=[];changes=[]
    for assertion in eligible:
        a=BoundsSizeAssertion.model_validate(assertion)
        selected=ids if a.target_ref is None else set(refs.get(a.target_ref,[]))
        if selected!=ids:continue
        expected=[a.width*scale,a.height*scale]
        if max(abs(x-y) for x,y in zip(actual,expected))<=a.tolerance*scale:continue
        removed.append(assertion)
        changes.append({'kind':'complete_source_proof_replaces_model_bounds',
            'assertion':deepcopy(assertion),'source_proof':proof,'actual_bounds_mm':actual,
            'model_bounds_mm':expected,'geometry_ids':sorted(ids),'geometry_unchanged':True,
            'authority':'complete_user_source_measurement'})
    if not removed:return payload,[]
    result=deepcopy(payload)
    result['plan']['assertions']=[a for a in assertions if a not in removed]
    return result,changes
