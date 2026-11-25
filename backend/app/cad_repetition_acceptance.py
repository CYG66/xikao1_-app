"""Source-grounded checks for local dimensions, tiling and rotational symmetry.

Only measures submitted geometry. No point generation or geometry repair.
"""
from .cad_length_units import length_factors
import math
import re
from .cad_structure_contract import StructureContractError
from .cad_creation_intent import local_creation_objects

NUMBER=r'\d+(?:\.\d+)?'
UNIT=r'(?:毫米|厘米|米|mm|cm|m)'


def mm(value,unit):
    return float(value)*length_factors('mm')[unit.lower()]


def tiling_structure_requirements(source):
    grid=re.search(r'(\d+)\s*列\s*(\d+)\s*行',source)
    side=re.search(rf'边长\s*({NUMBER})\s*({UNIT})',source,re.I)
    if not (grid and side and '六边形' in source and re.search(r'无缝|共边',source)):
        return None
    length=mm(side[1],side[2])
    return {'columns':int(grid[1]),'rows':int(grid[2]),'cell_count':int(grid[1])*int(grid[2]),
        'cell_sides':6,'cell_side_mm':length,'neighbor_center_distance_mm':math.sqrt(3)*length,
        'instruction':'边长是单元局部尺寸，不是整体宽高。正多边形没有花瓣内谷，不要使用radial_pattern。所有单元同尺寸同朝向，相邻单元沿公共边法线平移两个内切圆半径，共享完整边且内部不重叠；错列排列，全部单元须通过公共边连通。坐标仍由模型规划并遵守plan.units，不能把毫米当米。'}


def parallel_strip_requirements(source):
    count=re.search(r'(\d+)条平行(?:横线|条带)',source)
    size=re.search(rf'每条长\s*({NUMBER})\s*({UNIT})\s*宽\s*({NUMBER})\s*({UNIT})',source,re.I)
    gap=re.search(rf'(中心距|净间距|间距)\s*({NUMBER})\s*({UNIT})',source,re.I)
    if not (count and size and gap):return None
    return {'count':int(count[1]),'length_mm':mm(size[1],size[2]),'width_mm':mm(size[3],size[4]),
        'spacing_mm':mm(gap[2],gap[3]),'spacing_reference':'center' if gap[1]=='中心距' else 'edge',
        'instruction':'长和宽属于每一条带，不能作为整体宽高。全部条带横向、相互平行并沿纵向排列；净间距不包含条带自身宽度，中心距才包含。不得用没有实际宽度的单条线替代有宽度的条带。'}


def tooth_boundary_requirements(source):
    count=re.search(r'(\d+)个齿',source)
    diameter=re.search(rf'外径\s*({NUMBER})\s*({UNIT})',source,re.I)
    if not (count and diameter and '轮廓' in source):return None
    if not 3<=int(count[1])<=100:return None
    root=re.search(rf'齿根圆直径\s*({NUMBER})\s*({UNIT})',source,re.I)
    width=re.search(rf'齿顶角宽\s*({NUMBER})\s*度',source)
    return {'count':int(count[1]),'period_degrees':360/int(count[1]),'outer_radius_mm':mm(diameter[1],diameter[2])/2,
        'root_radius_mm':mm(root[1],root[2])/2 if root else None,
        'tip_angle_degrees':float(width[1]) if width else None,
        'instruction':'齿形近似边界须表达有宽度的齿顶和较低齿根，不是单一尖点构成的星形。各齿绕共同中心等距重复。一个周期从任意径向点开始，到该点绕同一中心旋转period_degrees后的同半径点结束；沿同一极角方向依次连接齿根、齿顶、下一齿根，不得回折交叉或把齿根起点接到齿顶终点。齿顶角宽小于整个周期角度。未给出的齿根和齿顶宽度可以选择合理值并声明假设。不要添加radial_pattern断言，它不支持齿顶平台；齿数、齿顶宽度、外径及重复关系由后端独立测量。此处只验证近似轮廓，不声明工业渐开线齿形合格。'}


