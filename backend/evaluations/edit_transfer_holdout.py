"""Frozen generation, ambiguous reference, explicit object edit production pilot."""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from scripts.local_dev import ROOT,isolated_environment
from evaluations import production_contract_pilot as base
from evaluations.frozen_release_validation import holdout_oracle

FREEZE=ROOT/'.local-dev/edit-holdout-freeze-b_ze0fwf'
SOURCE='在同一张图中画三个独立图形。左圆：圆，圆心(-1600,800)，半径340毫米，坐标单位毫米；右圆：圆，圆心(2100,800)，半径220毫米，坐标单位毫米；下矩形：矩形，左下角(-400,-1300)，宽900毫米，高650毫米，坐标单位毫米。不要增加连接线或标注。'
AMBIGUOUS='把圆的半径改为460毫米，其他图形保持不变。只生成预览，不执行小车。'


def cases():
    gold=[{'type':'circle','center':{'x':-1600,'y':800},'radius':340},
          {'type':'circle','center':{'x':2100,'y':800},'radius':220},
          {'type':'polyline','closed':True,'vertices':[{'x':x,'y':y} for x,y in [(-400,-1300),(500,-1300),(500,-650),(-400,-650)]]}]
    a=deepcopy(gold);a[0]['radius']=510
    b=deepcopy(gold)
    for p in b[2]['vertices']:p['x']+=230
    return [({'id':'E1','family':'explicit_geometry','text':SOURCE,'expected':gold},
             '将左圆的半径改为510毫米，圆心不动，其他图形保持不变。只生成预览，不执行小车。',a),
            ({'id':'E2','family':'explicit_geometry','text':SOURCE,'expected':gold},
             '将下矩形整体向右移动230毫米，尺寸不变，其他图形保持不变。只生成预览，不执行小车。',b)]


