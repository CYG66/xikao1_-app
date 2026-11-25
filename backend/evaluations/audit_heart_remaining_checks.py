"""Isolated counterfactual audit. Never persists candidates or changes scores."""
from functools import partial
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path

from app import cad_semantic_acceptance as semantic
from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import interpret_construction_request
from evaluations.notch_relation_v1 import upper_notch_relation


def diagnostic_verifier():
    """Bind one request-local predicate through the explicit verifier API.

    All other checks and the checked geometry remain unchanged. The original
    function and its module file are never rewritten or replaced globally.
    """
    return partial(semantic.verify_semantic_requirements,_heart_notch_verifier=upper_notch_relation)


def audit(run):
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    project=read(run/'A9/projects.json')['projects'][0]
    source='\n'.join([project['original_prompt'],*project['requirements'].get('source_followups',[])])
    responses=[json.loads(line) for line in (run/'A9/model-responses.jsonl').read_text(encoding='utf-8').splitlines()]
    original=semantic.verify_semantic_requirements; diagnostic=diagnostic_verifier();rows=[]
    for index in (3,5):
        payload=json.loads(responses[index-1]['response'])
        def interpret(verifier=None):
            return interpret_construction_request(source,lambda *_:deepcopy(payload),force_structured_model=True,_semantic_verifier=verifier)
        baseline=interpret()
        geometry=execute_construction_plan(baseline['plan'])['geometries']
        trial=interpret(diagnostic)
        assert semantic.verify_semantic_requirements is original
        after=execute_construction_plan(trial['plan'])['geometries']
        assert geometry==after, 'Diagnostic must never change geometry'
        row={'response_index':index,'original_status':baseline['status'],
            'original_error':baseline.get('construction_error'),
            'diagnostic_only':True,'formal_candidate_accepted':False,
            'diagnostic_status':trial['status'], 'diagnostic_error':trial.get('construction_error') or trial.get('error'),
            'diagnostic_acceptance_summary':trial.get('acceptance_summary'),
            'diagnostic_source_acceptance':trial.get('source_acceptance'),
            'geometry_unchanged':True,
            'geometry_sha256':hashlib.sha256(json.dumps(geometry,sort_keys=True).encode()).hexdigest()}
        rows.append(row)
    output={'scope':'Counterfactual diagnostic only; one notch predicate replaced in memory; no persistence or rescoring',
        'source_run':str(run.resolve()),'source':source,'rows':rows,
        'original_verifier_source_sha256':hashlib.sha256(inspect.getsource(original).encode()).hexdigest(),
        'diagnostic_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (run/'A9/remaining-checks-counterfactual.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    for row in rows: print(json.dumps({k:v for k,v in row.items() if k not in {'original_error','diagnostic_source_acceptance'}},ensure_ascii=False))


if __name__=='__main__':
    import sys
    audit(Path(sys.argv[1]))
