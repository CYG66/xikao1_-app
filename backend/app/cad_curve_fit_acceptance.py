"""Measure curve identities from actual geometry; never construct curves."""
import numpy as np
from scipy.optimize import least_squares


def _valid_boundary(geometry,points):
    from shapely.geometry import Polygon
    if (geometry.get('type','polyline')!='polyline' or not geometry.get('closed')
            or not np.isfinite(points).all()
            or any(p.get('bulge',0)!=0 for p in geometry.get('vertices',[]))):
        return False
    if len(points)>1 and np.linalg.norm(points[0]-points[-1])<1e-6:
        points=points[:-1]
    return len(points)>=3 and Polygon(points).is_valid and Polygon(points).area>0


def verify_astroid(geometry, expected_radius_mm=None):
    """Check the curve identity on vertices and between sampled vertices."""
    points=np.array([[p['x'],p['y']] for p in geometry.get('vertices') or []],dtype=float)
    if len(points)<16 or not _valid_boundary(geometry,points):
        return {'passed':False,'reason':'unsupported_or_invalid_closed_geometry'}
    center=(np.min(points,axis=0)+np.max(points,axis=0))/2
    delta=points-center;distances=np.linalg.norm(delta,axis=1)
    radius=float(np.max(distances))
    if radius<=0:return {'passed':False,'reason':'degenerate_geometry'}
    cusp=delta[int(np.argmax(distances))]
    angle=float(np.arctan2(cusp[1],cusp[0]))
    rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    following=np.roll(points,-1,axis=0)
    probes=np.concatenate([points+(following-points)*fraction for fraction in (0,.25,.5,.75)])
    q=((probes-center)@rotation)/radius
    residual=np.abs(np.sum(np.abs(q)**(2/3),axis=1)-1)
    local=delta@rotation
    cusps=bool(all(abs(v)>=.99*radius for v in [np.max(local[:,0]),np.min(local[:,0]),np.max(local[:,1]),np.min(local[:,1])]))
    maximum=float(np.max(residual))
    radius_error=abs(radius-expected_radius_mm) if expected_radius_mm is not None else None
    return {'passed':maximum<=.01 and cusps and (radius_error is None or radius_error<=.5),
        'max_identity_residual':maximum,'identity_tolerance':.01,'four_cusps_present':cusps,
        'center_mm':center.tolist(),'orientation_degrees':float(np.degrees(angle)),
        'radius_mm':radius,'expected_radius_mm':expected_radius_mm,'radius_error_mm':radius_error,
        'radius_tolerance_mm':.5}


def verify_cardioid(geometry):
    points=np.array([[p['x'],p['y']] for p in geometry.get('vertices') or []],dtype=float)
    if len(points)<20 or not _valid_boundary(geometry,points):
        return {'passed':False,'reason':'unsupported_or_invalid_closed_geometry'}
    span=float(np.max(np.ptp(points,axis=0)))
    if span<=0:return {'passed':False,'reason':'degenerate_geometry'}
    origin=np.mean(points,axis=0);xy=(points-origin)/span
    def residual(p,values=None):
        delta=(xy if values is None else values)-p[:2];radius=np.linalg.norm(delta,axis=1)
        projection=delta[:,0]*np.cos(p[3])+delta[:,1]*np.sin(p[3])
        return radius-p[2]*(1+projection/np.maximum(radius,1e-12))
    fits=[]
    seeds=[np.mean(xy,axis=0),*[xy[i] for i in np.linspace(0,len(xy)-1,8,dtype=int)]]
    for center in seeds:
        for phi in (0,np.pi/2,np.pi,3*np.pi/2):
            fit=least_squares(residual,[*center,.4,phi],
                bounds=([-2,-2,.01,-2*np.pi],[2,2,3,4*np.pi]),max_nfev=300)
            fits.append(fit)
    best=min(fits,key=lambda f:float(np.mean(residual(f.x)**2)))
    following=np.roll(xy,-1,axis=0)
    probes=np.concatenate([xy+(following-xy)*fraction for fraction in (0,.25,.5,.75)])
    errors=np.abs(residual(best.x,probes));maximum=float(np.max(errors))
    delta=xy-best.x[:2];lengths=np.linalg.norm(delta,axis=1)
    angles=np.sort(np.mod(np.arctan2(delta[lengths>1e-8,1],delta[lengths>1e-8,0]),2*np.pi))
    maximum_gap=float(np.max(np.diff(np.r_[angles,angles[0]+2*np.pi]))) if len(angles)>1 else float(2*np.pi)
    return {'passed':maximum<=.005 and maximum_gap<=np.pi/2,'max_relative_radial_residual':maximum,
            'rms_relative_radial_residual':float(np.sqrt(np.mean(errors**2))),
            'tolerance_relative_to_extent':.005,'cusp_mm':(best.x[:2]*span+origin).tolist(),
            'axis_radians':float(best.x[3]),'scale_mm':float(best.x[2]*span),
            'authority':'independent_geometry_fit',
            'bounds_mm':[float(np.min(points[:,0])),float(np.min(points[:,1])),float(np.max(points[:,0])),float(np.max(points[:,1]))],
            'maximum_polar_gap_radians':maximum_gap,'checked_between_vertices':True,
            'cusp_pointing_unit_vector':[float(np.cos(best.x[3])),float(np.sin(best.x[3]))],
            'direction_definition':'opposite the ray from cusp to its neighboring curve points'}

