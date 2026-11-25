"""Measure native circular boundaries, an S divider and paired circular holes."""
from .cad_length_units import length_factors
import math
import re
from .cad_source_acceptance import source_texts,N
from .cad_structure_contract import StructureContractError


def verify_symmetric_divider_source(source,geometries, *, evidence_context=None):
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    text='\n'.join(source_texts(source));rest=text;checks=[]
    if not re.search(r'太极图',text) or not re.search(r'S形分割线',text,re.I):return partial
    gs=[g for g in geometries if g.get('selected') is not False and g.get('role') not in {'annotation','reference','ignored'}]
    circles=sorted([g for g in gs if g.get('type')=='circle'],key=lambda g:g['radius'])
    arcs=[g for g in gs if g.get('type')=='arc']
    def require(ok,name):
        check={'name':name,'status':'passed' if ok else 'failed','authority':'backend_measured_geometry',
               'geometry_ids':[g['id'] for g in gs]}
        if not ok:raise StructureContractError('圆形分割与对称部件验收失败：'+name,check)
        checks.append(check)
    if any(g.get('type') not in {'circle','arc'} for g in gs):return partial
    require(len(circles)==3 and len(arcs)==2 and len(gs)==5,'外圆、两个小圆和两段圆弧的完整清单')
    from .cad_geometry_measurements import measure_path_geometry,circle_facts,arc_facts
    facts=measure_path_geometry(gs,evidence_context=evidence_context)
    for g in circles:
        if g['id'] not in facts['circle_facts']:facts['circle_facts'][g['id']]=circle_facts(g)
    for g in arcs:
        if g['id'] not in facts['arc_facts']:facts['arc_facts'][g['id']]=arc_facts(g)
    dots=circles[:2];outer=circles[-1];R=facts['circle_facts'][outer['id']]['radius_mm'];O=list(facts['circle_facts'][outer['id']]['center_mm'])
    def center(g):
        group=facts['circle_facts'] if g['type']=='circle' else facts['arc_facts']
        return list(group[g['id']]['center_mm'])
    ends=[];mids=[]
    for arc in arcs:
        arc_data=facts['arc_facts'][arc['id']]
        sweep=arc_data['sweep_degrees']
        require(abs(sweep-180)<1e-6 and abs(arc_data['radius_mm']-R/2)<=.5,'两段半圆的曲率尺度')
        pair=arc_data['endpoints_mm']
        require(sum(math.dist(p,O)<=.5 for p in pair)==1,'分割线在圆心相连')
        end=max(pair,key=lambda p:math.dist(p,O));ends.append(end)
        require(abs(math.dist(end,O)-R)<=.5,'分割线外端落在外圆')
        mids.append(arc_data['midpoint_90_mm'])
    require(math.dist([(ends[0][i]+ends[1][i])/2 for i in range(2)],O)<=.5,'外端关于圆心对称')
    axis=[ends[0][i]-O[i] for i in range(2)]
    sides=[axis[0]*(p[1]-O[1])-axis[1]*(p[0]-O[0]) for p in mids]
    require(sides[0]*sides[1]<0,'分割线两瓣在轴线两侧反向弯曲')
    require(abs(dots[0]['radius']-dots[1]['radius'])<=.5 and 0<dots[0]['radius']<R/2-.5,'小圆同尺寸且小于半瓣')
    require(all(any(math.dist(center(dot),center(arc))<=.5 for arc in arcs) for dot in dots)
            and math.dist(center(dots[0]),center(dots[1]))>R/2,'小圆分别位于两瓣中心')
    unit=r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])';factors=length_factors('mm')
    pattern=r'外圆半径\s*('+N+r')\s*'+unit
    matches=list(re.finditer(pattern,rest,re.I))
    if not matches:return partial
    for m in matches:require(abs(R-float(m[1])*factors[m[2].lower()])<=.5,'来源外圆半径')
    rest=re.sub(pattern,' ',rest,flags=re.I)
    rest=re.sub(r'坐标单位(?:为|是|[:：])?\s*'+unit,' ',rest,flags=re.I)
    rest=re.sub(r'保持原始太极图要求|只生成预览|太极图|S形分割线|两个对称小圆|生成|创建|画|一个|和',' ',rest,flags=re.I)
    if rest.strip(' \t\r\n，,。；;'):return {**partial,'unconsumed_text':rest,'checks':checks}
    return {'status':'passed','coverage':'complete','checks':checks,'outer_circle_id':outer['id'],
            'authority':'backend_measured_geometry','source_evidence':source_texts(source)}
