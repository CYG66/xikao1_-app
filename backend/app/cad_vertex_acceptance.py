"""Read-only source-coordinate proof for a single closed straight vertex path."""
from .cad_length_units import length_factors
import math
import re

from .cad_source_acceptance import P, source_texts
from .cad_structure_contract import StructureContractError, _points


def normalize_relative_walk_source(text):
    """Normalize sequential walk verbs to the existing ordered-path grammar.

    Text only: no geometry, coordinates or inferred lengths are produced.
    Unconsumed clauses remain in place for the normal coverage gate.
    """
    from .cad_source_acceptance import N
    unit=r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'
    head=re.match(r'从\s*'+P+r'\s*出发画折线[，,]\s*先沿与x轴正向成\s*('+N+r')度的方向走\s*('+N+r')\s*'+unit,text)
    if not head:return text
    tail=text[head.end():];turns=[]
    pattern=r'^[，,]\s*再向(左|右)转\s*('+N+r')度接着画\s*('+N+r')\s*'+unit
    while match:=re.match(pattern,tail):
        turns.append(match.groups());tail=tail[match.end():]
        if len(turns)>9:return text
    if not turns:return text
    count=len(turns)+1;names='一二三四五六七八九十'
    join=re.match(r'[。；;]\s*([两二三四五六七八九十]|\d+)段(?:连在一起|连续连接|依次连接)[，,]\s*末端不连回起点[，,]\s*不加其他图形',tail)
    if not join:return text
    declared=int(join[1]) if join[1].isdigit() else 2 if join[1]=='两' else names.index(join[1])+1
    if declared!=count:return text
    x,y,angle,length,units=head.groups()
    normalized=f'画{count}段首尾相接的开放折线。起点({x},{y})，第一段长{length}{units}，与x轴正向夹角{angle}度；'
    for i,(direction,turn,length,units) in enumerate(turns,1):
        normalized+=f'第{names[i]}段从第{names[i-1]}段末点出发，长{length}{units}，在第{names[i-1]}段方向基础上'+('顺时针' if direction=='右' else '逆时针')+f'转{turn}度；'
    return normalized+'不要闭合或增加其他图形'+tail[join.end():]


def open_straight_path_requirements(source):
    """Ground an ordered sequence of lengths and relative turns in actual CAD."""
    from .cad_source_acceptance import N
    from .cad_source_intent import partition_preview_intent
    original='\n'.join(source_texts(source));text,intents=partition_preview_intent(original)
    original_walk=text
    text=normalize_relative_walk_source(text)
    normalized=text!=original_walk
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    if '开放折线' not in text:return partial
    names=['一','二','三','四','五','六','七','八','九','十']
    count_values={s:i+1 for i,s in enumerate(names)}
    count_values['两']=2
    unit=r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])';factors=length_factors('mm')
    units=re.findall(r'坐标单位(?:为|是)?\s*'+unit,text,re.I)
    if not units or len(set(u.lower() for u in units))!=1:return partial
    starts=list(re.finditer(r'起点\s*'+P,text))
    if len(starts)!=1:return partial
    start=[float(v)*factors[units[0].lower()] for v in starts[0].groups()]
    rest=re.sub(r'起点\s*'+P,' ',text)
    rest=re.sub(r'坐标单位(?:为|是)?\s*'+unit,' ',rest,flags=re.I)
    declaration=re.search(r'(?:只画|绘制|画)([两二三四五六七八九十]|[2-9]|10)段(?:首尾相接|相接)的开放折线',rest)
    if not declaration:return partial
    count=int(declaration[1]) if declaration[1].isdigit() else count_values[declaration[1]]
    rest=rest[:declaration.start()]+' '+rest[declaration.end():]
    markers=list(re.finditer(r'第([一二三四五六七八九十]|[1-9]|10)段(?=长|从)',rest))
    if len(markers)!=count:return partial
    if rest[:markers[0].start()].strip(' \t\n，,。；;'):return partial
    requirements=[]
    for index,marker in enumerate(markers):
        ordinal=int(marker[1]) if marker[1].isdigit() else count_values[marker[1]]
        if ordinal!=index+1:return partial
        block=rest[marker.end():markers[index+1].start() if index+1<count else len(rest)]
        lengths=list(re.finditer(r'(?:长度|长)\s*('+N+r')\s*'+unit,block,re.I))
        if len(lengths)!=1:return partial
        lm=lengths[0];length=float(lm[1])*factors[lm[2].lower()]
        if length<=0 or not math.isfinite(length):return partial
        block=re.sub(r'(?:长度|长)\s*'+N+r'\s*'+unit,' ',block,flags=re.I)
        if index==0:
            angular=r'(?:与x轴正向夹角|相对x轴正向(?:角)?为)\s*('+N+r')\s*度'
            matches=list(re.finditer(angular,block,re.I))
            if len(matches)!=1:return partial
            angle=float(matches[0][1]);quote=matches[0][0]
        else:
            previous='第'+names[index-1]+'段'
            connection=r'从(?:'+previous+r'末点出发|'+previous+r'终点开始|前一段终点开始)'
            if not re.search(connection,block):return partial
            block=re.sub(connection,' ',block)
            angular=(r'(?:在'+previous+r'方向基础上|方向再相对'+previous+r')'
                     r'(顺时针|逆时针)转\s*('+N+r')\s*度')
            matches=list(re.finditer(angular,block))
            if len(matches)!=1:return partial
            angle=float(matches[0][2])*(-1 if matches[0][1]=='顺时针' else 1);quote=matches[0][0]
        block=re.sub(angular,' ',block,flags=re.I)
        # Closedness/count/no-extra-edge claims are proved by path topology.
        block=re.sub(r'不要闭合或增加其他图形|不闭合|不加标注',' ',block)
        if block.strip(' \t\n，,。；;'):
            return {**partial,'unconsumed_text':block.strip()}
        requirements.append({'length_mm':length,'angle_deg':angle,'length_evidence':lm[0],'angle_evidence':quote})
    if any(abs((r['angle_deg']+180)%360-180)<1e-9 for r in requirements[1:]):
        return {**partial,'reason':'collinear_source_junction_requires_explicit_binding'}
    return {'status':'parsed','coverage':'complete','count':count,'start_mm':start,
            'requirements':requirements,'original_text':original_walk,'normalized_text':text,
            'normalized':normalized,'start_evidence':original_walk if normalized else starts[0][0],
            'intent_evidence':intents}


