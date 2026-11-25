from copy import deepcopy
import json
import math
import pytest
from evaluations.relation_pilot.compiler import compile_relations,relational_schema
from evaluations.relation_pilot.cases import cases,expected_entities
from evaluations.relation_pilot.oracle import evaluate,boundary
from evaluations.relation_pilot.run import schema_for_pilot
from app.cad_construction import execute_construction_plan


SOURCE='坐标单位为厘米。线段起点(12,-8)，长度37厘米，方向23度。'


def packet():
    return {'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,'confidence':.99,'evidence_text':[SOURCE],
        'source_parameters':[{'name':name,'value':value,'unit':unit,'quote':quote} for name,value,unit,quote in
            [('x0',12,'cm','(12,-8)'),('y0',-8,'cm','(12,-8)'),('length',37,'cm','长度37厘米'),('angle',23,'deg','方向23度')]],
        'relations':{'dx':'length*cosd(angle)','dy':'length*sind(angle)'},
        'plan':{'units':'m','steps':[{'op':'add_line','step_id':'s','output_ref':'s','semantic':{'label':'线段'},
            'start':{'x':{'$expr':'x0'},'y':{'$expr':'y0'}},'end':{'x':{'$expr':'x0+dx'},'y':{'$expr':'y0+dy'}}}]}}


def test_generic_compiler_uses_existing_safe_arithmetic_and_preserves_input():
    payload=packet();before=deepcopy(payload)
    compiled,trace=compile_relations(payload,SOURCE)
    geometry=execute_construction_plan(compiled['plan'])['geometries'][0]
    assert geometry['start']['x']==pytest.approx(120)
    assert geometry['end']['x']==pytest.approx(120+370*math.cos(math.radians(23)))
    assert geometry['end']['y']==pytest.approx(-80+370*math.sin(math.radians(23)))
    assert trace['expression_substitution_count']==4
    assert payload==before and 'source_parameters' not in compiled


@pytest.mark.parametrize('damage',['cycle','undefined','python','wrong_quote','wrong_unit','no_expression'])
def test_invalid_relation_packets_never_generate_geometry(damage):
    payload=packet()
    if damage=='cycle':payload['relations'].update(dx='dy',dy='dx')
    elif damage=='undefined':payload['relations']['dx']='unknown+1'
    elif damage=='python':payload['relations']['dx']="__import__('os').getcwd()"
    elif damage=='wrong_quote':payload['source_parameters'][2]['quote']='长度38厘米'
    elif damage=='wrong_unit':payload['source_parameters'][2]['unit']='m'
    else:payload['plan']['steps']=[]
    with pytest.raises((ValueError,RecursionError)):compile_relations(payload,SOURCE)


def test_both_schemas_retain_shared_points_and_constraint_tools():
    schema=schema_for_pilot();alternative=relational_schema(schema)
    for s in (schema,alternative):
        assert 'shared_points' in s['$defs']['CadConstructionPlan']['properties']
        assert 'constraints' in s['$defs']['CadConstructionPlan']['properties']
        assert len(s['$defs']['CadConstructionPlan']['properties']['steps']['items']['oneOf'])==6
        def visit(value):
            if isinstance(value,dict):
                if '$ref' in value:assert value['$ref'].rsplit('/',1)[-1] in s['$defs']
                for child in value.values():visit(child)
            elif isinstance(value,list):
                for child in value:visit(child)
        visit(s)
    assert 'source_parameters' not in schema['properties']


@pytest.mark.parametrize('row',cases(),ids=lambda row:row['id'])
def test_all_frozen_targets_are_executable_and_oracle_accepts(row):
    entities=expected_entities(row)
    plan={'units':'mm','steps':[{'op':'add_'+g['type'],'step_id':str(i),'output_ref':'g'+str(i),
        'semantic':{'label':'部件'+str(i),'assembly_id':'pilot','assembly_label':'图形'},
        **{k:v for k,v in g.items() if k not in {'id','type'}}} for i,g in enumerate(entities)]}
    result=execute_construction_plan(plan)
    assert evaluate(row,result['geometries'])['passed']


def test_oracle_rejects_extra_shortcut_even_when_vertices_are_on_correct_boundary():
    row=next(r for r in cases() if r['id']=='H1');entities=expected_entities(row)
    a=entities[0]['start'];b=entities[1]['end']
    entities.append({'id':99,'type':'line','start':a,'end':b})
    result=evaluate(row,entities)
    assert not result['passed'] and result['candidate_outside_target_tolerance']


def test_oracle_rejects_missing_curve_and_wrong_units():
    row=cases()[0];entities=expected_entities(row)
    assert not evaluate(row,entities[:1])['passed']
    bad=deepcopy(entities)
    for g in bad:
        for field in ('start','end','center'):
            if field in g:
                for axis in ('x','y'):g[field][axis]*=1000
        if 'radius' in g:g['radius']*=1000
    assert not evaluate(row,bad)['passed']


def test_analytic_arch_and_capsule_dimensions_are_independently_consistent():
    row=next(r for r in cases() if r['id']=='H1');shape=boundary(expected_entities(row))
    assert shape.bounds==pytest.approx((730,-1210,4130,3490))
    row=next(r for r in cases() if r['id']=='R1');shape=boundary(expected_entities(row))
    assert shape.length==pytest.approx((2*(5.7-1.46)+math.pi*1.46)*1000,abs=.2)
