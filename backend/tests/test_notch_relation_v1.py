import pytest
from evaluations.notch_relation_v1 import upper_notch_relation


@pytest.mark.parametrize('depth', [10, 1000])
@pytest.mark.parametrize('dx,dy', [(0,0),(12345,-400)])
def test_shallow_and_deep_notches_have_same_relation_without_a_depth_ratio(depth,dx,dy):
    points=[(0,0),(-2000,2000),(-1000,4000),(0,4000-depth),(1000,4000),(2000,2000)]
    result=upper_notch_relation([(x+dx,y+dy) for x,y in points])
    assert result['relation_passed']
    assert result['measurements']['notch_depth_mm']==pytest.approx(depth)
    assert not result['formal_candidate_accepted']


@pytest.mark.parametrize('points', [
    [(0,0),(-2,2),(0,4),(2,2)],
    [(0,0),(-2,2),(-1,4),(0,3),(1,2),(2,1)],
    [(-2,0),(-2,4),(2,4),(2,0)],
    [(0,0),(2,2),(0,2),(2,0)],
    [(0,0),(1,0),(2,0)],
])
def test_peak_one_sided_outline_flat_top_self_intersection_and_degenerate_are_rejected(points):
    assert not upper_notch_relation([(x*1000,y*1000) for x,y in points])['relation_passed']


def test_u_shape_relation_is_not_misreported_as_full_heart_acceptance():
    result=upper_notch_relation([(-2,0),(-2,4),(-1,4),(-1,1),(1,1),(1,4),(2,4),(2,0)])
    assert result['relation_passed']
    assert result['scope']=='upper_notch_relation_only'
    assert not result['formal_candidate_accepted']
