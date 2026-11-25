from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from app.cad_construction import ConstructionPlanError, execute_construction_plan
from app.cad_construction_interpreter import (
    interpret_construction_request, normalize_composite_path_connections_once,
)

ROWS = {r['case']: r for r in json.loads((Path(__file__).parent / 'fixtures' /
    'recorded_joint_and_array_failures.json').read_text(encoding='utf-8'))}


def test_sampling_edges_are_not_reported_as_editable_curve_segment_indices():
    plan={'units':'m','steps':[{'op':'add_composite_path','step_id':'bow','output_ref':'bow',
        'semantic':{'label':'交叉路径'},'closed':True,'segments':[
            {'kind':'bezier','control_points':[{'x':0,'y':0},{'x':.5,'y':.5},{'x':1.5,'y':1.5},{'x':2,'y':2}]},
            {'kind':'line','start':{'x':2,'y':2},'end':{'x':0,'y':2}},
            {'kind':'line','start':{'x':0,'y':2},'end':{'x':2,'y':0}},
            {'kind':'line','start':{'x':2,'y':0},'end':{'x':0,'y':0}}]}]}
    before=deepcopy(plan)
    with pytest.raises(ConstructionPlanError) as caught:execute_construction_plan(plan)
    details=caught.value.details
    assert caught.value.code=='self_intersecting_composite_path'
    assert details['affected_segment_indices']==[0,2]
    assert max(details['affected_sample_edge_indices'])>3
    assert plan==before


def test_recorded_rotational_crossing_reaches_repair_with_effective_seed_evidence():
    row=json.loads((Path(__file__).parent/'fixtures/recorded_rotational_crossing_handoff.json').read_text(encoding='utf-8'))
    payload=deepcopy(row['payload']);before=deepcopy(payload)
    result=interpret_construction_request(row['source'],lambda *_:payload,force_structured_model=True)
    assert result['status']=='invalid'
    error=result['construction_error'];details=error['details']
    assert error['code']=='self_intersecting_composite_path'
    assert details['affected_output_refs']==[payload['plan']['steps'][0]['output_ref']]
    assert details['affected_seed_segment_indices']==sorted({i for pair in details['conflicts'] for i in pair['seed_segment_indices']})
    assert len(details['effective_seed_segments'])==details['seed_segment_count']==4
    assert details['rotation_count']==8
    assert '零起算索引' in details['repair_instruction']
    assert 'trial_result' not in result
    assert payload==before


def test_formal_rotational_repair_receives_seed_indices_and_stops_repeated_failure(tmp_path):
    from unittest.mock import patch
    from app.agent_service import RobotAgentService
    from app.creative_projects import CreativeProjectStore
    row=json.loads((Path(__file__).parent/'fixtures/recorded_rotational_crossing_handoff.json').read_text(encoding='utf-8'))
    calls=[]
    def model(text,**kwargs):
        calls.append((text,kwargs))
        result=interpret_construction_request(row['source'],lambda *_:deepcopy(row['payload']),force_structured_model=True)
        result['provider_attempted']=True
        return result
    service=RobotAgentService(restore_pending_actions=False)
    store=CreativeProjectStore(tmp_path/'projects.json')
    with patch('app.agent_service.get_creative_project_store',return_value=store),patch.object(service,'_interpret_cad_construction_plan',side_effect=model):
        result=service._formal_cad_construction(row['source'],{'name':'drawing_design','operation':'create'},mode='advanced')
    assert len(calls)==2
    assert 'affected_seed_segment_indices' in calls[1][0]
    assert 'effective_seed_segments' in calls[1][0]
    assert '采样小边编号' in calls[1][0]
    assert calls[1][1]['component_repair_context']['construction_error']['code']=='self_intersecting_composite_path'
    assert result['ok'] is False
    assert all(not project['variants'] for project in store.list())


@pytest.mark.parametrize('closed', [True, False])
def test_all_disconnected_joints_are_reported_without_moving_endpoints(closed):
    plan = json.loads((Path(__file__).parent / 'fixtures/recorded_disconnected_outline.json').read_text(encoding='utf-8'))
    plan['steps'][0]['closed'] = closed
    if not closed:
        plan['steps'][0]['junction_constraints'] = [j for j in plan['steps'][0]['junction_constraints'] if j['right_segment_index'] != 0]
    before = deepcopy(plan)
    with pytest.raises(ConstructionPlanError) as caught:
        execute_construction_plan(plan)
    assert plan == before
    error = caught.value
    assert error.code == 'disconnected_composite_path'
    gaps = error.details['disconnected_joints']
    assert [(g['previous_segment'], g['next_segment']) for g in gaps] == [(1, 2), (3, 4)]
    assert all(g['gap'] == pytest.approx(.90553851381374) for g in gaps)
    assert 'shared_points' in error.details['repair_instruction']


