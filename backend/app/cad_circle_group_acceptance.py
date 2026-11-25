"""Bind a counted circle group to measured radii and pair relations.

No geometry construction or model-label matching is performed here. Unknown
clauses remain unconsumed so a partial proof never becomes full acceptance.
"""
from .cad_length_units import length_factors
import math
import re

from .cad_source_acceptance import N, P, source_texts, nested_circle_roles
from .cad_structure_contract import StructureContractError


def verify_circle_group_source(source, geometries):
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    from .cad_source_intent import partition_preview_intent, partition_outline_scope, verify_output_restrictions
    text='\n'.join(source_texts(source));rest,intents=partition_preview_intent(text);checks=[]
    gs=[g for g in geometries if g.get('selected') is not False
        and g.get('role') not in {'reference','annotation','ignored'}]
    # Pair relations below have a unique binding only for exactly two circles.
    if len(gs)!=2 or any(g.get('type')!='circle' for g in gs):return partial
    if not re.search(r'两个(?:相交|同心)?圆|两圆',text):return partial
    # Bind output scope to this measured pair, not an arbitrary named object.
    # The declaration/count and all dimensions still need independent proof.
    rest,output_intents=partition_outline_scope(rest,('内外两个圆','两个圆','两圆'),source=text)
    checks.extend(verify_output_restrictions(geometries,output_intents))
    unit=r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'
    factors=length_factors('mm')

    def consume(pattern, verify):
        nonlocal rest
        matches=list(re.finditer(pattern,rest,re.I))
        if not matches:return False
        for match in matches:
            actual,expected,ok=verify(match)
            check={'name':'circle_group_source_clause','status':'passed' if ok else 'failed',
                   'source_evidence':match[0],'actual':actual,'expected':expected,
                   'geometry_ids':[g['id'] for g in gs]}
            if not ok:raise StructureContractError('圆组尺寸或关系不符合原文',check)
            checks.append(check)
        rest=re.sub(pattern,' ',rest,flags=re.I)
        return True

    def radii(m):
        expected=float(m[1])*factors[m[2].lower()]
        actual=[g['radius'] for g in gs]
        return actual,expected,expected>0 and all(abs(r-expected)<=.5 for r in actual)

    if '同心圆' in rest:
        if '不加其他线条' in rest and any(g.get('selected') is not False and g.get('role')=='annotation' for g in geometries):
            raise StructureContractError('原文要求仅两个圆但存在额外标注')
        roles=nested_circle_roles(gs)
        if set(roles)!={'内圆','外圆'}:
            raise StructureContractError('同心圆缺少唯一内外包含关系')
        def role_radius(m):
            expected=float(m[2])*factors[m[3].lower()];actual=roles[m[1]]['radius']
            return actual,expected,expected>0 and abs(actual-expected)<=.5
        matched=list(re.finditer(r'(内圆|外圆)(?:的)?半径(?:为|是)?\s*('+N+r')\s*'+unit,rest))
        if {m[1] for m in matched}!={'内圆','外圆'}:return partial
        consume(r'(内圆|外圆)(?:的)?半径(?:为|是)?\s*('+N+r')\s*'+unit,role_radius)
        units=re.findall(r'坐标单位(?:为|是)?\s*'+unit,rest,re.I)
        if not units or len(set(u.lower() for u in units))!=1:return partial
        def shared_center(m):
            expected=[float(v)*factors[units[0].lower()] for v in m.groups()]
            actual=[[g['center']['x'],g['center']['y']] for g in gs]
            return actual,expected,all(math.dist(p,expected)<=.5 for p in actual)
        if not consume(r'(?:共同|共用|共享)圆心(?:为|在)?\s*'+P,shared_center):return partial
        consume('两个同心圆',lambda m:(len(gs),2,len(gs)==2))
        rest=re.sub(r'只保留内外两个圆|不加其他线条',' ',rest)
    else:
        if not consume(r'(?:两个圆|两圆)(?:的)?半径(?:均|都)?(?:为|是)?\s*('+N+r')\s*'+unit,radii):return partial
    a,b=gs;distance=math.dist([a['center']['x'],a['center']['y']],[b['center']['x'],b['center']['y']])
    if '同心圆' not in text and not consume(r'(?:两个圆的|两圆心|两个圆心|圆心)(?:之间的)?(?:相距|距离|距)\s*('+N+r')\s*'+unit,
        lambda m:(distance,float(m[1])*factors[m[2].lower()],
                  float(m[1])>0 and abs(distance-float(m[1])*factors[m[2].lower()])<=.5)):return partial
    if re.search('水平排列',rest):
        consume('水平排列',lambda m:(abs(a['center']['y']-b['center']['y']),0,
                                    abs(a['center']['y']-b['center']['y'])<=.5))
    if re.search('相交',rest):
        consume('相交',lambda m:(distance,'two distinct intersections',
                                abs(a['radius']-b['radius'])+.5<distance<a['radius']+b['radius']-.5))
    # The object name is covered only when the source explicitly defines its
    # composition; "眼镜" alone does not license ignoring missing parts.
    rest=re.sub(r'由两个\s*圆组成的眼镜轮廓',' ',rest)
    rest=re.sub(r'坐标单位\s*(?:为|是|[:：])?\s*'+unit,' ',rest,flags=re.I)
    rest=re.sub(r'生成|创建|绘制|画出|画|请|一个',' ',rest)
    if rest.strip(' \t\r\n，,、。；;：:'):
        return {**partial,'unconsumed_text':rest.strip(),'checks':checks}
    return {'status':'passed','coverage':'complete','checks':checks,
            'intent_evidence':intents,
            'output_intent_evidence':output_intents,
            'authority':'backend_measured_geometry','source_evidence':source_texts(source),
            'measurement_scope':'fully_consumed_counted_circle_group'}
