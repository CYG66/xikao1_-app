"""Bind fully consumed repetition prose to existing measured geometry."""
from .cad_length_units import length_factors
import math
import re

from .cad_source_acceptance import N, P, source_texts
from .cad_structure_contract import StructureContractError

FACTORS=length_factors('mm')
UNIT=r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'


def verify_repetition_source_coverage(source, measured):
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    contracts=measured.get('measured_contracts') or {}
    if len(contracts)!=1 or not measured.get('checks'):
        return partial
    if any(c.get('status')!='passed' for c in measured['checks']):
        return partial
    text='\n'.join(source_texts(source));rest=text;evidence=[];extra_checks=[]
    def consume(pattern, accept):
        nonlocal rest
        matches=list(re.finditer(pattern,rest,re.I))
        if not matches or any(not accept(m) for m in matches):
            return False
        evidence.extend(m[0] for m in matches)
        rest=re.sub(pattern,' ',rest,flags=re.I)
        return True
    def mm(value,unit):return float(value)*FACTORS[unit.lower()]
    def near(a,b):return math.isfinite(a) and abs(a-b)<=1e-6
    if 'hexagonal_tiling' in contracts:
        spec=contracts['hexagonal_tiling']
        if not spec['center_grid_verified']:return partial
        if not consume(r'(\d+)\s*列\s*(\d+)\s*行',lambda m:int(m[1])==spec['columns'] and int(m[2])==spec['rows']):return partial
        if not consume(r'边长\s*('+N+r')\s*'+UNIT,lambda m:abs(mm(m[1],m[2])-spec['side_length_mm'])<=.5):return partial
        if re.search(r'共\d+个',rest) and not consume(r'共(\d+)个',lambda m:int(m[1])==spec['count']):return partial
        rest=re.sub(r'坐标单位(?:为|是)?\s*'+UNIT,' ',rest,flags=re.I)
        rest=re.sub(r'蜂窝错列共边拼接|无缝拼接|蜂窝六边形阵列|正六边形|的',' ',rest)
    elif 'tooth_boundary' in contracts:
        spec=contracts['tooth_boundary']
        if not consume(r'(\d+)个(?:等距)?齿',lambda m:int(m[1])==spec['count']):return partial
        if not consume(r'外径\s*('+N+r')\s*'+UNIT,
                       lambda m:abs(mm(m[1],m[2])-spec['outer_diameter_mm'])<=.5):return partial
        if not consume(r'齿根圆直径\s*('+N+r')\s*'+UNIT,
                       lambda m:abs(mm(m[1],m[2])-spec['root_diameter_mm'])<=.5):return partial
        if not consume(r'各齿齿顶角宽\s*('+N+r')\s*度',
                       lambda m:all(abs(float(m[1])-w)<=.05 for w in spec['tip_angles_degrees'])):return partial
        units=re.findall(UNIT,text,re.I);scales={FACTORS[u.lower()] for u in units}
        if len(scales)!=1:return partial
        scale=next(iter(scales))
        if not consume(r'中心\s*'+P,lambda m:math.dist(spec['center_mm'],[float(m[1])*scale,float(m[2])*scale])<=.5):return partial
        rest=re.sub(r'齿轮轮廓',' ',rest)
    elif 'radial_branches' in contracts:
        spec=contracts['radial_branches']
        if not spec.get('rotation_and_attachment_verified'):return partial
        if not consume(r'(\d+)\s*条对称分支',lambda m:int(m[1])==spec['main_count']):return partial
        if not consume(r'每条分支带\s*(\d+)\s*个侧枝',lambda m:int(m[1])==spec['sides_per_main']):return partial
        if not consume(r'最大半径\s*('+N+r')\s*'+UNIT,
                       lambda m:abs(mm(m[1],m[2])-spec['maximum_radius_mm'])<=.5):return partial
        pattern=r'(\d+)条主枝半径均\s*('+N+r')\s*'+UNIT
        if re.search(pattern,rest) and not consume(pattern,
                lambda m:int(m[1])==spec['main_count'] and all(abs(r-mm(m[2],m[3]))<=.5
                    for r in spec['main_radii_mm'])):return partial
        pattern=r'角间隔\s*('+N+r')\s*度'
        if re.search(pattern,rest) and not consume(pattern,
                lambda m:near(float(m[1]),360/spec['main_count'])):return partial
        pattern=(r'每条主枝在半径\s*('+N+r')\s*'+UNIT+r'\s*处有两条长度\s*('
                 +N+r')\s*'+UNIT+r'[、，,\s]*与主枝夹角\s*('+N+r')\s*度的对称侧枝')
        if re.search(pattern,rest) and not consume(pattern,
                lambda m:spec['sides_per_main']==2 and spec.get('anchor_radius_mm') is not None
                    and near(mm(m[1],m[2]),spec['anchor_radius_mm'])
                    and spec.get('side_length_mm') is not None and near(mm(m[3],m[4]),spec['side_length_mm'])
                    and spec.get('branch_angle_degrees') is not None and near(float(m[5]),spec['branch_angle_degrees'])):return partial
        pattern=r'中心\s*'+P
        if re.search(pattern,rest):
            units=re.findall(r'坐标单位(?:为|是|[:：])?\s*'+UNIT,rest,re.I)
            scales={FACTORS[u.lower()] for u in units}
            if len(scales)!=1:return partial
            scale=next(iter(scales))
            if not consume(pattern,lambda m:math.dist(spec['center_mm'],
                    [float(m[1])*scale,float(m[2])*scale])<=.5):return partial
        rest=re.sub(r'坐标单位(?:为|是|[:：])?\s*'+UNIT,' ',rest,flags=re.I)
        # These optional clauses are consumed only if the geometry verifier
        # actually measured the same source-bound constraints.
        for pattern,key in [
            (r'侧枝长度\s*('+N+r')\s*'+UNIT,'side_length_mm'),
            (r'在半径\s*('+N+r')\s*'+UNIT+r'\s*处','anchor_radius_mm')]:
            if re.search(pattern,rest,re.I) and not consume(pattern,
                    lambda m:spec.get(key) is not None and near(mm(m[1],m[2]),spec[key])):return partial
        pattern=r'与主枝夹角\s*('+N+r')\s*度'
        if re.search(pattern,rest) and not consume(pattern,
                lambda m:spec.get('branch_angle_degrees') is not None and near(float(m[1]),spec['branch_angle_degrees'])):return partial
        rest=re.sub(r'雪花图案',' ',rest)
    elif 'parallel_strips' in contracts:
        spec=contracts['parallel_strips']
        if not consume(r'(\d+)\s*条平行(?:横线|条带)',lambda m:int(m[1])==spec['count']):
            return partial
        if not consume(r'每条长\s*('+N+r')\s*'+UNIT+r'\s*宽\s*('+N+r')\s*'+UNIT,
                       lambda m:near(mm(m[1],m[2]),spec['length_mm']) and near(mm(m[3],m[4]),spec['width_mm'])):
            return partial
        if not consume(r'(中心距|净间距|间距)\s*('+N+r')\s*'+UNIT,
                       lambda m:('center' if m[1]=='中心距' else 'edge')==spec['spacing_reference']
                       and near(mm(m[2],m[3]),spec['spacing_mm'])):
            return partial
        rest=re.sub(r'斑马线',' ',rest)
    elif 'stairs' in contracts:
        spec=contracts['stairs']
        if not consume(r'(\d+)\s*级(?:台阶)?',lambda m:int(m[1])==spec['count']):
            return partial
        if not consume(r'每级\s*(?:宽|水平)\s*('+N+r')\s*'+UNIT+r'[、，,\s]*(?:高|竖直)\s*('+N+r')\s*'+UNIT,
                       lambda m:near(mm(m[1],m[2]),spec['step_width_mm'])
                       and near(mm(m[3],m[4]),spec['step_height_mm'])):
            return partial
        directions=list(re.finditer(r'从\s*'+P+r'\s*向(右|左)向(上|下)',rest))
        if directions:
            units=re.findall(r'坐标单位(?:为|是|[:：])?\s*'+UNIT,rest,re.I)
            scales={FACTORS[u.lower()] for u in units}
            if len(scales)!=1:return partial
            scale=next(iter(scales))
            for match in directions:
                start=[float(match[1])*scale,float(match[2])*scale]
                sx=1 if match[3]=='右' else -1;sy=1 if match[4]=='上' else -1
                valid=any(math.dist(t['start_mm'],start)<=.5
                    and sx*(t['end_mm'][0]-t['start_mm'][0])>.5
                    and sy*(t['end_mm'][1]-t['start_mm'][1])>.5 for t in spec['traversals'])
                check={'name':'explicit_step_origin_and_direction','status':'passed' if valid else 'failed',
                       'expected_start_mm':start,'direction':[sx,sy],
                       'measured_traversals':spec['traversals'],'geometry_ids':[spec['geometry_id']]}
                if not valid:
                    raise StructureContractError('台阶起点或方向不符合原文要求',check)
                extra_checks.append(check)
            evidence.extend(m[0] for m in directions)
            rest=re.sub(r'从\s*'+P+r'\s*向(右|左)向(上|下)',' ',rest)
            rest=re.sub(r'坐标单位(?:为|是|[:：])?\s*'+UNIT,' ',rest,flags=re.I)
        rest=re.sub(r'楼梯轮廓|台阶轮廓',' ',rest)
    else:
        return partial
    rest=re.sub(r'生成|创建|绘制|画出|画|请|一段|一条|一个',' ',rest)
    if rest.strip(' \t\r\n，,、。；;'):
        return {**partial,'unconsumed_text':rest.strip(),'source_evidence':source_texts(source)}
    return {'status':'passed','coverage':'complete',
            'checks':measured['checks']+extra_checks,'measured_contracts':contracts,
            'geometry_ids':measured.get('geometry_ids',[]),'authority':'backend_measured_geometry',
            'source_evidence':source_texts(source),'consumed_evidence':evidence,
            'measurement_scope':'fully_consumed_existing_repetition_measurements'}
