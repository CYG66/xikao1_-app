from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.cad_construction import execute_construction_plan
from evaluations.trig_layout_minimum_v1 import measure
from evaluations.heart_acceptance_candidate_v3 import compare as v3
from evaluations.heart_acceptance_candidate_v4 import compare as v4
ROWS={r['response_index']:r for r in json.loads((Path(__file__).parent/'fixtures/recorded_shallow_notch_audit.json').read_text(encoding='utf-8'))}


def test_recorded_formula_layout_is_verified_without_replacing_geometry():
    plan=ROWS[3]['payload']['plan'];before=deepcopy(plan)
    result=measure(plan)
    assert plan==before
    assert result['status']=='mapped_analytic_candidates'
    assert result['minimum_kind']=='isolated_point'
    assert result['minimum_points_mm'][0]==pytest.approx([2000,1000])
    assert result['layout_map_mm']['residual_mm']<1e-6
    assert result['sampling_evidence']['guaranteed_global_error_bound'] is False


def test_v3_remains_uncertain_while_v4_has_source_evidence():
    row=ROWS[3];old=v3(row['source'],row['payload']);new=v4(row['source'],row['payload'])
    assert old['decision']=='undetermined'
    assert new['decision']=='passed' and new['geometry_unchanged']
    assert not new['legacy_passed'] and not new['formal_candidate_accepted']


@pytest.mark.parametrize('index',[5,7])
def test_bezier_and_existing_rejections_keep_their_v3_decisions(index):
    row=ROWS[index]
    assert v4(row['source'],row['payload'])['decision']==v3(row['source'],row['payload'])['decision']


def test_unsupported_expression_remains_unverified():
    plan=deepcopy(ROWS[3]['payload']['plan'])
    plan['steps'][0]['x_expression']='2+sin(t)+cos(t)'
    assert measure(plan)['status']=='unverified'


def test_changed_sampling_is_not_accepted_as_a_verified_pointwise_mapping():
    plan=deepcopy(ROWS[3]['payload']['plan'])
    plan['free_outline_layout'][0].update(width=40,height=40)
    result=measure(plan)
    assert result['status']=='unverified'


def test_millimetre_expression_uses_same_final_coordinate_frame():
    plan=deepcopy(ROWS[3]['payload']['plan']);plan['units']='mm'
    step=plan['steps'][0]
    for axis in ('x','y'):step[f'{axis}_expression']=f"1000*({step[f'{axis}_expression']})"
    step['max_sampling_error']=.5
    layout=plan['free_outline_layout'][0]
    layout.update(width=4000,height=4000,center={'x':2000,'y':3000})
    for assertion in plan['assertions']:
        if assertion['kind']=='bounds_size':assertion.update(width=4000,height=4000,tolerance=10)
    result=measure(plan)
    assert result['status']=='mapped_analytic_candidates'
    assert result['minimum_points_mm'][0]==pytest.approx([2000,1000])
