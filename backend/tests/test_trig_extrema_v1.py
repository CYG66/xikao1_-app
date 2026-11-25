import math
import pytest
from evaluations.trig_extrema_v1 import extrema


def test_recorded_harmonic_curve_has_a_shallow_but_real_top_notch():
    result=extrema('3 - 2*cos(t) - 0.6*cos(2*t) + 1.1',0,math.tau)
    assert result['status']=='analytic_candidates_evaluated'
    assert result['minimum']==pytest.approx(1.5)
    assert result['maximum']==pytest.approx(4.1+5/3-7/30)
    assert result['maximum']-5.5==pytest.approx(1/30)


@pytest.mark.parametrize('start',[-2*math.pi,0,.123])
def test_sine_extrema_do_not_depend_on_sampling_phase(start):
    result=extrema('2+2*sin(t)',start,start+math.tau)
    assert result['minimum']==pytest.approx(0)
    assert result['maximum']==pytest.approx(4)


@pytest.mark.parametrize('source',['sin(t)+cos(t)','sin(2*t)','cos(t+.1)','sin(t)**3','t*sin(t)','cos(3*t)'])
def test_unsupported_forms_are_not_guessed_by_sampling(source):
    assert extrema(source,0,math.tau)['status']=='unverified'


def test_constant_axis_endpoint_interval_and_no_stationary_point_in_short_interval():
    assert extrema('3',0,1)['status']=='constant_axis'
    result=extrema('sin(t)',.1,.2)
    assert result['minimum']==pytest.approx(math.sin(.1))
    assert result['maximum']==pytest.approx(math.sin(.2))


def test_constants_and_units_scale_without_changing_extremum_parameters():
    a=extrema('2-2*cos(t)-.6*cos(2*t)',0,math.tau)
    b=extrema('1000*(2-2*cos(t)-.6*cos(2*t))+123',0,math.tau)
    assert b['minimum']==pytest.approx(1000*a['minimum']+123)
    assert b['maximum']==pytest.approx(1000*a['maximum']+123)


def test_second_harmonic_internal_stationary_points_and_no_extra_real_roots():
    result=extrema('cos(t)+cos(2*t)',0,math.tau)
    assert result['minimum']==pytest.approx(-1.125)
    assert result['maximum']==pytest.approx(2)
    result=extrema('-cos(t)-.1*cos(2*t)',0,math.tau)
    assert result['minimum']==pytest.approx(-1.1)
    assert result['maximum']==pytest.approx(.9)


def test_unsafe_ast_and_unbounded_work_are_not_evaluated():
    assert extrema('__import__("os")',0,math.tau)['status']=='unverified'
    assert extrema('cos(t)',0,100000)['status']=='unverified'
