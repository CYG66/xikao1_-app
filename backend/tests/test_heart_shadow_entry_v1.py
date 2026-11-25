from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch
from app import cad_semantic_acceptance as semantic
from app.cad_construction_interpreter import interpret_construction_request
from evaluations.heart_shadow_entry_v1 import interpret_with_shadow

ROW=json.loads((Path(__file__).parent/'fixtures/recorded_shallow_notch_audit.json').read_text(encoding='utf-8'))[0]


def invoke(enabled=False,rule_version='v5'):
    calls=[]
    def callback(*args):calls.append(args);return deepcopy(ROW['payload'])
    result=interpret_with_shadow(ROW['source'],callback,enabled=enabled,rule_version=rule_version)
    assert len(calls)==1
    return result


def test_default_off_preserves_formal_output():
    baseline=interpret_construction_request(ROW['source'],lambda *_:deepcopy(ROW['payload']))
    assert invoke()==baseline
    assert 'shadow_acceptance' not in baseline


def test_shadow_pass_cannot_promote_formal_failure_or_trigger_a_second_model_call():
    baseline=invoke();shadow=invoke(True)
    report=shadow.pop('shadow_acceptance')
    assert shadow==baseline and shadow['status']=='invalid'
    assert report['status']=='completed'
    assert report['comparison']['candidate_passed']
    assert not report['affects_formal_acceptance']


def test_concurrent_legacy_and_shadow_do_not_replace_global_verifier():
    verifier=semantic.verify_semantic_requirements
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(invoke,[False,True,False,True]))
    assert semantic.verify_semantic_requirements is verifier
    assert all(r['status']=='invalid' for r in results)
    assert ['shadow_acceptance' in r for r in results]==[False,True,False,True]


def test_shadow_failure_and_unknown_rule_leave_formal_result_intact():
    baseline=invoke()
    with patch('evaluations.heart_acceptance_candidate_v5.compare',side_effect=RuntimeError('test failure')):
        failure=invoke(True)
    assert failure.pop('shadow_acceptance')['status']=='audit_error'
    assert failure==baseline
    unsupported=invoke(True,rule_version='missing')
    assert unsupported.pop('shadow_acceptance')['status']=='unsupported_rule'
    assert unsupported==baseline
