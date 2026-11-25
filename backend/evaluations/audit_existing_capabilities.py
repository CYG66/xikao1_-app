"""Read-only reference audit. Replay artifacts is not an LLM success test."""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
REFERENCE=Path(r'C:\Users\29924\Codes\xikao\backend')
HISTORY=ROOT/'.local-dev/live-corpus-acjm57j_/run'

def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def inventory(root):
    result={}
    for path in sorted((root/'app').rglob('*.py')):
        if '__pycache__' in path.parts:continue
        raw=path.read_bytes();tree=ast.parse(raw.decode('utf-8-sig'))
        result[path.relative_to(root).as_posix()]={
            'sha256':hashlib.sha256(raw).hexdigest(),
            'definitions':[{'name':n.name,'line':n.lineno,'kind':type(n).__name__}
                for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))]}
    return result

def worker(output):
    sys.path.insert(0,str(output/'reference-snapshot'))
    from app.cad_construction import execute_construction_plan
    from app.cad_edit_gate import validate_declared_edit_effect
    from app.drawing_store import geometry_preview_paths
    import importlib.util
    oracle_path=REFERENCE/'tests/manual/run_user_cad_corpus.py'
    spec=importlib.util.spec_from_file_location('reference_corpus_oracle',oracle_path)
    oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle)
    from app.agent_skills import heart_outline_geometry,check_drawing_feasibility
    from app.cad_semantic_acceptance import verify_semantic_requirements
    heart=heart_outline_geometry(4,4)
    heart_probe={'origin':'reference app.agent_skills.heart_outline_geometry (existing function)',
                 'scope':'tool capability only; not production routing or candidate acceptance',
                 'feasibility':check_drawing_feasibility([heart]),
                 'semantic':verify_semantic_requirements('生成一个闭合爱心轮廓，宽度4米，高度4米',[heart]),
                 'oracle':oracle.create_checks('A1',{'ok':True,'variant':{'geometries':[heart]},
                    'preview_paths':geometry_preview_paths({'lines':[heart]})},['生成一个闭合爱心轮廓，宽度4米，高度4米'])}
    dump(output/'existing-heart-tool-proof.json',heart_probe)
    from app.cad_path_relation_acceptance import verify_path_relations
    from app.cad_repetition_acceptance import verify_repetition_requirements
    probes=[]
    divider=json.loads((ROOT/'tests/fixtures/recorded_symmetric_divider.json').read_text(encoding='utf-8'))
    geometry=execute_construction_plan(divider['plan'])['geometries']
    probes.append({'case':'C31','existing_function':'cad_path_relation_acceptance.verify_path_relations',
        'artifact_provenance':divider['provenance'],'report':verify_path_relations(divider['original'],geometry)})
    for row in json.loads((ROOT/'tests/fixtures/recorded_source_proof_gaps.json').read_text(encoding='utf-8'))['rows']:
        if row['case'] not in {'C18','C22'}:continue
        geometry=execute_construction_plan(row['plan'])['geometries']
        report=(verify_semantic_requirements(row['original'],geometry) if row['case']=='C18'
                else verify_repetition_requirements(row['source'],geometry))
        probes.append({'case':row['case'],'scope':'existing independent verifier on a recorded plan, not end-to-end',
                       'report':report})
    dump(output/'existing-measurement-proofs.json',probes)
    manifest=json.loads((HISTORY/'manifest.json').read_text(encoding='utf-8'))
    records=[]
    for case,prompt in manifest['prompts'].items():
        folder=HISTORY/case;plans={};projects=[]
        store=folder/'projects.json'
        if store.exists():projects=json.loads(store.read_text(encoding='utf-8')).get('projects',[])
        for project in projects:
            for variant in project.get('variants',[]):
                plan=(variant.get('construction_record') or {}).get('plan')
                if plan:plans[json.dumps(plan,sort_keys=True)]=('saved_construction',plan)
        responses=folder/'model-responses.jsonl'
        if responses.exists():
            for line in responses.read_text(encoding='utf-8').splitlines():
                try:
                    payload=json.loads(json.loads(line)['response']);plan=payload.get('plan')
                    if isinstance(plan,dict):plans.setdefault(json.dumps(plan,sort_keys=True),('raw_model_plan',plan))
                except (ValueError,KeyError,TypeError):pass
        trials=[]
        for _,(origin,plan) in plans.items():
            record={'origin':origin,'plan_sha256':hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest(),
                    'ops':sorted({s.get('op','') for s in plan.get('steps',[])})}
            try:
                result=execute_construction_plan(plan)
                record.update(executable=True,geometry_count=len(result['geometries']))
                if case not in manifest['edit_bases']:
                    # A diagnostic wrapper only supplies geometry to the old
                    # oracle. It is not a saved/accepted production candidate.
                    probe={'ok':True,'variant':{'geometries':result['geometries'],
                           'logical_objects':result.get('logical_objects',[])},
                           'preview_paths':geometry_preview_paths({'lines':result['geometries']})}
                    alias=manifest['aliases'][case]
                    messages=[prompt,*([manifest['supplements'][alias]] if alias in manifest['supplements'] else [])]
                    try:record['reference_geometry_oracle']=oracle.create_checks(alias,probe,messages)
                    except Exception as exc:record['oracle_error']=str(exc)[:1000]
            except Exception as exc:record.update(executable=False,error_type=type(exc).__name__,reason=str(exc)[:2000])
            trials.append(record)
        edits=[]
        contracts={}
        for path in folder.glob('*step-*.json'):
            response=json.loads(path.read_text(encoding='utf-8'))
            contract=response.get('cad_edit_contract')
            if isinstance(contract,dict):contracts[contract.get('parent_variant_id')]=contract
        for project in projects:
            variants={v['id']:v for v in project.get('variants',[])}
            for variant in variants.values():
                contract=variant.get('edit_contract') or contracts.get(variant.get('parent_variant_id'))
                parent=variants.get(variant.get('parent_variant_id'))
                if not isinstance(contract,dict) or not parent:continue
                try:
                    checked=validate_declared_edit_effect(parent['geometries'],variant['geometries'],contract)
                    edits.append({'operation':contract.get('operation'),'result':checked})
                except Exception as exc:edits.append({'error':str(exc)[:1000]})
        later_edits=[]
        if case in manifest['edit_bases']:
            for run_folder in sorted((ROOT/'.local-dev').glob('live-corpus-*/run')):
                if run_folder==HISTORY:continue
                path=run_folder/case/'projects.json'
                if not path.exists():continue
                snapshot=json.loads(path.read_text(encoding='utf-8'))
                variants={v['id']:v for p in snapshot.get('projects',[]) for v in p.get('variants',[])}
                seen=set()
                for response_path in (run_folder/case).glob('*step-*.json'):
                    response=json.loads(response_path.read_text(encoding='utf-8'));command=response.get('cad_edit_contract')
                    if not isinstance(command,dict):continue
                    key=json.dumps(command,sort_keys=True)
                    if key in seen:continue
                    seen.add(key);parent=variants.get(command.get('parent_variant_id'))
                    target=response.get('variant') or {}
                    if not target and response.get('cad_edit_outcome')=='already_satisfied':target=parent or {}
                    if not parent or not target.get('geometries'):continue
                    try:
                        checked=validate_declared_edit_effect(parent['geometries'],target['geometries'],command)
                        later_edits.append({'artifact':str(response_path),'operation':command.get('operation'),'result':checked,
                            'scope':'Later real artifacts replayed on old engine; not old-model or old-delivery proof.'})
                    except Exception as exc:later_edits.append({'artifact':str(response_path),'error':str(exc)[:1000]})
        records.append({'case':case,'prompt':prompt,'edit_base':manifest['edit_bases'].get(case),
            'construction_artifact_replays':trials,'edit_artifact_replays':edits,
            'later_edit_artifact_replays':later_edits,
            'boundary':('historical_plan_executable' if any(t['executable'] for t in trials)
                        else 'available_artifacts_failed' if trials else 'no_artifact_proof'),
            'end_to_end_on_reference':'not_tested',
            'warning':'Execution is not proof of source geometry correctness, NLP planning, acceptance or delivery.'})
    dump(output/'70-case-evidence.json',records)
    print(json.dumps({'cases':len(records),'with_executable_artifact':sum(any(t['executable'] for t in r['construction_artifact_replays']) for r in records),
        'with_edit_replay':sum(bool(r['edit_artifact_replays']) for r in records)},ensure_ascii=False),flush=True)

