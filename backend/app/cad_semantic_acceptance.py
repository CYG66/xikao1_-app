"""Measure narrow canonical straight-line profiles; never generate geometry.

Coverage is structural and partial, not typography or architectural compliance.
"""
import math
import re

from .cad_creation_intent import local_creation_objects
from .cad_structure_contract import StructureContractError


def nested_frame_requirement(text):
    unit=r'(毫米|厘米|米|mm|cm|m)'
    outer=re.search(r'外框边长\s*(\d+(?:\.\d+)?)\s*'+unit,text,re.I)
    inner=re.search(r'内框边长\s*(\d+(?:\.\d+)?)\s*'+unit,text,re.I)
    if not (outer and inner and re.search(r'内框居中|同心',text)):return None
    factors={'毫米':1,'mm':1,'厘米':10,'cm':10,'米':1000,'m':1000}
    return {'kind':'nested_square_frames','outer_side_mm':float(outer[1])*factors[outer[2].lower()],
        'inner_side_mm':float(inner[1])*factors[inner[2].lower()],
        'instruction':'外框和内框是两个独立闭合正方形，边长分别绑定，中心相同，内框完全在外框内部；不能把内框边长当成整体尺寸。'}


def regular_polygon_requirement(text):
    match=re.search(r'(?:正|外)?([三四五六七八九十]|\d+)(?:边形|角)(?:形)?(?:的)?[，,\s]*外接圆半径\s*(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)',text,re.I)
    if not match:return None
    counts=dict(zip('三四五六七八九十',range(3,11)))
    n=counts.get(match[1],int(match[1]) if match[1].isdigit() else 0)
    if n<3:return None
    factors={'毫米':1,'mm':1,'厘米':10,'cm':10,'米':1000,'m':1000}
    hole=re.search(r'中心圆孔半径\s*(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)',text,re.I)
    return {'kind':'regular_polygon','sides':n,
        'circumradius_mm':float(match[2])*factors[match[3].lower()],
        'hole_radius_mm':float(hole[1])*factors[hole[2].lower()] if hole else None,
        'instruction':'正多边形不是星形/花瓣，各顶点同半径且等角有序连接，不需要内谷；禁止对它使用radial_pattern花瓣断言。圆孔保持同心和独立半径。'}


def semantic_requirements(source):
    from .cad_source_acceptance import source_texts
    text='\n'.join(source_texts(source))
    if re.search(r'astroid|星形线',text,re.I):
        return [{'kind':'astroid_identity','instruction':'星形线astroid具有四个内禀尖点，按用户数学关系和最大半径构造；不要添加要求处处无尖角的radial_pattern profile=smooth断言。不能用直边四角星替代。'}]
    nested=nested_frame_requirement(text)
    if nested:return [nested]
    polygon=regular_polygon_requirement(text)
    if polygon:
        return [polygon]
    if len(local_creation_objects(text))!=1 or re.search(r'艺术字|手写|曲线字体|花体|多个|两个|两栋|[2-9]栋',text):return []
    letter=re.search(r'大写字母\s*A',text,re.I)
    if letter:
        return [{'kind':'straight_capital_a','origin':'derived_semantic_requirement','source_evidence':[letter[0]],
            'representation_contract':{'minimum_path_count':2,
                'reason':'带内部空隙的边界需要外边界与内边界分别表达；笔画网络需要分别表达斜笔与横笔，不能用连接桥把它们强塞进单一闭合路径。'},
            'instruction':'保留两侧支脚与横笔，以及两斜笔和横笔围成的上部三角区域。上部三角区域的唯一尖点朝上，尖点高于水平底边，不能画成尖点朝下的倒三角。若采用有笔画宽度的描边轮廓，必须保留对应内部空隙，不能只画拱形外框。'}]
    if '房子轮廓' in text and re.search(r'屋顶.*?三角|三角.*?屋顶',text) and '门' in text:
        return [{'kind':'triangle_roof_house','origin':'derived_semantic_requirement','source_evidence':['房子轮廓',re.search(r'屋顶.*?三角|三角.*?屋顶',text)[0],'门'],
            'instruction':'屋顶须有共同尖顶和两侧斜边，两侧墙体在同高屋檐接入，门位于墙体内且落在底边；墙和屋顶可以共用一个外轮廓，不以图元数量代替组成验收。'}]
    return []


