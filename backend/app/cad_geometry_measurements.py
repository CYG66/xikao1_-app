"""Shared geometry facts. No source interpretation, acceptance or generation."""
import math


def measured(function,*args,evidence_context=None):
    if evidence_context is None:return function(*args)
    return evidence_context.measure(function,*args)


def closed_polyline_points(g):
    if g.get('type')!='polyline' or not g.get('closed'):return []
    points=[(p['x'],p['y']) for p in g.get('vertices',[])]
    if len(points)>1 and math.dist(points[0],points[-1])<1e-6:points.pop()
    return points


def straight_polyline_corners(points):
    result=[]
    for i,p in enumerate(points):
        a,b=points[i-1],points[(i+1)%len(points)]
        ux,uy=p[0]-a[0],p[1]-a[1];vx,vy=b[0]-p[0],b[1]-p[1]
        if abs(ux*vy-uy*vx)>1e-7*max(1,math.hypot(ux,uy)*math.hypot(vx,vy)) or ux*vx+uy*vy<0:result.append(p)
    return result


def rectangle_frame(g):
    raw=closed_polyline_points(g)
    if len(raw)<4 or any(p.get('bulge',0)!=0 for p in g.get('vertices',[])):return None
    from shapely.geometry import Polygon
    if not Polygon(raw).is_valid:return None
    points=straight_polyline_corners(raw)
    if len(points)!=4:return None
    xs,ys=zip(*points);x0,x1,y0,y1=min(xs),max(xs),min(ys),max(ys)
    if x1-x0<=0 or y1-y0<=0:return None
    expected=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
    if not all(any(math.dist(p,q)<1e-5 for p in points) for q in expected):return None
    return x0,y0,x1-x0,y1-y0


def circle_facts(g):
    return {'center_mm':(g['center']['x'],g['center']['y']),'radius_mm':g['radius']}


def polygon_circumcircle(g):
    """Measure a cyclic convex hull; concave inner vertices need not lie on it."""
    facts=polygon_circumcircle_diagnostics(g)
    if facts is None or not facts['cyclic_hull']:return None
    return {'center_mm':facts['center_mm'],'radius_mm':facts['radius_mm']}


def polygon_circumcircle_diagnostics(g):
    """Retain actual hull residuals when a requested circumcircle is invalid."""
    from shapely import minimum_bounding_circle, minimum_bounding_radius
    from shapely.geometry import Polygon
    points=closed_polyline_points(g)
    if len(points)<3 or any(p.get('bulge',0) for p in g.get('vertices',[])):
        return None
    if any(not math.isfinite(v) for p in points for v in p):return None
    shape=Polygon(points)
    if not shape.is_valid or shape.area<=0:return None
    hull=shape.convex_hull
    center=minimum_bounding_circle(hull).centroid
    radius=float(minimum_bounding_radius(hull))
    distances=[math.dist(p,(center.x,center.y)) for p in list(hull.exterior.coords)[:-1]]
    residuals=[abs(value-radius) for value in distances]
    return {'center_mm':(center.x,center.y),'radius_mm':radius,
            'hull_vertex_radii_mm':distances,'maximum_hull_residual_mm':max(residuals),
            'cyclic_hull':all(value<=.5 for value in residuals)}


def rounded_rectangle_facts(g,radius):
    """Check straight spans and sampled quarter-circles of a closed boundary."""
    from shapely.geometry import Polygon
    points=closed_polyline_points(g)
    if len(points)<12 or radius<=0 or any(p.get('bulge',0) for p in g.get('vertices',[])):return None
    polygon=Polygon(points)
    if not polygon.is_valid or polygon.area<=0:return None
    x,y,X,Y=polygon.bounds;r=radius;t=.5
    if 2*r>min(X-x,Y-y)+t:return None
    centers=[(x+r,y+r,-1,-1),(X-r,y+r,1,-1),(X-r,Y-r,1,1),(x+r,Y-r,-1,1)]
    error=0;covered=set()
    for a,b in zip(points,points[1:]+points[:1]):
        vertical=any(abs(a[0]-edge)<=t and abs(b[0]-edge)<=t and all(y+r-t<=p[1]<=Y-r+t for p in (a,b)) for edge in (x,X))
        horizontal=any(abs(a[1]-edge)<=t and abs(b[1]-edge)<=t and all(x+r-t<=p[0]<=X-r+t for p in (a,b)) for edge in (y,Y))
        if vertical or horizontal:continue
        matches=[i for i,(cx,cy,sx,sy) in enumerate(centers) if all(
            sx*(p[0]-cx)>=-t and sy*(p[1]-cy)>=-t and abs(math.dist(p,(cx,cy))-r)<=t for p in (a,b))]
        if len(matches)!=1:return None
        i=matches[0];covered.add(i);cx,cy,*_=centers[i]
        midpoint=((a[0]+b[0])/2,(a[1]+b[1])/2)
        error=max(error,abs(math.dist(midpoint,(cx,cy))-r))
    tangents=[(x+r,y),(X-r,y),(X,y+r),(X,Y-r),(X-r,Y),(x+r,Y),(x,Y-r),(x,y+r)]
    if len(covered)!=4 or error>r*.005 or any(min(math.dist(p,q) for p in points)>t for q in tangents):return None
    return {'width_mm':X-x,'height_mm':Y-y,'radius_mm':r,'max_chord_error_mm':error,'geometry_ids':[g['id']]}


