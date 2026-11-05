"""Recognize explicit coordinate scale, without constructing a curve."""
import re


def coordinate_scale(source):
    source=source.split('\n后端试算反馈：',1)[0]
    number=r'[-+]?\d+(?:\.\d+)?'
    points=re.findall(rf'[（(]\s*({number})\s*[,，]\s*({number})\s*[）)]',source)
    defined=bool(re.search(r'控制点|顶点|端点',source)) and len(points)>=2
    units=re.findall(r'(?:坐标)?单位\s*(?:为|是|[:：])?\s*(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])',source,re.I)
    return {'defined':defined,'has_scale':defined and bool(units),
        'units':units[-1].lower() if units else None}