def main():
    from evaluations.run_live_user_corpus import load_key
    load_key();env,state=isolated_environment('edit-transfer-live',True)
    os.environ.update({k:v for k,v in env.items() if k!='PATH'})
    frozen=json.loads((FREEZE/'freeze.json').read_text(encoding='utf-8'))
    assert base.tree_hashes(ROOT/'app')==frozen['source_files']==base.tree_hashes(FREEZE/'app')
    output=base.prepare(state);staged=base.tree_hashes(output/'versions/B');data=cases()
    for c,_,expected in data:
        assert holdout_oracle(c,c['expected'])['passed']
        assert holdout_oracle({'expected':expected},expected)['passed']
        assert not holdout_oracle({'expected':expected},c['expected'])['passed']
    names=['evaluations/edit_transfer_holdout.py','evaluations/production_contract_pilot.py','evaluations/frozen_release_validation.py',
           'evaluations/relation_pilot/oracle.py','docs/EDIT_TRANSFER_PROTOCOL_20261125.md']
    manifest={'scope':'New small internal generation/edit/reference holdout; not broad CAD success rate.',
              'cases':data,'ambiguous':AMBIGUOUS,'source_files':frozen['source_files'],'frozen_source':str(FREEZE),'staged_files':staged,
              'hashes':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}}
    base.dump(output/'edit-manifest.json',manifest)
    sys.path.insert(0,str(ROOT/'tests/manual'))
    from eval_budget_store import BudgetLedger
    os.environ.update(P12_MAX_REQUESTS='96',P12_MAX_INPUT_TOKENS='2000000',P12_MAX_OUTPUT_TOKENS='240000',P12_MAX_COST_USD='1')
    ledger=BudgetLedger(output/'budget.json');base.oracle=holdout_oracle;rows=[]
    print('EDIT OUTPUT '+str(output),flush=True)
    for repeat in (1,2):
        for case,message,expected in data:
            result=base.run_trial(output,{'case':case['id'],'repeat':repeat,'arm':'B'},case)
            row={'trial':result['trial'],'base':result,'edit_passed':False,'ambiguity_passed':False,'blocked':not result['passed']}
            folder=output/result['trial'];store=folder/'projects.json'
            read=lambda:json.loads(store.read_text(encoding='utf-8'))['projects']
            if result['passed']:
                from app.cad_candidate_state import candidate_is_accepted
                projects=read();project=next(p for p in projects if any(candidate_is_accepted(v) for v in p['variants']))
                parent=next(v for v in reversed(project['variants']) if candidate_is_accepted(v))
                parent_before=deepcopy(parent);before=deepcopy(project['variants']);prompt_before=project['original_prompt']
                worker_env,_=isolated_environment('edit-transfer-worker',True)
                worker_env.update(PYTHONPATH=str(output/'versions/B'),P12_EVAL_MODE='1',P12_EVAL_RUN_ID=output.parent.name,
                    P12_EVAL_BUDGET_PATH=str(output/'budget.json'),XLINE_KNOWLEDGE_ROOTS=str(folder/'empty-knowledge'),
                    XLINE_CONSTRAINT_BACKEND_AUTO='builtin',PYTHONDONTWRITEBYTECODE='1')
                def call(text):
                    step=max(int(f.stem.split('-')[-1]) for f in folder.glob('step-*.json'))+1
                    body={'message':text,'mode':'advanced','conversation_id':result['trial'],
                          'project_id':project['id'],'variant_id':parent['id'],'history':[]}
                    completed=subprocess.run([sys.executable,str(output/'versions/B/tests/manual/cad_widget_live_worker.py'),'--output',str(folder)],
                        input=json.dumps({'case_id':result['trial'],'operation':'chat','step':step,'body':body}),
                        text=True,encoding='utf-8',capture_output=True,env=worker_env,cwd=output/'versions/B',timeout=360)
                    (folder/f'worker-{step}.stderr.txt').write_text(completed.stderr,encoding='utf-8')
                    if completed.returncode:raise RuntimeError(completed.stderr[-1000:])
                    return json.loads(completed.stdout)
                try:
                    ambiguous=call(AMBIGUOUS);after=next(p for p in read() if p['id']==project['id'])
                    unchanged=after['variants']==before and after['original_prompt']==prompt_before
                    signal=bool(ambiguous.get('clarification')) or any(t in str(ambiguous.get('message','')) for t in ('哪个','选择','明确','多个','请指定'))
                    row['ambiguity']={'response':ambiguous,'unchanged':unchanged,'clarification_signal':signal}
                    row['ambiguity_passed']=unchanged and signal and not ambiguous.get('variant')
                    response=call(message);after=next(p for p in read() if p['id']==project['id'])
                    candidate=response.get('variant') or {};saved=next((v for v in after['variants'] if v['id']==candidate.get('id')),None)
                    proof=holdout_oracle({'expected':expected},candidate.get('geometries') or []) if candidate else {'passed':False,'reason':'no_response_variant'}
                    retained=next(v for v in after['variants'] if v['id']==parent['id'])==parent_before
                    row['edit']={'response':response,'geometry':proof,'parent_unchanged':retained,'new_variant':bool(saved and saved['id']!=parent['id'])}
                    row['edit_passed']=bool(response.get('ok') and response.get('preview_paths') and saved and candidate==saved
                        and candidate_is_accepted(saved) and proof['passed'] and retained and saved['id']!=parent['id'])
                except Exception as exc:row['error']=str(exc)
            rows.append(row);base.dump(output/'edit-results.json',rows)
            print(json.dumps({k:v for k,v in row.items() if k in ['trial','edit_passed','ambiguity_passed','blocked','error']}),flush=True)
    assert base.tree_hashes(ROOT/'app')==frozen['source_files']==base.tree_hashes(FREEZE/'app')
    assert base.tree_hashes(output/'versions/B')==staged
    for n,h in manifest['hashes'].items():assert hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h
    book=ledger.snapshot();assert not book['pending'] and not book['stopped']
    req=[p for p in output.glob('E*/api-request-*.json')];rep=[p for p in output.glob('E*/api-response-*.json')]
    assert len(req)==len(rep)==book['used']['requests']
    assert all(json.loads(p.read_text(encoding='utf-8'))['model']=='deepseek-flash' for p in req)
    assert len({json.loads(p.read_text(encoding='utf-8'))['id'] for p in rep})==len(rep)
    summary={'trials':len(rows),'base_passed':sum(r['base']['passed'] for r in rows),'edit_passed':sum(r['edit_passed'] for r in rows),
        'ambiguity_passed':sum(r['ambiguity_passed'] for r in rows),'blocked':sum(r['blocked'] for r in rows),'source_unchanged':True,'usage':book['used']}
    base.dump(output/'edit-analysis.json',summary);print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