def arc_facts(g):
    circle=circle_facts(g)
    def point(angle):
        return [g['center']['x']+g['radius']*math.cos(math.radians(angle)),
                g['center']['y']+g['radius']*math.sin(math.radians(angle))]
    return {**circle,'sweep_degrees':(g['end_angle']-g['start_angle'])%360,
            'endpoints_mm':[point(g['start_angle']),point(g['end_angle'])],
            'midpoint_90_mm':point(g['start_angle']+90)}


def path_geometry_facts(active, *, evidence_context=None):
    # Retain the renderer's meter-space samples used by the existing generic
    # path checks. Native arc facts serve the extra semicircle rules only.
    from .drawing_store import _geometry_points
    paths=[];ids=[]
    for g in active:
        if g['type'] in {'circle','text'} or g.get('closed'):continue
        points=_geometry_points(g)
        if len(points)>1 and math.dist(points[0],points[-1])>.0005:
            paths.append(points);ids.append(g['id'])
    circles={};arcs={}
    for g in active:
        # The generic path contract may ignore unrelated circles or accept
        # renderer-coercible arcs. Optional native facts cannot narrow it.
        try:
            if g['type']=='circle':circles[g['id']]=measured(circle_facts,g,evidence_context=evidence_context)
            elif g['type']=='arc':arcs[g['id']]=measured(arc_facts,g,evidence_context=evidence_context)
        except (KeyError,TypeError,ValueError,OverflowError):
            continue
    return {'paths_m':paths,'path_ids':ids,'circle_facts':circles,'arc_facts':arcs}


def measure_path_geometry(active, *, evidence_context=None):
    if evidence_context is None:return path_geometry_facts(active)
    return evidence_context.measure(path_geometry_facts,active,evidence_context=evidence_context)


def ordered_straight_path(geometries, start_mm, *, evidence_context=None):
    """Measure one open chain from a source-bound start, without creating CAD.

    Ordering and native entity direction are irrelevant. Collinear subdivisions
    have the same measured semantics; gaps, branches and overlaps are rejected.
    """
    from .cad_precision import ACCEPTANCE_MM
    from shapely.geometry import LineString
    if not geometries or any(g.get('type') not in {'line','polyline'} or g.get('closed')
        or any(p.get('bulge',0) for p in g.get('vertices',[])) for g in geometries):
        raise ValueError('unsupported_open_straight_path')
    facts=measure_path_geometry(geometries,evidence_context=evidence_context)
    if len(facts['paths_m'])!=len(geometries):raise ValueError('missing_or_degenerate_path')
    edges=[(tuple(v*1000 for v in a),tuple(v*1000 for v in b))
           for path in facts['paths_m'] for a,b in zip(path,path[1:])]
    if any(math.dist(a,b)<1e-9 for a,b in edges):raise ValueError('zero_length_edge')
    if len(edges)>4096:raise ValueError('path_measurement_budget_exceeded')
    unused=set(range(len(edges)));points=[];current=tuple(start_mm)
    while unused:
        candidates=[(i,reverse) for i in unused for reverse in (False,True)
                    if math.dist(current,edges[i][1 if reverse else 0])<=ACCEPTANCE_MM]
        if len(candidates)!=1:raise ValueError('disconnected_branched_or_ambiguous_path')
        index,reverse=candidates[0];a,b=edges[index][::-1] if reverse else edges[index]
        if not points:points.append(a)
        points.append(b);current=b;unused.remove(index)
    if math.dist(points[0],points[-1])<=ACCEPTANCE_MM or not LineString(points).is_simple:
        raise ValueError('closed_or_self_overlapping_path')
    simplified=[]
    for p in points:
        simplified.append(p)
        while len(simplified)>=3:
            a,b,c=simplified[-3:];u=(b[0]-a[0],b[1]-a[1]);v=(c[0]-b[0],c[1]-b[1])
            if u[0]*v[0]+u[1]*v[1]<=0:break
            if abs(u[0]*v[1]-u[1]*v[0])>1e-9*math.hypot(*u)*math.hypot(*v):break
            simplified.pop(-2)
    return {'points_mm':simplified,'lengths_mm':[math.dist(a,b) for a,b in zip(simplified,simplified[1:])],
            'directions_deg':[math.degrees(math.atan2(b[1]-a[1],b[0]-a[0])) for a,b in zip(simplified,simplified[1:])],
            'geometry_ids':[g['id'] for g in geometries],'endpoint_tolerance_mm':ACCEPTANCE_MM}
