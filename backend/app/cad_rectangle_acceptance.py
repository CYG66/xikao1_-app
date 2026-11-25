"""Measure a fully consumed single-rectangle requirement without making geometry."""
from .cad_length_units import length_factors
import math
import re

from .cad_source_acceptance import N, P, source_texts
from .cad_source_intent import partition_preview_intent
from .cad_precision import ACCEPTANCE_MM
from .cad_structure_contract import StructureContractError, _frame, _points


def verify_single_rectangle(text, geometries, *, evidence_context=None):
    """Only explicit width/height prose is covered; unknown clauses stay partial.

    A bounding box or model label alone cannot prove rectangle identity. The
    actual outline must be one closed, simple, straight-edged rectangle.
    """
    partial = {'status': 'not_checked', 'coverage': 'partial', 'checks': []}
    factors = length_factors('mm')
    unit = r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'
    scalar = r'(宽度|高度|宽|高)(?:为|是|改为|=|[:：])?\s*(' + N + r')\s*' + unit
    fields = {}
    evidence = []
    named = False
    origin=None;intent_evidence=[]
    for source in source_texts(text):
        source,intents=partition_preview_intent(source);intent_evidence.extend(intents)
        local = {}
        for match in re.finditer(scalar, source, re.I):
            key = 'width' if match[1].startswith('宽') else 'height'
            value = float(match[2]) * factors[match[3].lower()]
            if not math.isfinite(value) or value <= 0:
                return partial
            if key in local and abs(local[key] - value) > 1e-9:
                return partial
            local[key] = value
            evidence.append(match[0])
        rest = re.sub(scalar, ' ', source, flags=re.I)
        origins=list(re.finditer(r'左下角(?:为|是|位于)?\s*'+P,rest))
        if origins:
            units=re.findall(r'坐标单位(?:为|是)?\s*'+unit,source,re.I)
            if not units or len(set(u.lower() for u in units))!=1:return partial
            values=[[float(m[1])*factors[units[0].lower()],float(m[2])*factors[units[0].lower()]] for m in origins]
            if any(v!=values[0] for v in values):return partial
            origin=values[0];rest=re.sub(r'左下角(?:为|是|位于)?\s*'+P,' ',rest)
        # Axis alignment and exclusivity are measured by _frame and count.
        rest=re.sub(r'边平行于坐标轴|只画矩形轮廓',' ',rest)
        rest = re.sub(r'(?:坐标)?单位(?:为|是|[:：])?\s*' + unit, ' ', rest, flags=re.I)
        # Repeated shape declarations on separate lines may restate the same
        # object. Multiple objects in a clause are outside this narrow scope.
        for clause in rest.splitlines():
            names = re.findall(r'长方形|矩形', clause)
            if len(names) > 1:
                return partial
            named = named or bool(names)
        rest = re.sub(r'新建图纸|生成|创建|绘制|画出|画|请|一个|长方形|矩形|闭合|的', ' ', rest)
        if rest.strip(' \t\r\n，,、。；;'):
            return {**partial,'unconsumed_text':rest.strip(),'source_text':source}
        fields.update(local)
    if not named or fields.keys() != {'width', 'height'}:
        return partial

    gs = [g for g in geometries if g.get('selected') is not False
          and g.get('role') not in {'annotation', 'reference', 'ignored'}]
    frame = None
    if len(gs) == 1 and gs[0].get('type') == 'polyline' and gs[0].get('closed') is True:
        geometry = gs[0]
        points = _points(geometry)
        finite = all(math.isfinite(v) for point in points for v in point)
        if finite:
            frame = _frame(geometry,evidence_context=evidence_context)
    checks = [{
        'field': 'single_rectangle_shape_and_count',
        'status': 'passed' if frame is not None else 'failed',
        'expected_count': 1, 'actual_count': len(gs),
        'expected_shape': 'closed_simple_straight_rectangle',
    }]
    if frame is not None:
        for key, index in (('width', 2), ('height', 3)):
            actual = frame[index]
            checks.append({'field': key, 'expected_mm': fields[key], 'actual_mm': actual,
                           'status': 'passed' if abs(actual - fields[key]) <= ACCEPTANCE_MM else 'failed'})
        if origin is not None:
            checks.append({'field':'origin','expected_mm':origin,'actual_mm':list(frame[:2]),
                           'status':'passed' if math.dist(origin,frame[:2])<=ACCEPTANCE_MM else 'failed'})
    report = {
        'checks': checks, 'geometry_ids': [g['id'] for g in gs],
        'source_evidence': source_texts(text), 'scalar_evidence': evidence,
        'authority': 'backend_measured_geometry',
        'measurement_scope': 'fully_consumed_single_rectangle_source','intent_evidence':intent_evidence,
    }
    if any(check['status'] == 'failed' for check in checks):
        raise StructureContractError('单矩形轮廓或尺寸不符合完整源需求', report)
    return {**report, 'status': 'passed', 'coverage': 'complete'}
