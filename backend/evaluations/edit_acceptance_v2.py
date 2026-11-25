"""Versioned evaluation only: structured clarification and global immutability."""
from copy import deepcopy

VERSION='edit-evaluation.v2'


def candidate_snapshot(projects):
    return {str(p['id']):{'original_prompt':p.get('original_prompt'),
                         'variants':deepcopy(p.get('variants') or [])} for p in projects}


def assess_clarification(response,before,after):
    checks={'structured_clarification':response.get('clarification_required') is True,
            'no_delivered_variant':not response.get('variant') and not response.get('variants'),
            'no_pending_action':not response.get('pending_action'),
            'all_projects_and_candidates_unchanged':before==after,
            'no_candidate_commit':not any(t.get('kind')=='candidate_commit' for t in response.get('tool_results') or [])}
    return {'version':VERSION,'passed':all(checks.values()),'checks':checks}
