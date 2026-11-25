"""Versioned evaluation-only oracles; no production acceptance imports.

The projection oracle reconstructs cube incidence from endpoint adjacency,
independently of the production verifier's parallel-family/sign search.
"""
from collections import Counter
from itertools import combinations
import math

VERSION='cad.business-oracles.v2'


def retained_circle_rotation(before,after,response):
    source=next((v for v in before.get('variants',[]) if v['id']==response.get('source_variant_id')),None)
    gs=(source or {}).get('geometries') or []
    params=(response.get('cad_edit_contract') or {}).get('parameters') or {}
    angle=params.get('angle_degrees')
    valid_circle=(len(gs)==1 and gs[0].get('type')=='circle' and gs[0].get('radius',0)>0
                  and all(math.isfinite(float(gs[0].get('center',{}).get(k,float('nan')))) for k in ('x','y')))
    checks={
        'accepted_source':bool(source and source.get('acceptance_summary',{}).get('status')=='passed'),
        'successful_noop_receipt':response.get('ok') is True and response.get('cad_edit_outcome')=='already_satisfied' and response.get('variant_saved') is False,
        'same_project':bool(before.get('id') and before['id']==after.get('id')==response.get('project_id')),
        'source_snapshot_and_version_inventory_unchanged':before.get('variants')==after.get('variants'),
        'retained_source_delivery':response.get('candidate_visibility',{}).get('status')=='retained_source',
        'rotation_invariance_proved':valid_circle and isinstance(angle,(float,int)) and math.isfinite(angle)
                                    and params.get('pivot')=='instance_center'
                                    and response.get('cad_edit_contract',{}).get('operation')=='rotate',
    }
    return {'version':VERSION,'passed':all(checks.values()),'checks':checks}


def projected_cube_incidence(geometries,edge_length_mm,tolerance_mm=.5):
    def fail(reason):return {'version':VERSION,'passed':False,'reason':reason}
    active=[g for g in geometries if g.get('selected') is not False and g.get('role') not in {'annotation','reference','ignored'}]
    if len(active)!=12 or any(g.get('type')!='line' for g in active):return fail('requires_twelve_actual_lines')
    if not math.isfinite(edge_length_mm) or edge_length_mm<=tolerance_mm:return fail('invalid_source_length')
    nodes=[];edges=[]
    def node(p):
        xy=(float(p['x']),float(p['y']))
        if not all(math.isfinite(x) for x in xy):raise ValueError('nonfinite_endpoint')
        matches=[i for i,q in enumerate(nodes) if math.dist(xy,q)<=tolerance_mm]
        if len(matches)>1:raise ValueError('ambiguous_endpoint_cluster')
        if not matches:nodes.append(xy);return len(nodes)-1
        return matches[0]
    try:
        for g in active:edges.append((node(g['start']),node(g['end'])))
    except (ValueError,KeyError,TypeError):return fail('invalid_endpoints')
    if len(nodes) not in {7,8} or any(a==b for a,b in edges):return fail('invalid_projected_vertex_inventory')
    observed=Counter(tuple(sorted(e)) for e in edges)
    if any(n!=1 for n in observed.values()):return fail('duplicate_edge')
    if any(abs(math.dist(nodes[a],nodes[b])-edge_length_mm)>tolerance_mm for a,b in edges):return fail('source_edge_length_mismatch')
    neighbors={i:set() for i in range(len(nodes))}
    for a,b in edges:neighbors[a].add(b);neighbors[b].add(a)
    for anchor,adjacent in neighbors.items():
        if len(adjacent)!=3:continue
        for adjacent_three in combinations(sorted(adjacent),3):
            origin=nodes[anchor]
            basis=[(nodes[j][0]-origin[0],nodes[j][1]-origin[1]) for j in adjacent_three]
            if any(abs(abs(sum(x*y for x,y in zip(a,b)))/(math.hypot(*a)*math.hypot(*b))-.5)>1e-6 for a,b in combinations(basis,2)):continue
            assignment=[]
            for mask in range(8):
                point=tuple(origin[k]+sum(basis[i][k] for i in range(3) if mask&(1<<i)) for k in (0,1))
                match=[j for j,q in enumerate(nodes) if math.dist(point,q)<=tolerance_mm]
                if len(match)!=1:break
                assignment.append(match[0])
            if len(assignment)!=8:continue
            predicted=Counter(tuple(sorted((assignment[m],assignment[m^(1<<i)])))
                              for m in range(8) for i in range(3) if not m&(1<<i))
            if predicted==observed:
                return {'version':VERSION,'passed':True,'checks':{
                    'source_edge_lengths':True,'isometric_axes':True,'all_twelve_cube_incidences':True,
                    'no_duplicate_or_missing_edges':True},'projected_vertex_count':len(nodes),
                    'collapsed_opposite_vertices_supported':len(nodes)==7}
    return fail('endpoint_adjacency_is_not_one_projected_cube')


def orthographic_cylinder_views(geometries,radius_mm,height_mm):
    """Independent oracle for the user's explicit two-view convention only."""
    def fail(reason):return {'schema':'cad.user-confirmed-projection.v1','passed':False,'reason':reason}
    circles=[g for g in geometries if g.get('type')=='circle']
    sides=[g for g in geometries if g.get('type')=='polyline' and g.get('closed')]
    if len(geometries)!=2 or len(circles)!=1 or len(sides)!=1:return fail('view_inventory')
    circle=circles[0];side=sides[0];raw=side.get('vertices') or []
    if any(p.get('bulge',0) for p in raw):return fail('side_must_have_straight_edges')
    points=[(float(p['x']),float(p['y'])) for p in raw]
    if len(points)>1 and math.dist(points[0],points[-1])<1e-6:points.pop()
    if len(points)!=4 or not all(math.isfinite(v) for p in points for v in p):return fail('side_rectangle_vertices')
    x,y=map(min,zip(*points));X,Y=map(max,zip(*points))
    corners={(x,y),(X,y),(X,Y),(x,Y)}
    if set(points)!=corners:return fail('side_not_axis_aligned_rectangle')
    # The four sides must follow the boundary, not traverse a diagonal.
    if any((abs(a[0]-b[0])>.5 and abs(a[1]-b[1])>.5) or math.dist(a,b)<=.5 for a,b in zip(points,points[1:]+points[:1])):return fail('side_boundary_order')
    cx,cy=float(circle['center']['x']),float(circle['center']['y']);r=float(circle['radius'])
    if not all(math.isfinite(v) for v in (cx,cy,r,radius_mm,height_mm)) or min(r,radius_mm,height_mm)<=0:return fail('invalid_dimensions')
    if max(abs(r-radius_mm),abs(X-x-2*radius_mm),abs(Y-y-height_mm))>.5:return fail('source_dimensions')
    closest=(min(max(cx,x),X),min(max(cy,y),Y))
    clearance=math.dist((cx,cy),closest)-r
    if clearance<=.5:return fail('views_not_separate')
    return {'schema':'cad.user-confirmed-projection.v1','passed':True,'checks':{
        'top_radius':True,'side_width_matches_diameter':True,'side_height':True,
        'two_separate_views':True,'side_rectangle_topology':True},'clearance_mm':clearance}
