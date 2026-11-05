"""Measure curve identities from actual geometry; never construct curves."""
import numpy as np
from scipy.optimize import least_squares


def verify_astroid(geometry, expected_radius_mm=None):
    """Check the curve identity on vertices and between sampled vertices."""
    points=np.array([[p['x'],p['y']] for p in geometry.get('vertices') or []],dtype=float)
    if len(points)<16 or not geometry.get('closed') or not np.isfinite(points).all():
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
    if len(points)<20 or not geometry.get('closed') or not np.isfinite(points).all():
        return {'passed':False,'reason':'unsupported_or_invalid_closed_geometry'}
    span=float(np.max(np.ptp(points,axis=0)))
    if span<=0:return {'passed':False,'reason':'degenerate_geometry'}
    origin=np.mean(points,axis=0);xy=(points-origin)/span
    def residual(p):
        delta=xy-p[:2];radius=np.linalg.norm(delta,axis=1)
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
    errors=np.abs(residual(best.x));maximum=float(np.max(errors))
    return {'passed':maximum<=.005,'max_relative_radial_residual':maximum,
            'rms_relative_radial_residual':float(np.sqrt(np.mean(errors**2))),
            'tolerance_relative_to_extent':.005,'cusp_mm':(best.x[:2]*span+origin).tolist(),
            'axis_radians':float(best.x[3]),'scale_mm':float(best.x[2]*span),
            'authority':'independent_geometry_fit',
            'cusp_pointing_unit_vector':[float(np.cos(best.x[3])),float(np.sin(best.x[3]))],
            'direction_definition':'opposite the ray from cusp to its neighboring curve points'}