def branch_structure_requirements(source):
    source=source.split('\n后端试算反馈：',1)[0]
    if len(local_creation_objects(source))>1 or re.search(r'曲线|圆弧|贝塞尔|样条',source):return None
    if re.search(r'(?:生成|画|绘制|创建)\s*(?:[2-9]\d*|两|二|三|四|五|六|七|八|九|十)\s*(?:个|幅|朵|组)',source):return None
    radial=re.search(r'(\d+)\s*条对称分支',source)
    sides=re.search(r'每条分支带\s*(\d+)\s*个侧枝',source)
    if not radial or not sides:return None
    count,per=int(radial[1]),int(sides[1])
    if not 2<=count<=50 or not 1<=per<=8 or count*(per+1)>100:return None
    return {'main_count':count,'sides_per_main':per,'entity_count':count*(per+1)}


def branch_attachment_dimensions(source):
    """Shared source parsing for readiness and existing branch measurement."""
    lengths=re.findall(rf'侧枝[^，。；;\n]{{0,8}}(?:长度|长)\s*({NUMBER})\s*({UNIT})|(?:长度|长)\s*({NUMBER})\s*({UNIT})[^；;。\n]{{0,30}}?侧枝',source,re.I)
    anchors=re.findall(rf'在半径\s*({NUMBER})\s*({UNIT})\s*处',source,re.I)
    angles=re.findall(rf'与主枝夹角\s*({NUMBER})\s*度',source)
    return {'side_length_mm':next((mm(a or c,b or d) for a,b,c,d in reversed(lengths)),None),
            'anchor_radius_mm':mm(*anchors[-1]) if anchors else None,
            'branch_angle_degrees':float(angles[-1]) if angles else None}


def branch_source_ready(source):
    if not branch_structure_requirements(source):return False
    d=branch_attachment_dimensions(source)
    return (d['side_length_mm'] is not None and d['side_length_mm']>0
            and d['anchor_radius_mm'] is not None and d['anchor_radius_mm']>0
            and d['branch_angle_degrees'] is not None and 0<d['branch_angle_degrees']<180
            and bool(re.search(r'对称侧枝|侧枝镜面对称',source)))


def validate_repetition_plan(source, plan):
    """Preflight branch inventory before executing coordinates."""
    if hasattr(plan,'model_dump'):
        plan=plan.model_dump(mode='json')
    requirement=branch_structure_requirements(source)
    if not requirement:
        return None
    from .cad_structure_contract import StructureContractError
    steps=plan.get('steps') or []
    if any(step.get('op')!='add_line' for step in steps):
        return {'status':'unverified','phase':'preflight_structure',
                'reason':'branch_inventory_requires_expansion','review_required':True}
    if len(steps)!=requirement['entity_count']:
        raise StructureContractError('分支计划数量与原文不一致', {
            'phase':'preflight_structure','expected_count':requirement['entity_count'],
            'observed_steps':len(steps),'main_count':requirement['main_count'],
            'sides_per_main':requirement['sides_per_main']})
    if any(step.get('op')!='add_line' for step in steps):
        raise StructureContractError('分支计划必须保留主枝和侧枝的独立线段',
            {'phase':'preflight_structure','expected_op':'add_line'})
    return {'status':'passed','phase':'preflight_structure',**requirement}