def interpret(row, source=None, plan=None):
    return interpret_construction_request(source or row['source'], lambda *_: {
        'schema_version': 'cad.construction-interpretation.v1',
        'is_construction_request': True, 'confidence': .99,
        'evidence_text': [row['original']], 'plan': deepcopy(plan or row['plan']),
    }, force_structured_model=True)


def test_recorded_smooth_outline_is_repaired_and_can_be_saved(tmp_path):
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    row = ROWS['A9']
    with pytest.raises(ConstructionPlanError, match='C1'):
        execute_construction_plan(row['plan'])
    original = deepcopy(row['plan'])
    result = interpret(row)
    assert row['plan'] == original
    assert result['acceptance_summary']['status'] == 'passed'
    changes = [r for r in result['deterministic_repairs'] if r['kind'] == 'align_free_cubic_joint']
    assert len(changes) == 2
    store = CreativeProjectStore(tmp_path / 'projects.json')
    saved = commit_construction_interpretation(row['source'], result, store=store)
    assert store.get(saved['project_id'])['variants'][-1]['acceptance_summary']['status'] == 'passed'


@pytest.mark.parametrize('extra', ['，面积20平方米', '，再加一个圆', '，整体旋转20度'])
def test_handle_correction_does_not_accept_unverified_requirements(extra):
    assert interpret(ROWS['A9'], ROWS['A9']['source'] + extra).get('acceptance_summary', {}).get('status') != 'passed'


def free_path(angle=0, scale=1):
    def point(x, y):
        t = math.radians(angle)
        return {'x': 13+scale*(x*math.cos(t)-y*math.sin(t)),
                'y': -7+scale*(x*math.sin(t)+y*math.cos(t))}
    return {'plan': {'schema_version': 'cad.construction-plan.v1', 'units': 'm',
        'steps': [{'step_id': 'path', 'output_ref': 'path', 'op': 'add_composite_path',
            'semantic': {'assembly_id': 'curve', 'assembly_label': '曲线',
                'object_id': 'path', 'object_type': 'free_curve', 'label': '曲线', 'role': 'outline'},
            'closed': False, 'continuity': 'C1', 'segments': [
                {'kind': 'bezier', 'control_points': [point(0, 0), point(.5, -.3), point(1, 0), point(2, 0)]},
                {'kind': 'bezier', 'control_points': [point(2, 0), point(2, 1), point(2.5, 2), point(3, 2)]},
            ]}], 'constraints': [], 'assertions': []}}


@pytest.mark.parametrize('angle,scale', [(0, 1), (37, .2), (90, 4), (213, 2)])
def test_general_open_cubic_chain_at_arbitrary_pose(angle, scale):
    payload = free_path(angle, scale)
    original = deepcopy(payload)
    with pytest.raises(ConstructionPlanError):
        execute_construction_plan(payload['plan'])
    corrected, changes = normalize_composite_path_connections_once(payload, '生成一条平滑曲线')
    assert payload == original
    assert [c['kind'] for c in changes] == ['align_free_cubic_joint']
    segments = corrected['plan']['steps'][0]['segments']
    for before, after in zip(original['plan']['steps'][0]['segments'], segments):
        assert before['control_points'][0] == after['control_points'][0]
        assert before['control_points'][-1] == after['control_points'][-1]
    a, b = [s['control_points'] for s in segments]
    for axis in ('x', 'y'):
        assert 3*(a[-1][axis]-a[-2][axis]) == pytest.approx(3*(b[1][axis]-b[0][axis]))
    assert execute_construction_plan(corrected['plan'])['geometries']
    assert normalize_composite_path_connections_once(corrected, '生成一条平滑曲线')[1] == []


@pytest.mark.parametrize('source', ['按控制点生成平滑曲线', '保持端点生成平滑曲线',
    '按参数式生成平滑曲线', '平滑曲线并保留尖点', '生成一条曲线'])
