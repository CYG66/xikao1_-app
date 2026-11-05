"""Generic selected-geometry transforms, independent of template instances."""
from copy import deepcopy
import math


def apply_selected_operation(geometries,selected,edit):
    from .incremental_cad import _bounds,_translate,_rotate,_mirror_transform,_geometry_signature
    selected=sorted(selected,key=lambda g:g['id'])
    operation=edit['operation'];b=_bounds(selected)
    if b is None:return None,'无法计算选区边界。'
    cx,cy=(b[0]+b[2])/2,(b[1]+b[3])/2
    batches=[]
    if operation=='duplicate':
        direction=edit.get('direction');distance=edit.get('distance_mm')
        if direction not in {'左','右','上','下'} or not isinstance(distance,(int,float)) or distance<=0:
            return None,'请明确复制方向和正的距离。'
        size=b[2]-b[0] if direction in {'左','右'} else b[3]-b[1]
        distance+=size if edit.get('placement')=='gap' else 0
        items=deepcopy(selected)
        _translate(items,(-distance if direction=='左' else distance) if direction in {'左','右'} else 0,
            (-distance if direction=='下' else distance) if direction in {'上','下'} else 0)
        batches=[items]
    elif operation=='array':
        if edit.get('array_mode')=='rectangular':
            rows,columns=edit.get('rows'),edit.get('columns');dy,dx=edit.get('row_spacing_mm'),edit.get('column_spacing_mm')
            if not all(isinstance(v,int) and v>0 for v in (rows,columns)) or not all(isinstance(v,(int,float)) and v>0 for v in (dx,dy)):
                return None,'请补充阵列行列数以及正的行列间距。'
            if rows*columns>50:return None,'阵列数量不能超过50。'
            for row in range(rows):
                for col in range(columns):
                    if row==col==0:continue
                    items=deepcopy(selected);_translate(items,col*dx,row*dy);batches.append(items)
        else:
            count=edit.get('count')
            if not isinstance(count,int) or not 2<=count<=50:return None,'请补充2到50之间的环形阵列数量。'
            edit.setdefault('angle_degrees',360/count)
            for i in range(1,count):
                items=deepcopy(selected);_rotate(items,edit['angle_degrees']*i,cx,cy);batches.append(items)
    elif operation=='mirror':
        axis=edit.get('mirror_axis')
        if axis not in {'vertical','horizontal'}:return None,'请明确左右或上下镜像。'
        items=deepcopy(selected);_mirror_transform(items,axis,edit.get('mirror_coordinate_mm'))
        if edit.get('keep_source',True) is False:
            replacements={g['id']:g for g in items}
            return [replacements.get(g['id'],g) for g in geometries],None
        signatures={_geometry_signature(g) for g in selected}
        if all(_geometry_signature(g) in signatures for g in items):
            return None,'镜像结果与原图重合，请明确镜像轴的位置或副本的位移。'
        # Mirroring in the selected bounding-box axis may overlap the source;
        # never invent an additional translation that the user did not specify.
        batches=[items]
    elif operation=='offset':
        distance=edit.get('distance_mm');side=edit.get('offset_side')
        if not isinstance(distance,(int,float)) or distance<=0 or side not in {'inside','outside'}:
            return None,'请明确向内或向外偏移及正的距离。'
        amount=distance*(-1 if side=='inside' else 1);items=deepcopy(selected)
        from shapely.geometry import Polygon
        for g in items:
            if g['type']=='circle':
                g['radius']+=amount
                if g['radius']<=0:return None,'向内偏移超过圆形半径。'
            elif g['type']=='polyline' and g.get('closed'):
                poly=Polygon([(p['x'],p['y']) for p in g['vertices']]).buffer(amount,join_style='mitre')
                if poly.is_empty or poly.geom_type!='Polygon' or poly.interiors:
                    return None,'偏移导致空图形、分裂或孔洞，未保存。'
                g['vertices']=[{'x':x,'y':y,'z':0.0} for x,y in list(poly.exterior.coords)[:-1]]
            else:return None,'此图元尚不支持经过独立校验的等距偏移。'
        batches=[items]
    else:return None,'不支持该选区操作。'
    if sum(map(len,batches))>100:return None,'新增图元超过单次修改预算100。'
    next_id=max(g['id'] for g in geometries)+1;created=[]
    for batch in batches:
        for g in batch:
            g['id']=next_id;created.append(next_id);next_id+=1
    edit['created_geometry_ids']=created
    return geometries+[g for batch in batches for g in batch],None