def verify_open_straight_path(source, geometries, *, evidence_context=None):
    """Measure the same parsed path contract used by planning and readiness."""
    from .cad_geometry_measurements import ordered_straight_path, measured
    from .cad_precision import ACCEPTANCE_MM
    parsed=open_straight_path_requirements(source)
    if parsed['coverage']!='complete':return parsed
    start=parsed['start_mm'];count=parsed['count'];requirements=parsed['requirements']
    original_walk=parsed['original_text'];text=parsed['normalized_text']
    normalized=parsed['normalized'];intents=parsed['intent_evidence']
    try:facts=measured(ordered_straight_path,geometries,start,evidence_context=evidence_context)
    except ValueError as exc:
        raise StructureContractError('开放折线未形成源要求的唯一连续路径',{'reason':str(exc),'geometry_ids':[g['id'] for g in geometries]}) from exc
    checks=[{'field':'segment_count','expected':count,'actual':len(facts['lengths_mm']),
             'status':'passed' if len(facts['lengths_mm'])==count else 'failed'}]
    checks.append({'field':'start','actual_mm':facts['points_mm'][0],'expected_mm':start,
                   'source_evidence':parsed['start_evidence'],'status':'passed'})
    if checks[0]['status']=='passed':
        for i,req in enumerate(requirements):
            actual=facts['directions_deg'][i] if i==0 else facts['directions_deg'][i]-facts['directions_deg'][i-1]
            error=abs((actual-req['angle_deg']+180)%360-180)
            checks.extend([{'field':'segment_length','segment':i+1,'actual_mm':facts['lengths_mm'][i],
                'expected_mm':req['length_mm'],'source_evidence':original_walk if normalized else req['length_evidence'],
                'status':'passed' if abs(facts['lengths_mm'][i]-req['length_mm'])<=ACCEPTANCE_MM else 'failed'},
                {'field':'absolute_angle' if i==0 else 'relative_turn','segment':i+1,'actual_deg':actual,
                 'expected_deg':req['angle_deg'],'error_deg':error,'source_evidence':original_walk if normalized else req['angle_evidence'],
                 'status':'passed' if error<=.01 else 'failed'}])
    report={'checks':checks,'measurements':facts,'geometry_ids':facts['geometry_ids'],
            'source_evidence':source_texts(source),'intent_evidence':intents,'authority':'backend_measured_geometry'}
    if normalized:
        report['source_normalization']={'kind':'sequential_walk_grammar','original_text':original_walk,'normalized_text':text}
    if any(c['status']=='failed' for c in checks):raise StructureContractError('开放折线不符合源长度或方向要求',report)
    return {**report,'status':'passed','coverage':'complete'}


