"""Measure source-requested path relations; never synthesize or repair CAD."""
import math
import re

from .cad_structure_contract import StructureContractError


def assemble_closed_boundary(geometries, tolerance_mm=.5):
    """Inspect an existing boundary, independent of primitive segmentation.

    Endpoints may share their measured tolerance; no missing edges are added.
    Return a polygon for measurement only, never replacement CAD geometry.
    """
    from .drawing_store import _geometry_points
    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union
    nodes=[];degrees=[];lines=[]
    def node(point):
        index=next((i for i,p in enumerate(nodes) if math.dist(p,point)<=tolerance_mm),None)
        if index is None:index=len(nodes);nodes.append(point);degrees.append(0)
        degrees[index]+=1
        return nodes[index]
    for g in geometries:
        points=[(p[0]*1000,p[1]*1000) for p in _geometry_points(g)]
        if len(points)<2:continue
        if g.get('closed') and math.dist(points[0],points[-1])>tolerance_mm:
            points.append(points[0])
        points[0]=node(points[0]);points[-1]=node(points[-1])
        lines.append(LineString(points))
    polygons=list(polygonize(unary_union(lines))) if lines else []
    if (len(lines)!=len(geometries) or not degrees or any(d!=2 for d in degrees)
            or len(polygons)!=1 or polygons[0].interiors
            or abs(sum(line.length for line in lines)-polygons[0].length)>tolerance_mm):
        raise StructureContractError('图元未组成唯一、无重复边的闭合边界',{
            'geometry_ids':[g['id'] for g in geometries],
            'endpoint_degrees':degrees,'closed_region_count':len(polygons),
            'requires_structural_replan':True,
            'repair_instruction':'保持用户部件和尺寸，将现有线段/圆弧首尾连接成唯一边界；不得用重复边、补画整圆或丢弃不相连片段绕过检查。'})
    return polygons[0]


def path_relation_requirements(text):
    from .cad_source_acceptance import source_texts
    source = '\n'.join(source_texts(text))
    return bool(re.search(r'[sSＳｓ]\s*[形型]\s*(?:分割线|分界线|曲线|路径)', source))


