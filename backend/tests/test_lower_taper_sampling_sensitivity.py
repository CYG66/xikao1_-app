import pytest
from evaluations.stress_lower_taper_sampling import study


@pytest.fixture(scope='module')
def result():return study()


def test_same_polygon_is_invariant_to_reindexing_reversal_collinear_density_scale_and_translation(result):
    assert result['summary']['exact_polygon_count']==108
    assert all(row['relation_passed'] for row in result['exact_polygon_rows'])


def test_records_phase_sensitive_false_rejection_with_small_chord_error(result):
    rows=[r for r in result['sampled_round_bottom_rows'] if r['radius_mm']==1000 and r['samples']==128 and r['translation_mm']==[0,0]]
    assert all(r['chord_error_within_tolerance'] for r in rows)
    assert next(r for r in rows if r['phase']==0)['proof']['relation_passed']
    assert not next(r for r in rows if r['phase']==.5)['proof']['relation_passed']
    # This test records an unsafe v2 limitation, not expected ideal behavior.


def test_thin_taper_exposes_dependency_on_probe_heights_not_a_full_heart_verdict(result):
    shallow=result['thin_taper_band_rows'][0]['proof']
    assert shallow['checks']['central_minimum'] and shallow['checks']['no_resolved_flat_bottom']
    assert not shallow['checks']['sections_expand_upward']
    assert not result['production_promotion_supported']
