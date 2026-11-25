"""Shared read-only affine trace for existing single-outline executions."""
from copy import deepcopy
import math
from app.cad_construction import execute_construction_plan, construction_geometry_bounds
from app.cad_length_units import length_factors


def trace_layout(plan):
    base={'status':'unverified'};plan=deepcopy(plan);steps=plan.get('steps',[])
    if len(steps)!=1 or plan.get('constraints'):return {**base,'reason':'only_single_unconstrained_source_supported'}
    layouts=plan.get('free_outline_layout',[])
    if len(layouts)>1 or any(l.get('target_ref')!=steps[0]['output_ref'] or l.get('right_of_ref') for l in layouts):
        return {**base,'reason':'layout_not_supported'}
    if plan.get('units','m') not in {'m','mm'}:return {**base,'reason':'unknown_unit'}
    try:
        final=execute_construction_plan(plan)
        raw_plan=deepcopy(plan);raw_plan['free_outline_layout']=[];raw_plan['assertions']=[]
        raw=execute_construction_plan(raw_plan)
        before=raw['geometries'][0]['vertices'];after=final['geometries'][0]['vertices']
        if len(before)!=len(after):return {**base,'reason':'sampling_changed_between_executions'}
        b=construction_geometry_bounds(raw['geometries']);f=construction_geometry_bounds(final['geometries'])
        sx=(f['max_x']-f['min_x'])/(b['max_x']-b['min_x'])
        sy=(f['max_y']-f['min_y'])/(b['max_y']-b['min_y'])
        tx=f['min_x']-sx*b['min_x'];ty=f['min_y']-sy*b['min_y']
        residual=max(math.hypot(sx*p['x']+tx-q['x'],sy*p['y']+ty-q['y']) for p,q in zip(before,after))
        if min(sx,sy)<=0 or residual>1e-6:return {**base,'reason':'affine_mapping_not_verified','residual_mm':residual}
        return {'status':'verified_affine_mapping','layout_map_mm':{'sx':sx,'sy':sy,'tx':tx,'ty':ty,'residual_mm':residual},
            'plan_to_mm':float(length_factors('mm')[plan.get('units','m')]),'final_trial':final,'delivered_bounds_mm':f}
    except (ValueError,KeyError,ZeroDivisionError):return {**base,'reason':'execution_or_geometry_not_supported'}
