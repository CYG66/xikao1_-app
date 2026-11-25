from copy import deepcopy
import pytest
from app.cad_construction import execute_construction_plan
from evaluations.curve_evidence_inventory import curve_evidence


def circle_plan(unit):
    radius=1 if unit=='m' else 1000
    return {'units':unit,'steps':[{'step_id':'curve','output_ref':'curve','semantic':{'label':'曲线'},
        'op':'add_parametric_curve','x_expression':f'{radius}*cos(t)',
        'y_expression':f'{radius}*sin(t)','t_start':'0','t_end':'2*pi','closed':True,
        'max_sampling_error':.001 if unit=='m' else 1}]}


@pytest.mark.parametrize('unit',['m','mm'])
def test_original_formula_and_quality_remain_available_with_explicit_units(unit):
    trial=execute_construction_plan(circle_plan(unit));before=deepcopy(trial)
    result=curve_evidence(trial,'curve')
    assert trial==before
    assert result['source_step']['op']=='add_parametric_curve'
    assert result['representation']=='curve_with_discrete_delivery'
    assert result['reported_error_mm'] is not None
    assert result['reported_error_mm']<=1
    assert result['status']=='unverified'
    assert not result['guaranteed_global_error_bound']
    assert not result['extremum_verified']


def test_literal_flat_polyline_does_not_acquire_a_hidden_curve():
    plan={'units':'m','steps':[{'step_id':'flat','output_ref':'flat','semantic':{'label':'平底'},
        'op':'add_polyline','closed':True,'vertices':[{'x':0,'y':0},{'x':2,'y':0},{'x':2,'y':2},{'x':0,'y':2}]}]}
    result=curve_evidence(execute_construction_plan(plan),'flat')
    assert result['representation']=='declared_piecewise_linear'
    assert 'reported_error_mm' not in result


def test_missing_sampling_quality_never_implies_zero_error():
    trial=execute_construction_plan(circle_plan('m'));trial['curve_quality']=[]
    assert curve_evidence(trial,'curve')['reported_error_mm'] is None


def test_missing_binding_cannot_be_resolved_by_shape_similarity():
    trial=execute_construction_plan(circle_plan('m'));trial['symbol_table']={}
    assert curve_evidence(trial,'curve')['reason']=='missing_or_ambiguous_source_binding'
