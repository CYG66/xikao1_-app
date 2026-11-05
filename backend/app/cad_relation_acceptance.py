"""Conservative source-bound relations over independently matched primitives.

No model labels, geometry generation or geometric repair is performed here.
"""
import math
import re

from .cad_structure_contract import StructureContractError


def extract_named_relations(text, subjects):
    from .cad_source_acceptance import source_texts
    names='|'.join(re.escape(s) for s in sorted(set(subjects),key=len,reverse=True))
    if not names:return []
    pair=rf'(?P<a>{names})(?:与|和)(?P<b>{names})'
    patterns=[(pair+r'(?:的)?端点相接','endpoint_connected'),
        (pair+r'(?:内部)?不重叠','interiors_disjoint'),(pair+r'外切','externally_tangent'),
        (rf'(?P<a>{names})位于(?P<b>{names})内部','inside')]
    for phrase,kind in [('左侧','left_of'),('右侧','right_of'),('上方','above'),('下方','below')]:
        patterns.append((rf'(?P<a>{names})完全位于(?P<b>{names})(?:的)?{phrase}',kind))
    result=[]
    for i,source in enumerate(source_texts(text)):
        for match in re.finditer(r'[^，,。；;\n]+',source):
            clause=match[0].strip()
            for pattern,kind in patterns:
                parsed=re.fullmatch(pattern,clause)
                if parsed and parsed['a']!=parsed['b']:
                    start=match.start()+len(match[0])-len(match[0].lstrip())
                    result.append({'subjects':[parsed['a'],parsed['b']],'kind':kind,
                        'source_id':f'source-{i+1}',
                        'evidence':{'start':start,'end':start+len(clause),'text':clause}})
                    break
    return result


def _region(g):
    from .cad_structure_contract import _frame
    if g.get('type')=='circle':
        return ('circle',(g['center']['x'],g['center']['y']),g['radius'])
    frame=_frame(g)
    return ('rectangle',frame) if frame else None


def _corners(region):
    x,y,w,h=region[1]
    return [(x,y),(x+w,y),(x+w,y+h),(x,y+h)]


def _inside(a,b,tolerance):
    if b[0]=='rectangle':
        x,y,w,h=b[1]
        if a[0]=='circle':
            (cx,cy),r=a[1:]
            points=[(cx-r,cy-r),(cx+r,cy+r)]
        else:points=_corners(a)
        return all(x-tolerance<=px<=x+w+tolerance and y-tolerance<=py<=y+h+tolerance for px,py in points)
    if a[0]=='circle':return math.dist(a[1],b[1])+a[2]<=b[2]+tolerance
    return all(math.dist(p,b[1])<=b[2]+tolerance for p in _corners(a))


def _disjoint(a,b,tolerance):
    if a[0]==b[0]=='circle':return math.dist(a[1],b[1])>=a[2]+b[2]-tolerance
    if a[0]==b[0]=='rectangle':
        x,y,w,h=a[1];xx,yy,ww,hh=b[1]
        return min(x+w,xx+ww)-max(x,xx)<=tolerance or min(y+h,yy+hh)-max(y,yy)<=tolerance
    if a[0]=='rectangle':a,b=b,a
    (cx,cy),r=a[1:];x,y,w,h=b[1]
    closest=(min(max(cx,x),x+w),min(max(cy,y),y+h))
    return math.dist((cx,cy),closest)>=r-tolerance


def _endpoints(g):
    if g.get('type')=='line':return [(g[k]['x'],g[k]['y']) for k in ('start','end')]
    if g.get('type')=='arc':
        return [(g['center']['x']+g['radius']*math.cos(math.radians(g[k])),
                 g['center']['y']+g['radius']*math.sin(math.radians(g[k]))) for k in ('start_angle','end_angle')]
    return None


def verify_named_relations(text, geometries, bindings):
    from .cad_construction import construction_geometry_bounds
    by_id={g['id']:g for g in geometries}
    subjects={b['subject']:b['geometry_ids'] for b in bindings}
    checks=[]
    for relation in extract_named_relations(text,subjects):
        ids=[subjects[s][0] for s in relation['subjects']]
        a,b=[by_id[i] for i in ids]
        kind=relation['kind'];tolerance=.5;valid=None
        regions=[_region(g) for g in (a,b)]
        if kind=='inside' and all(regions):valid=_inside(*regions,tolerance)
        elif kind=='interiors_disjoint' and all(regions):valid=_disjoint(*regions,tolerance)
        elif kind=='externally_tangent' and all(r and r[0]=='circle' for r in regions):
            valid=abs(math.dist(regions[0][1],regions[1][1])-regions[0][2]-regions[1][2])<=tolerance
        elif kind=='endpoint_connected':
            aa,bb=_endpoints(a),_endpoints(b)
            if aa and bb:valid=min(math.dist(x,y) for x in aa for y in bb)<=tolerance
        elif kind in {'left_of','right_of','above','below'}:
            aa,bb=construction_geometry_bounds([a]),construction_geometry_bounds([b])
            if kind=='left_of':valid=aa['max_x']<=bb['min_x']+tolerance
            elif kind=='right_of':valid=aa['min_x']>=bb['max_x']-tolerance
            elif kind=='above':valid=aa['min_y']>=bb['max_y']-tolerance
            else:valid=aa['max_y']<=bb['min_y']+tolerance
        check={**relation,'geometry_ids':ids,'status':'passed' if valid else 'unverified' if valid is None else 'failed',
            'authority':'backend_measured_geometry','tolerance_mm':tolerance}
        if valid is False:
            raise StructureContractError('原文部件关系不满足：'+relation['evidence']['text'],{'relation_check':check})
        if valid is None:check['reason']='unsupported_primitive_pair'
        checks.append(check)
    return {'status':'partial' if checks else 'not_checked','coverage':'explicit_named_relations_only',
        'checks':checks,'review_required':any(c['status']=='unverified' for c in checks)}
