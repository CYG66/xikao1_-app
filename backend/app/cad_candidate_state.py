"""Shared candidate eligibility for restore, selection and editing.

Acceptance is evidence, not a default.  Every consumer must use this helper so
that a candidate cannot be visible in one route and rejected in another.
"""


def candidate_is_accepted(variant):
    if not isinstance(variant, dict):
        return False
    record = variant.get('construction_record')
    record = record if isinstance(record, dict) else {}
    summaries = [variant.get('acceptance_summary'), record.get('acceptance_summary')]
    evidence = [s for s in summaries if isinstance(s, dict)]
    return isinstance(variant.get('acceptance_summary'), dict) and bool(evidence) and all(
        s.get('status') == 'passed' and s.get('review_required') is not True
        for s in evidence
    )


def authoritative_acceptance_summary(variant):
    if not isinstance(variant, dict):
        return None
    record=variant.get('construction_record')
    values=[variant.get('acceptance_summary'),
            record.get('acceptance_summary') if isinstance(record,dict) else None]
    evidence=[v for v in values if isinstance(v,dict)]
    if not isinstance(variant.get('acceptance_summary'), dict) or not evidence or not all(v.get('status') == 'passed' and v.get('review_required') is not True for v in evidence):
        return None
    return evidence[0]


def accepted_project_view(project):
    """Return the project shape safe for all read-only project endpoints."""
    if not isinstance(project, dict):
        return project
    from copy import deepcopy
    view=deepcopy(project)
    variants=view.get('variants')
    if isinstance(variants,list):
        view['variants']=[v for v in variants if candidate_is_accepted(v)]
        visible_ids={str(v.get('id')) for v in view['variants']}
        if str(view.get('selected_variant_id') or '') not in visible_ids:
            view['selected_variant_id']=None
        if str(view.get('design_base_variant_id') or '') not in visible_ids:
            view['design_base_variant_id']=None
    return view
