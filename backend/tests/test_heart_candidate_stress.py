from copy import deepcopy
import json
from pathlib import Path
import pytest
from shapely.geometry import Polygon
from shapely.affinity import scale
from evaluations.stress_heart_candidate_v1 import scenarios
from evaluations.heart_acceptance_candidate_v1 import compare

ROW=json.loads((Path(__file__).parent/'fixtures/recorded_shallow_notch_audit.json').read_text(encoding='utf-8'))[0]


@pytest.mark.parametrize('name',['rounded_u_160','rounded_u_400'])
def test_records_known_false_positive_that_blocks_candidate_promotion(name):
    payload=dict(scenarios(ROW))[name]
    pts=[(p['x'],p['y']) for p in payload['plan']['steps'][0]['vertices']]
    polygon=Polygon(pts)
    assert polygon.is_valid
    assert polygon.boundary.hausdorff_distance(scale(polygon,xfact=-1,yfact=1,origin=(2,0)).boundary)<1e-8
    low=min(y for x,y in pts)
    bottom=[x for x,y in pts if abs(y-low)<1e-9]
    assert max(bottom)-min(bottom)>2  # Broad flat bottom, not a tapering heart tip.
    result=compare(ROW['source'],payload)
    assert not result['legacy_passed']
    assert result['candidate_passed']  # Deliberately records a v1 defect, not approval.
    assert not result['formal_candidate_accepted']


def test_orientation_and_asymmetry_fixtures_actually_change_the_parametric_plan():
    original=deepcopy(ROW)
    for name,payload in scenarios(ROW):
        if name in {'inverted','sideways','asymmetric'}:
            assert payload['plan']!=ROW['payload']['plan']
    assert ROW==original
