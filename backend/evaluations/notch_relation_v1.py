"""Evaluation-only upper-boundary relation; never a full shape acceptance."""
import math
from shapely.geometry import Polygon, LineString

VERSION = 'cad.notch-relation.v1'


def upper_notch_relation(points, tolerance_mm=.5):
    result = {'version': VERSION, 'scope': 'upper_notch_relation_only',
        'relation_passed': False, 'formal_candidate_accepted': False}
    if not math.isfinite(tolerance_mm) or tolerance_mm <= 0:
        raise ValueError('positive finite measurement tolerance required')
    try:
        points = [(float(x), float(y)) for x,y in points]
        if not all(math.isfinite(v) for p in points for v in p):
            return {**result, 'reason': 'nonfinite_coordinates'}
        polygon = Polygon(points)
        if not polygon.is_valid or polygon.area <= 0:
            return {**result, 'reason': 'invalid_or_degenerate_boundary'}
        xmin,ymin,xmax,ymax = polygon.bounds
        cx = (xmin+xmax)/2
        top = polygon.intersection(LineString([(cx,ymin-1),(cx,ymax+1)])).bounds[3]
        left = max(y for x,y in points if x < cx)
        right = max(y for x,y in points if x > cx)
        depth = min(left,right)-top
        result['measurements'] = {'center_top_mm':[cx,top], 'side_peak_y_mm':[left,right],
            'notch_depth_mm':depth, 'tolerance_mm':tolerance_mm,
            'depth_fraction_of_height':depth/(ymax-ymin)}
        if depth <= tolerance_mm:
            return {**result, 'reason':'no_resolved_central_depression'}
        level = top + depth/2
        cut = polygon.intersection(LineString([(xmin-1,level),(xmax+1,level)]))
        parts = list(cut.geoms) if hasattr(cut,'geoms') else [cut]
        intervals = sorted([list(p.bounds[::2]) for p in parts if p.geom_type=='LineString' and p.length>tolerance_mm])
        result['measurements'].update(probe_height_mm=level, upper_intervals_mm=intervals)
        separated = (len(intervals)==2 and intervals[0][1]<cx and intervals[1][0]>cx)
        return {**result, 'relation_passed':separated,
            'reason':'two_separated_upper_lobes' if separated else 'upper_lobes_not_separated_about_center'}
    except (ValueError, TypeError, IndexError):
        return {**result, 'reason':'unsupported_boundary'}
