from copy import deepcopy
import pytest

from app.cad_source_acceptance import verify_single_round_primitive
from app.cad_structure_contract import StructureContractError


def circle():
    return {'id': 1, 'type': 'circle', 'center': {'x': 0, 'y': 0}, 'radius': 2000}


@pytest.mark.parametrize('source', ['生成一个半径2米的圆形',
    '画一个圆，半径200厘米', '画一个圆，直径4米',
    '生成一个半径2米的圆形\n半径2米，圆心(0,0)，坐标单位米。'])
def test_full_source_is_measured_independently(source):
    report = verify_single_round_primitive(source, [circle()])
    assert report['coverage'] == 'complete'
    assert report['checks'] and all(c['status']=='passed' for c in report['checks'])


@pytest.mark.parametrize('extra', ['，放在矩形上方', '，再画一个矩形',
    '，不要圆心在原点', '，半径不超过3米', '，顺时针', '，标注直径',
    '，闭合样条', '，并且面积等于10平方米'])
def test_unconsumed_requirement_never_claims_complete_coverage(extra):
    assert verify_single_round_primitive('生成一个半径2米的圆形'+extra,
                                          [circle()])['coverage'] == 'partial'


@pytest.mark.parametrize('mutation', ['radius', 'center', 'count', 'type'])
def test_incorrect_geometry_is_rejected_without_reading_model_assertions(mutation):
    gs = [circle()]
    if mutation == 'radius': gs[0]['radius'] = 1900
    elif mutation == 'center': gs[0]['center']['x'] = 5
    elif mutation == 'count': gs.append({**deepcopy(gs[0]), 'id': 2})
    else: gs[0]['type'] = 'polyline'
    with pytest.raises(StructureContractError):
        verify_single_round_primitive('画一个圆，圆心(0,0)，半径2米，坐标单位米', gs)


def test_arc_angle_and_directional_sweep_are_independently_measured():
    source = '生成一个圆弧，圆心在(0,0)，半径3米，从0度到90度'
    g = {'id': 1, 'type': 'arc', 'center': {'x': 0, 'y': 0}, 'radius': 3000,
         'start_angle': 0, 'end_angle': 90}
    assert verify_single_round_primitive(source, [g])['coverage'] == 'complete'
    followup='\n圆心(0,0)，半径3米，起始角0度、终止角90度，坐标单位米。'
    assert verify_single_round_primitive(source+followup,[g])['coverage']=='complete'
    g['end_angle'] = 450
    with pytest.raises(StructureContractError):
        verify_single_round_primitive(source, [g])


def test_source_conflict_is_not_silently_resolved_within_one_turn():
    assert verify_single_round_primitive('画一个圆，半径2米，半径3米',
                                         [circle()])['coverage'] == 'partial'


def test_whole_interpreter_can_deliver_recorded_circle_shape_with_proven_source(tmp_path):
    from app.cad_construction_interpreter import interpret_construction_request
    source = '生成一个半径2米的圆形'
    def callback(*_):
        return {'schema_version':'cad.construction-interpretation.v1',
                'is_construction_request':True,'confidence':.99,'evidence_text':[source],
                'plan':{'units':'m','steps':[{'op':'add_circle','step_id':'s1',
                    'output_ref':'round','semantic':{'label':'圆'},
                    'center':{'x':0,'y':0},'radius':2}]}}
    result = interpret_construction_request(source, callback, force_structured_model=True)
    assert result['status'] == 'ready', result.get('error')
    assert result['acceptance_summary']['status'] == 'passed'
    assert result['trial_result']['geometries'][0]['type'] == 'circle'
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    store = CreativeProjectStore(tmp_path / 'projects.json')
    committed = commit_construction_interpretation(source, result, store=store)
    project = store.get(committed['project_id'])
    variant = project['variants'][0]
    assert variant['geometries'][0]['type'] == 'circle'
    assert variant['acceptance_summary']['status'] == 'passed'
    proof = variant['construction_record']['source_acceptance']['single_primitive_acceptance']
    assert proof['checks'] and proof['coverage'] == 'complete'


def test_source_measurement_uses_current_executor_geometry_refs():
    from app.cad_source_acceptance import verify_final_source_contract
    source = '孔：圆，圆心(0,0)，半径2米，坐标单位米'
    objects = [{'object_id':'hole', 'label':'孔', 'geometry_refs':[1]}]
    report = verify_final_source_contract(source, [circle()], objects)
    assert report['checks'] and not report['unknown_requirements']
    wrong = circle(); wrong['radius'] = 1900
    with pytest.raises(StructureContractError):
        verify_final_source_contract(source, [wrong], objects)


def test_arc_radius_measurement_is_not_left_unknown_after_specific_check_passes():
    from app.cad_construction_interpreter import interpret_construction_request
    source = '生成一个圆弧，圆心在(0,0)，半径3米，从0度到90度'
    def callback(*_):
        return {'schema_version':'cad.construction-interpretation.v1',
            'is_construction_request':True,'confidence':.99,'evidence_text':[source],
            'plan':{'units':'m','steps':[{'op':'add_arc','step_id':'s1',
                'output_ref':'arc','semantic':{'label':'圆弧'},'center':{'x':0,'y':0},
                'radius':3,'start_angle':0,'end_angle':90}]}}
    result = interpret_construction_request(source, callback, force_structured_model=True)
    assert result['status']=='ready', result.get('error')
    assert result['acceptance_summary']['status']=='passed'
    assert not result['source_acceptance']['final_source_acceptance']['unknown_requirements']