def verify_vertex_path(source, geometries):
    partial = {'status': 'not_checked', 'coverage': 'partial', 'checks': []}
    text = '\n'.join(source_texts(source))
    from .cad_source_intent import partition_preview_intent
    text,intents=partition_preview_intent(text)
    unit = r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'
    units = re.findall(r'坐标单位(?:为|是|[:：])?\s*' + unit, text, re.I)
    factors = length_factors('mm')
    scales = {factors[u.lower()] for u in units}
    if len(scales) != 1:
        return partial
    blocks = list(re.finditer(r'顶点\s*(' + P + r'(?:\s*[、，,]?\s*' + P + r')+)', text))
    if len(blocks) != 1:
        return partial
    scale = next(iter(scales))
    expected = [(float(x) * scale, float(y) * scale)
                for x, y in re.findall(P, blocks[0][1])]
    if len(expected) > 1 and expected[0] == expected[-1]:
        expected.pop()
    if len(expected) < 3 or not all(math.isfinite(v) for p in expected for v in p):
        return partial
    from shapely.geometry import Polygon
    polygon = Polygon(expected)
    if not polygon.is_valid or polygon.area <= 0:
        return partial
    rest = text[:blocks[0].start()] + ' ' + text[blocks[0].end():]
    rest = re.sub(r'坐标单位(?:为|是|[:：])?\s*' + unit, ' ', rest, flags=re.I)
    number = r'(\d+|[三四五六七八九十])'
    statements = list(re.finditer(r'使用(?:原文给出的)?' + number + r'个顶点', rest))
    counts = {'三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
    if any((int(m[1]) if m[1].isdigit() else counts[m[1]]) != len(expected)
           for m in statements):
        return partial
    rest = re.sub(r'使用(?:原文给出的)?' + number + r'个顶点', ' ', rest)
    shape_pattern = r'三角形|多边形|折线|' + number + r'边形'
    names = list(re.finditer(shape_pattern, rest))
    closed = '闭合' in rest or any(m[0] != '折线' for m in names)
    if len(names) != 1 or not closed:
        return partial
    shape=names[0][0]
    declared_count=3 if shape=='三角形' else None
    if shape.endswith('边形') and shape!='多边形':
        value=shape[:-2]
        declared_count=int(value) if value.isdigit() else counts[value]
    if declared_count is not None and declared_count!=len(expected):return partial
    # These clauses assert the same measured cyclic adjacency/closedness below.
    # Do not remove arbitrary connection instructions or unrecognized suffixes.
    connection_pattern=r'最后连接回第一个顶点|依次连接|按顺序连接'
    connections=[m[0] for m in re.finditer(connection_pattern,rest)]
    rest=re.sub(connection_pattern,' ',rest)
    rest=re.sub(shape_pattern,' ',rest)
    rest = re.sub(r'生成|创建|绘制|画出|画|请|一个|一条|形成|轮廓|闭合|的', ' ', rest)
    if rest.strip(' \t\r\n，,、。；;'):
        return partial
    gs = [g for g in geometries if g.get('selected') is not False
          and g.get('role') not in {'annotation', 'reference', 'ignored'}]
    actual = []
    straight = False
    if len(gs) == 1 and gs[0].get('type') == 'polyline' and gs[0].get('closed') is True:
        actual = _points(gs[0])
        straight = not any(p.get('bulge', 0) != 0 for p in gs[0].get('vertices', []))
    # Closed paths have no distinguished first vertex or traversal direction;
    # coordinates and adjacency still must match the user's ordered vertices.
    ordered = False
    if straight and len(actual) == len(expected):
        ordered = any(all(math.dist(a, b) <= .5 for a, b in zip(
            candidate[offset:] + candidate[:offset], expected))
            for candidate in (actual, list(reversed(actual)))
            for offset in range(len(actual)))
    valid = len(actual) >= 3 and Polygon(actual).is_valid and Polygon(actual).area > 0
    checks = [{'field': field, 'status': 'passed' if ok else 'failed'}
              for field, ok in (
                  ('single_closed_straight_path', len(gs) == 1 and straight),
                  ('ordered_source_vertices', ordered), ('simple_nonzero_polygon', valid))]
    report = {
        'checks': checks, 'geometry_ids': [g['id'] for g in gs],
        'expected_vertices_mm': expected, 'actual_vertices_mm': actual,
        'source_clause_evidence':{'vertex_list':blocks[0][0], 'shape':shape,
                                  'declared_vertex_count':declared_count,'connections':connections},
        'source_evidence': source_texts(source),
        'authority': 'backend_measured_geometry',
        'measurement_scope': 'fully_consumed_ordered_vertex_source',
        'intent_evidence':intents,
    }
    if any(check['status'] == 'failed' for check in checks):
        raise StructureContractError('闭合轮廓不符合原始顶点及连接顺序', report)
    return {**report, 'status': 'passed', 'coverage': 'complete'}
