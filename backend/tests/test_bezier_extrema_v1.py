from copy import deepcopy
import pytest
from evaluations.bezier_extrema_v1 import bezier_extrema


def points(ys):
    return [{'x':i/(len(ys)-1),'y':y} for i,y in enumerate(ys)]


def test_quadratic_minimum_between_sampling_points():
    original=points([2.09,1.79,2.49]);before=deepcopy(original)
    result=bezier_extrema(original)
    assert original==before
    assert result['axes']['y']['roots']==pytest.approx([.3])
    assert result['bounds']['min_y']==pytest.approx(2)
    assert result['bounds']['max_y']==pytest.approx(2.49)


def test_cubic_with_two_interior_stationary_points():
    result=bezier_extrema(points([2,2+.16/3,2+2*.16/3-.5/3,2+.16-.5+1/3]))
    assert result['axes']['y']['roots']==pytest.approx([.2,.8])
    assert result['bounds']['max_y']==pytest.approx(2+.16*.2-.5*.2**2+.2**3/3)
    assert result['bounds']['min_y']==pytest.approx(2+.16*.8-.5*.8**2+.8**3/3)


@pytest.mark.parametrize('ys',[[1,1,1],[1,1,1,1]])
def test_flat_axis_is_not_reported_as_an_isolated_tip(ys):
    result=bezier_extrema(points(ys))
    assert result['axes']['y']['status']=='constant_axis'
    assert result['bounds']['min_y']==result['bounds']['max_y']==1


def test_near_linear_cubic_and_endpoint_roots():
    assert bezier_extrema(points([0,1,2,3+1e-12]))['axes']['y']['roots']==[]
    assert bezier_extrema(points([0,0,1]))['bounds']['min_y']==0


@pytest.mark.parametrize('scale,offset',[(.001,0),(1,1000),(1000,-10000)])
def test_unit_scale_and_translation_follow_the_same_minimum(scale,offset):
    result=bezier_extrema([{'x':p['x']*scale+offset,'y':p['y']*scale+offset} for p in points([2.09,1.79,2.49])])
    assert result['bounds']['min_y']==pytest.approx(2*scale+offset)
    assert result['axes']['y']['roots']==pytest.approx([.3])


def test_degenerate_curve_and_unsupported_degree():
    result=bezier_extrema([{'x':3,'y':4}]*4)
    assert all(a['status']=='constant_axis' for a in result['axes'].values())
    with pytest.raises(ValueError):bezier_extrema(points([1,2]))


def test_repeated_derivative_root_is_not_mistaken_for_a_global_extremum():
    result=bezier_extrema(points([0,1,0,1]))
    assert result['axes']['y']['roots']==pytest.approx([.5])
    assert result['bounds']['min_y']==0 and result['bounds']['max_y']==1
