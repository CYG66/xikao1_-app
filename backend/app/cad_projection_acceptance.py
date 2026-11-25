"""Measure projected parallelotope edges; never construct or persist geometry."""
from .cad_length_units import length_factors
import itertools
import math
import re

from .cad_structure_contract import StructureContractError
from .cad_creation_intent import local_creation_objects


def projection_requirements(source):
    """Shared source constraints for planning and measurement; no coordinates."""
    source=source.split('\n后端试算反馈：',1)[0]
    if len(local_creation_objects(source))>1:
        return None
    if not re.search(r'立方体|正方体',source) or not re.search(r'等轴|等距投影',source):
        return None
    # Only an explicit complete edge inventory authorizes exact cardinality.
    if not re.search(r'(?:12|十二)\s*条.*?(?:棱|边)',source):
        return None
    target=None
    requested=re.findall(r'(?:投影棱长|棱长)\s*(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)',source,re.I)
    if requested:
        value,unit=requested[-1];target=float(value)*length_factors('mm')[unit.lower()]
    return {'edge_count':12,'parallel_family_count':3,'edges_per_family':4,
            'equal_projected_lengths':True,'projected_edge_length_mm':target,
            'absolute_axis_dot_product':0.5,
            'instruction':'先建立共同基点和三条等长投影轴向量，再用向量和定义共享顶点与棱线连接。逐对核对轴向量的点积绝对值为各自长度乘积的一半；无向直线夹角为60度，有向轴可取120度。每条边只绘制一次，不以删除重复线代替补齐缺边。毫米是约束单位，输出坐标仍遵守plan.units。'}


def projection_clarification_is_redundant(source, question):
    """Reject only questions fully consumed by already confirmed projection facts."""
    facts=projection_requirements(source)
    if not facts or facts['projected_edge_length_mm'] is None or not re.search(r'投影|等轴|等距',question):return False
    rest=question
    sizes=list(re.finditer(r'(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])',rest,re.I))
    if any(abs(float(m[1])*length_factors('mm')[m[2].lower()]-facts['projected_edge_length_mm'])>.5 for m in sizes):return False
    rest=re.sub(r'\d+(?:\.\d+)?\s*(?:毫米|厘米|米|mm|cm|m)(?![a-zA-Z])',' ',rest,flags=re.I)
    angles=list(re.finditer(r'(\d+(?:\.\d+)?)\s*度',rest))
    if any(abs(float(m[1])-120)>1e-6 for m in angles):return False
    rest=re.sub(r'120(?:\.0+)?\s*度',' ',rest)
    rest=re.sub(r'(?:12|十二)\s*条(?:棱线|边)',' ',rest)
    rest=re.sub(r'请|确认|说明|是否|采用|使用|需要|立方体|正方体|透视投影|透视轮廓|视角约定|投影方式|二维|等轴投影|等距投影|三(?:条|个)投影轴|夹角|每条投影棱线|各投影棱长|投影棱长|在图纸上|仍为|均为|为|且|和|的|只画|可见及隐藏',' ',rest)
    return not rest.strip(' \t\r\n，,、。；;：:？?（）()')


