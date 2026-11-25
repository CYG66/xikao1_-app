"""Offline source-curve minima mapped through verified existing execution layout."""
from copy import deepcopy
import math
from evaluations.bezier_extrema_v1 import bezier_extrema


def measure(plan):
    base={'version':'cad.bezier-layout-minimum.v1','status':'unverified',
        'formal_candidate_accepted':False,'interval_arithmetic_proof':False}
    plan=deepcopy(plan);steps=plan.get('steps',[])
    if len(steps)!=1 or plan.get('constraints'):
        return {**base,'reason':'only_single_unconstrained_source_supported'}
    step=steps[0];segments=step.get('segments',[])
    if step.get('op')!='add_composite_path' or not step.get('closed') or not segments or any(s.get('kind')!='bezier' for s in segments):
        return {**base,'reason':'only_closed_all_bezier_composite_supported'}
    from evaluations.execution_layout_trace_v1 import trace_layout
    trace=trace_layout(plan)
    if trace['status']!='verified_affine_mapping':return {**base,**trace}
    try:
        mapping=trace['layout_map_mm']
        sx,sy,tx,ty,residual=(mapping[k] for k in ('sx','sy','tx','ty','residual_mm'))
        factor=trace['plan_to_mm'];f=trace['delivered_bounds_mm']
        proofs=[bezier_extrema(s['control_points']) for s in segments]
        if any(p['status']!='analytic_candidates_evaluated' for p in proofs):
            return {**base,'reason':'uncertain_source_extrema'}
        minimum=min(p['bounds']['min_y'] for p in proofs)
        mapped_min=sy*factor*minimum+ty
        epsilon=max(1e-7,32*math.ulp(mapped_min))
        intervals=[];points=[]
        for index,proof in enumerate(proofs):
            if abs(sy*factor*proof['bounds']['min_y']+ty-mapped_min)>epsilon:continue
            if proof['axes']['y']['status']=='constant_axis':
                left=sx*factor*proof['bounds']['min_x']+tx
                right=sx*factor*proof['bounds']['max_x']+tx
                if right-left>epsilon:
                    intervals.append({'segment_index':index,'x_interval_mm':[left,right],'y_mm':mapped_min})
                    continue
            for sample in proof['candidates']:
                if abs(sy*factor*sample['point']['y']+ty-mapped_min)<=epsilon:
                    x=sx*factor*sample['point']['x']+tx
                    if not any(abs(x-p[0])<=epsilon for p in points):points.append([x,mapped_min])
        if not intervals and not points:return {**base,'reason':'minimum_set_not_resolved'}
        kind='flat_interval' if intervals else 'isolated_point' if len(points)==1 else 'multiple_isolated_points'
        return {**base,'status':'mapped_analytic_candidates','minimum_kind':kind,
            'minimum_y_mm':mapped_min,'minimum_points_mm':points,'minimum_intervals_mm':intervals,
            'numeric_comparison_epsilon_mm':epsilon,'source_extrema':proofs,
            'layout_map_mm':{'sx':sx,'sy':sy,'tx':tx,'ty':ty,'residual_mm':residual},
            'delivered_sample_min_y_mm':f['min_y'],
            'source_min_below_sample_mm':f['min_y']-mapped_min}
    except (ValueError,KeyError,ZeroDivisionError):
        return {**base,'reason':'execution_or_geometry_not_supported'}
