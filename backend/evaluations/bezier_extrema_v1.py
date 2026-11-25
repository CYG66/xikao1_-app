"""Offline derivative-root measurements; reuses the existing Bezier evaluator."""
import math
from app.cad_construction import ConstructionPoint, _bezier_point

VERSION='cad.bezier-extrema.v1'


def derivative_roots(values):
    differences=[b-a for a,b in zip(values,values[1:])]
    if len(values)==3:
        a,b,c=0.0,differences[1]-differences[0],differences[0]
    else:
        d0,d1,d2=differences
        a,b,c=d2-2*d1+d0,2*(d1-d0),d0
    magnitude=max(abs(a),abs(b),abs(c))
    if magnitude==0:return {'status':'constant_axis','roots':[]}
    a,b,c=(v/magnitude for v in (a,b,c))
    if a==0:
        roots=[] if b==0 else [-c/b]
    else:
        discriminant=math.fsum([b*b,-4*a*c])
        uncertainty=64*math.ulp(1.0)*(b*b+abs(4*a*c))
        if discriminant<0:
            return {'status':'uncertain_discriminant' if -discriminant<=uncertainty else 'resolved','roots':[]}
        if discriminant==0:
            roots=[-b/(2*a)]
        else:
            q=-.5*(b+math.copysign(math.sqrt(discriminant),b))
            roots=[q/a,c/q]
    roots=sorted(set(t for t in roots if math.isfinite(t) and 0<=t<=1))
    residuals=[abs((a*t+b)*t+c) for t in roots]
    return {'status':'resolved' if all(r<=1e-10 for r in residuals) else 'uncertain_residual',
        'roots':roots,'normalized_derivative_residuals':residuals}


def bezier_extrema(control_points):
    if len(control_points) not in (3,4):raise ValueError('Only quadratic and cubic Beziers are supported')
    points=[ConstructionPoint.model_validate(p) for p in control_points]
    if not all(math.isfinite(v) for p in points for v in (p.x,p.y)):
        raise ValueError('Finite coordinates required')
    axes={axis:derivative_roots([getattr(p,axis) for p in points]) for axis in ('x','y')}
    result={'version':VERSION,'degree':len(points)-1,'coordinate_frame':'input_control_points',
        'coordinate_units':'same_as_input','axes':axes,'formal_candidate_accepted':False,
        'interval_arithmetic_proof':False,'layout_applied':False}
    if any(a['status'].startswith('uncertain') for a in axes.values()):
        return {**result,'status':'unverified_numeric_condition'}
    parameters=sorted({0.0,1.0,*axes['x']['roots'],*axes['y']['roots']})
    samples=[{'t':t,'point':_bezier_point(points,t).model_dump()} for t in parameters]
    bounds={f'{side}_{axis}':fn(p['point'][axis] for p in samples)
        for side,fn in [('min',min),('max',max)] for axis in ('x','y')}
    return {**result,'status':'analytic_candidates_evaluated','candidates':samples,'bounds':bounds,
        'limitation':'Floating-point derivative roots, not certified interval arithmetic; no inference about layout or complete shape'}
