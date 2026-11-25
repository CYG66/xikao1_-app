from copy import deepcopy
from unittest.mock import patch

import pytest

from app.agent_service import RobotAgentService
from app.creative_projects import CreativeProjectStore
from app.cad_edit_contract import build_cad_edit_contract
from app.cad_edit_gate import build_cad_edit_preflight
from app.cad_semantic_acceptance import verify_semantic_requirements
from app.cad_semantic_source_coverage import verify_measured_semantic_coverage
from app.cad_structure_contract import StructureContractError


@pytest.mark.parametrize('original,answer', [
    ('画两个相交圆，圆心距离1.5米', '两个圆半径均为1米，坐标单位为米。'),
    ('生成四尖点星形线，闭合', '最大半径2米，坐标单位为米。'),
    ('画一个由六条线组成的图案', '每条线长2米，坐标单位为米。'),
    ('画一个闭合轮廓，顶点(0,0)(2,0)(1,1)', '坐标单位为米。'),
])
def test_source_scale_survives_followup_without_legacy_dimensions(tmp_path, original, answer):
    store = CreativeProjectStore(tmp_path/'projects.json')
    project = store.create('图案', original, requirements={'shape':'generic_2d_cad'},
                           missing_parameters=['dimensions'])
    with patch('app.agent_service.get_creative_project_store', return_value=store):
        result = RobotAgentService(restore_pending_actions=False)._apply_design_requirement_followup(
            answer, {'selected_project_id': project['id']})
    assert result['project_id'] == project['id']
    assert result['requirements']['source_followups'] == [answer]
    assert 'dimensions' not in result['missing_parameters']
    assert result['requirements_confirmation_required']


def test_units_alone_do_not_supply_a_missing_size(tmp_path):
    store = CreativeProjectStore(tmp_path/'projects.json')
    project = store.create('图案', '画一个闭合轮廓', requirements={'shape':'generic_2d_cad'},
                           missing_parameters=['dimensions'])
    with patch('app.agent_service.get_creative_project_store', return_value=store):
        result = RobotAgentService(restore_pending_actions=False)._apply_design_requirement_followup(
            '坐标单位为米。', {'selected_project_id':project['id']})
    assert 'dimensions' in result['missing_parameters']


@pytest.mark.parametrize('source,cleared',[
    ('画一个立方体的透视轮廓，边长2米',True),
    ('画一个带圆弧的轮廓，宽2米高2米',False)])
def test_straight_inventory_resolves_only_spurious_curve_question(tmp_path,source,cleared):
    store=CreativeProjectStore(tmp_path/'projects.json')
    project=store.create('轮廓',source,requirements={'shape':'generic_2d_cad'},missing_parameters=['curve_constraints'])
    with patch('app.agent_service.get_creative_project_store',return_value=store):
        result=RobotAgentService(restore_pending_actions=False)._apply_design_requirement_followup(
            '二维等轴投影，各投影棱长2米，只画12条棱线。',{'selected_project_id':project['id']})
    assert ('curve_constraints' not in result['missing_parameters'])==cleared


def test_structural_followup_to_review_draft_keeps_project_and_source_snapshot(tmp_path):
    from app.cad_construction_interpreter import interpret_construction_request
    original='生成一个闭合爱心轮廓，宽度4米，高度4米'
    answer='使用左右对称的平滑闭合轮廓。'
    store=CreativeProjectStore(tmp_path/'projects.json')
    project=store.create('图案',original,requirements={'shape':'generic_2d_cad',
        'dimensions':{'width_m':4,'height_m':4}},missing_parameters=[])
    store.add_variant(project['id'],'待复核',outline(),'尚待来源验证',{},[],
                      acceptance_summary={'status':'review_required','review_required':True})
    service=RobotAgentService(restore_pending_actions=False)
    seen=[]
    def interpret(text,**kwargs):
        seen.append(text)
        return interpret_construction_request(text,lambda *_:{
            'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
            'plan':{'units':'mm','steps':[{'op':'add_polyline','step_id':'outline','output_ref':'outline',
                'semantic':{'label':'爱心轮廓'},'closed':True,'vertices':outline()[0]['vertices']}]},
            'confidence':.95,'evidence_text':[original],'assumptions':[]},force_structured_model=True)
    with patch('app.agent_service.get_creative_project_store',return_value=store),patch.object(
            service,'_interpret_cad_construction_plan',side_effect=interpret):
        result=service._formal_cad_construction(answer,{'name':'drawing_design','operation':'create',
            'selected_project_id':project['id'],'user_message':answer},mode='advanced')
    assert result['project_id']==project['id'],result
    assert len(store.list())==1
    assert store.get(project['id'])['original_prompt']==original
    assert answer in store.get(project['id'])['requirements']['source_followups']
    assert all(answer in text and 'CAD_REQUIREMENT_CONTRACT_SNAPSHOT' in text for text in seen)


