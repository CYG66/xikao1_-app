"""Measure projected parallelotope edges; never construct or persist geometry."""
import itertools
import math
import re

from .cad_structure_contract import StructureContractError
from .cad_creation_intent import local_creation_objects


def verify_projection_requirements(source, geometries):
    source=source.split('\n后端试算反馈：',1)[0]
    if len(local_creation_objects(source))>1:
        return {'status':'not_checked','checks':[]}
    if not re.search(r'立方体|正方体',source) or not re.search(r'等轴|等距投影',source):
        return {'status':'not_checked','checks':[]}
    # Only an explicit complete edge inventory authorizes exact cardinality.
    if not re.search(r'(?:12|十二)\s*条.*?(?:棱|边)',source):
        return {'status':'not_checked','checks':[]}
    lines=[g for g in geometries if g.get('role') not in {'annotation','reference','ignored'}
           and g.get('selected') is not False]
    def fail(reason):
        raise StructureContractError('等轴投影棱线验收失败：'+reason,
            {'authority':'backend_measured_geometry','reason':reason})
    if len(lines)!=12 or any(g.get('type')!='line' for g in lines):
        fail('完整棱线必须为12条直线')
    edges=[];families=[]
    for g in lines:
        a=tuple(float(g['start'][k]) for k in ('x','y'))
        b=tuple(float(g['end'][k]) for k in ('x','y'))
        length=math.dist(a,b)
        if not math.isfinite(length) or length<=.5:fail('存在退化棱线')
        unit=((b[0]-a[0])/length,(b[1]-a[1])/length)
        if unit[0]<-1e-8 or (abs(unit[0])<=1e-8 and unit[1]<0):unit=(-unit[0],-unit[1])
        family=next((f for f in families if abs(f['unit'][0]*unit[1]-f['unit'][1]*unit[0])<1e-6),None)
        if family is None:
            family={'unit':unit,'lengths':[]};families.append(family)
        family['lengths'].append(length);edges.append((a,b))
    if len(families)!=3 or any(len(f['lengths'])!=4 for f in families):
        fail('应有三组平行棱线，每组4条')
    lengths=[sum(f['lengths'])/4 for f in families]
    if max(length for f in families for length in f['lengths'])-min(length for f in families for length in f['lengths'])>.5:
        fail('等轴投影棱长不一致')
    for first,second in itertools.combinations(families,2):
        if abs(abs(sum(a*b for a,b in zip(first['unit'],second['unit'])))-.5)>1e-6:
            fail('投影轴方向不符合等轴关系')
    requested=re.findall(r'(?:投影棱长|棱长)\s*(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)',source,re.I)
    if requested:
        value,unit=requested[-1];target=float(value)*{'毫米':1,'mm':1,'厘米':10,'cm':10,'米':1000,'m':1000}[unit.lower()]
        if any(abs(length-target)>.5 for length in lengths):fail('投影棱长不符合原文尺寸')
    # Recover the affine box incidence from actual endpoints. Isometric views
    # may collapse two opposite 3D vertices onto the same 2D center; therefore
    # a naive endpoint degree-three test would incorrectly reject valid views.
    for anchor in [p for edge in edges for p in edge]:
        for signs in itertools.product((-1,1),repeat=3):
            vectors=[(f['unit'][0]*length*s,f['unit'][1]*length*s)
                     for f,length,s in zip(families,lengths,signs)]
            vertices={bits:tuple(anchor[k]+sum(bits[i]*vectors[i][k] for i in range(3)) for k in range(2))
                      for bits in itertools.product((0,1),repeat=3)}
            unmatched=list(edges)
            for bits,point in vertices.items():
                for axis in range(3):
                    if bits[axis]:continue
                    other=list(bits);other[axis]=1;end=vertices[tuple(other)]
                    index=next((i for i,(a,b) in enumerate(unmatched)
                        if (math.dist(a,point)<=.5 and math.dist(b,end)<=.5)
                        or (math.dist(b,point)<=.5 and math.dist(a,end)<=.5)),None)
                    if index is None:break
                    unmatched.pop(index)
                else:continue
                break
            else:
                if not unmatched:return {'status':'passed','coverage':'isometric_edge_incidence_and_projected_lengths',
                    'checks':[{'name':'projected_box_edges','status':'passed','authority':'backend_measured_geometry',
                               'geometry_ids':[g['id'] for g in lines]}]}
    fail('棱线端点连接不构成同一投影立方体，存在重复、错位或缺边')