def test_fixed_or_unspecified_smoothness_does_not_move_handles(source):
    payload = free_path()
    corrected, changes = normalize_composite_path_connections_once(payload, source)
    assert all(c['kind'] != 'align_free_cubic_joint' for c in changes)
    assert [s['control_points'] for s in corrected['plan']['steps'][0]['segments']] == [
        s['control_points'] for s in payload['plan']['steps'][0]['segments']]


@pytest.mark.parametrize('mode', ['opposite', 'degenerate', 'mixed_degree', 'constraints'])
def test_ambiguous_or_constrained_handles_remain_rejected(mode):
    payload = free_path()
    segments = payload['plan']['steps'][0]['segments']
    if mode == 'opposite':
        segments[1]['control_points'][1] = deepcopy(segments[0]['control_points'][-2])
    elif mode == 'degenerate':
        segments[1]['control_points'][1] = deepcopy(segments[1]['control_points'][0])
    elif mode == 'mixed_degree':
        del segments[1]['control_points'][2]
    else:
        payload['plan']['constraints'] = [{'kind': 'some_constraint'}]
    corrected, changes = normalize_composite_path_connections_once(payload, '生成一条平滑曲线')
    assert corrected == payload and not changes


def test_model_assertion_failure_exposes_independent_array_overlap():
    row = ROWS['C17']
    result = interpret(row)
    error = result['construction_error']
    assert error['code'] == 'assertion_failed'
    details = error['details']
    source = details['independent_source_failure']
    assert source['diagnostic_only'] and not source['candidate_accepted']
    assert source['details']['check'] == '单元内部不得重叠'
    assert len(source['details']['measurements']['overlap_pairs']) == 3
    vectors = source['details']['measurements']['validated_cell_neighbor_displacements_mm']
    assert len(vectors) == 6
    assert all(math.hypot(*v) == pytest.approx(math.sqrt(3)*500) for v in vectors)
    assert len(details['affected_output_refs']) == 4
    assert 'trial_result' not in result


def test_deleting_model_assertions_cannot_hide_overlap():
    row = ROWS['C17']
    plan = deepcopy(row['plan'])
    plan['assertions'] = []
    result = interpret(row, plan=plan)
    assert result.get('acceptance_summary', {}).get('status') != 'passed'
    assert result['construction_error']['code'] == 'structure_requirement_failed'


@pytest.mark.parametrize('refs', [[], ['unknown:99']])
def test_missing_or_unknown_junction_sources_return_repairable_errors(refs):
    row = ROWS['A9']
    plan = deepcopy(row['plan'])
    for joint in plan['steps'][0]['junction_constraints']:
        joint['source_requirement_refs'] = refs
    result = interpret(row, plan=plan)
    assert result['status'] == 'invalid'
    error = result['construction_error']
    assert error['code'] == 'invalid_junction_source_refs'
    assert 'user:0' in error['details']['allowed_source_index']['entries']
    assert error['details']['affected_output_refs'] == ['heart.outline']
    assert 'trial_result' not in result


def test_recorded_gear_bad_junction_ref_cannot_escape_as_provider_failure():
    row = ROWS['C14']
    result = interpret(row)
    assert result['status'] == 'invalid'
    assert result['construction_error']['code'] == 'invalid_junction_source_refs'
    plan = deepcopy(row['plan'])
    # This gear source has no smooth/corner authorization. Remove the model's
    # unsupported optional metadata, preserving the entire submitted geometry.
    for step in plan['steps']:
        step['junction_constraints'] = []
    fixed = interpret(row, plan=plan)
    assert fixed.get('acceptance_summary', {}).get('status') == 'passed', fixed.get('construction_error')


@pytest.mark.parametrize('text,intent', [('生成平滑闭合曲线', 'smooth'),
    ('连接处保留尖点', 'intentional_cusp'), ('在连接处保留直角', 'intentional_corner')])
def test_intent_guidance_reuses_source_validation(text, intent):
    from app.cad_requirement_contract import build_requirement_source_index, requirement_contract, junction_intent_guidance
    index = build_requirement_source_index(requirement_contract([{'source_id': 'user:0', 'text': text}]))
    original = deepcopy(index)
    allowed = junction_intent_guidance(index)['allowed_source_refs_by_intent']
    assert index == original
    assert allowed[intent] == ['user:0']
    assert all(not refs for name, refs in allowed.items() if name != intent)


