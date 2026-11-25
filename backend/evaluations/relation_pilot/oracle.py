"""Independent sampled boundary comparison, not production source acceptance."""
import math
from shapely.geometry import LineString
from shapely.ops import unary_union
from .cases import expected_entities


def boundary(geometries):
    paths=[]
    for g in geometries:
        kind=g['type']
        if kind=='line':points=[(g[k]['x'],g[k]['y']) for k in ('start','end')]
        elif kind=='polyline':
            if any(p.get('bulge',0) for p in g['vertices']):raise ValueError('unsupported_bulge')
            points=[(p['x'],p['y']) for p in g['vertices']]
            if g.get('closed') and points[-1]!=points[0]:points.append(points[0])
        elif kind in {'arc','circle'}:
            r=g['radius'];start=g.get('start_angle',0);sweep=(g.get('end_angle',360)-start)%360 or 360
            if kind=='arc' and abs(g['end_angle']-start)<1e-9:raise ValueError('zero_arc')
            step=2*math.acos(max(-1,min(1,1-min(.02,r*.1)/r)))
            count=max(2,math.ceil(math.radians(sweep)/step))
            if count>8192:raise ValueError('oracle_sampling_budget')
            points=[(g['center']['x']+r*math.cos(math.radians(start+sweep*i/count)),
                     g['center']['y']+r*math.sin(math.radians(start+sweep*i/count))) for i in range(count+1)]
        else:raise ValueError('unsupported_geometry_'+kind)
        if len(points)<2 or not all(math.isfinite(v) for p in points for v in p):raise ValueError('invalid_geometry')
        paths.append(LineString(points))
    if not paths:raise ValueError('empty_geometry')
    return unary_union(paths)


def evaluate(row,geometries):
    target=boundary(expected_entities(row));actual=boundary(geometries)
    distance=float(target.hausdorff_distance(actual))
    # Both the desired and candidate native arcs use <=0.02mm chord error.
    # A conservative 0.45mm sampled limit stays below 0.5mm with both errors.
    missing=not target.difference(actual.buffer(.45,quad_segs=32)).is_empty
    extra=not actual.difference(target.buffer(.45,quad_segs=32)).is_empty
    passed=not missing and not extra
    return {'passed':passed,'boundary_hausdorff_mm':distance,'sampled_limit_mm':.45,
            'maximum_native_arc_chord_error_mm':.02,'scope':'geometry_planning_only',
            'target_outside_candidate_tolerance':missing,'candidate_outside_target_tolerance':extra,
            'expected_total_length_mm':target.length,'actual_total_length_mm':actual.length}
