from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.cad_construction import execute_construction_plan
from app.cad_coordinate_requirements import verify_control_point_curve
from app.cad_structure_contract import StructureContractError

FIXTURES = json.loads((Path(__file__).parent/'fixtures/recorded_control_point_curves.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('fixture', FIXTURES, ids=lambda f:f['case'])
def test_recorded_native_curve_controls_have_independent_source_proof(fixture):
    gs = execute_construction_plan(fixture['plan'])['geometries']
    report = verify_control_point_curve(fixture['source'], gs)
    assert report['coverage']=='complete'
    assert all(c['status']=='passed' for c in report['checks'])


@pytest.mark.parametrize('mutation', ['control','order','degree','extra','closed','periodic','z'])
def test_cannot_pass_wrong_geometry_with_model_claims(mutation):
    f = FIXTURES[0]
    gs = execute_construction_plan(f['plan'])['geometries']
    if mutation=='control': gs[0]['control_points'][1]['y'] += 10
    elif mutation=='order': gs[0]['control_points'].reverse()
    elif mutation=='degree': gs[0]['degree'] = 2
    elif mutation=='extra': gs.append({**deepcopy(gs[0]),'id':2})
    elif mutation=='closed': gs[0]['closed'] = True
    elif mutation=='periodic': gs[0]['periodic'] = True
    else: gs[0]['control_points'][0]['z'] = 10
    with pytest.raises(StructureContractError):
        verify_control_point_curve(f['source'], gs)


@pytest.mark.parametrize('extra', ['，再画一个圆', '，向右偏移1米', '，曲率不超过2', '，顺时针旋转30度'])
def test_unknown_curve_requirements_keep_partial_coverage(extra):
    f = FIXTURES[0]
    gs = execute_construction_plan(f['plan'])['geometries']
    assert verify_control_point_curve(f['source']+extra, gs)['coverage']=='partial'


def test_periodic_spline_does_not_silently_override_user_degree():
    f = FIXTURES[1]
    gs = execute_construction_plan(f['plan'])['geometries']
    with pytest.raises(StructureContractError):
        verify_control_point_curve(f['source']+'，指定三次样条', gs)
    gs[0]['periodic'] = False
    with pytest.raises(StructureContractError):
        verify_control_point_curve(f['source'], gs)


def test_custom_knots_and_preview_overrides_do_not_gain_false_proof():
    f = FIXTURES[0]
    for key,value in [('knots',[0,0,0,0,1,1,1,1]),('weights',[1,1,2,1]),
                      ('vertices',[{'x':0,'y':0},{'x':1,'y':1}])]:
        gs = execute_construction_plan(f['plan'])['geometries']
        gs[0][key] = value
        assert verify_control_point_curve(f['source'],gs)['coverage']=='partial'


@pytest.mark.parametrize('fixture', FIXTURES, ids=lambda f:f['case'])
def test_complete_interpreter_and_commit_preserve_curve_proof(tmp_path, fixture):
    from app.cad_construction_interpreter import interpret_construction_request
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    def callback(*_):
        return {'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
                'confidence':.98,'evidence_text':[fixture['source']],'plan':fixture['plan']}
    result=interpret_construction_request(fixture['source'],callback,force_structured_model=True)
    assert result['status']=='ready',result.get('error')
    assert result['acceptance_summary']['status']=='passed'
    store=CreativeProjectStore(tmp_path/'projects.json')
    committed=commit_construction_interpretation(fixture['source'],result,store=store)
    variant=store.get(committed['project_id'])['variants'][0]
    assert variant['geometries'][0]['type']=='spline'
    assert variant['construction_record']['source_acceptance']['control_point_acceptance']['coverage']=='complete'


def test_no_coordinate_units_still_clarifies_before_model():
    from app.cad_construction_interpreter import interpret_construction_request
    source=FIXTURES[0]['source'].splitlines()[0]
    model=Mock(side_effect=AssertionError('missing units reached model'))
    result=interpret_construction_request(source,model)
    assert result['error']['code']=='missing_coordinate_units'
    model.assert_not_called()


@pytest.mark.parametrize('unit,ratio', [('毫米', .001), ('厘米', .01)])
def test_coordinate_unit_changes_are_measured_without_moving_source_points(unit, ratio):
    f = FIXTURES[0]
    source = f['source'].replace('坐标单位为米', '坐标单位为'+unit)
    gs = execute_construction_plan(f['plan'])['geometries']
    with pytest.raises(StructureContractError):
        verify_control_point_curve(source, gs)
    for point in gs[0]['control_points']:
        point['x'] *= ratio
        point['y'] *= ratio
    assert verify_control_point_curve(source, gs)['coverage']=='complete'


def test_source_proof_does_not_disable_existing_self_intersection_gate():
    from app.cad_construction_interpreter import interpret_construction_request
    f = FIXTURES[1]
    plan = deepcopy(f['plan'])
    plan['steps'][0]['degree'] = 3
    def callback(*_):
        return {'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
                'confidence':.98,'evidence_text':[f['source']],'plan':plan}
    result = interpret_construction_request(f['source'],callback,force_structured_model=True)
    assert result['status']=='invalid'
    assert result['construction_error']['code']=='drawing_infeasible'
