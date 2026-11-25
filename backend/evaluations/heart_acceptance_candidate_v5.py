"""Offline compatibility decision: unsupported new analysis is not a regression."""
from copy import deepcopy
from evaluations.heart_acceptance_candidate_v4 import compare as compare_v4

VERSION='cad.heart-acceptance-candidate.v5'


def compatibility_decision(previous):
    result=deepcopy(previous);result['version']=VERSION
    result['v4_decision']=previous['decision']
    result['formal_candidate_accepted']=False
    if previous['legacy_passed'] and previous['decision']=='undetermined' and previous['reason']=='source_extremum_not_resolved':
        result.update(decision='passed',candidate_passed=True,
            decision_origin='legacy_acceptance_retained',reason='new_analysis_unsupported_does_not_invalidate_existing_acceptance')
    elif previous['legacy_passed'] and previous['decision']=='rejected':
        result.update(decision='undetermined',candidate_passed=False,
            decision_origin='legacy_new_rule_conflict',reason='new_rejection_conflicts_with_legacy_acceptance_requires_review')
    else:
        result['decision_origin']='v4_evidence'
    return result


def compare(source,payload):return compatibility_decision(compare_v4(source,payload))
