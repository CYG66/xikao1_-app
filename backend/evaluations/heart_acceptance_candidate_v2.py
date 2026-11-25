"""Offline v2 adds lower taper to v1; production and v1 stay unchanged."""
from copy import deepcopy
import hashlib
import json
from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_structure_contract import _points
from evaluations.heart_acceptance_candidate_v1 import compare as compare_v1
from evaluations.lower_taper_relation_v1 import lower_taper_relation

VERSION='cad.heart-acceptance-candidate.v2'


def compare(source,payload):
    old=compare_v1(source,payload)
    result={**old,'version':VERSION,'v1_candidate_passed':old['candidate_passed'],
        'v1_acceptance_summary':old.get('candidate_acceptance_summary'),
        'candidate_passed':False,'lower_taper':{'status':'not_checked'}}
    if not old['candidate_passed']:return result
    baseline=interpret_construction_request(source,lambda *_:deepcopy(payload),force_structured_model=True)
    geometries=execute_construction_plan(baseline['plan'])['geometries']
    digest=hashlib.sha256(json.dumps(geometries,sort_keys=True).encode()).hexdigest()
    if digest!=old['geometry_sha256']:raise RuntimeError('Geometry changed during rule comparison')
    proof=lower_taper_relation(_points(geometries[0]))
    return {**result,'candidate_passed':proof['relation_passed'],'lower_taper':proof,
        'candidate_status':'ready' if proof['relation_passed'] else 'invalid',
        'candidate_acceptance_summary':{**old['candidate_acceptance_summary'],
            'status':'passed' if proof['relation_passed'] else 'failed',
            'failed_checks':[] if proof['relation_passed'] else ['lower_taper_relation'],
            'evaluation_rule_version':VERSION},
        'candidate_error':None if proof['relation_passed'] else {'code':'lower_taper_relation_failed','details':proof}}
