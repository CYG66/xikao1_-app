from copy import deepcopy
import json
import math
from pathlib import Path
import pytest
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_projection_acceptance import projection_clarification_is_redundant

ROWS=json.loads((Path(__file__).parent/'fixtures/recorded_confirmed_source_failures.json').read_text(encoding='utf-8'))


def interpret(source,payload):
    return interpret_construction_request(source,lambda *_:deepcopy(payload),force_structured_model=True)


def test_recorded_bad_star_is_geometry_failure_not_unsupported_measurement():
    result=interpret(**ROWS['A10'])
    assert result['status']=='invalid'
    details=result['construction_error']['details']
    assert details['measurements']['cyclic_hull'] is False
    assert details['measurements']['maximum_hull_residual_mm']>.5
    assert details['requires_structural_replan']
    assert 'trial_result' not in result


def test_unresolved_arbitrary_circumcircle_is_not_misreported_as_bad_periodic_star():
    from app.cad_source_acceptance import verify_final_source_contract
    geometry={'id':1,'type':'polyline','closed':True,'vertices':[{'x':0,'y':0},{'x':4000,'y':0},{'x':500,'y':500}]}
    result=verify_final_source_contract('画一个三角形，外接圆半径3米',[geometry],[{'label':'三角形','geometry_refs':[1]}])
    assert result['coverage']!='complete'


def star_payload(radius=2,ratio=.381966,angle=90):
    vertices=[{'x':radius*(1 if i%2==0 else ratio)*math.cos(math.radians(angle+36*i)),
               'y':radius*(1 if i%2==0 else ratio)*math.sin(math.radians(angle+36*i))} for i in range(10)]
    return {'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
        'confidence':.99,'evidence_text':['生成一个五角星轮廓'],
        'plan':{'units':'m','steps':[{'op':'add_polyline','step_id':'outline','output_ref':'outline',
            'semantic':{'label':'五角星轮廓'},'closed':True,'vertices':vertices}]}}


@pytest.mark.parametrize('radius',[1.3,2,2.75])
def test_valid_star_reuses_source_radius_ratio_and_orientation_measurements(radius):
    source=ROWS['A10']['source'].replace('半径2米',f'半径{radius}米')
    result=interpret(source,star_payload(radius))
    assert result['status']=='ready',result.get('construction_error') or result.get('error')
    assert result['acceptance_summary']['status']=='passed',result['source_acceptance']


@pytest.mark.parametrize('damage',['radius','ratio','direction','extra_requirement'])
def test_star_source_checks_still_reject_wrong_geometry_or_unknown_clauses(damage):
    source=ROWS['A10']['source']
    payload=star_payload(2.2 if damage=='radius' else 2,.55 if damage=='ratio' else .381966,0 if damage=='direction' else 90)
    if damage=='extra_requirement':source+='，增加一个圆'
    assert interpret(source,payload).get('acceptance_summary',{}).get('status')!='passed'


def test_recorded_repeated_projection_question_becomes_repairable_planning_error():
    result=interpret(**ROWS['C27'])
    assert result['status']=='invalid'
    assert result['error']['code']=='confirmed_projection_reasked'
    assert result['requirements_complete']
    assert 'clarification' not in result


def test_recorded_missing_plan_is_a_planning_failure():
    result=interpret(**ROWS['C27_nonrequest'])
    assert result['status']=='invalid'
    assert result['error']['code']=='confirmed_projection_plan_missing'
    assert result['requirements_complete']
    assert 'clarification' not in result


@pytest.mark.parametrize('question',[
    '是否采用二维等轴投影？',
    '请确认各投影棱长2米，三条投影轴夹角120度。',
])
def test_confirmed_projection_paraphrases_are_redundant(question):
    assert projection_clarification_is_redundant(ROWS['C27']['source'],question)


@pytest.mark.parametrize('question',[
    '请确认投影棱长3米？','是否采用三条投影轴夹角90度？',
    '请确认投影观察方向和线宽？','请确认尺寸？',
])
def test_new_or_conflicting_projection_questions_are_not_suppressed(question):
    assert not projection_clarification_is_redundant(ROWS['C27']['source'],question)