def _corners(points,tolerance=.5):
    pts=list(points)
    if len(pts)>1 and math.dist(pts[0],pts[-1])<=tolerance:pts.pop()
    while len(pts)>3:
        for i,b in enumerate(pts):
            a,c=pts[i-1],pts[(i+1)%len(pts)]
            cross=abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))
            if cross<=tolerance*max(1,math.dist(a,c)) and (b[0]-a[0])*(c[0]-b[0])+(b[1]-a[1])*(c[1]-b[1])>=0:
                pts.pop(i);break
        else:break
    return pts


def verify_semantic_requirements(source,geometries):
    from shapely.geometry import LineString,Polygon
    from shapely.ops import polygonize,unary_union
    requirements=semantic_requirements(source)
    direct_checks=[]
    from .cad_source_acceptance import source_texts
    original='\n'.join(source_texts(source))
    if re.search(r'astroid|星形线',original,re.I):
        from .cad_curve_fit_acceptance import verify_astroid
        size=re.search(r'最大半径\s*(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)',original,re.I)
        factors={'毫米':1,'mm':1,'厘米':10,'cm':10,'米':1000,'m':1000}
        required=float(size[1])*factors[size[2].lower()] if size else None
        measured=verify_astroid(geometries[0],required) if len(geometries)==1 else {'passed':False,'geometry_count':len(geometries)}
        if not measured['passed']:
            raise StructureContractError('实际曲线不满足astroid四尖点数学关系',{
                'geometry_ids':[g['id'] for g in geometries],'authority':'backend_measured_geometry',
                'measurements':measured,'required_relation':'|x/a|^(2/3)+|y/a|^(2/3)=1（允许刚性平移和旋转）',
                'repair_instruction':'按星形线数学关系修正曲线，保留四个内禀尖点和用户尺寸，不能用直边四角星、圆或椭圆替代；普通平滑凸瓣断言不适用于该曲线。'})
        return {'status':'passed','coverage':'astroid_identity_radius_and_four_cusps',
            'checks':[{'name':'astroid_identity','status':'passed','measurements':measured}],
            'review_required':False}
    nested=nested_frame_requirement(original)
    if nested:
        if len(geometries)!=2:
            raise StructureContractError('嵌套框需要两个独立边界',{
                'geometry_ids':[g['id'] for g in geometries],'requires_structural_replan':True,
                'expected_count':2,'actual_count':len(geometries)})
        measured=[]
        for g in geometries:
            points=_corners([(p['x'],p['y']) for p in g.get('vertices',[])])
            polygon=Polygon(points) if len(points)>=3 else None
            if g.get('type')!='polyline' or not g.get('closed') or len(points)!=4 or not polygon.is_valid:
                raise StructureContractError('嵌套框必须是闭合正方形边界',{'geometry_ids':[g['id']]})
            lengths=[math.dist(p,q) for p,q in zip(points,points[1:]+points[:1])]
            edges=[(q[0]-p[0],q[1]-p[1]) for p,q in zip(points,points[1:]+points[:1])]
            if any(abs(a[0]*b[0]+a[1]*b[1])>.5*max(math.hypot(*a),math.hypot(*b))
                    for a,b in zip(edges,edges[1:]+edges[:1])):
                raise StructureContractError('嵌套框边界存在非直角连接',{'geometry_ids':[g['id']]})
            center=(sum(x for x,y in points)/4,sum(y for x,y in points)/4)
            measured.append((polygon.area,g,polygon,lengths,center))
        measured.sort(key=lambda v:v[0],reverse=True)
        for item,key in zip(measured,('outer_side_mm','inner_side_mm')):
            area,g,polygon,lengths,center=item;size=nested[key]
            if any(abs(v-size)>.5 for v in lengths) or abs(area-size*size)>size:
                raise StructureContractError('内外框局部边长或直角关系错误',{
                    'geometry_ids':[g['id']],'frame':key,'actual_side_lengths_mm':lengths,
                    'expected_side_mm':size,'actual_area_mm2':area})
        outer,inner=measured
        center_error=math.dist(outer[4],inner[4])
        if center_error>.5 or not outer[2].contains(inner[2]):
            raise StructureContractError('内框未居中或未完全位于外框内部',{
                'geometry_ids':[inner[1]['id']],'reference_geometry_id':outer[1]['id'],
                'center_error_mm':center_error,'expected_center_mm':outer[4],
                'repair_instruction':'只调整内框位置，保留内外框边长和外框几何。'})
        return {'status':'passed','coverage':'explicit_nested_square_frames',
            'checks':[{'name':'nested_frame_dimensions_center_and_containment','status':'passed',
                'outer_side_mm':nested['outer_side_mm'],'inner_side_mm':nested['inner_side_mm'],
                'center_error_mm':center_error,'geometry_ids':[g['id'] for g in geometries]}]}
    polygon=regular_polygon_requirement(original)
    if polygon:
        n=polygon['sides'];radius=polygon['circumradius_mm']
        outlines=[g for g in geometries if g.get('type')=='polyline' and g.get('closed')]
        holes=[g for g in geometries if g.get('type')=='circle']
        points=_corners([(p['x'],p['y']) for p in outlines[0].get('vertices',[])]) if len(outlines)==1 else []
        center=(sum(p[0] for p in points)/len(points),sum(p[1] for p in points)/len(points)) if points else (0,0)
        angles=[math.atan2(y-center[1],x-center[0]) for x,y in points]
        turns=[(angles[(i+1)%len(angles)]-angle+math.pi)%math.tau-math.pi for i,angle in enumerate(angles)]
        correct=(len(points)==n and all(abs(math.dist(p,center)-radius)<=.5 for p in points)
            and all(abs(abs(t)-math.tau/n)<=math.radians(.05) and t*turns[0]>0 for t in turns))
        if polygon.get('hole_radius_mm') is not None:
            correct=correct and len(geometries)==2 and len(holes)==1 and abs(holes[0]['radius']-polygon['hole_radius_mm'])<=.5 and math.dist(center,(holes[0]['center']['x'],holes[0]['center']['y']))<=.5
        if not correct:
            raise StructureContractError('正多边形边数、外接圆半径或同心圆孔不符合用户要求',{
                'geometry_ids':[g['id'] for g in geometries], 'expected':polygon,
                'observed_corner_count':len(points),'observed_radii_mm':[math.dist(p,center) for p in points],
                'requires_structural_replan':True,
                'repair_instruction':'正多边形的各角顶点在同一外接圆上，等角有序连接，不包含外峰与内谷。不要使用表示花瓣/星形的radial_pattern断言，不得增加内谷来通过它。保留用户要求的同心孔及其半径，重新编译错误断言。'})
        return {'status':'passed','coverage':'explicit_regular_polygon_and_concentric_hole',
            'checks':[{'name':'regular_polygon_dimensions','status':'passed','sides':n,'circumradius_mm':radius,'center_mm':center,'hole_radius_mm':polygon.get('hole_radius_mm')}]}
    if re.search(r'cardioid|心形线', original, re.I):
        from .cad_curve_fit_acceptance import verify_cardioid
        if len(geometries)!=1:
            raise StructureContractError('cardioid要求一个独立闭合轮廓')
        measured=verify_cardioid(geometries[0])
        if not measured['passed']:
            raise StructureContractError('实际轮廓不满足cardioid数学关系', {
                'authority':'backend_measured_geometry','geometry_id':geometries[0]['id'],
                'check':'cardioid_polar_identity','measurements':measured,
                'required_relation':'以尖点为极坐标原点，r=a*(1+cos(theta-phi))；允许平移、旋转和等比缩放',
                'repair_instruction':'当前采样轮廓与cardioid的残差超限；修正曲线数学表达式，保留用户宽度上限、闭合性和朝向，不能用普通爱心或椭圆替代，不能修改验收阈值。'})
        if re.search(r'尖点朝下', original):
            vector=measured['cusp_pointing_unit_vector']
            if vector[1] > -math.cos(math.radians(10)):
                current=math.atan2(vector[1],vector[0])
                rotation=(-math.pi/2-current+math.pi)%(2*math.pi)-math.pi
                raise StructureContractError('cardioid尖点方向不符合朝下要求', {
                    'authority':'backend_measured_geometry','geometry_id':geometries[0]['id'],
                    'measured_direction':vector,'required_direction':[0,-1],
                    'angular_tolerance_degrees':10,
                    'rotation_degrees_to_required_direction':math.degrees(rotation),
                    'measured_cusp_mm':measured['cusp_mm'],
                    'repair_instruction':'保持现有cardioid形状，仅将整个参数曲线旋转给定角度（正数逆时针，负数顺时针）。尖点坐标以毫米报告，须转换为plan.units；同时更新x/y表达式，不能只改参数区间。保留宽度上限和闭合性，不得替换为普通爱心。'})
        return {'status':'passed','coverage':'cardioid_shape_and_declared_direction',
                'checks':[{'name':'cardioid_polar_identity','status':'passed','measurements':measured}],
                'review_required':False}
    if re.search(r'爱心|心形',original) and len(geometries)==1:
        from .cad_structure_contract import _points
        points=_points(geometries[0])
        if points:
            xs,ys=zip(*points);w,h=max(xs)-min(xs),max(ys)-min(ys)
            if w>0 and h>0:
                normalized=[((x-min(xs))/w,(y-min(ys))/h) for x,y in points]
                features = {
                    'center_notch': any(abs(x-.5)<.03 and .5<y<.98 for x,y in normalized),
                    'left_upper_lobe': any(x<.45 and y>.98 for x,y in normalized),
                    'right_upper_lobe': any(x>.55 and y>.98 for x,y in normalized),
                    'lower_tip': any(abs(x-.5)<.1 and y<.01 for x,y in normalized),
                }
                if not all(features.values()):
                    raise StructureContractError('爱心缺少双侧上凸、中央凹口或下方尖点', {
                        'authority': 'backend_measured_geometry',
                        'check': 'heart_bilateral_lobes_notch_and_lower_tip',
                        'geometry_id': geometries[0]['id'],
                        'measured_features': features,
                        'failed_features': [key for key,value in features.items() if not value],
                        'normalization': 'x/y normalized independently to measured bounds [0,1]',
                        'repair_instruction': '修复失败的上方双峰、中央凹口或下方中心尖点；仅改变曲线参数区间不会改变完整周期的几何形态。保留尺寸与中心布局。',
                    })
                direct_checks.append({
                    'name':'heart_bilateral_lobes_notch_and_lower_tip',
                    'status':'passed',
                    'authority':'backend_measured_geometry',
                    'geometry_ids':[geometries[0]['id']],
                })
    if not requirements:
        return ({'status':'partial','coverage':'supported_semantic_profile',
                 'checks':direct_checks,'review_required':False}
                if direct_checks else {'status':'not_checked','coverage':'partial','checks':[]})
    gs=[g for g in geometries if g.get('selected') is not False and g.get('role') not in {'annotation','reference','ignored'}]
    if not gs or any(g.get('type') not in {'line','polyline'} for g in gs):
        return {'status':'unverified','coverage':'unsupported_profile_representation','requirements':requirements,'checks':[], 'review_required':True}
    lines=[];polys=[]
    for g in gs:
        pts=[(g[k]['x'],g[k]['y']) for k in ('start','end')] if g['type']=='line' else [(p['x'],p['y']) for p in g['vertices']]
        if g.get('closed') and pts[0]!=pts[-1]:pts.append(pts[0])
        lines.append(LineString(pts))
        if g.get('closed') and len(pts)>=4:
            polygon=Polygon(pts)
            if polygon.is_valid and polygon.area>.25:polys.append(polygon)
    network=unary_union(lines);checks=[];tolerance=.5
    def require(ok,name,measurements=None):
        if not ok:raise StructureContractError('图形语义结构验收失败：'+name,
            {'authority':'backend_measured_geometry','check':name,'measurements':measurements})
        checks.append({'name':name,'status':'passed','authority':'backend_measured_geometry',
            'geometry_ids':[g['id'] for g in gs],'measurements':measurements})
    kind=requirements[0]['kind']
    if kind=='triangle_roof_house':
        faces=list(polygonize(network))
        region=unary_union(faces)
        require(region.geom_type=='Polygon','墙体与三角屋顶必须组成一个完整区域')
        pts=_corners(region.exterior.coords)
        require(len(pts)==5,'房子外轮廓应包含两侧墙、底边和两侧三角屋顶斜边')
        apex=max(pts,key=lambda p:p[1]);i=pts.index(apex)
        left,right=sorted([pts[i-1],pts[(i+1)%5]])
        minx,miny,maxx,maxy=region.bounds
        eave=(left[1]+right[1])/2
        require(abs(left[1]-right[1])<=tolerance and apex[1]>eave+tolerance
            and left[0]+tolerance<apex[0]<right[0]-tolerance,'屋顶须为同高屋檐上的两斜边与共同尖顶')
        expected=[(minx,miny),(maxx,miny),(maxx,eave),apex,(minx,eave)]
        require(all(any(math.dist(a,b)<=tolerance for b in pts) for a in expected),'墙体须竖直连接屋檐与底边')
        doors=[]
        for face in faces:
            x,y,X,Y=face.bounds;w,h=X-x,Y-y
            if len(_corners(face.exterior.coords))!=4 or face.interiors or abs(face.area-w*h)>tolerance:continue
            if (w>tolerance and h>tolerance and w<maxx-minx-tolerance and abs(y-miny)<=tolerance
                    and x>=minx-tolerance and x+w<=maxx+tolerance and y+h<eave-tolerance):doors.append([x,y,w,h])
        require(bool(doors),'门须位于墙体内并连接底边',{'door_bounds_mm':doors})
    else:
        minx,miny,maxx,maxy=network.bounds
        triangles=[];triangle_diagnostics=[]
        for polygon in polygonize(network):
            pts=_corners(polygon.exterior.coords)
            if len(pts)!=3:continue
            diagnostic={'corners_mm':[list(p) for p in pts]}
            for j in range(3):
                a,b,tip=pts[j],pts[(j+1)%3],pts[(j+2)%3]
                if abs(a[1]-b[1])<=tolerance:
                    diagnostic.update(horizontal_base_y_mm=(a[1]+b[1])/2,tip_y_mm=tip[1],
                                      tip_above_base=tip[1]>(a[1]+b[1])/2+tolerance)
                    break
            triangle_diagnostics.append(diagnostic)
            apex=max(pts,key=lambda p:p[1]);base=[p for p in pts if p!=apex]
            if (abs(base[0][1]-base[1][1])<=tolerance and miny+tolerance<base[0][1]<apex[1]-tolerance
                    and min(p[0] for p in base)+tolerance<apex[0]<max(p[0] for p in base)-tolerance):triangles.append(polygon)
        require(bool(triangles),'大写A缺少由两斜笔与横笔围成的上部三角区域',
                {'required_relation':'triangle_tip_above_horizontal_base',
                 'observed_triangular_regions':triangle_diagnostics[:16]})
        outer=max(polys,key=lambda p:p.area) if polys else None
        nested=bool(outer and any(outer.area>t.area+.25 and outer.buffer(tolerance).covers(t) for t in triangles))
        if not nested:
            connected={0}
            while True:
                expanded=connected|{i for i,line in enumerate(lines) if any(line.distance(lines[j])<=tolerance for j in connected)}
                if expanded==connected:break
                connected=expanded
            require(len(connected)==len(lines),'大写A的三角区域须属于同一笔画结构，不能用游离三角形代替')
        bottom_probe=LineString([(minx-1,miny),(maxx+1,miny)])
        feet=network.intersection(bottom_probe)
        parts=list(feet.geoms) if hasattr(feet,'geoms') else [feet]
        contacts=[]
        for geometry,line in zip(gs,lines):
            intersection=line.intersection(bottom_probe)
            if not intersection.is_empty:
                contacts.append({'geometry_id':geometry.get('id'),'intersection_bounds_mm':list(intersection.bounds)})
        require(len(parts)==2 and parts[0].distance(parts[1])>tolerance,'大写A底部须保留分离的左右支脚',
                {'required_bottom_components':2,'actual_bottom_components':len(parts),
                 'probe_y_mm':miny,'bottom_component_bounds_mm':[list(p.bounds) for p in parts if not p.is_empty],
                 'affected_geometries':contacts,'previously_passed_checks':[{'check':c['name'],'status':'passed'} for c in checks],
                 'verified_structure':{'upper_triangle_present':True,'triangle_associated_with_letter':True},
                 'repair_guidance':'检查与底部探测线相交的路径，保留上部三角区域和原始整体宽高。脚底水平线与图形应只相交成两段互不连接的脚底；脚间内边界必须离开底线并沿上方绕过开口，不能用一条底边横跨两脚，也不能把底边移到顶端来逃避检查。'})
        top=network.intersection(LineString([(minx-1,maxy),(maxx+1,maxy)]))
        require(top.bounds[2]-top.bounds[0]<maxx-minx-tolerance,'大写A须具有向上收拢的斜笔结构')
    return {'status':'partial','coverage':kind+'_structural_relations_only','requirements':requirements,'checks':checks,'review_required':False}