def main():
    from scripts.local_dev import isolated_environment,run
    env,state=isolated_environment('capability-audit',False)
    env['PYTHONDONTWRITEBYTECODE']='1'
    before=inventory(REFERENCE);current=inventory(ROOT)
    for name in before:
        target=state/'reference-snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(REFERENCE/name,target)
    for path in (REFERENCE/'app/cad_reference_data').glob('*.json'):
        target=state/'reference-snapshot/app/cad_reference_data'/path.name
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    dump(state/'reference-inventory.json',before);dump(state/'current-inventory.json',current)
    dump(state/'comparison.json',{'reference':str(REFERENCE),'current':str(ROOT),
        'reference_is_pristine_github_baseline':False,
        'new_modules':[n for n in current if n not in before],
        'changed_modules':[n for n in current if n in before and current[n]['sha256']!=before[n]['sha256']],
        'same_modules':[n for n in current if n in before and current[n]['sha256']==before[n]['sha256']]})
    print('AUDIT OUTPUT: '+str(state),flush=True)
    code=run([sys.executable,str(Path(__file__).resolve()),'--worker',str(state)],env)
    dump(state/'reference-integrity.json',{'source_unchanged':inventory(REFERENCE)==before,'worker_exit_code':code})
    if code==0:
        rows=json.loads((state/'70-case-evidence.json').read_text(encoding='utf-8'))
        lines=['# 70项原有能力证据矩阵','',
            '参考对象是旧目录的只读快照，不是已证明的初始GitHub版本。全部回放为离线工具测试，不请求模型，不提交候选。',
            '编辑案例的源构造计划不会算作该项编辑能力证据。历史检查存在人工复核标记等已知限制，未修改原始结果。','',
            '| 案例 | 原文 | 旧工具证据 | 独立几何/命令检查 | 旧端到端 |',
            '| --- | --- | --- | --- | --- |']
        geometric=0;edit_proofs=0
        for row in rows:
            if row['edit_base']:
                trials=row['edit_artifact_replays']+row['later_edit_artifact_replays']
                good=[t for t in trials if t.get('result',{}).get('enforced') and t['result'].get('verified')]
                edit_proofs+=bool(good)
                tool=' / '.join(sorted({t.get('operation','') for t in good})) or '无命令回放证据，不等于不支持'
                measured='实际历史命令重放一致' if good else '待补证据；不能用基图可执行代替编辑通过'
            else:
                trials=[t for t in row['construction_artifact_replays'] if t['executable']]
                good=[t for t in trials if t.get('reference_geometry_oracle') and all(c['passed'] for c in t['reference_geometry_oracle'])]
                geometric+=bool(good)
                tool=' / '.join(sorted({op for t in trials for op in t['ops']})) or '未证明'
                measured='至少一份历史计划通过旧几何检查（诊断包装）' if good else '可执行，但历史几何检查未全部通过；详见JSON'
            lines.append('| '+ ' | '.join([row['case'],row['prompt'].replace('|','／'),tool,measured,'未重测'])+' |')
        (state/'70-case-matrix.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        dump(state/'audit-summary.json',{'cases':len(rows),'generation_cases':45,
            'generation_cases_with_executable_plan':sum(not r['edit_base'] and any(t['executable'] for t in r['construction_artifact_replays']) for r in rows),
            'generation_cases_with_old_geometry_oracle_proof':geometric,'edit_cases_with_command_replay_proof':edit_proofs,
            'reference_end_to_end_cases_tested':0,'real_model_calls':0,'interpretation':'These counts are capability evidence, NOT corpus pass rates.'})
    return code

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--worker':worker(Path(sys.argv[2]))
    else:raise SystemExit(main())