def _staggered_grid_matches(centers,neighbor_vectors,columns,rows,tolerance=.5):
    """Recognize a rectangular staggered lattice from measured cell centres.

    Predictions are comparisons only: this verifier never emits CAD points.
    Accept either flat- or point-topped layouts and rigidly rotated grids.
    """
    if len(centers)!=columns*rows or min(columns,rows)<1:return False
    for a in neighbor_vectors:
        for b in neighbor_vectors:
            if abs(sum(x*y for x,y in zip(a,b))-.5*math.hypot(*a)*math.hypot(*b))>1e-5*max(1,math.hypot(*a)*math.hypot(*b)):continue
            perpendicular=[b[k]-.5*a[k] for k in range(2)]
            for stagger_columns in (True,False):
                u,v=(perpendicular,a) if stagger_columns else (a,perpendicular)
                for origin in centers:
                    used=set()
                    for j in range(rows):
                        for i in range(columns):
                            parity=i%2 if stagger_columns else j%2
                            point=[origin[k]+i*u[k]+j*v[k]+.5*parity*a[k] for k in range(2)]
                            matches=[index for index,c in enumerate(centers) if index not in used and math.dist(point,c)<=tolerance]
                            if len(matches)!=1:break
                            used.add(matches[0])
                        else:continue
                        break
                    else:
                        if len(used)==len(centers):return True
    return False


