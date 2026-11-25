"""Single-threaded offline rule candidate; never used by production delivery."""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import re

from app import cad_semantic_acceptance as semantic
from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import interpret_construction_request
from evaluations.audit_heart_remaining_checks import diagnostic_verifier

VERSION='cad.heart-acceptance-candidate.v1'


def compare(source,payload):
    original=semantic.verify_semantic_requirements
    def interpret(verifier=None):
        return interpret_construction_request(source,lambda *_:deepcopy(payload),force_structured_model=True,_semantic_verifier=verifier)
    legacy=interpret()
    output={'version':VERSION,'scope':'offline_rule_comparison_only',
        'formal_candidate_accepted':False,'candidate_passed':False,
        'legacy_status':legacy['status'],'legacy_passed':legacy.get('acceptance_summary',{}).get('status')=='passed',
        'legacy_error':legacy.get('construction_error') or legacy.get('error')}
    if not any(r['kind']=='heart_outline_features' for r in semantic.semantic_requirements(source)):
        return {**output,'candidate_status':'unsupported','reason':'not_supported_heart_request'}
    # Never drop an explicit depth/shape instruction into the default rule.
    # Unsupported clauses require a separate source-bound measurement adapter.
    if re.search(r'凹口|凹陷|凹槽|notch',source,re.I):
        return {**output,'candidate_status':'unsupported','reason':'explicit_notch_requirement_needs_source_measurement'}
    candidate=interpret(diagnostic_verifier())
    assert semantic.verify_semantic_requirements is original
    unchanged=None;geometry_hash=None
    try:
        before=execute_construction_plan(legacy['plan'])['geometries']
        after=execute_construction_plan(candidate['plan'])['geometries']
        unchanged=before==after
        assert unchanged,'Rule comparison must not change geometry'
        geometry_hash=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest()
    except (ValueError,KeyError):
        pass
    passed=(candidate['status']=='ready' and candidate.get('acceptance_summary',{}).get('status')=='passed'
        and unchanged is True)
    return {**output,'candidate_status':candidate['status'],'candidate_passed':passed,
        'candidate_error':candidate.get('construction_error') or candidate.get('error'),
        'candidate_acceptance_summary':candidate.get('acceptance_summary'),
        'candidate_source_acceptance':candidate.get('source_acceptance'),
        'geometry_unchanged':unchanged,'geometry_sha256':geometry_hash}


def report(fixture,output):
    rows=json.loads(fixture.read_text(encoding='utf-8'))
    results=[{'response_index':r['response_index'],**compare(r['source'],r['payload'])} for r in rows]
    result={'version':VERSION,'scope':'Recorded-plan rule comparison; not a fresh model test or revised corpus score',
        'fixture_sha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),
        'candidate_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'legacy_verifier_sha256':hashlib.sha256(inspect.getsource(semantic.verify_semantic_requirements).encode()).hexdigest(),
        'rows':results}
    result['dependency_source_sha256']={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ('notch_relation_v1.py','audit_heart_remaining_checks.py')}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{k:r[k] for k in ('response_index','legacy_passed','candidate_passed','formal_candidate_accepted')} for r in results]))


if __name__=='__main__':
    import sys
    report(Path(sys.argv[1]),Path(sys.argv[2]))