def circle():
    return [{'id':1,'type':'circle','center':{'x':0,'y':0},'radius':2000,'template_instance':1}]


def rotation():
    return build_cad_edit_contract({'operation':'rotate','instances':[1],
                                    'angle_degrees':-90,'pivot':'instance_center'})


def test_replayed_invariant_transform_is_success_without_new_version():
    source = circle()
    preflight = build_cad_edit_preflight(source, deepcopy(source), rotation())
    assert preflight['ready'] and preflight['already_satisfied']
    # An unchanged result cannot stand in for a requested translation.
    translation = build_cad_edit_contract({'operation':'translate','instances':[1],
                                           'dx_mm':1000,'dy_mm':0})
    rejected = build_cad_edit_preflight(source, deepcopy(source), translation)
    assert not rejected['ready'] and not rejected['already_satisfied']


def test_rotation_about_group_centre_cannot_leave_displaced_circles_unchanged():
    source = circle()+[{**circle()[0], 'id':2,'template_instance':2,'center':{'x':6000,'y':0}}]
    contract = build_cad_edit_contract({'operation':'rotate','instances':[1,2],
                                       'angle_degrees':90,'pivot':'group_center'})
    result = build_cad_edit_preflight(source, deepcopy(source), contract)
    assert not result['ready'] and not result['already_satisfied']


def outline():
    points=[(0,-2000),(-2000,500),(-1500,2000),(-500,2000),
            (0,1000),(500,2000),(1500,2000),(2000,500)]
    return [{'id':1,'type':'polyline','closed':True,
             'vertices':[{'x':x,'y':y} for x,y in points]}]


def test_source_proof_checks_dimensions_and_keeps_unmeasured_clauses_pending():
    source='生成一个闭合爱心轮廓，宽度4米，高度4米'
    measured=verify_semantic_requirements(source,outline())
    assert verify_measured_semantic_coverage(source,measured)['coverage']=='complete'
    assert verify_measured_semantic_coverage(source.replace('4米','5米'),measured)['coverage']=='partial'
    assert verify_measured_semantic_coverage(source+'，要求平滑并在(2,3)居中',measured)['coverage']=='partial'


def test_wrong_topology_requests_structural_replanning_without_weakening_shape_checks():
    source='生成一个闭合爱心轮廓，宽度4米，高度4米'
    wrong=outline()
    wrong[0]['vertices']=[{'x':-2000,'y':-2000},{'x':2000,'y':-2000},
                           {'x':2000,'y':2000},{'x':-2000,'y':2000}]
    with pytest.raises(StructureContractError) as failure:
        verify_semantic_requirements(source,wrong)
    assert failure.value.details['requires_structural_replan']
    assert failure.value.details['failed_features']


@pytest.mark.parametrize('case',['C9','C18','C22'])
def test_recorded_geometry_can_supply_missing_source_proof_without_a_generator(case):
    import json
    from pathlib import Path
    from app.cad_construction_interpreter import interpret_construction_request
    rows=json.loads((Path(__file__).parent/'fixtures/recorded_source_proof_gaps.json').read_text(encoding='utf-8'))['rows']
    row=next(r for r in rows if r['case']==case)
    source=row['original'] if case=='C18' else row['source']
    def interpret(text,plan):
        return interpret_construction_request(text,lambda *_:{
            'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
            'plan':deepcopy(plan),'confidence':.95,'evidence_text':[text],'assumptions':[]},
            force_structured_model=True)
    result=interpret(source,row['plan'])
    assert result['status']=='ready',result.get('error')
    assert result['acceptance_summary']['status']=='passed',result['source_acceptance']
    extra=interpret(source+'，另外添加一个红色标记',row['plan'])
    assert extra.get('acceptance_summary',{}).get('status')!='passed'
    # A scalar error must remain a measured failure, even after proof binding.
    wrong=deepcopy(row['plan'])
    first=wrong['steps'][0]
    if case=='C9':first['radius']*=.8
    elif case=='C18':first['x_expression']='cos(t)**3'
    else:first['end']['x']+=.2
    assert interpret(source,wrong)['status']=='invalid'
