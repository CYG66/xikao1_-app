"""Offline lower-boundary relation; not a complete shape recognizer."""
import math
from shapely.geometry import Polygon, LineString

VERSION='cad.lower-taper-relation.v1'


def lower_taper_relation(points,tolerance_mm=.5):
    if not math.isfinite(tolerance_mm) or tolerance_mm<=0:
        raise ValueError('positive finite tolerance required')
    result={'version':VERSION,'scope':'lower_taper_only','relation_passed':False,
        'formal_candidate_accepted':False}
    try:
        polygon=Polygon(points)
        if not polygon.is_valid or polygon.area<=0:
            return {**result,'reason':'invalid_boundary'}
        xmin,ymin,xmax,ymax=polygon.bounds;cx=(xmin+xmax)/2;h=ymax-ymin
        fractions=(0,.02,.05,.1,.2)
        sections=[]
        for fraction in fractions:
            cut=polygon.intersection(LineString([(xmin-1,ymin+fraction*h),(xmax+1,ymin+fraction*h)]))
            parts=list(cut.geoms) if hasattr(cut,'geoms') else [cut]
            parts=[p for p in parts if not p.is_empty]
            intervals=[]
            # GEOS can return adjacent collinear pieces as separate lines.
            # Merge touching intervals so densifying the same flat edge
            # cannot change its geometric connectivity.
            for left,right in sorted((p.bounds[0],p.bounds[2]) for p in parts):
                if intervals and left<=intervals[-1][1]+tolerance_mm:
                    intervals[-1]=(intervals[-1][0],max(right,intervals[-1][1]))
                else:
                    intervals.append((left,right))
            if len(intervals)!=1:
                return {**result,'reason':'disconnected_lower_section','sections':sections}
            left,right=intervals[0]
            sections.append({'height_fraction':fraction,'interval_mm':[left,right],'width_mm':right-left})
        bottom=sections[0]
        centered=all(abs(x-cx)<=tolerance_mm for x in bottom['interval_mm'])
        narrow=bottom['width_mm']<=tolerance_mm
        expanding=all(b['width_mm']>a['width_mm']+tolerance_mm for a,b in zip(sections,sections[1:]))
        containing_center=all(a['interval_mm'][0]<=cx<=a['interval_mm'][1] for a in sections[1:])
        return {**result,'relation_passed':centered and narrow and expanding and containing_center,
            'reason':'central_taper' if centered and narrow and expanding and containing_center else 'lower_boundary_not_central_taper',
            'sections':sections,'checks':{'central_minimum':centered,'no_resolved_flat_bottom':narrow,
                'sections_expand_upward':expanding,'sections_contain_center':containing_center},
            'tolerance_mm':tolerance_mm}
    except (ValueError,TypeError,IndexError):
        return {**result,'reason':'unsupported_boundary'}
