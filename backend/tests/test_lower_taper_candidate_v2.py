import json
from pathlib import Path
import pytest
from evaluations.lower_taper_relation_v1 import lower_taper_relation
from evaluations.heart_acceptance_candidate_v2 import compare
from evaluations.stress_heart_candidate_v1 import scenarios

ROWS={r['response_index']:r for r in json.loads((Path(__file__).parent/'fixtures/recorded_shallow_notch_audit.json').read_text(encoding='utf-8'))}


@pytest.mark.parametrize('segments',[1,5,20])
def test_same_tapering_or_flat_boundary_is_invariant_to_collinear_resampling(segments):
    def sample(points):
        return [(a[0]+(b[0]-a[0])*i/segments,a[1]+(b[1]-a[1])*i/segments)
            for a,b in zip(points,points[1:]+points[:1]) for i in range(segments)]
    assert lower_taper_relation(sample([(0,0),(-2000,4000),(2000,4000)]))['relation_passed']
    assert not lower_taper_relation(sample([(-2000,0),(-2000,4000),(2000,4000),(2000,0)]))['relation_passed']


@pytest.mark.parametrize('index',[3,5])
def test_historical_shallow_notch_is_preserved(index):
    row=ROWS[index];result=compare(row['source'],row['payload'])
    assert result['candidate_passed'] and result['v1_candidate_passed']
    assert not result['legacy_passed'] and not result['formal_candidate_accepted']


@pytest.mark.parametrize('name',['rounded_u_160','rounded_u_400'])
def test_v2_rejects_known_v1_false_positive(name):
    row=ROWS[3];payload=dict(scenarios(row))[name];result=compare(row['source'],payload)
    assert result['v1_candidate_passed']
    assert not result['candidate_passed']
    assert result['candidate_acceptance_summary']['status']=='failed'
    assert not result['lower_taper']['checks']['no_resolved_flat_bottom']


@pytest.mark.parametrize('samples',[32,64,128])
def test_smooth_round_bottom_is_measurable_but_not_full_shape_acceptance(samples):
    import math
    points=[(1000*math.cos(2*math.pi*i/samples),1000+1000*math.sin(2*math.pi*i/samples)) for i in range(samples)]
    result=lower_taper_relation(points)
    assert result['relation_passed']
    assert not result['formal_candidate_accepted']