def verify_projection_requirements(source, geometries):
    requirements=projection_requirements(source)
    if requirements is None:
        return {'status':'not_checked','checks':[]}
    lines=[g for g in geometries if g.get('role') not in {'annotation','reference','ignored'}
           and g.get('selected') is not False]
    families=[];measured_edges=[];target=requirements['projected_edge_length_mm'];topology_verified=False
    best_incidence=None
    def fail(reason):
        raise StructureContractError('等轴投影棱线验收失败：'+reason,
            {'authority':'backend_measured_geometry','reason':reason,
             'geometry_ids':[g['id'] for g in lines], 'requires_structural_replan':True,
             'measured_axis_families':families,
             'measured_edges':measured_edges,
             'incidence_diagnostic':best_incidence,
             'topology_verified':topology_verified,
             'requested_projected_edge_length_mm':target,
             'measured_projected_edge_lengths_mm':[v for f in families for v in f['lengths']],
             'source_length_satisfied':(all(abs(v-target)<=.5 for f in families for v in f['lengths']) if target is not None else None),
             'measured_undirected_angles_degrees':[
                 math.degrees(math.acos(min(1,abs(sum(a*b for a,b in zip(f['unit'],s['unit']))))))
                 for f,s in itertools.combinations(families,2)],
             'repair_instruction':'从共同基点及一致的投影轴向量重新规划失败棱线；先核对三组轴的夹角、长度，再由向量和计算共享顶点。不要逐条猜测端点。保留用户投影棱长、完整棱线数量和连接关系；旧计划不是用户要求。'
                +(' 三组轴向和等长关系已通过；incidence_diagnostic给出同一框架中已匹配与未匹配的实际棱线ID。优先核对未匹配棱线的端点连接，不能仅通过重复边或删除缺边来凑数；部分匹配不代表候选已通过。' if best_incidence else '')})
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
            family={'unit':unit,'lengths':[],'geometry_ids':[]};families.append(family)
        family['lengths'].append(length);family['geometry_ids'].append(g['id']);edges.append((a,b))
        measured_edges.append({'geometry_id':g['id'],'start_mm':a,'end_mm':b,'length_mm':length})
    if len(families)!=3 or any(len(f['lengths'])!=4 for f in families):
        fail('应有三组平行棱线，每组4条')
    lengths=[sum(f['lengths'])/4 for f in families]
    if max(length for f in families for length in f['lengths'])-min(length for f in families for length in f['lengths'])>.5:
        fail('等轴投影棱长不一致')
    for first,second in itertools.combinations(families,2):
        if abs(abs(sum(a*b for a,b in zip(first['unit'],second['unit'])))-.5)>1e-6:
            fail('投影轴方向不符合等轴关系')
    # Recover the affine box incidence from actual endpoints. Isometric views
    # may collapse two opposite 3D vertices onto the same 2D center; therefore
    # a naive endpoint degree-three test would incorrectly reject valid views.
    for anchor in [p for edge in edges for p in edge]:
        for signs in itertools.product((-1,1),repeat=3):
            vectors=[(f['unit'][0]*length*s,f['unit'][1]*length*s)
                     for f,length,s in zip(families,lengths,signs)]
            vertices={bits:tuple(anchor[k]+sum(bits[i]*vectors[i][k] for i in range(3)) for k in range(2))
                      for bits in itertools.product((0,1),repeat=3)}
            unmatched=[(g['id'],a,b) for g,(a,b) in zip(lines,edges)]
            matched=[]
            for bits,point in vertices.items():
                for axis in range(3):
                    if bits[axis]:continue
                    other=list(bits);other[axis]=1;end=vertices[tuple(other)]
                    index=next((i for i,(_,a,b) in enumerate(unmatched)
                        if (math.dist(a,point)<=.5 and math.dist(b,end)<=.5)
                        or (math.dist(b,point)<=.5 and math.dist(a,end)<=.5)),None)
                    if index is not None:matched.append(unmatched.pop(index)[0])
            if best_incidence is None or len(matched)>len(best_incidence['matched_geometry_ids']):
                best_incidence={'matched_geometry_ids':sorted(matched),
                    'unmatched_geometry_ids':sorted(gid for gid,_,_ in unmatched),
                    'missing_edge_count':12-len(matched),'diagnostic_only':True,'candidate_accepted':False}
            if not unmatched:
                topology_verified=True
                if target is not None and any(abs(length-target)>.5 for length in lengths):fail('投影棱长不符合原文尺寸')
                return {'status':'passed','coverage':'isometric_edge_incidence_and_projected_lengths',
                    'projected_edge_length_mm':lengths[0],
                    'checks':[{'name':'projected_box_edges','status':'passed','authority':'backend_measured_geometry',
                               'geometry_ids':[g['id'] for g in lines]}]}
    fail('棱线端点连接不构成同一投影立方体，存在重复、错位或缺边')


def verify_projection_source_coverage(source, measured):
    from .cad_source_acceptance import source_texts
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    if measured.get('status')!='passed':return partial
    text='\n'.join(source_texts(source));rest=text
    pattern=r'(?:各投影棱长|投影棱长|棱长|边长)\s*(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)'
    if not re.search(r'投影棱长',text):return partial
    factors=length_factors('mm')
    for match in re.finditer(pattern,rest,re.I):
        if abs(float(match[1])*factors[match[2].lower()]-measured['projected_edge_length_mm'])>.5:return partial
    rest=re.sub(pattern,' ',rest,flags=re.I)
    rest=re.sub(r'三个投影轴夹角120度|(?:12|十二)条棱线|可见及隐藏|包含隐藏|只画|等轴投影|等距投影|二维|立方体|正方体|透视轮廓|的|画|生成|一个',' ',rest)
    if rest.strip(' \t\r\n，,。；;（）()'):return {**partial,'unconsumed_text':rest}
    return {'status':'passed','coverage':'complete','checks':measured['checks'],
            'authority':'backend_measured_geometry','source_evidence':source_texts(source)}
