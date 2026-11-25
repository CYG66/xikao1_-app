"""Recognize explicit coordinate scale, without constructing a curve."""
from .cad_length_units import length_factors
import re
import math


def coordinate_scale(source):
    source=source.split('\n后端试算反馈：',1)[0]
    number=r'[-+]?\d+(?:\.\d+)?'
    points=re.findall(rf'[（(]\s*({number})\s*[,，]\s*({number})\s*[）)]',source)
    defined=bool(re.search(r'控制点|顶点|端点',source)) and len(points)>=2
    units=re.findall(r'(?:坐标)?单位\s*(?:为|是|[:：])?\s*(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])',source,re.I)
    return {'defined':defined,'has_scale':defined and bool(units),
        'units':units[-1].lower() if units else None}


def verify_control_point_curve(source, geometries):
    """Verify source controls against actual native non-rational curve data.

    Native control points, degree and implicit knots define these curves
    exactly; preview sampling is not used as proof. Unknown source text or
    alternative representations remain partial rather than gaining coverage.
    """
    from .cad_source_acceptance import source_texts
    from .cad_structure_contract import StructureContractError
    number = r'[-+]?\d+(?:\.\d+)?'
    point = rf'[（(]\s*({number})\s*[,，]\s*({number})\s*[）)]'
    text = '\n'.join(source_texts(source))
    units = re.findall(r'坐标单位(?:为|是|[:：])?\s*(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])',text,re.I)
    partial = {'status':'not_checked','coverage':'partial','checks':[]}
    if not units or len(set(u.lower() for u in units)) != 1:
        return partial
    blocks = list(re.finditer(r'控制点\s*('+point+r'(?:\s*'+point+r')+)',text))
    if len(blocks) != 1:
        return partial
    scale = length_factors('mm')[units[0].lower()]
    expected = [[float(x)*scale,float(y)*scale] for x,y in re.findall(point,blocks[0][1])]
    if not all(math.isfinite(v) for p in expected for v in p):
        return partial
    rest = text[:blocks[0].start()] + ' ' + text[blocks[0].end():]
    names = re.findall(r'贝塞尔(?:曲线)?|Bezier(?:曲线)?|样条(?:曲线)?',rest,re.I)
    kinds = {'spline' if n.startswith('样条') else 'bezier' for n in names}
    if len(kinds) != 1:
        return partial
    kind = next(iter(kinds))
    degree_names = {'二':2,'三':3,'四':4,'五':5,'2':2,'3':3,'4':4,'5':5}
    degrees = [degree_names[n] for n in re.findall(r'([二三四五2-5])次',rest)]
    if len(set(degrees)) > 1:
        return partial
    rest = re.sub(r'(?:指定)?[二三四五2-5]次', ' ',rest)
    references = re.findall(r'使用原文给出的([二三四五六七八九十\d]+)个控制点',rest)
    for count in references:
        n = int(count) if count.isdigit() else '零一二三四五六七八九十'.index(count) if len(count)==1 else -1
        if n != len(expected):
            return partial
    rest = re.sub(r'使用原文给出的[二三四五六七八九十\d]+个控制点', ' ',rest)
    rest = re.sub(r'坐标单位(?:为|是|[:：])?\s*(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])',' ',rest,flags=re.I)
    closed = '闭合' in rest
    smooth = bool(re.search(r'平滑|光滑',rest))
    rest = re.sub(r'贝塞尔(?:曲线)?|Bezier(?:曲线)?|样条(?:曲线)?|生成|绘制|创建|画出|画|请|一条|闭合|平滑|光滑|要求',' ',rest,flags=re.I)
    if rest.strip(' \t\r\n，,。；;'):
        return partial
    gs = [g for g in geometries if g.get('selected') is not False and g.get('role') not in {'reference','annotation','ignored'}]
    if len(gs)!=1 or gs[0].get('type')!='spline':
        raise StructureContractError('实际几何未保留源控制点曲线',{'geometry_ids':[g['id'] for g in gs]})
    g = gs[0]
    # Custom knots, weights or preview overrides require their own evidence.
    if any(g.get(k) for k in ('knots','weights','vertices','fit_points','fitPoints')):
        return partial
    actual = g.get('control_points') or []
    points_ok = len(actual)==len(expected) and all(
        math.dist([p['x'],p['y']], q)<=.5 and abs(p.get('z',0))<=.5
        for p,q in zip(actual,expected))
    degree = g.get('degree')
    degree_ok = isinstance(degree,int) and not isinstance(degree,bool) and 1<=degree<len(expected)
    if kind=='bezier':
        degree_ok = degree_ok and degree==len(expected)-1 and len(expected) in (3,4) and not g.get('periodic')
    if degrees:
        degree_ok = degree_ok and degree==degrees[0]
    closure_ok = bool(g.get('closed')) == closed
    periodic_ok = bool(g.get('periodic')) if closed else not bool(g.get('periodic'))
    # Uniform periodic knots have C^(degree-1) continuity, including the seam.
    smooth_ok = not smooth or (degree_ok and degree>=2 and (not closed or periodic_ok))
    checks = [{'field':field,'status':'passed' if ok else 'failed'} for field,ok in (
        ('ordered_source_controls',points_ok),('curve_basis_and_degree',degree_ok),
        ('source_closure',closure_ok and periodic_ok),('source_smoothness',smooth_ok))]
    if any(c['status']=='failed' for c in checks):
        raise StructureContractError('曲线未遵守原始控制点、次数或闭合连续性',{
            'geometry_ids':[g['id']], 'checks':checks,'expected_control_points_mm':expected,
            'actual_control_points_mm':actual,'expected_degree':degrees[0] if degrees else None,
            'actual_degree':degree,'closed_required':closed,'smooth_required':smooth})
    return {'status':'passed','coverage':'complete','checks':checks,
            'geometry_ids':[g['id']],'source_evidence':[blocks[0][0]],
            'authority':'backend_measured_geometry',
            'measurement_method':'native_non_rational_basis_and_ordered_controls',
            'continuity_basis':'implicit_uniform_periodic_knots' if closed else 'implicit_clamped_knots'}