def test_generation_receives_source_intent_permissions_without_changing_plan():
    row = ROWS['A9']; prompts = []
    def model(text, schema):
        prompts.append(text)
        branches = schema['$defs']['JunctionConstraint']['oneOf']
        assert [b['properties']['intent']['enum'] for b in branches] == [['smooth']]
        return {'schema_version': 'cad.construction-interpretation.v1', 'is_construction_request': True,
            'plan': deepcopy(row['plan']), 'confidence': .99, 'evidence_text': [row['original']]}
    result = interpret_construction_request(row['source'], model, force_structured_model=True)
    assert result['acceptance_summary']['status'] == 'passed'
    assert '"intentional_cusp": []' in prompts[0]
    assert '用户明确的连接要求优先' in prompts[0]


@pytest.mark.parametrize('source,intent,continuity', [('生成平滑曲线', 'smooth', ['G1', 'C1']),
    ('连接处保留尖点', 'intentional_cusp', ['C0']), ('连接处保留直角', 'intentional_corner', ['C0'])])
def test_schema_allows_only_source_bound_intent_and_continuity(source, intent, continuity):
    from app.cad_construction_interpreter import _request_construction_schema
    branches = _request_construction_schema(source)['$defs']['JunctionConstraint']['oneOf']
    assert len(branches) == 1
    props = branches[0]['properties']
    assert props['intent']['enum'] == [intent]
    assert props['required_continuity']['enum'] == continuity
    assert props['source_requirement_refs']['items']['enum'] == ['user:0']
    assert props['source_requirement_refs']['minItems'] == 1
    assert 'source_requirement_refs' in branches[0]['required']


def test_feedback_cannot_authorize_cusp_in_schema_and_requests_are_isolated():
    from app.cad_construction_interpreter import _request_construction_schema
    before = _request_construction_schema('生成平滑曲线')
    retry = _request_construction_schema('生成平滑曲线\n后端试算反馈：保留尖点')
    assert retry == before
    _request_construction_schema('连接处保留尖点')
    assert _request_construction_schema('生成平滑曲线') == before


def test_no_authorized_intent_does_not_invent_a_source():
    from app.cad_construction_interpreter import _request_construction_schema
    schema = _request_construction_schema('画一个半径2米的圆')
    assert schema['$defs']['JunctionConstraint'] == {'not': {}}


def test_cusp_and_smooth_permissions_remain_bound_to_their_own_sources():
    from app.cad_construction_interpreter import _request_construction_schema
    from app.cad_requirement_contract import build_requirement_source_index, requirement_contract
    index = build_requirement_source_index(requirement_contract([
        {'source_id':'a', 'text':'第一处平滑'}, {'source_id':'b', 'text':'第二处保留尖点'}]))
    schema = _request_construction_schema('曲线', source_index=index)
    branches = schema['$defs']['JunctionConstraint']['oneOf']
    assert {b['properties']['intent']['enum'][0]: b['properties']['source_requirement_refs']['items']['enum']
        for b in branches} == {'smooth':['a'], 'intentional_cusp':['b']}


def test_repeated_center_followup_does_not_disable_existing_curve_repair():
    payload = free_path()
    once, first = normalize_composite_path_connections_once(payload, '生成平滑曲线，中心在(13,-7)')
    repeated, second = normalize_composite_path_connections_once(payload,
        '生成平滑曲线，中心在(13,-7)\n中心(13.0,-7.0)，坐标单位米。')
    assert first and second
    assert repeated == once
    assert execute_construction_plan(repeated['plan'])['geometries']


@pytest.mark.parametrize('suffix', ['中心(14,-7)', '(13,-7)', '端点(13,-7)', '控制点(13,-7)'])
def test_other_fixed_coordinate_requirements_still_disable_handle_changes(suffix):
    payload = free_path()
    corrected, changes = normalize_composite_path_connections_once(payload,
        '生成平滑曲线，中心在(13,-7)，'+suffix)
    assert corrected == payload
    assert not changes


def test_repeated_center_can_reach_formal_acceptance_through_interpreter():
    row = ROWS['A9']
    result = interpret(row, source=row['source']+'\n中心(2.0,3.0)，宽4米、高4米，坐标单位米。')
    assert result['acceptance_summary']['status'] == 'passed', result.get('construction_error')
    assert any(r['kind']=='align_free_cubic_joint' for r in result['deterministic_repairs'])
