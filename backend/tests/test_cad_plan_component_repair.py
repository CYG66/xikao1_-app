from copy import deepcopy
import pytest
from app.cad_plan_component_repair import merge_component_repair


def test_identity_repair_cannot_change_geometry_or_assembly():
    plan={'units':'m','steps':[{'step_id':ref,'output_ref':ref,'op':'add_circle',
        'radius':radius,'center':{'x':0,'y':0},
        'semantic':{'object_id':'duplicate','assembly_id':'whole','label':ref}}
        for ref,radius in [('a',2),('b',1)]], 'assertions':[{'kind':'closed','assertion_id':'closed','target_ref':'a'}]}
    context={'plan':plan,'construction_error':{'details':{
        'identity_only_repair':True,'affected_output_refs':['a','b']}}}
    payload={'plan':deepcopy(plan)}
    for i,step in enumerate(payload['plan']['steps']):
        step['radius']=99
        step['semantic'].update(object_id=f'part-{i}',assembly_id='wrong')
    result=merge_component_repair(context,payload)['plan']
    for i,step in enumerate(result['steps']):
        expected=deepcopy(plan['steps'][i]);expected['semantic']['object_id']=f'part-{i}'
        assert step==expected
    assert result['assertions']==plan['assertions']


def test_executor_exposes_only_conflicting_step_refs_for_identity_repair():
    from app.cad_construction import execute_construction_plan, ConstructionPlanError
    plan={'units':'m','steps':[{'op':'add_circle','step_id':ref,'output_ref':ref,
        'center':{'x':x,'y':0},'radius':.2,
        'semantic':{'label':ref,'object_id':identity,'assembly_id':'whole','assembly_label':'完整对象'}}
        for ref,x,identity in [('a',0,'duplicate'),('b',1,'duplicate'),('c',2,'unique')]]}
    with pytest.raises(ConstructionPlanError) as caught:
        execute_construction_plan(plan)
    assert caught.value.code=='logical_graph_invalid'
    assert caught.value.details['identity_only_repair'] is True
    assert caught.value.details['affected_output_refs']==['a','b']


def test_only_failed_assertion_can_change_with_affected_component():
    old={'units':'m','steps':[{'step_id':'a','output_ref':'a','op':'add_polyline'},
        {'step_id':'b','output_ref':'b','op':'add_circle'}],
        'assertions':[{'assertion_id':'bad','target_ref':'a','width':3,'height':3},
                      {'assertion_id':'keep','target_ref':'b','radius':.8}]}
    context={'plan':old,'construction_error':{'assertion_id':'bad','details':{'affected_output_refs':['a']}}}
    proposed={'plan':{'units':'m','steps':[old['steps'][0]],'assertions':[
        {'assertion_id':'bad','target_ref':'a','width':3,'height':2.598},
        {'assertion_id':'keep','target_ref':'b','radius':9}]}}
    merged=merge_component_repair(context,proposed)['plan']
    assert merged['assertions'][0]['height']==2.598
    assert merged['assertions'][1]==old['assertions'][1]
    assert merged['steps'][1]==old['steps'][1]


def test_partial_repair_preserves_other_component_and_layout():
    plan = {'units': 'm', 'steps': [
        {'step_id': 'a', 'output_ref': 'a', 'op': 'add_polyline', 'vertices': [1]},
        {'step_id': 'b', 'output_ref': 'b', 'op': 'add_rotational_path', 'center': {'x': 6, 'y': 0}}],
        'assertions': [{'target_ref': 'b'}], 'free_outline_layout': [{'target_ref': 'b'}]}
    context = {'plan': plan, 'construction_error': {'details': {'affected_output_refs': ['a']}}}
    payload = {'plan': {'units': 'm', 'steps': [
        {'step_id': 'changed', 'output_ref': 'a', 'op': 'add_polyline', 'vertices': [2]}]}}
    before = deepcopy((context, payload))
    result = merge_component_repair(context, payload)['plan']
    assert result['steps'][0]['vertices'] == [2]
    assert result['steps'][0]['step_id'] == 'a'
    assert result['steps'][1] == plan['steps'][1]
    assert result['units'] == 'm'
    assert result['assertions'] == plan['assertions']
    assert result['free_outline_layout'] == plan['free_outline_layout']
    assert (context, payload) == before
    with pytest.raises(ValueError):
        merge_component_repair(context, {'plan': {'steps': []}})
    changed_units = deepcopy(payload)
    changed_units['plan']['units'] = 'mm'
    with pytest.raises(ValueError, match='单位'):
        merge_component_repair(context, changed_units)
