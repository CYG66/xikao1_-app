"""Evaluation-only boundary connectivity, independent of production acceptance.

One physical boundary may contain multiple native entities. This does not
change legacy scores or prove the source shape, dimensions or delivery status.
"""
import math

VERSION='cad.closed-boundary-oracle.v3'


def single_closed_boundary(geometries,tolerance_mm=.5):
    from shapely.geometry import LineString,Polygon
    failed={'version':VERSION,'passed':False}
    active=[g for g in geometries if g.get('selected') is not False and g.get('role') not in {'reference','annotation','ignored'}]
    paths=[]
    try:
        for g in active:
            if g['type']=='line':points=[tuple(g[k][a] for a in ('x','y')) for k in ('start','end')]
            elif g['type']=='polyline':
                if any(p.get('bulge',0) for p in g['vertices']):return {**failed,'reason':'unsupported_bulge'}
                points=[(p['x'],p['y']) for p in g['vertices']]
                if g.get('closed') and points and points[-1]!=points[0]:points.append(points[0])
            elif g['type']=='arc':
                r=float(g['radius']);delta=float(g['end_angle'])-float(g['start_angle'])
                if r<=0 or abs(delta)<1e-9:return {**failed,'reason':'invalid_arc'}
                clockwise=g.get('clockwise',False)
                sweep=(-((-delta)%360 or 360)) if clockwise else (delta%360 or 360)
                step=2*math.acos(max(-1,min(1,1-min(.1,r*.1)/r)))
                count=max(2,math.ceil(abs(math.radians(sweep))/step))
                if count>2048:return {**failed,'reason':'sampling_budget'}
                angles=[math.radians(g['start_angle']+sweep*i/count) for i in range(count+1)]
                points=[(g['center']['x']+r*math.cos(a),g['center']['y']+r*math.sin(a)) for a in angles]
            else:return {**failed,'reason':'unsupported_entity'}
            if len(points)<2 or not all(math.isfinite(v) for p in points for v in p):return {**failed,'reason':'invalid_coordinates'}
            if any(math.dist(a,b)<1e-9 for a,b in zip(points,points[1:])):return {**failed,'reason':'zero_edge'}
            paths.append(points)
        if not paths:return {**failed,'reason':'empty'}
        nodes=[];adjacency={};ends=[]
        def node(point):
            matches=[i for i,cluster in enumerate(nodes) if all(math.dist(point,p)<=tolerance_mm for p in cluster)]
            if len(matches)>1:raise ValueError('ambiguous_endpoint_cluster')
            if matches:
                nodes[matches[0]].append(point);return matches[0]
            nodes.append([point]);return len(nodes)-1
        for index,path in enumerate(paths):
            a,b=node(path[0]),node(path[-1]);ends.append((a,b))
            adjacency.setdefault(a,[]).append(index);adjacency.setdefault(b,[]).append(index)
        if any(len(edges)!=2 for edges in adjacency.values()):return {**failed,'reason':'open_or_branched_boundary'}
        current=ends[0][0];start=current;used=set();ordered=[]
        while len(used)<len(paths):
            edge=next((i for i in adjacency[current] if i not in used),None)
            if edge is None:return {**failed,'reason':'multiple_boundary_components'}
            a,b=ends[edge];path=paths[edge] if a==current else list(reversed(paths[edge]))
            if not ordered:ordered.extend(path)
            else:ordered.extend(path[1:])
            used.add(edge);current=b if a==current else a
        if current!=start:return {**failed,'reason':'open_boundary'}
        ordered[-1]=ordered[0]
        ring=LineString(ordered);polygon=Polygon(ordered)
        if not ring.is_ring or not ring.is_simple or not polygon.is_valid or polygon.area<=0:
            return {**failed,'reason':'self_intersecting_or_degenerate_boundary'}
        return {'version':VERSION,'passed':True,'physical_boundary_count':1,
                'entity_count':len(active),'geometry_ids':[g['id'] for g in active],
                'endpoint_tolerance_mm':tolerance_mm,'maximum_arc_chord_error_mm':.1}
    except (KeyError,TypeError,ValueError,OverflowError,ZeroDivisionError) as exc:
        return {**failed,'reason':'invalid_or_ambiguous_geometry','detail':str(exc)}
