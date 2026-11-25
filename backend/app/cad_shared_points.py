"""Resolve explicit coordinate references through the existing safe evaluator."""
from copy import deepcopy
import re
from .cad_parametric import expression

REF=re.compile(r'@([A-Za-z][A-Za-z0-9_]{0,63})\.(x|y)\b')

def resolve_shared_points(value):
    if not isinstance(value,dict) or not value.get('shared_points'):return value
    result=deepcopy(value);table=result['shared_points']
    if not isinstance(table,dict) or len(table)>64:raise ValueError('共享点必须是最多64项的对象')
    resolved={};active=set()
    def scalar(raw):
        if not isinstance(raw,str):return raw
        text=REF.sub(lambda m:'('+repr(point(m[1])[m[2]])+')',raw)
        if '@' in text:raise ValueError('共享点引用格式必须为@name.x或@name.y')
        if re.search(r'\bt\b',text):raise ValueError('共享点不能依赖参数t')
        return expression(text)(0)
    def point(name):
        if name in resolved:return resolved[name]
        if name in active:raise ValueError('共享点存在循环引用：'+name)
        if name not in table:raise ValueError('共享点不存在：'+name)
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',name):raise ValueError('共享点名称无效')
        raw=table[name]
        if not isinstance(raw,dict) or set(raw)!={'x','y'}:raise ValueError('共享点必须包含且仅包含x/y')
        active.add(name);p={k:scalar(raw[k]) for k in ('x','y')};active.remove(name)
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not -100000<=v<=100000 for v in p.values()):raise ValueError('共享点坐标超出范围')
        resolved[name]=p;return p
    for name in table:point(name)
    def walk(obj):
        if isinstance(obj,list):return [walk(v) for v in obj]
        if not isinstance(obj,dict):return obj
        return {k:(scalar(v) if k in {'x','y'} and isinstance(v,str) and '@' in v else walk(v)) for k,v in obj.items()}
    result['shared_points']=resolved
    return walk(result)