def test_formal_repair_replans_redundant_projection_question_once(tmp_path):
    from unittest.mock import patch
    from app.agent_service import RobotAgentService
    from app.creative_projects import CreativeProjectStore
    good=json.loads((Path(__file__).parent/'fixtures/recorded_projection_dimension_snapshot.json').read_text(encoding='utf-8'))['previous_success_payload']
    calls=[]
    def model(text,**kwargs):
        calls.append(text)
        result=interpret(ROWS['C27']['source'],ROWS['C27']['payload'] if len(calls)==1 else good)
        result['provider_attempted']=True
        return result
    service=RobotAgentService(restore_pending_actions=False)
    store=CreativeProjectStore(tmp_path/'projects.json')
    with patch('app.agent_service.get_creative_project_store',return_value=store),patch.object(service,'_interpret_cad_construction_plan',side_effect=model):
        result=service._formal_cad_construction(ROWS['C27']['source'],{'name':'drawing_design','operation':'create'},mode='advanced')
    assert len(calls)==2
    assert '投影约定和尺寸已由原文确认' in calls[1]
    assert result['ok'] and result['variant']['acceptance_summary']['status']=='passed'


def test_native_circle_is_a_read_only_layout_reference_not_a_mutable_outline():
    from app.cad_construction import execute_construction_plan
    row=json.loads((Path(__file__).parent/'fixtures/recorded_native_layout_reference.json').read_text(encoding='utf-8'))
    payload=deepcopy(row['payload']);before=deepcopy(payload)
    baseline=deepcopy(payload['plan']);baseline['free_outline_layout']=[]
    circle=next(g for g in execute_construction_plan(baseline)['geometries'] if g['type']=='circle')
    result=interpret(**row)
    assert result['status']=='ready',result.get('construction_error') or result.get('error')
    assert result['acceptance_summary']['status']=='passed',result['source_acceptance']
    assert next(g for g in result['trial_result']['geometries'] if g['type']=='circle')==circle
    assert payload==before


def test_native_circle_still_rejects_mutable_free_outline_layout():
    row=json.loads((Path(__file__).parent/'fixtures/recorded_native_layout_reference.json').read_text(encoding='utf-8'))
    circle=next(s['output_ref'] for s in row['payload']['plan']['steps'] if s['op']=='add_circle')
    row['payload']['plan']['free_outline_layout'].insert(0,{'target_ref':circle,'width':2,'height':2})
    result=interpret(**row)
    assert result['status']=='invalid'
    details=result['construction_error']['details']
    assert details['layout_ref']==circle and details['reference_only'] is False
    assert details['actual_types']==['circle']


def test_overlapping_complete_views_allow_layout_replanning_without_changing_sizes():
    row=json.loads((Path(__file__).parent/'fixtures/recorded_native_layout_reference.json').read_text(encoding='utf-8'))
    row['payload']['plan']['free_outline_layout']=[]
    side=next(s for s in row['payload']['plan']['steps'] if s['op']=='add_polyline')
    cx=sum(float(p['x']) for p in side['vertices'])/len(side['vertices'])
    cy=sum(float(p['y']) for p in side['vertices'])/len(side['vertices'])
    for p in side['vertices']:p['x']=float(p['x'])-cx;p['y']=float(p['y'])-cy
    result=interpret(**row)
    assert result['status']=='invalid'
    details=result['construction_error']['details']
    assert details['side_width_matches_diameter'] is True
    assert details['views_disjoint'] is False
    assert details['requires_structural_replan'] is True
    assert len(details['affected_output_refs'])==2
    assert details['source_view_requirements']['side_width_mm']==2000


def test_dual_view_planning_receives_confirmed_roles_without_generated_coordinates():
    from app.cad_primitive_layout_acceptance import cylinder_view_requirements
    row=json.loads((Path(__file__).parent/'fixtures/recorded_native_layout_reference.json').read_text(encoding='utf-8'))
    prompts=[]
    def model(source,schema):prompts.append(source);return deepcopy(row['payload'])
    result=interpret_construction_request(row['source'],model,force_structured_model=True)
    assert result['acceptance_summary']['status']=='passed'
    assert '两个独立正投影视图的角色与尺寸关系' in prompts[0]
    assert cylinder_view_requirements('画一个圆柱体的轮廓，底面半径1米，高3米，俯视顶圆可见') is None