def verify_path_relations(text, geometries):
    arms = verify_perpendicular_arm_dimensions(text, geometries)
    if arms is not None:
        return arms
    if not path_relation_requirements(text):
        return {'status':'not_checked','coverage':'partial','checks':[]}
    from .drawing_store import _geometry_points
    from shapely.geometry import LineString, Point
    from .cad_source_acceptance import source_texts
    source='\n'.join(source_texts(text))
    pair_checks=[]
    active=[g for g in geometries if g.get('role') not in {'reference','annotation','ignored'}
            and g.get('selected') is not False]
    paths=[]
    ids=[]
    for g in active:
        if g['type'] in {'circle','text'} or g.get('closed'):
            continue
        points=_geometry_points(g)
        if len(points)>1 and math.dist(points[0],points[-1])>.0005:
            paths.append(points)
            ids.append(g['id'])
    def fail(message, **measurements):
        raise StructureContractError(message,{'authority':'backend_measured_geometry',
            'geometry_ids':ids,'required_relation':'continuous_open_s_path',
            'measurements':measurements,
            'instruction':'保留外边界与独立闭合部件，只修正开放分割路径的坐标或圆弧角度；相邻端点须重合，整条路径须连续且弯曲方向发生一次反转。'})
    if not paths:
        fail('缺少用户要求的开放S形路径。')
    nodes=[];edges=[]
    for points in paths:
        edge=[]
        for point in (points[0],points[-1]):
            index=next((i for i,p in enumerate(nodes) if math.dist(point,p)<=.0005),None)
            if index is None:
                index=len(nodes);nodes.append(point)
            edge.append(index)
        edges.append(edge)
    degrees=[sum(edge.count(i) for edge in edges) for i in range(len(nodes))]
    ends=[i for i,d in enumerate(degrees) if d==1]
    if len(ends)!=2 or any(d not in {1,2} for d in degrees):
        fail('S形路径端点未连接为一条无分叉开放链。',endpoint_degrees=degrees)
    current=ends[0];used=set();chain=[]
    while len(used)<len(edges):
        index=next((i for i,e in enumerate(edges) if i not in used and current in e),None)
        if index is None:fail('S形路径包含互不连接的片段。')
        points=paths[index] if edges[index][0]==current else list(reversed(paths[index]))
        chain.extend(points if not chain else points[1:])
        current=edges[index][1] if edges[index][0]==current else edges[index][0]
        used.add(index)
    shape=LineString(chain)
    if not shape.is_simple:fail('S形路径自相交或回走。')
    signs=[]
    for a,b,c in zip(chain,chain[1:],chain[2:]):
        ux,uy=b[0]-a[0],b[1]-a[1];vx,vy=c[0]-b[0],c[1]-b[1]
        angle=math.atan2(ux*vy-uy*vx,ux*vx+uy*vy)
        if abs(angle)>.001:
            sign=1 if angle>0 else -1
            if not signs or signs[-1]!=sign:signs.append(sign)
    if len(signs)!=2:fail('路径不符合S形的两个相反弯曲段。',curvature_sign_sequence=signs)
    outer=None
    if '外圆' in source and re.search(r'分割线|分界线',source):
        circles=[g for g in active if g['type']=='circle']
        if not circles:fail('缺少分割路径所属的外圆。')
        outer=max(circles,key=lambda g:g['radius'])
        center=[outer['center']['x']/1000,outer['center']['y']/1000];radius=outer['radius']/1000
        errors=[abs(math.dist(p,center)-radius) for p in (chain[0],chain[-1])]
        if max(errors)>.0005:fail('分割路径两端未连接外圆。',boundary_errors_m=errors)
        if any(math.dist(p,center)>radius+.0005 for p in chain):fail('分割路径超出外圆。')
        if re.search(r'经过(?:圆心|中心)|穿过(?:圆心|中心)',source) and shape.distance(Point(center))>.0005:
            fail('分割路径未经过用户指定的圆心。')
        if re.search(r'(?:两个|2个)对称小圆',source):
            inner=[g for g in circles if g['id']!=outer['id']]
            circle_ids=[g['id'] for g in inner]
            if len(inner)!=2:
                raise StructureContractError('对称小圆数量不符合要求',{'geometry_ids':circle_ids,
                    'required_count':2,'observed_count':len(inner)})
            centers=[(g['center']['x']/1000,g['center']['y']/1000) for g in inner]
            radii=[g['radius']/1000 for g in inner]
            measured={'center_symmetry_error_m':math.hypot(centers[0][0]+centers[1][0]-2*center[0],
                centers[0][1]+centers[1][1]-2*center[1]),
                'radius_difference_m':abs(radii[0]-radii[1]),
                'outer_clearance_m':[radius-math.dist(c,center)-r for c,r in zip(centers,radii)],
                'divider_clearance_m':[shape.distance(Point(c))-r for c,r in zip(centers,radii)]}
            if (measured['center_symmetry_error_m']>.0005 or measured['radius_difference_m']>.0005
                    or min(measured['outer_clearance_m'])<=.0005
                    or min(measured['divider_clearance_m'])<=.0005):
                raise StructureContractError('对称小圆未位于分割区域内部，或与边界重合相交',{
                    'geometry_ids':circle_ids,'authority':'backend_measured_geometry','measurements':measured,
                    'repair_instruction':'仅修复两个小圆的位置或半径，保留已正确的外圆及开放S形分割线。小圆须等半径、关于外圆中心对称，并严格位于各自分割区域内部，不得与外圆或分割线重合。用户未给出小圆半径时可声明建模假设，不能将分割线的半圆当成小圆。'})
            pair_checks.append({'name':'symmetric_contained_circles','status':'passed',
                'geometry_ids':circle_ids,'measurements':measured,'authority':'backend_measured_geometry'})
    return {'status':'partial','coverage':'explicit_open_s_path_relations_only',
        'checks':[{'name':'continuous_open_s_path','status':'passed','authority':'backend_measured_geometry',
                   'geometry_ids':ids,'tolerance_mm':.5}]+pair_checks}


