"""Verify explicitly supplied two-stroke chains and a horizontal cross stroke.

Only source coordinates define this contract; no font or glyph catalog is used.
Expected linework is temporary measurement data, never returned as CAD output.
"""
from .cad_length_units import length_factors
import re
from .cad_structure_contract import StructureContractError

N=r'[-+]?\d+(?:\.\d+)?'
UNIT=r'毫米|厘米|米|mm|cm|m'
POINT=rf'[（(]\s*{N}\s*[,，]\s*{N}\s*[）)]'
FACTORS=length_factors('mm')


def stroke_requirements(text):
    from .cad_creation_intent import local_creation_objects
    from .cad_source_acceptance import source_texts
    sources=source_texts(text)
    if len(local_creation_objects('\n'.join(sources)))!=1:return None
    if re.search(r'笔画宽度|线宽|描边宽|填充|实心|空心','\n'.join(sources)):return None
    contract=None
    for source in sources:
        chain=re.search(rf'(?:两|2)(?:条)?(?:斜笔|斜线)(?:的)?端点\s*((?:{POINT}[、\s]*){{3}})',source)
        height=re.search(rf'横(?:笔|线)(?:在|位于)高度\s*({N})\s*({UNIT})处?',source,re.I)
        units=re.findall(rf'坐标单位(?:为|是)?\s*({UNIT})(?![a-zA-Z])',source,re.I)
        if not chain or not height or not units:continue
        if re.match(r'[、\s]*[（(]',source[chain.end():]):continue
        scale=FACTORS[units[-1].lower()]
        points=[[float(x)*scale,float(y)*scale] for x,y in re.findall(rf'[（(]\s*({N})\s*[,，]\s*({N})\s*[）)]',chain[1])]
        y=float(height[1])*FACTORS[height[2].lower()];intersections=[]
        for a,b in zip(points,points[1:]):
            if a[1]==b[1] or not min(a[1],b[1])<y<max(a[1],b[1]):break
            intersections.append([a[0]+(b[0]-a[0])*(y-a[1])/(b[1]-a[1]),y])
        if len(intersections)!=2 or abs(intersections[0][0]-intersections[1][0])<=.5:continue
        contract={'kind':'explicit_two_stroke_chain_and_crossbar','origin':'user_coordinate_constraints',
            'chain_points_mm':points,'crossbar_endpoints_mm':intersections,
            'source_evidence':[chain[0].strip(),height[0]],
            'instruction':'原文已指定两笔画的端点链及横笔高度；按该开放笔画骨架与交点连接构造。未指定描边线宽时，不把端点链替换成有宽度字体的外围轮廓。'}
    return contract


def verify_stroke_requirements(text,geometries):
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    contract=stroke_requirements(text)
    if not contract:return {'status':'not_checked','coverage':'partial','checks':[]}
    gs=[g for g in geometries if g.get('selected') is not False and g.get('role') not in {'annotation','reference','ignored'}]
    paths=[]
    for g in gs:
        if g.get('type')=='line':points=[(g[k]['x'],g[k]['y']) for k in ('start','end')]
        elif g.get('type')=='polyline' and not g.get('closed'):points=[(p['x'],p['y']) for p in g['vertices']]
        else:
            raise StructureContractError('原文指定开放笔画端点，不可替换为字体描边或其他曲线。',{'stroke_requirements':contract})
        if any(p.get('bulge',0)!=0 for p in g.get('vertices',[])):
            raise StructureContractError('原文指定直线笔画，实际路径含有曲边。',{'geometry_ids':[g['id']]})
        paths.append(LineString(points))
    expected=unary_union([LineString(contract['chain_points_mm']),LineString(contract['crossbar_endpoints_mm'])])
    actual=unary_union(paths)
    duplicate_length=sum(path.length for path in paths)-actual.length
    if duplicate_length>.5:
        raise StructureContractError('实际笔画包含重叠或回叠的重复线段。',{
            'geometry_ids':[g['id'] for g in gs],'duplicate_length_mm':duplicate_length,'tolerance_mm':.5})
    error=expected.hausdorff_distance(actual) if paths else None
    missing=expected.difference(actual.buffer(.5)).length if paths else expected.length
    extra=actual.difference(expected.buffer(.5)).length if paths else 0
    if error is None or not error<=.5 or missing>.5 or extra>.5:
        raise StructureContractError('实际笔画未遵守原文端点链或横笔交点；不得改变坐标、遗漏横笔或增加无关边。',
            {'stroke_requirements':contract,'hausdorff_error_mm':error,'missing_length_mm':missing,'extra_length_mm':extra,'tolerance_mm':.5})
    return {'status':'partial','coverage':'explicit_stroke_coordinates_and_crossbar_only','requirements':contract,
        'bounds_mm':list(actual.bounds),
        'checks':[{'name':'source_stroke_linework','status':'passed','authority':'backend_measured_geometry',
            'geometry_ids':[g['id'] for g in gs],'hausdorff_error_mm':error,'tolerance_mm':.5}]}


def verify_stroke_source_coverage(source, measured, semantic):
    """Cover only fully specified source linework plus measured overall size."""
    from .cad_source_acceptance import source_texts
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    if measured.get('coverage')!='explicit_stroke_coordinates_and_crossbar_only':return partial
    contract=measured.get('requirements') or {}
    if not measured.get('checks') or any(c.get('status')!='passed' for c in measured['checks']):return partial
    text='\n'.join(source_texts(source));rest=text
    unit=r'('+UNIT+r')(?![a-zA-Z])'
    units=re.findall(r'坐标单位(?:为|是)?\s*'+unit,text,re.I)
    if len({FACTORS[u.lower()] for u in units})!=1:return partial
    if re.search(r'(?:大写)?字母\s*A',text,re.I):
        if (semantic.get('coverage')!='straight_capital_a_structural_relations_only'
                or not semantic.get('checks') or semantic.get('review_required') is True
                or any(c.get('status')!='passed' for c in semantic['checks'])):
            return partial
    for evidence in contract.get('source_evidence',[]):
        rest=re.sub(re.escape(evidence),' ',rest,flags=re.I)
    rest=re.sub(r'坐标单位(?:为|是)?\s*'+unit,' ',rest,flags=re.I)
    bounds=measured.get('bounds_mm') or []
    if len(bounds)!=4:return partial
    size={'width':bounds[2]-bounds[0],'height':bounds[3]-bounds[1]}
    dimensions=r'(总宽|总高|宽度|高度|宽|高)(?:为|是|[:：])?\s*('+N+r')\s*'+unit
    checks=list(measured['checks'])
    for match in re.finditer(dimensions,rest,re.I):
        field='height' if '高' in match[1] else 'width'
        expected=float(match[2])*FACTORS[match[3].lower()]
        if expected<=0 or abs(size[field]-expected)>.5:return partial
        checks.append({'field':field,'status':'passed','expected_mm':expected,'actual_mm':size[field]})
    rest=re.sub(dimensions,' ',rest,flags=re.I)
    rest=re.sub(r'大写字母\s*A|字母\s*A|折线图案',' ',rest,flags=re.I)
    rest=re.sub(r'生成|创建|绘制|画出|画|请|一个|轮廓|的',' ',rest)
    if rest.strip(' \t\r\n，,、。；;'):
        return {**partial,'unconsumed_text':rest.strip(),'source_evidence':source_texts(source)}
    return {'status':'passed','coverage':'complete','checks':checks,
            'source_evidence':source_texts(source),'authority':'backend_measured_geometry',
            'measurement_scope':'fully_consumed_explicit_stroke_source'}
