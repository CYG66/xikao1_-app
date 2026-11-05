from copy import deepcopy
from unittest.mock import patch, PropertyMock
import json
import pytest
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_local_repair import validate_local_repair, build_local_repair_scope, apply_coordinate_patch, coordinate_patch_example
from app.agent_service import RobotAgentService
from app.creative_projects import CreativeProjectStore

SOURCE='生成一个大写字母A的轮廓，高3米宽2米'


def payload(fixed=False):
    points=([(0,0),(.85,3),(1.15,3),(2,0),(1.55,0),(1.35,.75),(.65,.75),(.45,0)]
            if fixed else [(0,0),(1,3),(2,0)])
    steps=[]
    for ref,vertices in [('outer',points),('inner',[(.8,1.4),(1.2,1.4),(1,2.4)])]:
        steps.append({'op':'add_polyline','step_id':ref,'output_ref':ref,'closed':True,
            'semantic':{'object_id':ref,'label':ref,'assembly_id':'A','assembly_label':'字母A'},
            'vertices':[{'x':x,'y':y} for x,y in vertices]})
    return {'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
            'confidence':.95,'evidence_text':[SOURCE],'assumptions':[],
            'plan':{'units':'m','steps':steps}}


def interpretations():
    before=interpret_construction_request(SOURCE,lambda *_:payload(),force_structured_model=True)
    after=interpret_construction_request(SOURCE,lambda *_:payload(True),force_structured_model=True)
    assert before['status']=='invalid' and after['status']=='ready'
    return before,after


def test_scope_is_backend_measured_and_permits_only_failed_path_coordinates():
    before,after=interpretations()
    scope=before['construction_error']['details']['local_repair_scope']
    assert scope['editable_fields_by_ref']=={'outer':['vertices']}
    assert list(scope['protected_geometry_sha256_by_ref'])==['inner']
    checked=validate_local_repair(before,after)
    assert checked['verified']
    assert checked['changed_step_refs']==['outer']
    assert checked['changed_fields_by_ref']['outer']['vertices']['before'] != checked['changed_fields_by_ref']['outer']['vertices']['after']


@pytest.mark.parametrize('mutation',['protected_coordinates','rename','global','actual_geometry','new_step'])
def test_local_repair_rejects_unrelated_changes_even_if_model_claims_success(mutation):
    before,after=interpretations()
    if mutation=='protected_coordinates':after['plan']['steps'][1]['vertices'][0]['x']+=.01
    elif mutation=='rename':after['plan']['steps'][0]['semantic']['object_id']='replacement'
    elif mutation=='global':after['plan']['units']='mm'
    elif mutation=='new_step':after['plan']['steps'].append(deepcopy(after['plan']['steps'][0]))
    else:after['trial_result']['geometries'][1]['vertices'][0]['x']+=10
    checked=validate_local_repair(before,after)
    assert checked['enforced'] and not checked['verified']


def test_unscoped_failure_does_not_claim_to_lock_parts():
    assert build_local_repair_scope({}, {}, {}) is None
    assert validate_local_repair({}, {})=={'enforced':False,'verified':True,'reason':'no_verified_local_scope'}


def test_format_example_contains_only_original_coordinates_and_cannot_be_saved_as_a_fix():
    before,_=interpretations();example=json.loads(json.dumps(coordinate_patch_example(before)))
    assert example['edits'][0]['vertices']==before['plan']['steps'][0]['vertices']
    with pytest.raises(ValueError,match='没有修改'):apply_coordinate_patch(before,example)


def test_plan_lock_is_not_full_success_when_geometry_trial_failed():
    before,after=interpretations();after['status']='invalid';after.pop('trial_result')
    checked=validate_local_repair(before,after)
    assert checked['plan_fields_preserved'] and not checked['verified']
    assert checked['reason']=='repair_trial_not_ready'


def test_coupled_constraints_disable_local_scope_inference():
    before,after=interpretations()
    plan=deepcopy(before['plan']);plan['constraints']=[{'kind':'coincident'}]
    assert build_local_repair_scope(plan,after['trial_result'],before['construction_error']['details']) is None