def perpendicular_arm_requirements(text):
    """Measure a constant-width, two-arm right-angle boundary from source.

    This is an acceptance rule, not a geometry constructor. Arm lengths refer
    to the two outer extents; an explicit inner/centreline length convention
    is left to its own verifier rather than silently reinterpreted.
    """
    from .cad_source_acceptance import source_texts
    source = '\n'.join(source_texts(text))
    if not re.search(r'直角连接', source) or re.search(r'内侧长|中心线长|净长', source):
        return None
    number = r'(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)'
    arms = re.search(r'(?:两|2)条臂分别长\s*' + number + r'\s*(?:和|与|、)\s*' + number, source, re.I)
    width = re.search(r'宽\s*' + number, source, re.I)
    if not arms or not width:
        return None
    factors = {'米':1, 'm':1, '厘米':.01, 'cm':.01, '毫米':.001, 'mm':.001}
    a,b = [float(arms[i])*factors[arms[i+1].lower()] for i in (1,3)]
    w = float(width[1])*factors[width[2].lower()]
    if min(a,b) <= w:
        return None
    return {'arm_extents_m':[a,b],'width_m':w,
        'boundary_lengths_m':sorted([a,b,a-w,b-w,w,w]),
        'instruction':'两臂外侧总长分别使用所给长度，通道宽度是横截面宽度，不能作为整图宽度。直角连接后表达一条连续边界，内凹转角也是该边界的一部分，不是另一个闭合内框。只使用通用构造原语，坐标由模型规划；后端独立测量长度、直角和重复边界。'}


def verify_perpendicular_arm_dimensions(text, geometries):
    requirement=perpendicular_arm_requirements(text)
    if requirement is None:
        return None
    a,b=requirement['arm_extents_m'];w=requirement['width_m']
    from .drawing_store import _geometry_points
    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union
    from .cad_semantic_acceptance import _corners
    lines=[]
    for geometry in geometries:
        points=_geometry_points(geometry)
        if geometry.get('closed') and points and points[0]!=points[-1]:
            points=points+[points[0]]
        if len(points)>1:
            lines.append(LineString(points))
    polygons=list(polygonize(unary_union(lines))) if lines else []
    expected=sorted([a,b,a-w,b-w,w,w])
    actual=[];orthogonal=False
    if len(polygons)==1 and not polygons[0].interiors:
        corners=_corners(list(polygons[0].exterior.coords),tolerance=.0005)
        vectors=[(q[0]-p[0],q[1]-p[1]) for p,q in zip(corners,corners[1:]+corners[:1])]
        actual=sorted(math.hypot(*v) for v in vectors)
        orthogonal=(len(vectors)==6 and all(abs(u[0]*v[0]+u[1]*v[1])
            <= .0005*max(math.hypot(*u),math.hypot(*v))
            for u,v in zip(vectors,vectors[1:]+vectors[:1])))
    passed=(orthogonal and len(actual)==6
        and all(abs(x-y)<=.0005 for x,y in zip(actual,expected))
        and abs(sum(line.length for line in lines)-polygons[0].length)<=.0005)
    evidence={'geometry_ids':[g['id'] for g in geometries],
        'required_arm_extents_m':[a,b],'required_width_m':w,
        'expected_boundary_lengths_m':expected,'actual_boundary_lengths_m':actual,
        'orthogonal':orthogonal,'polygon_count':len(polygons),
        'authority':'backend_measured_geometry'}
    if not passed:
        raise StructureContractError('两臂直角连接的长度、通道宽度或边界数量不符合原始要求。',{
            **evidence,'requires_structural_replan':True,
            'repair_instruction':'以原始需求的两条臂外侧长度和通道宽度约束边界；保留一个连续无自交的边界，不得再叠加相同轮廓，不得将通道宽度当成整图宽度。错误部件可合并或删除，其错误断言须一并重新编译，不能把旧模型假设当成用户要求。'})
    return {'status':'passed','coverage':'explicit_perpendicular_arm_extents_and_width',
        'checks':[{'name':'perpendicular_arm_dimensions','status':'passed',**evidence}]}
