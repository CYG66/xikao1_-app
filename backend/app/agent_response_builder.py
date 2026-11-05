"""Pure response adapters; no CAD execution, storage or model requests."""
from copy import deepcopy


def normalize_acceptance_response(result):
    """Expose acceptance at each response envelope, including tool results.

    Legacy storage paths are interpreted here only. Missing evidence never
    becomes a claim that every user requirement has passed.
    """
    out=dict(result)
    tools=out.get('tool_results')
    if isinstance(tools,list):
        out['tool_results']=[normalize_acceptance_response(t) if isinstance(t,dict) else t for t in tools]
    variant=out.get('variant') or {}
    if not variant and isinstance(out.get('variants'), list):
        current_ids = {
            str(item.get('variant_id')) for item in out.get('tool_results', [])
            if isinstance(item, dict) and item.get('variant_id')
        }
        matches = [
            item for item in out['variants']
            if isinstance(item, dict) and str(item.get('id')) in current_ids
        ]
        if len(matches) == 1:
            variant = matches[0]
            out['variant'] = deepcopy(variant)
    record=variant.get('construction_record') or {} if isinstance(variant,dict) else {}
    interpretation=out.get('construction_interpretation') or {}
    candidates=[variant.get('acceptance_summary') if isinstance(variant,dict) else None,
                record.get('acceptance_summary'), out.get('acceptance_summary'),
                interpretation.get('acceptance_summary') if isinstance(interpretation,dict) else None]
    reports=[out.get('source_acceptance'),record.get('source_acceptance')]
    repair_validation = out.get('local_repair_validation')
    if not isinstance(repair_validation, dict) and isinstance(interpretation, dict):
        repair_validation = interpretation.get('local_repair_validation')
    if not isinstance(repair_validation, dict):
        repair_validation = record.get('local_repair_validation') if isinstance(record,dict) else None
    persisted_repair_changes = record.get('repair_changes') if isinstance(record, dict) else None
    summary=next((s for s in candidates if isinstance(s,dict)),None)
    report=next((s for s in reports if isinstance(s,dict)),None)
    if summary is not None:
        summary=deepcopy(summary)
    elif report is not None:
        summary={'status':'review_required','review_required':True,
                 'coverage':report.get('coverage','partial'),'authority':'backend_measured_geometry'}
    else:
        summaries=[t['acceptance_summary'] for t in out.get('tool_results',[]) if isinstance(t,dict) and isinstance(t.get('acceptance_summary'),dict)]
        summary=deepcopy(summaries[-1]) if summaries else None
    if summary is None and isinstance(persisted_repair_changes, dict):
        summary={
            'status':'review_required',
            'review_required':True,
            'authority':'backend_measured_geometry',
            'repair_changes':deepcopy(persisted_repair_changes),
        }
    if summary is not None:
        from .cad_candidate_state import candidate_is_accepted
        persisted_accepted = candidate_is_accepted(variant)
        # The persisted summary already converges all independent validators.
        # A single partial sub-report must not overwrite that authoritative
        # result. Without an accepted persisted variant, uncertainty still
        # conservatively requires review.
        review=summary.get('review_required') is True or summary.get('status')!='passed'
        if report is not None and not persisted_accepted:
            review=review or report.get('review_required') is True or report.get('status') in {'partial','not_checked'}
        if isinstance(repair_validation, dict):
            review=review or repair_validation.get('verified') is False
            summary['local_repair_validation']=deepcopy(repair_validation)
            summary['repair_changes']={
                'changed_step_refs': list(repair_validation.get('changed_step_refs') or []),
                'changed_fields_by_ref': deepcopy(repair_validation.get('changed_fields_by_ref') or {}),
            }
        elif isinstance(persisted_repair_changes, dict):
            summary['repair_changes']=deepcopy(persisted_repair_changes)
        summary.update(status='review_required' if review else 'passed',review_required=review)
        out['acceptance_summary']=summary
    return out