@pytest.mark.parametrize('change_protected',[False,True])
def test_production_commit_stops_protected_part_change(tmp_path,change_protected):
    service=RobotAgentService(restore_pending_actions=False);service.mode='deepseek'
    repaired=payload(True)
    if change_protected:
        for p in repaired['plan']['steps'][1]['vertices']:p['x']+=.01
    # Both geometric results remain valid; only the repair scope distinguishes them.
    assert interpret_construction_request(SOURCE,lambda *_:repaired,force_structured_model=True)['status']=='ready'
    before,_=interpretations()
    patch_payload={'schema_version':'cad.coordinate-patch.v2',
        'source_plan_sha256':before['construction_error']['details']['local_repair_scope']['source_plan_sha256'],
        'confidence':.95,'edits':[{'output_ref':'inner' if change_protected else 'outer',
            'vertices':repaired['plan']['steps'][1 if change_protected else 0]['vertices']}]}
    store=CreativeProjectStore(tmp_path/'projects.json')
    with patch('app.agent_service.get_creative_project_store',return_value=store),patch.object(RobotAgentService,'configured',new_callable=PropertyMock,return_value=True),patch.object(service,'_structured_review_text',side_effect=[json.dumps(payload()),json.dumps(patch_payload)]):
        result=service._formal_cad_construction(SOURCE,{'name':'drawing_design','operation':'create'},mode='advanced')
    variants=[v for project in store.list() for v in project.get('variants') or []]
    assert len(variants)==(0 if change_protected else 1)
    if change_protected:
        assert result['ok'] is False
        recovery=result['construction_interpretation']['recovery']
        assert recovery['attempts'][1]['local_repair_validation']['verified'] is False
    else:
        assert result['ok'] is True
        attempt=result['variant']['construction_record']['recovery']['attempts'][1]
        assert attempt['coordinate_patch']['schema']=='cad.coordinate-patch.v2'
        assert attempt['coordinate_patch']['patched_refs']==['outer']
        assert attempt['local_repair_validation']['protected_step_refs']==['inner']


@pytest.mark.parametrize('mutation',['source_hash','protected_ref','metadata','duplicate','full_plan','no_change'])
def test_patch_protocol_cannot_modify_protected_data_or_replay_against_different_source(mutation):
    before,after=interpretations();snapshot=deepcopy(before)
    p={'schema_version':'cad.coordinate-patch.v2',
       'source_plan_sha256':before['construction_error']['details']['local_repair_scope']['source_plan_sha256'],
       'confidence':.95,'edits':[{'output_ref':'outer','vertices':after['plan']['steps'][0]['vertices']}]}
    valid=apply_coordinate_patch(before,p)
    assert valid['steps'][1]==before['plan']['steps'][1] and before==snapshot
    if mutation=='source_hash':p['source_plan_sha256']='0'*64
    elif mutation=='protected_ref':p['edits'][0]['output_ref']='inner'
    elif mutation=='metadata':p['edits'][0]['semantic']={'object_id':'other'}
    elif mutation=='duplicate':p['edits'].append(deepcopy(p['edits'][0]))
    elif mutation=='full_plan':p['plan']=after['plan']
    else:p['edits'][0]['vertices']=before['plan']['steps'][0]['vertices']
    with pytest.raises(ValueError):apply_coordinate_patch(before,p)
    assert before==snapshot


def boolean_patch(before,rectangle):
    return {'schema_version':'cad.coordinate-patch.v2','source_plan_sha256':before['construction_error']['details']['local_repair_scope']['source_plan_sha256'],
            'confidence':.95,'edits':[{'output_ref':'outer','subtract_rectangle':rectangle}]}


