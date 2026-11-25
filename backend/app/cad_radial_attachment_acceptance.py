"""Measure circle-bound radial line inventories; never construct geometry."""
from .cad_length_units import length_factors
import math
import re
from .cad_source_acceptance import N, P, source_texts
from .cad_structure_contract import StructureContractError


def verify_radial_attachment_source(source, geometries):
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    text='\n'.join(source_texts(source));rest=text;checks=[]
    unit=r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'
    factors=length_factors('mm')
    inventory=re.search(r'向外伸出\s*(\d+)\s*条等角放射线',text)
    radius=re.search(r'外环半径\s*('+N+r')\s*'+unit,text,re.I)
    length=re.search(r'每条长\s*('+N+r')\s*'+unit,text,re.I)
    if not inventory or not radius or not length:return partial
    count=int(inventory[1]);r=float(radius[1])*factors[radius[2].lower()]
    size=float(length[1])*factors[length[2].lower()]
    if count<2 or r<=0 or size<=0:return partial
    gs=[g for g in geometries if g.get('selected') is not False and g.get('role') not in {'annotation','reference','ignored'}]
    circles=[g for g in gs if g.get('type')=='circle'];lines=[g for g in gs if g.get('type')=='line']
    def require(ok,name,actual=None,expected=None):
        check={'name':name,'status':'passed' if ok else 'failed','actual':actual,'expected':expected,
               'geometry_ids':[g['id'] for g in gs],'authority':'backend_measured_geometry'}
        if not ok:raise StructureContractError('圆周放射连接验收失败：'+name,check)
        checks.append(check)
    require(len(circles)==1 and len(lines)==count and len(gs)==count+1,'精确图元清单',len(gs),count+1)
    circle=circles[0];center=[circle['center']['x'],circle['center']['y']]
    require(abs(circle['radius']-r)<=.5,'外环半径',circle['radius'],r)
    angles=[]
    for line in lines:
        a,b=sorted(([line[k]['x'],line[k]['y']] for k in ('start','end')),key=lambda p:math.dist(p,center))
        da,db=math.dist(a,center),math.dist(b,center)
        require(abs(da-r)<=.5 and abs(db-r-size)<=.5 and abs(math.dist(a,b)-size)<=.5,
                '从圆周径向向外连接及长度',[da,db,math.dist(a,b)],[r,r+size,size])
        angles.append(math.atan2(b[1]-center[1],b[0]-center[0])%math.tau)
    angles.sort();gaps=[(angles[(i+1)%count]-angles[i])%math.tau for i in range(count)]
    require(all(abs(g-math.tau/count)<1e-6 for g in gaps),'等角且无重复方向',gaps,math.tau/count)
    # Consume every stated scalar, including repetitions and corrections.
    for pattern,expected in [(r'外环半径\s*('+N+r')\s*'+unit,r),
                             (r'每条长\s*('+N+r')\s*'+unit,size),
                             (r'(?<!外环)半径\s*('+N+r')\s*'+unit,r)]:
        for match in re.finditer(pattern,rest,re.I):
            require(abs(float(match[1])*factors[match[2].lower()]-expected)<=.5,'来源尺寸一致',match[0],expected)
        rest=re.sub(pattern,' ',rest,flags=re.I)
    rest=re.sub(r'向外伸出\s*'+str(count)+r'\s*条等角放射线',' ',rest)
    centers=list(re.finditer(r'外环圆心\s*'+P,rest))
    if centers:
        units=re.findall(r'坐标单位(?:为|是|[:：])?\s*'+unit,rest,re.I)
        scales={factors[u.lower()] for u in units}
        if len(scales)!=1:return partial
        scale=next(iter(scales))
        for match in centers:require(math.dist(center,[float(match[1])*scale,float(match[2])*scale])<=.5,'来源圆心',center,match[0])
        rest=re.sub(r'外环圆心\s*'+P,' ',rest)
    pattern=r'向东南西北四方向从圆周向外各延伸\s*('+N+r')\s*'+unit
    for match in re.finditer(pattern,rest,re.I):
        require(count==4 and abs(float(match[1])*factors[match[2].lower()]-size)<=.5
                and all(abs(math.sin(2*a))<1e-6 for a in angles),'四个坐标轴方向',angles,match[0])
    rest=re.sub(pattern,' ',rest,flags=re.I)
    rest=re.sub(r'坐标单位(?:为|是|[:：])?\s*'+unit,' ',rest,flags=re.I)
    rest=re.sub(r'环形交叉路口|生成|创建|绘制|画出|画|请|一个',' ',rest)
    if rest.strip(' \t\r\n，,、。；;'):return {**partial,'unconsumed_text':rest,'checks':checks}
    return {'status':'passed','coverage':'complete','checks':checks,'source_evidence':source_texts(source),
            'authority':'backend_measured_geometry','measurement_scope':'fully_consumed_radial_attachments'}
