import pytest
from evaluations.audit_heart_notch import measure_notch_topology


@pytest.mark.parametrize('depth', [1000, 10, -100])
@pytest.mark.parametrize('offset', [0, 12345])
def test_vertical_intersection_distinguishes_shallow_notch_from_central_peak(depth,offset):
    points=[(0,0),(-2000,2000),(-1000,4000),(0,4000-depth),(1000,4000),(2000,2000)]
    translated=[(x+offset,y-offset) for x,y in points]
    result=measure_notch_topology(translated)
    assert result['notch_depth_below_both_peaks_mm']==pytest.approx(depth)
    assert result['center_below_both_side_peaks']==(depth>0)
    assert result['center_upper_boundary_mm']==pytest.approx([offset,4000-depth-offset])
