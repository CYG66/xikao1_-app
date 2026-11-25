"""Read existing execution evidence; no new sampler, solver or geometry."""
from copy import deepcopy
from app.cad_length_units import length_factors


def curve_evidence(trial,output_ref):
    base={'version':'cad.curve-evidence-inventory.v1','output_ref':output_ref,
        'formal_candidate_accepted':False,'extremum_verified':False}
    plan=trial.get('plan') or {}
    steps=[s for s in plan.get('steps',[]) if s.get('output_ref')==output_ref]
    ids=(trial.get('symbol_table') or {}).get(output_ref,[])
    geometries=[g for g in trial.get('geometries',[]) if g.get('id') in ids]
    if len(steps)!=1 or len(ids)!=1 or len(geometries)!=1:
        return {**base,'status':'unverified','reason':'missing_or_ambiguous_source_binding'}
    step=steps[0];op=step['op'];unit=plan.get('units')
    if unit not in {'m','mm'}:
        return {**base,'status':'unverified','reason':'unknown_plan_unit'}
    factor=float(length_factors('mm')[unit])
    quality=[q for q in trial.get('curve_quality',[]) if q.get('step_id')==step['step_id'] and q.get('output_ref')==output_ref]
    shared={**base,'source_operation':op,'source_step':deepcopy(step),'geometry_ids':ids,
        'plan_units':unit,'geometry_units':'mm','reported_error_unit':unit,
        'layout':deepcopy(plan.get('free_outline_layout',[])),
        'quality':deepcopy(quality),'other_steps_present':len(plan.get('steps',[]))!=1}
    if op=='add_polyline':
        return {**shared,'representation':'declared_piecewise_linear',
            'status':'literal_boundary_available','reason':'do_not_infer_hidden_curve_from_vertices'}
    if op not in {'add_parametric_curve','add_composite_path','add_rotational_path','add_bezier','add_spline'}:
        return {**shared,'status':'unverified','reason':'representation_not_audited'}
    q=quality[0] if len(quality)==1 else {}
    field=('post_layout_sampling_error_bound' if 'post_layout_sampling_error_bound' in q else
        'observed_sampling_error' if op=='add_parametric_curve' else 'maximum_sampling_error')
    value=q.get(field)
    error=float(value)*factor if isinstance(value,(int,float)) and not isinstance(value,bool) else None
    return {**shared,'representation':'curve_with_discrete_delivery',
        'status':'unverified','reason':'sampled_bottom_is_not_original_curve_extremum',
        'reported_error_mm':error,'reported_error_field':field if value is not None else None,
        'error_authority':'observed_probe_estimate_not_global_proof',
        'guaranteed_global_error_bound':False,
        'next_measurement':'reuse_original_expression_or_control_point_evaluator; retain uncertainty until extrema are resolved'}
