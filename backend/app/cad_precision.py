"""Internal millimetre precision budget shared by construction and measurement."""
ACCEPTANCE_MM = 0.5
SAMPLING_MM = 0.2  # leaves room for two independently sampled representations


def bounded_sampling(plan):
    from copy import deepcopy
    if not isinstance(plan, dict):return plan
    result=deepcopy(plan)
    limit=SAMPLING_MM/(1000 if result.get('units','m')=='m' else 1)
    for step in result.get('steps',[]):
        if not isinstance(step,dict) or step.get('op') not in {'add_composite_path','add_rotational_path','add_parametric_curve'}:continue
        raw=step.get('max_sampling_error')
        if raw is None:step['max_sampling_error']=limit
        elif isinstance(raw,(int,float)) and not isinstance(raw,bool) and raw>limit:step['max_sampling_error']=limit
    return result
