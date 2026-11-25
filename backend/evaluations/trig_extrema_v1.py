"""Offline extrema candidates for a strict linear harmonic subset; no fitting."""
import ast
import math
from app.cad_parametric import expression

VERSION='cad.trig-extrema.v1'


def harmonic_coefficients(source):
    expression(source)  # Reuse the backend safety and complexity validation.
    def constant(node):
        if any(isinstance(n,ast.Name) and n.id=='t' for n in ast.walk(node)):raise ValueError('not constant')
        return expression(ast.unparse(node))(0)
    def add(a,b,scale=1):
        result=dict(a)
        for key,value in b.items():result[key]=result.get(key,0)+scale*value
        return {k:v for k,v in result.items() if v!=0}
    def parse(node):
        try:return {'constant':constant(node)}
        except ValueError:pass
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            sign=-1 if isinstance(node.op,ast.USub) else 1
            return {k:sign*v for k,v in parse(node.operand).items()}
        if isinstance(node,ast.BinOp):
            if isinstance(node.op,(ast.Add,ast.Sub)):
                return add(parse(node.left),parse(node.right),-1 if isinstance(node.op,ast.Sub) else 1)
            if isinstance(node.op,ast.Mult):
                try:scale=constant(node.left);other=node.right
                except ValueError:scale=constant(node.right);other=node.left
                return {k:scale*v for k,v in parse(other).items()}
            if isinstance(node.op,ast.Div):
                scale=constant(node.right)
                if scale==0:raise ValueError('zero denominator')
                return {k:v/scale for k,v in parse(node.left).items()}
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in {'sin','cos'} and len(node.args)==1:
            arg=node.args[0];frequency=1
            if not (isinstance(arg,ast.Name) and arg.id=='t'):
                if not isinstance(arg,ast.BinOp) or not isinstance(arg.op,ast.Mult):raise ValueError('unsupported phase')
                if isinstance(arg.left,ast.Name) and arg.left.id=='t':frequency=constant(arg.right)
                elif isinstance(arg.right,ast.Name) and arg.right.id=='t':frequency=constant(arg.left)
                else:raise ValueError('unsupported argument')
            if frequency not in (1,2):raise ValueError('unsupported frequency')
            return {f'{node.func.id}{int(frequency)}':1.0}
        raise ValueError('unsupported harmonic expression')
    return parse(ast.parse(source,mode='eval').body)


def extrema(source,start,end):
    result={'version':VERSION,'formal_candidate_accepted':False,'interval_arithmetic_proof':False,
        'coordinate_units':'same_as_expression','layout_applied':False}
    try:
        if not (math.isfinite(start) and math.isfinite(end) and 0<end-start<=4*math.pi):raise ValueError('unsupported interval')
        coefficients=harmonic_coefficients(source)
        sin1=coefficients.get('sin1',0);sin2=coefficients.get('sin2',0)
        cos1=coefficients.get('cos1',0);cos2=coefficients.get('cos2',0)
        if sin2 or (sin1 and (cos1 or cos2)):raise ValueError('unsupported harmonic mixture')
        if not (sin1 or cos1 or cos2):
            value=expression(source)(start)
            return {**result,'status':'constant_axis','minimum':value,'maximum':value,'coefficients':coefficients}
        seeds=[math.pi/2,3*math.pi/2] if sin1 else [0,math.pi]
        if cos2:
            ratio=-cos1/(4*cos2)
            if -1<=ratio<=1:
                angle=math.acos(ratio);seeds += [angle,-angle]
        ts={start,end}
        for seed in seeds:
            for turn in range(math.floor((start-seed)/math.tau),math.ceil((end-seed)/math.tau)+1):
                t=seed+turn*math.tau
                if start<=t<=end:ts.add(t)
        evaluate=expression(source)
        candidates=[{'t':t,'value':evaluate(t)} for t in sorted(ts)]
        return {**result,'status':'analytic_candidates_evaluated','coefficients':coefficients,
            'candidates':candidates,'minimum':min(p['value'] for p in candidates),
            'maximum':max(p['value'] for p in candidates)}
    except (ValueError,OverflowError,RecursionError):
        return {**result,'status':'unverified','reason':'outside_supported_expression_or_numeric_scope'}
