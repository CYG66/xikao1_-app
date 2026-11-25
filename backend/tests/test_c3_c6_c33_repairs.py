from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from app.cad_construction_interpreter import interpret_construction_request
ROWS={r['case']:r for r in json.loads((Path(__file__).parent/'fixtures/recorded_c3_c6_failures.json').read_text(encoding='utf-8'))}


@pytest.mark.parametrize('case',['C3','C6'])
def test_recorded_failure_reaches_complete_acceptance(case):
    row=ROWS[case]
    result=interpret_construction_request(row['source'],lambda *_:deepcopy(row['payload']),force_structured_model=True)
    assert result.get('acceptance_summary',{}).get('status')=='passed',result.get('construction_error') or result.get('source_acceptance')


@pytest.mark.parametrize('change',['missing','extra','lower_arc','gap','bad_radius'])
def test_native_arch_rejects_incomplete_or_wrong_boundaries(change):
    from app.cad_construction import execute_construction_plan
    from app.cad_curve_fit_acceptance import verify_native_semicircular_arch
    gs=execute_construction_plan(ROWS['C3']['payload']['plan'])['geometries']
    assert verify_native_semicircular_arch(gs)['passed']
    if change=='missing':gs.pop()
    elif change=='extra':gs.append(deepcopy(gs[0]))
    elif change=='lower_arc':
        arc=next(g for g in gs if g['type']=='arc');arc.update(start_angle=180,end_angle=360)
    elif change=='gap':next(g for g in gs if g['type']=='line')['start']['x']+=10
    else:next(g for g in gs if g['type']=='arc')['radius']+=10
    assert not verify_native_semicircular_arch(gs)['passed']


def test_c33_clarification_reaches_formal_handler_without_key_error():
    from app.agent_service import RobotAgentService
    source='圆柱体轮廓，底面半径1米，高3米，俯视顶圆可见'
    interpretation=interpret_construction_request(source)
    assert interpretation['error']['code']=='missing_projection_convention'
    service=RobotAgentService(restore_pending_actions=False)
    with patch.object(service,'_interpret_cad_construction_plan',return_value=interpretation),patch.object(service,'_is_generic_cad_construction_request',return_value=True):
        result=service._formal_cad_construction(source,{'name':'drawing_design','operation':'create','user_message':source},mode='advanced')
    assert result['ok'] is False
    assert result['suggested_prompt']


def test_geometric_sampler_is_not_penalized_for_nonuniform_speed_on_a_line():
    from app.cad_parametric import sample_curve
    points,error=sample_curve('t**3','0',0,1,1e-8)
    assert error==0 and len(points)==65


def test_recorded_flower_stays_inside_original_budget_and_geometric_tolerance():
    import math
    from shapely.geometry import LineString,Point
    from app.cad_parametric import sample_curve,expression
    step=ROWS['C6']['payload']['plan']['steps'][0]
    points,error=sample_curve(step['x_expression'],step['y_expression'],0,math.tau,step['max_sampling_error'])
    assert len(points)<=500 and error<=step['max_sampling_error']
    boundary=LineString(points);x=expression(step['x_expression']);y=expression(step['y_expression'])
    assert max(boundary.distance(Point(x(t),y(t))) for t in [math.tau*i/4000 for i in range(4001)])<=step['max_sampling_error']+1e-9
