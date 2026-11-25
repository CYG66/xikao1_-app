"""Generic scalar-DAG substitution into existing CAD plans, no shape recipes."""
import ast
from copy import deepcopy
import math
import re

from app.cad_parametric import expression

FUNCTIONS={'sin','cos','tan','sqrt','exp','log','abs','atan','asin','acos','atan2'}
UNITS={'m':1000.,'cm':10.,'mm':1.,'deg':1.,'scalar':1.}
SOURCE_UNITS={'米':'m','厘米':'cm','毫米':'mm','度':'deg','m':'m','cm':'cm','mm':'mm'}
NAME=re.compile(r'[A-Za-z][A-Za-z0-9_]{0,31}\Z')


def relational_schema(base):
    schema=deepcopy(base)
    def numeric(node):
        if isinstance(node,list):return [numeric(v) for v in node]
        if not isinstance(node,dict):return node
        result={k:numeric(v) for k,v in node.items()}
        if node.get('type') in {'number','integer'} and not node.get('enum'):
            return {'anyOf':[result,{'type':'object','properties':{'$expr':{'type':'string','maxLength':512}},'required':['$expr'],'additionalProperties':False}]}
        return result
    # Only construction-plan numeric fields can be calculated. Confidence,
    # interpretation flags and source claims retain their original schemas.
    for name,value in list(schema.get('$defs',{}).items()):
        if name not in {'ConstructionClarification','StructuredConstructionInterpretation'}:
            schema['$defs'][name]=numeric(value)
    schema['properties']['source_parameters']={'type':'array','maxItems':32,'items':{
        'type':'object','properties':{'name':{'type':'string'},'value':{'type':'number'},
            'unit':{'enum':list(UNITS)},'quote':{'type':'string'}},
        'required':['name','value','unit','quote'],'additionalProperties':False}}
    schema['properties']['relations']={'type':'object','maxProperties':64,'additionalProperties':{'type':'string','maxLength':512}}
    schema['required']=list(dict.fromkeys([*schema.get('required',[]),'source_parameters','relations']))
    return schema


def compile_relations(payload,source):
    if not isinstance(payload,dict):raise ValueError('关系输出必须为对象')
    result=deepcopy(payload);plan=result.get('plan')
    if not isinstance(plan,dict):raise ValueError('关系输出缺少plan')
    units=plan.get('units','m')
    if units not in {'m','mm'}:raise ValueError('计划单位仅允许m/mm')
    scale=UNITS[units]
    parameters=result.pop('source_parameters',None);relations=result.pop('relations',None)
    if not isinstance(parameters,list) or not 1<=len(parameters)<=32 or not isinstance(relations,dict) or not 1<=len(relations)<=64:
        raise ValueError('缺少有界参数表或关系表')
    values={};trace=[];active=set()
    def legal(name):
        return isinstance(name,str) and NAME.fullmatch(name) and name not in FUNCTIONS|{'pi','e','t','sind','cosd'}
    for p in parameters:
        if not isinstance(p,dict) or set(p)!={'name','value','unit','quote'}:raise ValueError('参数字段不完整')
        name,value,unit,quote=(p[k] for k in ('name','value','unit','quote'))
        if not legal(name) or name in values or name in relations:raise ValueError('参数名称无效或重复')
        if type(value) not in (int,float) or not math.isfinite(value) or abs(value)>1e6 or unit not in UNITS:raise ValueError('参数数值或单位无效')
        if not isinstance(quote,str) or not quote or quote not in source:raise ValueError('参数来源不能回指原文')
        literals=list(re.finditer(r'([-+]?\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m|度)(?![a-zA-Z])',quote,re.I))
        if unit=='scalar':
            grounded=not literals and any(abs(float(m[0])-value)<1e-10 for m in re.finditer(r'[-+]?\d+(?:\.\d+)?',quote))
        else:
            grounded=any(SOURCE_UNITS[m[2].lower()]==unit and abs(float(m[1])-value)<1e-10 for m in literals)
            # Coordinate tuples inherit the explicitly stated coordinate unit.
            if not grounded and re.search(r'[（(].*[,，].*[）)]',quote):
                coordinate_units=re.findall(r'坐标单位(?:为|是)?\s*(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])',source,re.I)
                grounded=bool(coordinate_units and all(SOURCE_UNITS[u.lower()]==unit for u in coordinate_units)
                    and any(abs(float(m[0])-value)<1e-10 for m in re.finditer(r'[-+]?\d+(?:\.\d+)?',quote)))
        if not grounded:raise ValueError('参数数值或单位与引用不一致：'+name)
        converted=value*UNITS[unit]/scale if unit in {'m','cm','mm'} else value
        values[name]=converted;trace.append({'name':name,'value_in_plan_units':converted,'quote':quote,'unit':unit})
    if any(not legal(name) or name in values for name in relations):raise ValueError('关系名称无效或与参数冲突')
    def resolve(name):
        if name in values:return values[name]
        if name not in relations:raise ValueError('关系引用未定义：'+name)
        if name in active:raise ValueError('关系循环依赖：'+name)
        active.add(name);value=calculate(relations[name]);active.remove(name)
        values[name]=value;trace.append({'name':name,'expression':relations[name],'value_in_plan_units':value})
        return value
    class Substitute(ast.NodeTransformer):
        def visit_Call(self,node):
            if not isinstance(node.func,ast.Name):raise ValueError('禁止属性或动态函数调用')
            if node.func.id in {'sind','cosd'}:
                if len(node.args)!=1 or node.keywords:raise ValueError('角度函数只接受一个参数')
                arg=self.visit(node.args[0])
                return ast.Call(func=ast.Name(id=node.func.id[:-1],ctx=ast.Load()),args=[ast.BinOp(left=ast.BinOp(left=arg,op=ast.Mult(),right=ast.Name(id='pi',ctx=ast.Load())),op=ast.Div(),right=ast.Constant(180))],keywords=[])
            if node.func.id not in FUNCTIONS:raise ValueError('未知函数')
            return ast.Call(func=node.func,args=[self.visit(a) for a in node.args],keywords=node.keywords)
        def visit_Name(self,node):
            if node.id in {'pi','e'}:return node
            if node.id=='t':raise ValueError('静态关系不能依赖t')
            return ast.copy_location(ast.Constant(resolve(node.id)),node)
    def calculate(raw):
        if not isinstance(raw,str) or len(raw)>512:raise ValueError('关系表达式无效')
        tree=ast.parse(raw,mode='eval')
        if len(list(ast.walk(tree)))>128:raise ValueError('关系过于复杂')
        tree=Substitute().visit(tree);ast.fix_missing_locations(tree)
        value=expression(ast.unparse(tree))(0)
        if not math.isfinite(value) or abs(value)>1e6:raise ValueError('关系数值越界')
        return value
    for name in relations:resolve(name)
    substitutions=0
    def walk(value):
        nonlocal substitutions
        if isinstance(value,list):return [walk(v) for v in value]
        if isinstance(value,dict):
            if set(value)=={'$expr'}:
                substitutions+=1
                return calculate(value['$expr'])
            return {k:walk(v) for k,v in value.items()}
        return value
    result['plan']=walk(plan)
    if substitutions==0:raise ValueError('关系组必须在计划中实际使用关系表达式')
    return result,{'parameters_and_relations':trace,'expression_substitution_count':substitutions,
                   'generic_compiler_only':True,'geometry_created_by_compiler':False}
