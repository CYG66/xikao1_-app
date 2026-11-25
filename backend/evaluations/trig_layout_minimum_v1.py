"""Map bounded-harmonic source minima with the shared execution trace."""
import math
import re
from app.cad_parametric import expression
from evaluations.trig_extrema_v1 import extrema
from evaluations.execution_layout_trace_v1 import trace_layout
from evaluations.curve_evidence_inventory import curve_evidence


def measure(plan):
    base={'version':'cad.trig-layout-minimum.v1','status':'unverified',
        'formal_candidate_accepted':False,'interval_arithmetic_proof':False}
    steps=plan.get('steps',[])
    if len(steps)!=1 or steps[0].get('op')!='add_parametric_curve' or not steps[0].get('closed'):
        return {**base,'reason':'only_single_closed_parametric_source_supported'}
    step=steps[0]
    try:
        if re.search(r'\bt\b',step['t_start']+' '+step['t_end']):raise ValueError('parameter dependent interval')
        start,end=expression(step['t_start'])(0),expression(step['t_end'])(0)
        axes={axis:extrema(step[f'{axis}_expression'],start,end) for axis in ('x','y')}
        if any(a['status']!='analytic_candidates_evaluated' for a in axes.values()):
            return {**base,'reason':'source_expression_or_degenerate_axis_unresolved'}
        trace=trace_layout(plan)
        if trace['status']!='verified_affine_mapping':return {**base,**trace}
        m=trace['layout_map_mm'];factor=trace['plan_to_mm'];minimum=axes['y']['minimum']
        mapped_y=m['sy']*factor*minimum+m['ty'];epsilon=max(1e-7,32*math.ulp(mapped_y))
        evaluate_x=expression(step['x_expression']);points=[]
        for c in axes['y']['candidates']:
            if abs((c['value']-minimum)*factor*m['sy'])>epsilon:continue
            x=m['sx']*factor*evaluate_x(c['t'])+m['tx']
            if not any(abs(x-p[0])<=epsilon for p in points):points.append([x,mapped_y])
        if not points:return {**base,'reason':'minimum_set_not_resolved'}
        return {**base,'status':'mapped_analytic_candidates',
            'minimum_kind':'isolated_point' if len(points)==1 else 'multiple_isolated_points',
            'minimum_points_mm':points,'minimum_intervals_mm':[], 'minimum_y_mm':mapped_y,
            'source_extrema':axes,'layout_map_mm':m,
            'source_min_below_sample_mm':trace['delivered_bounds_mm']['min_y']-mapped_y,
            'sampling_evidence':curve_evidence(trace['final_trial'],step['output_ref'])}
    except (ValueError,KeyError,OverflowError):return {**base,'reason':'source_expression_or_execution_unresolved'}
