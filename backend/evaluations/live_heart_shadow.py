"""Post-delivery shadow sidecar: captured payloads only, no provider credentials."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def protected_hashes(folder):
    paths=[folder/'result.json',folder/'projects.json',*folder.glob('step-*.json')]
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.exists()}


def sidecar(folder,formal_duration_ms,timeout=180):
    before=protected_hashes(folder);env=os.environ.copy()
    for name in list(env):
        if name.endswith('_API_KEY') or name.endswith('_API_KEYS'):env.pop(name)
    env['XLINE_AGENT_PROVIDER']='local'
    start=time.perf_counter()
    try:
        child=subprocess.run([sys.executable,'-m','evaluations.live_heart_shadow',str(folder)],
            env=env,capture_output=True,text=True,encoding='utf-8',timeout=timeout)
        status='completed' if child.returncode==0 else 'audit_error'
        error=None if child.returncode==0 else child.stderr[-2000:]
    except Exception as exc:
        status='audit_error';error=str(exc)
    result={'status':status,'error':error,'formal_duration_ms':formal_duration_ms,
        'shadow_duration_ms':(time.perf_counter()-start)*1000,
        'formal_files_unchanged':before==protected_hashes(folder),
        'provider_credentials_removed':True,'affects_formal_acceptance':False}
    (folder/'heart-shadow-sidecar.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def audit(folder):
    from evaluations.replay_recorded_hearts_v4 import collect
    from evaluations.heart_shadow_entry_v1 import interpret_with_shadow
    from app.cad_semantic_acceptance import semantic_requirements
    if (folder/'model-responses.jsonl').exists():
        records,skipped=collect(folder)
    else:
        records,skipped=[],[{'reason':'no_captured_model_responses'}]
    rows=[]
    for row in records:
        if not any(r['kind']=='heart_outline_features' for r in semantic_requirements(row['source'])):
            rows.append({'response_index':row['response_index'],'status':'not_applicable'});continue
        calls=[]
        def captured_model(*_):calls.append(1);return deepcopy(row['payload'])
        start=time.perf_counter()
        try:
            interpretation=interpret_with_shadow(row['source'],captured_model,enabled=True)
            report=interpretation.get('shadow_acceptance',{'status':'not_applicable'})
            comparison=report.get('comparison') or {}
            result={'status':report['status'],'formal_replay_status':interpretation['status'],
                'comparison':comparison,'disagreement':comparison.get('candidate_passed')!=comparison.get('legacy_passed')
                    if comparison else None}
        except Exception as exc:result={'status':'audit_error','reason':str(exc)}
        rows.append({'response_index':row['response_index'],'turn':row['turn'],'fingerprint':row['fingerprint'],
            'source':row['source'],'request_sha256':row['request_sha256'],
            'duration_ms':(time.perf_counter()-start)*1000,'captured_payload_callback_calls':len(calls),
            'fresh_provider_calls':0,**result})
    output={'scope':'Shadow replay of payloads from this real run; not a fresh generation score',
        'rule':'v5','formal_candidate_accepted_by_shadow':False,'rows':rows,'skipped':skipped}
    (folder/'heart-shadow-v5.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':audit(Path(sys.argv[1]))
