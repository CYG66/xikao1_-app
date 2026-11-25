import json
from pathlib import Path
from unittest.mock import patch
from evaluations.live_heart_shadow import sidecar,protected_hashes

ROW=json.loads((Path(__file__).parent/'fixtures/recorded_shallow_notch_audit.json').read_text(encoding='utf-8'))[0]


def setup(folder):
    def write(name,data):(folder/name).write_text(json.dumps(data),encoding='utf-8')
    write('request-1.json',{'message':ROW['source'],'history':[]})
    write('result.json',{'formal_passed':False})
    write('projects.json',{'projects':[]})
    write('step-1.json',{'ok':False})
    (folder/'model-responses.jsonl').write_text(json.dumps({'step':1,'response':json.dumps(ROW['payload'])}),encoding='utf-8')


def test_real_subprocess_sidecar_preserves_formal_files_and_does_not_receive_credentials(tmp_path,monkeypatch):
    setup(tmp_path);before=protected_hashes(tmp_path)
    monkeypatch.setenv('TEST_API_KEY','not_a_real_key')
    from evaluations import live_heart_shadow as module
    original=module.subprocess.run;seen=[]
    def child(*args,**kwargs):
        assert not any(k.endswith('_API_KEY') or k.endswith('_API_KEYS') for k in kwargs['env'])
        seen.append(1);return original(*args,**kwargs)
    with patch.object(module.subprocess,'run',side_effect=child):result=sidecar(tmp_path,12)
    assert len(seen)==1 and result['status']=='completed'
    assert result['formal_files_unchanged'] and protected_hashes(tmp_path)==before
    report=json.loads((tmp_path/'heart-shadow-v5.json').read_text(encoding='utf-8'))
    assert report['rows'][0]['fresh_provider_calls']==0
    assert report['rows'][0]['comparison']['candidate_passed']


def test_shadow_timeout_is_recorded_without_mutating_formal_output(tmp_path):
    setup(tmp_path);before=protected_hashes(tmp_path)
    with patch('evaluations.live_heart_shadow.subprocess.run',side_effect=TimeoutError('test timeout')):
        result=sidecar(tmp_path,10)
    assert result['status']=='audit_error'
    assert protected_hashes(tmp_path)==before


def test_rule_only_case_has_no_model_payload_and_is_not_an_audit_error(tmp_path):
    (tmp_path/'result.json').write_text('{"formal_passed": true}',encoding='utf-8')
    result=sidecar(tmp_path,10)
    assert result['status']=='completed' and result['formal_files_unchanged']
    report=json.loads((tmp_path/'heart-shadow-v5.json').read_text(encoding='utf-8'))
    assert report['rows']==[]
    assert report['skipped']==[{'reason':'no_captured_model_responses'}]
