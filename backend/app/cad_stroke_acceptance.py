"""Verify explicitly supplied two-stroke chains and a horizontal cross stroke.

Only source coordinates define this contract; no font or glyph catalog is used.
Expected linework is temporary measurement data, never returned as CAD output.
"""
import re
from .cad_structure_contract import StructureContractError

N=r'[-+]?\d+(?:\.\d+)?'
UNIT=r'毫米|厘米|米|mm|cm|m'
POINT=rf'[（(]\s*{N}\s*[,，]\s*{N}\s*[）)]'
FACTORS={'毫米':1,'厘米':10,'米':1000,'mm':1,'cm':10,'m':1000}


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
        paths.append(LineString(points))
    expected=unary_union([LineString(contract['chain_points_mm']),LineString(contract['crossbar_endpoints_mm'])])
    actual=unary_union(paths)
    error=expected.hausdorff_distance(actual) if paths else None
    missing=expected.difference(actual.buffer(.5)).length if paths else expected.length
    extra=actual.difference(expected.buffer(.5)).length if paths else 0
    if error is None or not error<=.5 or missing>.5 or extra>.5:
        raise StructureContractError('实际笔画未遵守原文端点链或横笔交点；不得改变坐标、遗漏横笔或增加无关边。',
            {'stroke_requirements':contract,'hausdorff_error_mm':error,'missing_length_mm':missing,'extra_length_mm':extra,'tolerance_mm':.5})
    return {'status':'partial','coverage':'explicit_stroke_coordinates_and_crossbar_only','requirements':contract,
        'checks':[{'name':'source_stroke_linework','status':'passed','authority':'backend_measured_geometry',
            'geometry_ids':[g['id'] for g in gs],'hausdorff_error_mm':error,'tolerance_mm':.5}]}