def verify_repetition_requirements(source,geometries):
    source=source.split('\n后端试算反馈：',1)[0]
    checks=[]
    measured_contracts={}
    if len(local_creation_objects(source))>1:
        return {'status':'not_checked','coverage':'unscoped_multiple_objects','checks':[]}
    gs=[g for g in geometries if g.get('selected') is not False
        and g.get('role') not in {'reference','annotation','ignored'}]
    def require(ok,name,measurements=None):
        if not ok:raise StructureContractError('重复结构验收失败：'+name,
            {'authority':'backend_measured_geometry','check':name,'measurements':measurements,
             **({'geometry_ids':[gs[i]['id'] for i in measurements['cells']],
                 'repair_instruction':'按原文局部尺寸和关系修正相关部件，保留无关正确部件；不得改变用户尺寸来绕过关系验收。'}
                if isinstance(measurements,dict) and 'cells' in measurements else {})})
        checks.append({'name':name,'status':'passed','authority':'backend_measured_geometry',
                       **({'measurements':measurements} if measurements is not None else {})})
    teeth=tooth_boundary_requirements(source)
    if teeth:
        from shapely.affinity import rotate
        from .cad_path_relation_acceptance import assemble_closed_boundary
        polygon=assemble_closed_boundary(gs)
        tooth_cells=list(range(len(gs)))
        checks.append({'name':'单一闭合齿形边界','status':'passed','authority':'backend_measured_geometry'})
        xy=list(polygon.exterior.coords)
        if len(xy)>1 and math.dist(xy[0],xy[-1])<=.5:xy.pop()
        require(len(xy)>=3 and polygon.is_valid,'齿形边界有效')
        # Odd repeat counts do not have a bounding-box-centred origin.
        cx,cy=polygon.centroid.x,polygon.centroid.y
        radii=[math.hypot(x-cx,y-cy) for x,y in xy];radius=teeth['outer_radius_mm']
        require(abs(max(radii)-radius)<=.5,'齿形外径',{'cells':tooth_cells,'actual_mm':2*max(radii),'expected_mm':2*radius})
        outer=[abs(r-radius)<=.5 for r in radii]
        starts=[i for i,value in enumerate(outer) if value and not outer[i-1]]
        widths=[]
        for start in starts:
            run=[start];i=(start+1)%len(xy)
            while outer[i] and i!=start:run.append(i);i=(i+1)%len(xy)
            a,b=xy[run[0]],xy[run[-1]]
            angle=abs((math.atan2(b[1]-cy,b[0]-cx)-math.atan2(a[1]-cy,a[0]-cx)+math.pi)%math.tau-math.pi)
            widths.append(math.degrees(angle) if len(run)>=2 else 0)
        require(len(starts)==teeth['count'] and all(w>0 for w in widths),'有宽度齿顶的数量',
            {'cells':tooth_cells,'expected':teeth['count'],'actual':len(starts),'tip_width_degrees':widths})
        if teeth['tip_angle_degrees'] is not None:
            require(all(abs(w-teeth['tip_angle_degrees'])<=.05 for w in widths),'齿顶角宽',{'cells':tooth_cells,'actual_degrees':widths,'expected_degrees':teeth['tip_angle_degrees']})
        if teeth['root_radius_mm'] is not None:
            require(abs(min(radii)-teeth['root_radius_mm'])<=.5,'齿根圆半径',{'cells':tooth_cells,'actual_mm':min(radii),'expected_mm':teeth['root_radius_mm']})
        error=polygon.boundary.hausdorff_distance(rotate(polygon,360/teeth['count'],origin=(cx,cy)).boundary)
        require(error<=.5,'齿形旋转重复关系',{'cells':tooth_cells,'hausdorff_error_mm':error})
        measured_contracts['tooth_boundary']={'count':len(starts),'outer_diameter_mm':2*max(radii),
            'root_diameter_mm':2*min(radii),'tip_angles_degrees':widths,'center_mm':[cx,cy],
            'geometry_ids':[g['id'] for g in gs]}
    strips=parallel_strip_requirements(source)
    if strips:
        from .cad_semantic_acceptance import _corners
        from shapely.geometry import Polygon
        require(strips['count']>0 and strips['length_mm']>0 and strips['width_mm']>0
            and strips['spacing_mm']>=0,'条带数量、尺寸和间距范围')
        require(len(gs)==strips['count'],'平行条带数量',{'actual':len(gs),'expected':strips['count']})
        boxes=[]
        for i,g in enumerate(gs):
            points=_corners([(p['x'],p['y']) for p in g.get('vertices',[])])
            require(g.get('type')=='polyline' and g.get('closed') and len(points)==4
                and not any(p.get('bulge',0)!=0 for p in g.get('vertices',[]))
                and Polygon(points).is_valid and Polygon(points).area>0,
                '条带闭合直边矩形',{'cells':[i]})
            xs,ys=zip(*points);x,y,X,Y=min(xs),min(ys),max(xs),max(ys)
            require(all(any(math.dist(p,q)<=.5 for p in points) for q in [(x,y),(X,y),(X,Y),(x,Y)])
                and abs(X-x-strips['length_mm'])<=.5 and abs(Y-y-strips['width_mm'])<=.5,
                '每条横向条带长宽',{'cells':[i],'actual_mm':[X-x,Y-y],'expected':strips})
            boxes.append((x,y,X,Y,i))
        boxes.sort(key=lambda b:b[1])
        require(all(abs(b[0]-boxes[0][0])<=.5 and abs(b[2]-boxes[0][2])<=.5 for b in boxes),
            '条带横向对齐',{'cells':list(range(len(gs)))})
        for a,b in zip(boxes,boxes[1:]):
            actual=(b[1]+b[3]-a[1]-a[3])/2 if strips['spacing_reference']=='center' else b[1]-a[3]
            require(abs(actual-strips['spacing_mm'])<=.5,'平行条带间距',{
                'cells':[a[4],b[4]],'actual_mm':actual,'expected_mm':strips['spacing_mm'],
                'spacing_reference':strips['spacing_reference']})
        measured_contracts['parallel_strips']={**strips,'frames_mm':[list(box[:4]) for box in boxes]}
    # Width/height scoped by “每级” cannot be interpreted as whole bounds.
    stair=re.search(rf'(\d+)\s*级.*?每级\s*宽\s*({NUMBER})\s*({UNIT})\s*高\s*({NUMBER})\s*({UNIT})',source,re.I)
    if stair:
        count=int(stair[1]);width=mm(stair[2],stair[3]);height=mm(stair[4],stair[5])
        require(count>0 and width>0 and height>0,'台阶数量和局部尺寸必须为正')
        require(len(gs)==1 and gs[0].get('type')=='polyline','单一台阶轮廓')
        from shapely.geometry import LineString, Polygon
        xy=[(p['x'],p['y']) for p in gs[0]['vertices']]
        boundary=xy+[xy[0]] if gs[0].get('closed') and xy and xy[0]!=xy[-1] else xy
        require(len(xy)>=2 and not any(p.get('bulge',0)!=0 for p in gs[0]['vertices'])
            and LineString(boundary).is_simple
            and (not gs[0].get('closed') or Polygon(xy).is_valid), '台阶必须是无自交直边轮廓')
        points=gs[0]['vertices'];segments=[(b['x']-a['x'],b['y']-a['y']) for a,b in zip(points,points[1:])]
        if gs[0].get('closed') and math.dist((points[0]['x'],points[0]['y']),(points[-1]['x'],points[-1]['y']))>.5:
            segments.append((points[0]['x']-points[-1]['x'],points[0]['y']-points[-1]['y']))
        valid=False;candidates=[]
        for start in range(len(segments)) if gs[0].get('closed') else [0]:
            ordered=segments[start:]+segments[:start];steps=ordered[:count*2];base=ordered[count*2:]
            horizontal=[abs(dy)<=.5 and abs(abs(dx)-width)<=.5 for dx,dy in steps]
            vertical=[abs(dx)<=.5 and abs(abs(dy)-height)<=.5 for dx,dy in steps]
            valid_steps=(len(steps)==count*2 and sum(horizontal)==count and sum(vertical)==count
                and all(horizontal[i]!=horizontal[i-1] for i in range(1,len(steps)))
                and abs(abs(sum(dx for dx,dy in steps))-count*width)<=.5
                and abs(abs(sum(dy for dx,dy in steps))-count*height)<=.5)
            valid_base=(not base and not gs[0].get('closed')) or (len(base)==2
                and any(abs(base[i][0])<=.5 and abs(abs(base[i][1])-count*height)<=.5
                    and abs(base[1-i][1])<=.5 and abs(abs(base[1-i][0])-count*width)<=.5
                    for i in (0,1)))
            valid=valid or (valid_steps and valid_base)
            if valid_steps and valid_base:
                origin=[points[start]['x'],points[start]['y']]
                finish=[origin[0]+sum(dx for dx,dy in steps),origin[1]+sum(dy for dx,dy in steps)]
                candidates.extend([{'start_mm':origin,'end_mm':finish},
                                   {'start_mm':finish,'end_mm':origin}])
        require(valid,
            '每级尺寸及交替数量',{'segments_mm':segments,'step_width_mm':width,'step_height_mm':height})
        measured_contracts['stairs']={'count':count,'step_width_mm':width,'step_height_mm':height,
                                     'traversals':candidates,'geometry_id':gs[0]['id']}
    grid=re.search(r'(\d+)\s*列\s*(\d+)\s*行',source)
    side=re.search(rf'边长\s*({NUMBER})\s*({UNIT})',source,re.I)
    if grid and side and re.search(r'六边形',source) and re.search(r'无缝|共边',source):
        from shapely.geometry import Polygon
        count=int(grid[1])*int(grid[2]);length=mm(side[1],side[2]);polygons=[]
        require(count>0 and len(gs)==count,'阵列单元数量',{'expected':count,'actual':len(gs)})
        for cell_index,g in enumerate(gs):
            points=g.get('vertices') or []
            if len(points)>1 and points[0]==points[-1]:points=points[:-1]
            require(g.get('type')=='polyline' and g.get('closed') and len(points)==6,'闭合六边形单元')
            xy=[(p['x'],p['y']) for p in points];polygon=Polygon(xy)
            cx=sum(x for x,y in xy)/6;cy=sum(y for x,y in xy)/6
            require(polygon.is_valid and all(abs(math.dist(a,b)-length)<=.5 for a,b in zip(xy,xy[1:]+xy[:1]))
                and all(abs(math.dist((cx,cy),p)-length)<=.5 for p in xy),'正六边形局部边长',
                {'cells':[cell_index],'expected_side_length_mm':length,
                 'actual_side_lengths_mm':[math.dist(a,b) for a,b in zip(xy,xy[1:]+xy[:1])],
                 'actual_vertex_radii_mm':[math.dist((cx,cy),p) for p in xy],
                 'center_mm':[cx,cy],'required_neighbor_center_distance_mm':math.sqrt(3)*length})
            polygons.append(polygon)
        centers=[[p.centroid.x,p.centroid.y] for p in polygons]
        first=list(polygons[0].exterior.coords)[:-1];center=centers[0]
        neighbor_vectors=[[a[k]+b[k]-2*center[k] for k in range(2)] for a,b in zip(first,first[1:]+first[:1])]
        adjacency={i:set() for i in range(count)}
        conflicts=[]
        for i in range(count):
            for j in range(i):
                overlap=polygons[i].intersection(polygons[j]).area
                if overlap>1:
                    conflicts.append({'cells':[i,j],'geometry_ids':[gs[i]['id'],gs[j]['id']],
                        'overlap_area_mm2':overlap,
                        'centers_mm':[[polygons[k].centroid.x,polygons[k].centroid.y] for k in (i,j)]})
                # Permit sub-millimetre coordinate rounding at a shared edge.
                shared=polygons[i].boundary.intersection(polygons[j].boundary.buffer(.25)).length
                if shared>=length-.5:adjacency[i].add(j);adjacency[j].add(i)
        if conflicts:
            require(False,'单元内部不得重叠',{
                'cells':sorted({k for pair in conflicts for k in pair['cells']}),
                'overlap_pairs':conflicts,'maximum_overlap_area_mm2':1,
                'centers_mm':centers,'validated_cell_neighbor_displacements_mm':neighbor_vectors,
                'required_neighbor_center_distance_mm':math.sqrt(3)*length,
                'instruction':'同时修复全部列出的冲突对；不能只修第一对后把重叠转移给其他邻居。边长和六边形形状保持不变，只调整重复单元的整体位置。必须使用当前实测六边形的公共边法向邻接位移，不能混用平顶与尖顶阵列的中心坐标公式。位移为毫米，须按plan.units换算；这是测量诊断，不是替换点集。'})
        visited=set();pending=[0] if count else []
        while pending:
            node=pending.pop()
            if node not in visited:visited.add(node);pending.extend(adjacency[node]-visited)
        require(len(visited)==count,'全部单元通过完整公共边连通',{
            'cells':list(range(count)),'connected_cells':sorted(visited),
            'adjacency':{str(i):sorted(v) for i,v in adjacency.items()},'centers_mm':centers,
            'validated_cell_neighbor_displacements_mm':neighbor_vectors,
            'required_neighbor_center_distance_mm':math.sqrt(3)*length,
            'instruction':'单元形状和边长已正确；按实际单元的公共边法向邻接位移统一修正排列，不能用外接圆直径作中心距。位移是毫米测量，按plan.units换算，不是替换点集。'})
        grid_ok=_staggered_grid_matches(centers,neighbor_vectors,int(grid[1]),int(grid[2]))
        require(grid_ok,'来源行列数与蜂窝错列布局',{'cells':list(range(count)),
            'columns':int(grid[1]),'rows':int(grid[2]),'centers_mm':centers,
            'validated_cell_neighbor_displacements_mm':neighbor_vectors})
        measured_contracts['hexagonal_tiling']={'columns':int(grid[1]),'rows':int(grid[2]),
            'count':count,'side_length_mm':length,'center_grid_verified':True,'centers_mm':centers,
            'geometry_ids':[g['id'] for g in gs]}
    network=branch_structure_requirements(source)
    if network:
        count=network['main_count'];per=network['sides_per_main']
        require(count>=2 and len(gs)==count*(per+1) and all(g.get('type')=='line' for g in gs),'主枝及侧枝总数量')
        edges=[tuple((g[k]['x'],g[k]['y']) for k in ('start','end')) for g in gs]
        # Centroid of all endpoints is rotation invariant, including when
        # branches share a center but their endpoints are not unique.
        cx=sum(p[0] for e in edges for p in e)/(2*len(edges));cy=sum(p[1] for e in edges for p in e)/(2*len(edges))
        center=(cx,cy);main=[];sides=[]
        for a,b in edges:
            if math.dist(a,center)<=.5:main.append((a,b))
            elif math.dist(b,center)<=.5:main.append((b,a))
            else:sides.append((a,b))
        require(len(main)==count and len(sides)==count*per,'主枝必须连接共同中心')
        dimensions=branch_attachment_dimensions(source)
        side_length=dimensions['side_length_mm'];anchor_radius=dimensions['anchor_radius_mm'];branch_angle=dimensions['branch_angle_degrees']
        assigned=set()
        for _,end in main:
            length=math.dist(end,center)
            require(length>.5,'主枝不得退化')
            ux=(end[0]-cx)/length;uy=(end[1]-cy)/length
            attached=[]
            for index,edge in enumerate(sides):
                if index in assigned:continue
                for anchor,tip in (edge,edge[::-1]):
                    x,y=anchor[0]-cx,anchor[1]-cy;along=x*ux+y*uy;cross=x*uy-y*ux
                    if .5<along<length-.5 and abs(cross)<=.5:
                        attached.append(((tip[0]-anchor[0])*ux+(tip[1]-anchor[1])*uy,
                                         -(tip[0]-anchor[0])*uy+(tip[1]-anchor[1])*ux,along))
                        assigned.add(index);break
            require(len(attached)==per,'每条主枝连接指定数量侧枝')
            if side_length is not None:
                require(all(abs(math.hypot(a,b)-side_length)<=.5 for a,b,_ in attached),'侧枝原文长度')
            if anchor_radius is not None:
                require(all(abs(position-anchor_radius)<=.5 for _,_,position in attached),'侧枝原文连接位置')
            if branch_angle is not None:
                require(all(abs(a/max(math.hypot(a,b),1e-9)-math.cos(math.radians(branch_angle)))<=.001
                            for a,b,_ in attached),'侧枝原文夹角')
            if per==2:
                a,b=attached
                require(abs(a[0]-b[0])<=.5 and abs(a[1]+b[1])<=.5
                    and abs(a[2]-b[2])<=.5 and abs(a[1])>.5,'同一主枝两侧枝镜面对称')
        require(len(assigned)==len(sides),'不得存在游离侧枝')
        radius=re.search(rf'最大半径\s*({NUMBER})\s*({UNIT})',source,re.I)
        if radius:
            target=mm(radius[1],radius[2]);actual=max(math.dist(center,p) for edge in edges for p in edge)
            require(abs(actual-target)<=.5,'整体最大半径',{'expected_mm':target,'actual_mm':actual})
        angle=math.tau/count;c,s=math.cos(angle),math.sin(angle)
        remaining=list(edges)
        for edge in edges:
            rotated=[(cx+(x-cx)*c-(y-cy)*s,cy+(x-cx)*s+(y-cy)*c) for x,y in edge]
            index=next((i for i,(a,b) in enumerate(remaining) if
                (math.dist(a,rotated[0])<=.5 and math.dist(b,rotated[1])<=.5)
                or (math.dist(b,rotated[0])<=.5 and math.dist(a,rotated[1])<=.5)),None)
            require(index is not None,'各分支旋转对应一致，侧枝长度与位置对称')
            remaining.pop(index)
        measured_contracts['radial_branches'] = {
            **network, 'center_mm':list(center),
            'main_radii_mm':[math.dist(center,end) for _,end in main],
            'maximum_radius_mm':max(math.dist(center,p) for edge in edges for p in edge),
            'side_length_mm':side_length,'anchor_radius_mm':anchor_radius,
            'branch_angle_degrees':branch_angle,
            'rotation_and_attachment_verified':True}
    return {'status':'partial' if checks else 'not_checked','coverage':'explicit_repetition_relations_only',
            'checks':checks,'measured_contracts':measured_contracts,'geometry_ids':[g['id'] for g in gs]}
