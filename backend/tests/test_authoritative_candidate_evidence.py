from app.cad_candidate_state import candidate_is_accepted, authoritative_acceptance_summary


def test_nested_legacy_pass_cannot_authorize_candidate():
    candidate = {'construction_record': {'acceptance_summary': {'status': 'passed'}}}
    assert candidate_is_accepted(candidate) is False
    assert authoritative_acceptance_summary(candidate) is None


def test_conflicting_nested_evidence_blocks_authoritative_pass():
    candidate = {'acceptance_summary': {'status': 'passed'},
                 'construction_record': {'acceptance_summary': {'status': 'failed'}}}
    assert candidate_is_accepted(candidate) is False
    assert authoritative_acceptance_summary(candidate) is None


def test_authoritative_pass_is_required_and_returned():
    candidate = {'acceptance_summary': {'status': 'passed', 'review_required': False}}
    assert candidate_is_accepted(candidate) is True
    assert authoritative_acceptance_summary(candidate) == candidate['acceptance_summary']
