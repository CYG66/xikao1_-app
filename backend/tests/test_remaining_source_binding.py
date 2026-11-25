from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.cad_construction_interpreter import interpret_construction_request

ROWS={r['case']:r for r in json.loads((Path(__file__).parent/'fixtures/recorded_source_binding_remaining.json').read_text(encoding='utf-8'))}


def interpret(row,source=None):
    return interpret_construction_request(source or row['source'],lambda *_:{
        'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
        'confidence':.99,'evidence_text':[row['original']],'plan':deepcopy(row['plan'])},force_structured_model=True)


@pytest.mark.parametrize('case',['C14','C16','C20','C21','C25','C28','C34'])
def test_existing_recorded_geometry_obtains_full_source_proof_and_persists(case,tmp_path):
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    row=ROWS[case];result=interpret(row)
    assert result['status']=='ready',result.get('error')
    assert result['acceptance_summary']['status']=='passed',result['source_acceptance']
    store=CreativeProjectStore(tmp_path/'projects.json')
    saved=commit_construction_interpretation(row['source'],result,store=store)
    assert store.get(saved['project_id'])['variants'][-1]['acceptance_summary']['status']=='passed'


@pytest.mark.parametrize('case',['C14','C16','C20','C21','C25','C28','C34'])
@pytest.mark.parametrize('extra',['，面积为123平方米','，再画一个圆','，整体旋转20度'])
def test_unmeasured_clauses_never_gain_complete_source_coverage(case,extra):
    result=interpret(ROWS[case],ROWS[case]['source']+extra)
    assert result.get('acceptance_summary',{}).get('status')!='passed'


def test_historical_symmetric_heart_is_actually_not_smooth():
    from app.cad_construction import AddCompositePathStep, _composite_continuity
    original = _composite_continuity(AddCompositePathStep.model_validate(ROWS['A9']['plan']['steps'][0]))
    assert original['maximum_tangent_delta_deg'] > 90
    result=interpret(ROWS['A9'])
    assert result['status']=='invalid'
    details=result['construction_error']['details']
    assert any(r['kind']=='align_free_cubic_joint' for r in result['deterministic_repairs'])
    assert details['check']=='heart_bilateral_lobes_notch_and_lower_tip'
    from app.cad_construction import execute_construction_plan
    from app.cad_structure_contract import _points
    boundary = _points(execute_construction_plan(result['plan'])['geometries'][0])
    bounds = details['measured_bounds_mm']
    diagnostics = details['sampled_feature_diagnostics']
    assert set(diagnostics) == set(details['measured_features'])
    for name, witness in diagnostics.items():
        x,y = witness['nearest_sample_mm']
        assert (x,y) in boundary
        assert witness['passed'] == details['measured_features'][name]
        assert witness['nearest_sample_normalized'] == pytest.approx([
            (x-bounds['min_x'])/(bounds['max_x']-bounds['min_x']),
            (y-bounds['min_y'])/(bounds['max_y']-bounds['min_y'])])
    assert result.get('acceptance_summary',{}).get('status')!='passed'


def test_cylinder_projection_requires_user_convention_before_model_call():
    def model(*_):raise AssertionError('Ambiguous projection must be clarified before planning')
    result=interpret_construction_request(ROWS['C33']['source'],model,force_structured_model=True)
    assert result['status']=='clarification_required'
    assert result['error']['code']=='missing_projection_convention'


def test_smooth_heart_uses_existing_bezier_tool_with_non_degenerate_junctions():
    row=deepcopy(ROWS['A9']);segments=row['plan']['steps'][0]['segments']
    low=segments[0]['control_points'][0]['y'];notch=low+.7*(segments[1]['control_points'][-1]['y']-low)
    segments[1]['control_points'][-1]['y']=notch
    segments[2]['control_points'][0]['y']=notch
    segments[0]['control_points'][1]['y']=low
    segments[-1]['control_points'][-2]['y']=low
    segments[1]['control_points'][-2]['y']=notch
    segments[2]['control_points'][1]['y']=notch
    result=interpret(row)
    assert result['status']=='ready',result.get('construction_error')
    assert result['acceptance_summary']['status']=='passed',result['source_acceptance']


PLANS={r['case']:r for r in json.loads((Path(__file__).parent/'fixtures/recorded_planning_failures.json').read_text(encoding='utf-8'))}


def test_spiral_source_proof_replaces_only_unrequested_wrong_bounds():
    row=PLANS['C12'];result=interpret(row)
    assert result['status']=='ready',result.get('construction_error')
    assert result['acceptance_summary']['status']=='passed'
    assert any(r['kind']=='source_polar_acceptance_replaces_unrequested_bounds' and r['geometry_unchanged'] for r in result['deterministic_repairs'])