def verify_native_semicircular_arch(geometries):
    """Measure an existing arc and three exact boundary lines; no construction."""
    import math
    from .cad_geometry_measurements import arc_facts
    arcs=[g for g in geometries if g.get('type')=='arc']
    lines=[g for g in geometries if g.get('type')=='line']
    failed={'passed':False}
    if len(geometries)!=4 or len(arcs)!=1 or len(lines)!=3:return failed
    arc=arcs[0];facts=arc_facts(arc);cx,cy=facts['center_mm'];r=facts['radius_mm']
    if r<=0 or abs(facts['sweep_degrees']-180)>1e-7 or abs(abs(arc['end_angle']-arc['start_angle'])-180)>1e-7:return failed
    if any(abs(y-cy)>.5 for x,y in facts['endpoints_mm']):return failed
    if facts['midpoint_90_mm'][1]<cy+r-.5:return failed
    y0=min(g[k]['y'] for g in lines for k in ('start','end'))
    if cy-y0<=.5:return failed
    expected=[((cx-r,y0),(cx-r,cy)),((cx+r,y0),(cx+r,cy)),((cx-r,y0),(cx+r,y0))]
    remaining=list(lines)
    for a,b in expected:
        matches=[g for g in remaining if any(math.dist((g['start']['x'],g['start']['y']),u)<=.5
            and math.dist((g['end']['x'],g['end']['y']),v)<=.5 for u,v in ((a,b),(b,a)))]
        if len(matches)!=1:return failed
        remaining.remove(matches[0])
    return {'passed':True,'width_mm':2*r,'height_mm':cy-y0+r,'radius_mm':r,
        'wall_height_mm':cy-y0,'center_mm':[cx,cy],'simple_closed_outline':True,
        'geometry_ids':[g['id'] for g in geometries],'representation':'native_arc_and_three_lines'}


def verify_semicircular_arch(geometry):
    """Measure a sampled closed arch; never read or reconstruct its plan.

    Vertices must lie on the two walls, floor or upper semicircle. Chord
    interiors have a separate, reported approximation bound, as for the
    existing sampled-curve identity checks in this module.
    """
    import math
    from shapely.geometry import Polygon
    from .cad_geometry_measurements import closed_polyline_points
    points=closed_polyline_points(geometry)
    failed={'passed':False}
    if len(points)<7 or any(p.get('bulge',0) for p in geometry.get('vertices',[])):return failed
    if any(not math.isfinite(v) for p in points for v in p):return failed
    shape=Polygon(points)
    if not shape.is_valid or shape.area<=0:return failed
    x0,y0,x1,y1=shape.bounds
    radius=(x1-x0)/2;leg=y1-y0-radius;cx=(x0+x1)/2;cy=y0+leg
    if radius<=0 or leg<=0:return failed
    tolerance=.5
    def straight_edge(a,b):
        return ((abs(a[0]-x0)<=tolerance and abs(b[0]-x0)<=tolerance
                 or abs(a[0]-x1)<=tolerance and abs(b[0]-x1)<=tolerance)
                and all(y0-tolerance<=p[1]<=cy+tolerance for p in (a,b))
                or all(abs(p[1]-y0)<=tolerance and x0-tolerance<=p[0]<=x1+tolerance for p in (a,b)))
    max_error=0
    for a,b in zip(points,points[1:]+points[:1]):
        if straight_edge(a,b):continue
        if any(p[1]<cy-tolerance or abs(math.dist(p,(cx,cy))-radius)>tolerance for p in (a,b)):
            return {**failed,'reason':'non_semicircular_boundary_edge','edge_mm':[a,b],
                    'inferred_center_mm':[cx,cy],'inferred_radius_mm':radius}
        midpoint=((a[0]+b[0])/2,(a[1]+b[1])/2)
        max_error=max(max_error,abs(math.dist(midpoint,(cx,cy))-radius))
    from .cad_precision import ACCEPTANCE_MM
    if max_error>min(ACCEPTANCE_MM,radius*.005):return failed
    required=[(x0,y0),(x1,y0),(x0,cy),(x1,cy),(cx,y1)]
    if any(min(math.dist(p,q) for p in points)>tolerance for q in required):return failed
    return {'passed':True,'width_mm':x1-x0,'height_mm':y1-y0,'radius_mm':radius,
            'wall_height_mm':leg,'center_mm':[cx,cy],'simple_closed_outline':True,
            'max_chord_radial_error_mm':max_error,'chord_tolerance_relative_to_radius':.005,
            'absolute_chord_tolerance_mm':ACCEPTANCE_MM,
            'vertex_tolerance_mm':tolerance,'geometry_id':geometry['id']}


