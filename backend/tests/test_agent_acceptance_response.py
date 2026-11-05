from copy import deepcopy
from app.agent_response_builder import normalize_acceptance_response


def test_legacy_record_is_adapted_without_mutating_storage():
    value={'variant':{'construction_record':{'source_acceptance':{'status':'partial','review_required':False}}}}
    original=deepcopy(value)
    result=normalize_acceptance_response(value)
    assert result['acceptance_summary']['review_required'] is True
    assert value==original


def test_tool_and_envelope_share_public_summary():
    summary={'status':'review_required','review_required':True}
    result=normalize_acceptance_response({'tool_results':[{'variant':{'construction_record':{'acceptance_summary':summary}}}]})
    assert result['acceptance_summary']==result['tool_results'][0]['acceptance_summary']==summary


def test_explicit_complete_acceptance_and_non_cad_response():
    summary={'status':'passed','review_required':False}
    assert normalize_acceptance_response({'acceptance_summary':summary})['acceptance_summary']==summary
    assert normalize_acceptance_response({'ok':True})=={'ok':True}


def test_partial_evidence_overrides_optimistic_summary():
    result=normalize_acceptance_response({'acceptance_summary':{'status':'passed','review_required':False},
        'source_acceptance':{'status':'partial'}})
    assert result['acceptance_summary']['status']=='review_required'


def test_current_persisted_variant_summary_is_not_overwritten_by_one_partial_subreport():
    summary={'status':'passed','review_required':False,'verified_checks':1}
    variant={
        'id':'variant-current',
        'acceptance_summary':summary,
        'construction_record':{
            'acceptance_summary':summary,
            'source_acceptance':{'status':'not_checked','coverage':'partial','checks':[]},
        },
    }
    result=normalize_acceptance_response({
        'variants':[variant],
        'tool_results':[{'kind':'candidate_commit','variant_id':'variant-current'}],
        'acceptance_summary':{'status':'review_required','review_required':True},
    })
    assert result['variant']['id']=='variant-current'
    assert result['acceptance_summary']['status']=='passed'
    assert result['acceptance_summary']['verified_checks']==1


def test_local_repair_is_exposed_as_public_repair_changes_contract():
    result=normalize_acceptance_response({
        'acceptance_summary':{'status':'passed','review_required':False},
        'local_repair_validation':{
            'verified':True,
            'changed_step_refs':['outer'],
            'changed_fields_by_ref':{'outer':{'vertices':{'before':[], 'after':[1]}}},
        },
    })
    assert result['acceptance_summary']['repair_changes']['changed_step_refs']==['outer']
    assert result['acceptance_summary']['repair_changes']['changed_fields_by_ref']['outer']['vertices']['after']==[1]


def test_persisted_repair_changes_are_restored_for_legacy_history():
    result=normalize_acceptance_response({
        'variant':{'construction_record':{
            'acceptance_summary':{'status':'passed','review_required':False},
            'repair_changes':{'changed_step_refs':['inner']},
        }},
    })
    assert result['acceptance_summary']['repair_changes']['changed_step_refs']==['inner']


def test_repair_only_history_is_marked_for_review():
    result=normalize_acceptance_response({'variant':{'construction_record':{
        'repair_changes':{'changed_step_refs':['outer']},
    }}})
    assert result['acceptance_summary']['status']=='review_required'
