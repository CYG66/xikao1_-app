"""New edit cases with independent explicit and ambiguous branches."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from scripts.local_dev import ROOT,isolated_environment
from evaluations import production_contract_pilot as base
from evaluations.frozen_release_validation import holdout_oracle
from evaluations.edit_acceptance_v2 import candidate_snapshot,assess_clarification

FREEZE=ROOT/'.local-dev/edit-transfer-new-freeze-ad8bu28q'
AMBIGUOUS='把圆的半径改为430毫米，其他图形不变。只生成预览，不执行小车。'


def cases():
    gold=[{'type':'circle','center':{'x':380,'y':1920},'radius':285},
          {'type':'circle','center':{'x':380,'y':-840},'radius':475},
          {'type':'polyline','closed':True,'vertices':[{'x':x,'y':y} for x,y in [(-1970,-220),(-1130,-220),(-1130,390),(-1970,390)]]}]
    source='在同一张图中画三个独立图形。上圆：圆，圆心(380,1920)，半径285毫米，坐标单位毫米；下圆：圆，圆心(380,-840)，半径475毫米，坐标单位毫米；左矩形：矩形，左下角(-1970,-220)，宽840毫米，高610毫米，坐标单位毫米。不要增加连接线或标注。'
    a=deepcopy(gold);a[0]['radius']=395
    other=[{'type':'circle','center':{'x':-1430,'y':-610},'radius':315},
           {'type':'circle','center':{'x':1860,'y':-610},'radius':590},
           {'type':'polyline','closed':True,'vertices':[{'x':x,'y':y} for x,y in [(-260,1370),(830,1370),(830,2140),(-260,2140)]]}]
    text='在同一张图中画三个独立图形。定位圆：圆，圆心(-1430,-610)，半径315毫米，坐标单位毫米；检测圆：圆，圆心(1860,-610)，半径590毫米，坐标单位毫米；支撑矩形：矩形，左下角(-260,1370)，宽1090毫米，高770毫米，坐标单位毫米。不要增加连接线或标注。'
    b=deepcopy(other)
    for v in b[2]['vertices']:v['x']-=170
    return [({'id':'F1','family':'explicit_geometry','text':source,'expected':gold},'将上圆的半径改为395毫米，圆心不动，其他图形保持不变。只生成预览，不执行小车。',a),
            ({'id':'F2','family':'explicit_geometry','text':text,'expected':other},'将支撑矩形整体向左移动170毫米，尺寸不变，其他图形保持不变。只生成预览，不执行小车。',b)]


def main():
    from evaluations.run_live_user_corpus import load_key
    load_key();env,state=isolated_environment('edit-transfer-v2-live',True)
    os.environ.update({k:v for k,v in env.items() if k!='PATH'})
    frozen=json.loads((FREEZE/'freeze.json').read_text(encoding='utf-8'));assert base.tree_hashes(ROOT/'app')==frozen['source_files']==base.tree_hashes(FREEZE/'app')
    output=base.prepare(state);stage=output/'versions/B';staged=base.tree_hashes(stage);data=cases()
    for c,_,gold in data:
        assert holdout_oracle(c,c['expected'])['passed']
        assert holdout_oracle({'expected':gold},gold)['passed']
        assert not holdout_oracle({'expected':gold},c['expected'])['passed']
    names=['evaluations/edit_transfer_holdout_v2.py','evaluations/edit_acceptance_v2.py','evaluations/production_contract_pilot.py',
           'evaluations/frozen_release_validation.py','evaluations/relation_pilot/oracle.py','docs/EDIT_HOLDOUT_V2_PROTOCOL_20261125.md']
    manifest={'scope':'New internal F1/F2 edit holdout, two independent branches; not broad CAD rate.',
        'cases':data,'ambiguous':AMBIGUOUS,'source_files':frozen['source_files'],'frozen_source':str(FREEZE),'staged_files':staged,
        'hashes':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names}}
    base.dump(output/'manifest.json',manifest)
    sys.path.insert(0,str(ROOT/'tests/manual'))
    from eval_budget_store import BudgetLedger
    os.environ.update(P12_MAX_REQUESTS='96',P12_MAX_INPUT_TOKENS='2000000',P12_MAX_OUTPUT_TOKENS='240000',P12_MAX_COST_USD='1')
    ledger=BudgetLedger(output/'budget.json');base.oracle=holdout_oracle;rows=[]
    print('V2 OUTPUT '+str(output),flush=True)
    for repeat in (1,2):
        for case,message,expected in data:
            generated=base.run_trial(output,{'case':case['id'],'repeat':repeat,'arm':'B'},case)
            folder=output/generated['trial'];row={'trial':generated['trial'],'base':generated,'edit_passed':False,'ambiguity_v2_passed':False,'blocked':not generated['passed']}
            if generated['passed']:
                from app.cad_candidate_state import candidate_is_accepted
                projects=json.loads((folder/'projects.json').read_text(encoding='utf-8'))['projects'];p=projects[0]
                parent=next(v for v in reversed(p['variants']) if candidate_is_accepted(v));snapshot=candidate_snapshot(projects)
                for branch,text in [('ambiguity',AMBIGUOUS),('edit',message)]:
                    dest=folder/branch;dest.mkdir();shutil.copy2(folder/'projects.json',dest/'projects.json')
                    if (folder/'cad').exists():shutil.copytree(folder/'cad',dest/'cad')
                    worker_env,_=isolated_environment('edit-v2-worker',True)
                    worker_env.update(PYTHONPATH=str(stage),P12_EVAL_MODE='1',P12_EVAL_RUN_ID=output.parent.name,
                        P12_EVAL_BUDGET_PATH=str(output/'budget.json'),XLINE_KNOWLEDGE_ROOTS=str(dest/'empty-knowledge'),
                        XLINE_CONSTRAINT_BACKEND_AUTO='builtin',PYTHONDONTWRITEBYTECODE='1')
                    body={'message':text,'mode':'advanced','conversation_id':generated['trial']+'-'+branch,'project_id':p['id'],'variant_id':parent['id'],'history':[]}
                    try:
                        proc=subprocess.run([sys.executable,str(stage/'tests/manual/cad_widget_live_worker.py'),'--output',str(dest)],
                            input=json.dumps({'case_id':generated['trial']+'-'+branch,'operation':'chat','step':1,'body':body}),
                            text=True,encoding='utf-8',capture_output=True,env=worker_env,cwd=stage,timeout=360)
                        (dest/'worker.stderr.txt').write_text(proc.stderr,encoding='utf-8')
                        if proc.returncode:raise RuntimeError(proc.stderr[-1000:])
                        response=json.loads(proc.stdout);after=json.loads((dest/'projects.json').read_text(encoding='utf-8'))['projects']
                        if branch=='ambiguity':
                            proof=assess_clarification(response,snapshot,candidate_snapshot(after));row['ambiguity_v2_passed']=proof['passed']
                            legacy=not response.get('variant') and bool(response.get('clarification') or any(t in str(response.get('message','')) for t in ('哪个','选择','明确','多个','请指定')))
                            row[branch]={'response':response,'proof':proof,'legacy_keyword_signal':legacy,'before':snapshot,'after':candidate_snapshot(after)}
                        else:
                            candidate=response.get('variant') or {};saved=next((v for pp in after for v in pp['variants'] if v['id']==candidate.get('id')),None)
                            retained=next(v for pp in after if pp['id']==p['id'] for v in pp['variants'] if v['id']==parent['id'])==parent
                            proof=holdout_oracle({'expected':expected},candidate['geometries']) if candidate else {'passed':False,'reason':'no_response_variant'}
                            passed=bool(response.get('ok') and response.get('preview_paths') and saved and candidate==saved and candidate_is_accepted(saved)
                                and proof['passed'] and retained and saved['id']!=parent['id'] and len(after)==len(projects))
                            row['edit_passed']=passed;row[branch]={'response':response,'proof':proof,'parent_unchanged':retained,'project_count':len(after)}
                    except Exception as exc:row[branch]={'error':str(exc)}
            rows.append(row);base.dump(output/'results.json',rows)
            print(json.dumps({k:row[k] for k in ['trial','blocked','edit_passed','ambiguity_v2_passed']}),flush=True)
    assert base.tree_hashes(ROOT/'app')==frozen['source_files']==base.tree_hashes(FREEZE/'app')
    assert base.tree_hashes(stage)==staged
    for n,h in manifest['hashes'].items():assert hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h
    book=ledger.snapshot();assert not book['pending'] and not book['stopped']
    summary={'trials':len(rows),'base_passed':sum(r['base']['passed'] for r in rows),'edit_passed':sum(r['edit_passed'] for r in rows),
        'ambiguity_v2_passed':sum(r['ambiguity_v2_passed'] for r in rows),'source_unchanged':True,'usage':book['used']}
    base.dump(output/'analysis.json',summary);print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
