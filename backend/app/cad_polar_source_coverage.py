"""Consume only source clauses covered by measured origin-based spiral checks."""
from .cad_length_units import length_factors
import re

from .cad_source_acceptance import N, P, source_texts


def verify_polar_source_coverage(source,measured):
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    if not measured or measured.get('status')!='passed':return partial
    req=measured['requirements']
    if not req.get('linear_radius'):return partial
    text='\n'.join(source_texts(source));rest=text
    factors=length_factors('m')
    unit=r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'
    turns=list(re.finditer(r'(逆时针|顺时针)?(?:旋转|转)\s*('+N+r')\s*圈',rest))
    if not turns or any(abs(float(m[2])-req['turns'])>1e-9
        or (m[1] and (1 if m[1]=='逆时针' else -1)!=req['direction']) for m in turns):return partial
    rest=re.sub(r'(逆时针|顺时针)?(?:旋转|转)\s*('+N+r')\s*圈',' ',rest)
    radii=list(re.finditer(r'最大半径\s*('+N+r')\s*'+unit,rest,re.I))
    if not radii or any(abs(float(m[1])*factors[m[2].lower()]-req['radius_m'])>1e-9 for m in radii):return partial
    rest=re.sub(r'最大半径\s*('+N+r')\s*'+unit,' ',rest,flags=re.I)
    growth=list(re.finditer(r'半径从0(?:\.0+)?线性增长到\s*('+N+r')\s*'+unit,rest,re.I))
    if any(abs(float(m[1])*factors[m[2].lower()]-req['radius_m'])>1e-9 for m in growth):return partial
    rest=re.sub(r'半径从0(?:\.0+)?线性增长到\s*('+N+r')\s*'+unit,' ',rest,flags=re.I)
    origins=list(re.finditer(r'从\s*'+P+r'(?:出发|开始)?',rest))
    if any(abs(float(m[1]))>1e-12 or abs(float(m[2]))>1e-12 for m in origins):return partial
    rest=re.sub(r'从\s*'+P+r'(?:出发|开始)?|从原点(?:开始|出发)?',' ',rest)
    units=re.findall(r'坐标单位(?:为|是)?\s*'+unit,rest,re.I)
    if len({factors[u.lower()] for u in units})>1:return partial
    rest=re.sub(r'坐标单位(?:为|是)?\s*'+unit,' ',rest,flags=re.I)
    rest=re.sub(r'阿基米德螺旋线|阿基米德螺线|螺旋线|螺线',' ',rest)
    rest=re.sub(r'生成|创建|绘制|画出|画|请|一个|一条',' ',rest)
    if rest.strip(' \t\r\n，,、。；;'):
        return {**partial,'unconsumed_text':rest.strip(),'source_evidence':source_texts(source)}
    return {**measured,'coverage':'complete','source_evidence':source_texts(source),
            'measurement_scope':'fully_consumed_measured_polar_requirements'}