def test_wrong_hexagon_stays_rejected_with_local_measurements_and_ids():
    result=interpret(PLANS['C17'])
    assert result['status']=='invalid'
    details=result['construction_error']['details']
    assert details['geometry_ids'] and details['affected_output_refs']
    assert details['measurements']['expected_side_length_mm']==500
    assert len(details['measurements']['actual_side_lengths_mm'])==6


def test_concentric_constraint_cannot_move_circle_to_open_path_box_center():
    row=PLANS['C31'];result=interpret(row)
    assert result['status']=='invalid'
    assert result['construction_error']['code']=='constraint_geometry_type_unsupported'
    assert 'inapplicable_constraint' in result['construction_error']['details']


def cylinder_views():
    row=deepcopy(ROWS['C33'])
    row['source']+='\n采用俯视圆与侧视轮廓两个独立正投影视图。'
    row['plan']['steps'][1]['center']['x']=4
    return row


def test_user_chosen_cylinder_views_bind_height_to_side_view_and_allow_separate_positions():
    row=cylinder_views()
    # Moving the top view vertically must not change the cylinder's height.
    row['plan']['steps'][0]['center']['y']=6
    result=interpret(row)
    assert result['status']=='ready',result.get('construction_error') or result.get('error')
    assert result['acceptance_summary']['status']=='passed',result['source_acceptance']
    final=result['source_acceptance']['final_source_acceptance']
    assert any(c['field']=='height' and c['geometry_ids']==[2] and c['actual_mm']==3000 for c in final['checks'])


@pytest.mark.parametrize('damage',['overlap','side_width','height','extra','unknown'])
def test_cylinder_views_require_correspondence_and_exact_inventory(damage):
    row=cylinder_views()
    if damage=='overlap':row['plan']['steps'][1]['center']['x']=0
    elif damage=='side_width':row['plan']['steps'][1]['width']=3
    elif damage=='height':row['plan']['steps'][1]['height']=4
    elif damage=='extra':
        step=deepcopy(row['plan']['steps'][0]);step.update(step_id='extra',output_ref='extra',semantic={'label':'额外圆'})
        row['plan']['steps'].append(step)
    else:row['source']+='，面积123平方米'
    result=interpret(row)
    assert result.get('acceptance_summary',{}).get('status')!='passed'


def test_sampled_s_path_reuses_generic_measurements_for_complete_source_proof():
    from app.cad_construction import execute_construction_plan
    from app.cad_path_relation_acceptance import verify_path_relations,verify_path_source_coverage
    from app.drawing_store import _geometry_points
    row=json.loads((Path(__file__).parent/'fixtures/recorded_symmetric_divider.json').read_text(encoding='utf-8'))
    source='\n'.join([row['original'],*row['followups']])
    gs=execute_construction_plan(row['plan'])['geometries']
    sampled=[g if g['type']!='arc' else {'id':g['id'],'type':'polyline','closed':False,
             'vertices':[{'x':p[0]*1000,'y':p[1]*1000} for p in _geometry_points(g)]} for g in gs]
    measured=verify_path_relations(source,sampled)
    assert verify_path_source_coverage(source,measured,sampled)['coverage']=='complete'
    assert verify_path_source_coverage(source+'，面积为5平方米',measured,sampled)['coverage']=='partial'


def test_recorded_valid_tiling_reuses_local_side_and_grid_proofs_and_persists(tmp_path):
    from app.cad_construction import execute_construction_plan
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    row=json.loads((Path(__file__).parent/'fixtures/recorded_valid_tiling.json').read_text(encoding='utf-8'))
    before=execute_construction_plan(row['plan'])['geometries']
    result=interpret(row)
    assert result['status']=='ready',result.get('construction_error')
    assert result['trial_result']['geometries']==before
    assert result['acceptance_summary']['status']=='passed',result['source_acceptance']
    store=CreativeProjectStore(tmp_path/'projects.json')
    saved=commit_construction_interpretation(row['source'],result,store=store)
    assert store.get(saved['project_id'])['variants'][-1]['acceptance_summary']['status']=='passed'
    assert interpret(row,row['source']+'，面积为123平方米').get('acceptance_summary',{}).get('status')!='passed'


def test_connected_six_cells_do_not_prove_three_columns_and_two_rows():
    import math
    from app.cad_repetition_acceptance import verify_repetition_requirements
    from app.cad_structure_contract import StructureContractError
    gs=[{'id':j+1,'type':'polyline','closed':True,'vertices':[
        {'x':j*750+500*math.cos(i*math.pi/3),'y':j*math.sqrt(3)*250+500*math.sin(i*math.pi/3)} for i in range(6)]} for j in range(6)]
    with pytest.raises(StructureContractError,match='来源行列数'):
        verify_repetition_requirements('生成3列2行蜂窝六边形阵列，边长0.5米，无缝拼接',gs)