def test_relative_cut_uses_measured_window_and_preserves_geometry():
    before,_=interpretations();snapshot=deepcopy(before)
    window=before['construction_error']['details']['local_repair_scope']['cut_windows_by_ref']['outer']
    assert window['bounds_in_plan_units']==[0,0,2,1.4]
    p=boolean_patch(before,{})
    p['edits'][0]={'output_ref':'outer','subtract_relative_rectangle':{
        'left_fraction':.3,'right_fraction':.7,'height_fraction':.5}}
    merged=apply_coordinate_patch(before,p)
    model=payload();model['plan']=merged
    repaired=interpret_construction_request(SOURCE,lambda *_:model,force_structured_model=True)
    assert repaired['status']=='ready',repaired
    assert validate_local_repair(before,repaired)['verified']
    assert before==snapshot


@pytest.mark.parametrize('left,right,height',[(0,.7,.5),(.3,1,.5),(.7,.3,.5),(.3,.7,False),(.3,.7,float('inf'))])
def test_relative_cut_rejects_invalid_ratios(left,right,height):
    before,_=interpretations();p=boolean_patch(before,{})
    p['edits'][0]={'output_ref':'outer','subtract_relative_rectangle':{
        'left_fraction':left,'right_fraction':right,'height_fraction':height}}
    with pytest.raises(ValueError):apply_coordinate_patch(before,p)


def test_relative_cut_requires_backend_window_and_exclusive_action():
    before,_=interpretations();p=boolean_patch(before,{})
    p['edits'][0]['subtract_relative_rectangle']={'left_fraction':.3,'right_fraction':.7,'height_fraction':.5}
    with pytest.raises(ValueError):apply_coordinate_patch(before,p)
    p['edits'][0].pop('subtract_rectangle')
    before['construction_error']['details']['local_repair_scope']['cut_windows_by_ref']={}
    with pytest.raises(ValueError):apply_coordinate_patch(before,p)


def test_generic_boolean_cut_computes_vertices_and_preserves_protected_path():
    before,_=interpretations();snapshot=deepcopy(before)
    patch_payload=boolean_patch(before,{'min_x':.6,'min_y':-.1,'max_x':1.4,'max_y':.75})
    merged=apply_coordinate_patch(before,patch_payload)
    assert before==snapshot and merged['steps'][1]==before['plan']['steps'][1]
    model=payload();model['plan']=merged
    repaired=interpret_construction_request(SOURCE,lambda *_:model,force_structured_model=True)
    assert repaired['status']=='ready',repaired
    assert validate_local_repair(before,repaired)['verified']


@pytest.mark.parametrize('rectangle',[
    {'min_x':.9,'min_y':1,'max_x':1.1,'max_y':1.2},  # Unsupported new inner ring.
    {'min_x':-.1,'min_y':1,'max_x':2.1,'max_y':1.1}, # Splits the boundary.
    {'min_x':-.1,'min_y':-.1,'max_x':2.1,'max_y':3.1}, # Removes protected region.
    {'min_x':10,'min_y':10,'max_x':11,'max_y':11}, # No geometric effect.
    {'min_x':.9,'min_y':1.3,'max_x':1.1,'max_y':1.6}, # Touches protected path.
    {'min_x':1,'min_y':0,'max_x':0,'max_y':1},
    {'min_x':False,'min_y':0,'max_x':1,'max_y':1},
    {'min_x':0,'min_y':0,'max_x':float('nan'),'max_y':1},
])
def test_boolean_patch_cannot_delete_split_touch_protected_or_create_holes(rectangle):
    before,_=interpretations();snapshot=deepcopy(before)
    with pytest.raises(ValueError):apply_coordinate_patch(before,boolean_patch(before,rectangle))
    assert before==snapshot


def test_boolean_patch_cannot_mix_operations_or_target_protected_ref():
    before,_=interpretations();p=boolean_patch(before,{'min_x':.6,'min_y':-.1,'max_x':1.4,'max_y':.75})
    p['edits'][0]['vertices']=before['plan']['steps'][0]['vertices']
    with pytest.raises(ValueError):apply_coordinate_patch(before,p)
    p['edits'][0].pop('vertices');p['edits'][0]['output_ref']='inner'
    with pytest.raises(ValueError):apply_coordinate_patch(before,p)
