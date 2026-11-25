from copy import deepcopy
import json
from pathlib import Path
import pytest

from app.cad_assertion_authority import reconcile_model_bounds
from app.cad_construction_interpreter import interpret_construction_request

DATA=json.loads((Path(__file__).parent/'fixtures/recorded_model_bounds_authority.json').read_text(encoding='utf-8'))


def normalized_payload():
    from app.cad_construction_interpreter import normalize_composite_path_connections_once,bind_explicit_outline_center
    payload,_=normalize_composite_path_connections_once(deepcopy(DATA['payload']),DATA['source'])
    payload,_=bind_explicit_outline_center(payload,DATA['source'])
    return payload


def test_recorded_correct_geometry_reaches_formal_commit(tmp_path):
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    from app.cad_candidate_state import candidate_is_accepted
    before=deepcopy(DATA)
    result=interpret_construction_request(DATA['source'],lambda *_:deepcopy(DATA['payload']),force_structured_model=True)
    assert result.get('acceptance_summary',{}).get('status')=='passed',result
    proof=next(c for c in result['deterministic_repairs'] if c['kind']=='complete_source_proof_replaces_model_bounds')
    assert proof['source_proof']['coverage']=='complete' and proof['geometry_unchanged']
    store=CreativeProjectStore(tmp_path/'projects.json')
    saved=commit_construction_interpretation(DATA['source'],result,store=store)
    assert candidate_is_accepted(store.get(saved['project_id'])['variants'][0]) and DATA==before


@pytest.mark.parametrize('mutation',['unknown_source','wrong_size','partial_target','valid_bounds','other_kind'])
def test_unproved_or_unrelated_assertions_are_retained(mutation):
    from app.cad_construction import construction_geometry_bounds
    from app.cad_construction_interpreter import _trial_plan_without_assertions
    payload=normalized_payload();source=DATA['source']
    assert reconcile_model_bounds(payload,source)[1]
    bounds=next(a for a in payload['plan']['assertions'] if a['kind']=='bounds_size')
    if mutation=='unknown_source':source+='世界外包框宽度5.7米。'
    elif mutation=='wrong_size':source=source.replace('572厘米','582厘米')
    elif mutation=='partial_target':bounds['target_ref']='missing-part'
    elif mutation=='other_kind':bounds.update(kind='entity_count',equals=8);[bounds.pop(k,None) for k in ('width','height','tolerance')]
    else:
        b=construction_geometry_bounds(_trial_plan_without_assertions(payload['plan'])['geometries'])
        bounds.update(width=(b['max_x']-b['min_x'])/1000,height=(b['max_y']-b['min_y'])/1000)
    before=deepcopy(payload)
    result,changes=reconcile_model_bounds(payload,source)
    assert result==before and not changes and payload==before


def test_authority_step_does_not_change_geometry_or_other_assertions():
    payload=normalized_payload()
    result,changes=reconcile_model_bounds(payload,DATA['source'])
    assert changes and result['plan']['steps']==payload['plan']['steps']
    assert [a for a in payload['plan']['assertions'] if a['kind']!='bounds_size']==result['plan']['assertions']
    again,changes=reconcile_model_bounds(result,DATA['source'])
    assert again==result and not changes
