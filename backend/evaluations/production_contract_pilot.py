"""Frozen full-handler paired live test; never injects construction plans."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
import zipfile

from scripts.local_dev import ROOT, isolated_environment

CONFIRM = '确认需求并生成CAD候选，只预览，不执行小车。'
REPEATS = 3


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def cases():
    return [
        {'id':'H1','family':'semicircle_walls','unit':'米','origin':[0,0],'width':2.6,'height':3.7,'angle':0,
         'text':'生成一个闭合拱门轮廓，总宽2.6米、总高3.7米。底边左端(0,0)，底边水平；两侧直墙等高且竖直，顶部为上半圆，直径等于总宽，总高包含半圆。只画外边界，坐标单位米。'},
        {'id':'H2','family':'semicircle_walls','unit':'厘米','origin':[-50,25],'width':230,'height':315,'angle':0,
         'text':'画闭合拱门的外轮廓：底边从(-50,25)水平向右，总宽230厘米，总高315厘米；两侧是等高竖直墙，顶部为连接两墙的上半圆，半圆直径230厘米，高度已包含在总高中。不画内部线，坐标单位厘米。'},
        {'id':'R1','family':'capsule_tangency','unit':'米','origin':[0,0],'length':5.2,'height':1.6,'angle':0,
         'text':'画一个水平胶囊形闭合外轮廓，中心(0,0)，总长5.2米，总高1.6米。左右两端是半径相等的向外半圆，上下两条直边平行并与半圆相切，总长包含两端半圆。不画整圆和内部线，坐标单位米。'},
        {'id':'R2','family':'capsule_tangency','unit':'毫米','origin':[210,-370],'length':3470,'height':930,'angle':17,
         'text':'绘制胶囊形闭合边界，中心位于(210,-370)，长轴相对x轴正向逆时针17度，沿长轴总长3470毫米、短轴总高930毫米。两端各为向外半圆，两条直边与半圆相切；两端半径相同，总长含半圆。不添加内部线，坐标单位毫米。'},
        {'id':'P1','family':'relative_turn_polyline','unit':'米','origin':[.4,-.8],'a':1.9,'b':1.3,'angle':31,'turn':-74,
         'text':'只画两段首尾相接的开放折线。起点(0.4,-0.8)，第一段长1.9米，与x轴正向夹角31度；第二段从第一段末点出发，长1.3米，在第一段方向基础上顺时针转74度。不闭合，不加标注，坐标单位米。'},
        {'id':'P2','family':'relative_turn_polyline','unit':'毫米','origin':[-330,270],'a':2140,'b':860,'angle':-23,'turn':102,
         'text':'绘制两段相接的开放折线，起点(-330,270)。第一段长度2140毫米，相对x轴正向为-23度；第二段从前一段终点开始，长度860毫米，方向再相对第一段逆时针转102度。不要闭合或增加其他图形，坐标单位毫米。'},
        {'id':'Q1','family':'rectangle_control','unit':'米','origin':[1.2,-.7],'width':3.6,'height':2.4,
         'text':'画一个矩形，左下角(1.2,-0.7)，宽3.6米、高2.4米，边平行于坐标轴。只画矩形轮廓，坐标单位米。'},
        {'id':'Q2','family':'circle_control','unit':'米','origin':[-.8,1.1],'radius':.65,
         'text':'画一个圆，圆心(-0.8,1.1)，半径0.65米，只画这一个圆，坐标单位米。'},
    ]


def oracle(row, geometries):
    from evaluations.relation_pilot.oracle import evaluate, boundary
    actual_length_sum=sum(boundary([g]).length for g in geometries)
    actual_union_length=boundary(geometries).length
    if actual_length_sum-actual_union_length>.5:
        return {'passed':False,'reason':'duplicate_or_overlapping_boundary','excess_length_mm':actual_length_sum-actual_union_length}
    if not row['family'].endswith('_control'):
        return evaluate(row, geometries)
    if row['family']=='circle_control':
        expected=[{'type':'circle','center':{'x':row['origin'][0]*1000,'y':row['origin'][1]*1000},'radius':row['radius']*1000}]
    else:
        x,y=[v*1000 for v in row['origin']];w=row['width']*1000;h=row['height']*1000
        expected=[{'type':'polyline','closed':True,'vertices':[{'x':a,'y':b} for a,b in [(x,y),(x+w,y),(x+w,y+h),(x,y+h)]]}]
    target=boundary(expected);actual=boundary(geometries)
    missing=not target.difference(actual.buffer(.45,quad_segs=32)).is_empty
    extra=not actual.difference(target.buffer(.45,quad_segs=32)).is_empty
    return {'passed':not missing and not extra,'target_outside_candidate_tolerance':missing,
            'candidate_outside_target_tolerance':extra,'sampled_limit_mm':.45,'boundary_hausdorff_mm':target.hausdorff_distance(actual)}


def tree_hashes(folder):
    return {p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}


def prepare(state):
    output=state/'run';output.mkdir()
    baseline=ROOT/'.local-dev/relation-pilot-cki0mytw/run/source.zip'
    original_worker=(ROOT/'tests/manual/cad_widget_live_worker.py').read_text(encoding='utf-8')
    # Instrument the shared bridge, not production code. Same bridge in A/B.
    worker=original_worker.replace("request_id=str(uuid.uuid4()); max_tokens=", """calls=list(root.glob('api-request-*.json'))
            if len(calls)>=12:raise RuntimeError('trial_request_budget_exhausted')
            request_id=str(uuid.uuid4()); max_tokens=""")
    worker=worker.replace("started=__import__('time').time()", """(root/f'api-request-{request_id}.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
            started=__import__('time').time()""")
    worker=worker.replace("budget.settle(response=response,http_status=200)", """budget.settle(response=response,http_status=200)
                (root/f'api-response-{request_id}.json').write_text(json.dumps(response,ensure_ascii=False,indent=2),encoding='utf-8')""")
    if worker==original_worker or 'api-response-' not in worker:raise ValueError('instrumentation failed')
    worker=worker.replace('patch("app.agent_service.conversation_memory",memory)):',
                          'patch("app.agent_service.conversation_memory",memory),patch("app.routers.agent.robot_agent",service)):')
    if 'patch("app.routers.agent.robot_agent",service)' not in worker:raise ValueError('confirmation service binding failed')
    for arm in ('A','B'):
        stage=output/'versions'/arm
        shutil.copytree(ROOT/'app',stage/'app',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        if arm=='A':
            with zipfile.ZipFile(baseline) as z:
                for name in z.namelist():
                    if name.startswith('app/'):
                        p=stage/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(name))
        folder=stage/'tests/manual';folder.mkdir(parents=True)
        (folder/'cad_widget_live_worker.py').write_text(worker,encoding='utf-8')
        shutil.copy2(ROOT/'tests/manual/eval_budget_store.py',folder/'eval_budget_store.py')
    rows=cases();schedule=[];rng=random.Random(230619)
    for repeat in range(1,REPEATS+1):
        shuffled=rows.copy();rng.shuffle(shuffled)
        for pos,row in enumerate(shuffled):
            for arm in (['A','B'] if (pos+repeat)%2 else ['B','A']):schedule.append({'case':row['id'],'repeat':repeat,'arm':arm})
    manifest={'schema':'cad.full-production-contract-pilot.v1','created_utc':datetime.now(timezone.utc).isoformat(),
        'cases':rows,'schedule':schedule,'model':'deepseek-flash','repeats':REPEATS,
        'versions':{a:tree_hashes(output/'versions'/a) for a in ('A','B')},
        'baseline_archive_sha256':hashlib.sha256(baseline.read_bytes()).hexdigest(),
        'protocol_sha256':hashlib.sha256((ROOT/'docs/FULL_PRODUCTION_CONTRACT_PILOT_PROTOCOL_20261123.md').read_bytes()).hexdigest(),
        'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'reporter_sha256':hashlib.sha256((ROOT/'evaluations/report_production_contract_pilot.py').read_bytes()).hexdigest(),
        'offline_test_sha256':hashlib.sha256((ROOT/'tests/test_production_contract_pilot.py').read_bytes()).hexdigest(),
        'oracle_source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['evaluations/relation_pilot/oracle.py','evaluations/relation_pilot/cases.py']},
        'per_trial':{'chat_turns':2,'messages':['original_case_text',CONFIRM],'requests':12},
        'scope':'Real HTTP chat-stream and confirmation handlers, project persistence, preview, independent geometry and formal acceptance; virtual hardware; no UI rendering',
        'limits':{'requests':576,'input_tokens':10000000,'output_tokens':1500000,'estimated_usd':4},
        'limitations':['8 developer-visible chosen cases: three challenge families and two basic controls; not blind or representative of arbitrary CAD',
                      'generation only; edits not evaluated','provider defaults/version not frozen','common empty external knowledge and isolated stores']}
    dump(output/'manifest.json',manifest)
    return output


def run_trial(output, entry, row):
    trial=f"{entry['case']}-r{entry['repeat']}-{entry['arm']}";folder=output/trial;folder.mkdir()
    env,_=isolated_environment('production-contract-worker',True)
    env.update(P12_EVAL_MODE='1',P12_EVAL_RUN_ID=output.parent.name,P12_EVAL_BUDGET_PATH=str(output/'budget.json'),
        P12_MAX_REQUESTS='576',P12_MAX_INPUT_TOKENS='10000000',P12_MAX_OUTPUT_TOKENS='1500000',P12_MAX_COST_USD='4',
        DEEPSEEK_ADVANCED_MAX_TOKENS='2400',DEEPSEEK_BASE_MAX_TOKENS='900',XLINE_AGENT_REVIEW_MAX_TOKENS='700',
        XLINE_AGENT_CONSTRUCTION_MAX_TOKENS='8192',PYTHONDONTWRITEBYTECODE='1',
        XLINE_KNOWLEDGE_ROOTS=str(folder/'empty-knowledge'),XLINE_CONSTRAINT_BACKEND_AUTO='builtin')
    env.pop('P12_EVAL_MOCK_PROVIDER',None)
    stage=output/'versions'/entry['arm'];env['PYTHONPATH']=str(stage)
    history=[];project_id=None;turns=[];error=None;started=time.perf_counter()
    worker=stage/'tests/manual/cad_widget_live_worker.py'
    def call(body, operation='chat'):
        step=len(turns)+1
        request={'case_id':trial,'operation':operation,'step':step,'body':body}
        completed=subprocess.run([sys.executable,str(worker),'--output',str(folder)],input=json.dumps(request,ensure_ascii=False),
            text=True,encoding='utf-8',capture_output=True,env=env,cwd=stage,timeout=360)
        (folder/f'worker-{step}.stderr.txt').write_text(completed.stderr,encoding='utf-8')
        if completed.returncode:raise RuntimeError(completed.stderr[-1800:])
        response=json.loads(completed.stdout);turns.append(response)
        return response
    try:
        for message in (row['text']+'只生成预览，不执行小车。',CONFIRM):
            body={'message':message,'mode':'advanced','conversation_id':trial,'history':history}
            if project_id:body['project_id']=project_id
            response=call(body)
            new_id=response.get('project_id') or (response.get('project') or {}).get('id')
            if project_id and new_id and project_id!=new_id:raise RuntimeError('project_changed_across_turns')
            project_id=new_id or project_id
            history.extend([{'role':'user','content':message},{'role':'assistant','content':response.get('message','')}])
            if response.get('pending_action'):
                action=response['pending_action'];label=json.dumps(action,ensure_ascii=False).lower()
                if any(s in label for s in ('execute_mission','start_print','move_robot')):raise RuntimeError('non_preview_action_not_authorized')
                if not any(s in label for s in ('drawing','cad','candidate','preview','project')):raise RuntimeError('unknown_pending_action_not_confirmed')
                response=call({'action_id':action['id'],'approved':True},'confirm')
            if response.get('variant') and response.get('preview_paths'):break
    except Exception as exc:error=str(exc)
    stored=json.loads((folder/'projects.json').read_text(encoding='utf-8')) if (folder/'projects.json').exists() else {}
    variants=[v for p in stored.get('projects',[]) for v in p.get('variants',[])]
    from app.cad_candidate_state import candidate_is_accepted
    diagnostics=[]
    for variant in variants:
        try:proof=oracle(row,variant.get('geometries') or [])
        except Exception as exc:proof={'passed':False,'error':str(exc)}
        diagnostics.append({'id':variant.get('id'),'geometry':proof,'accepted':candidate_is_accepted(variant),
                            'acceptance_summary':variant.get('acceptance_summary')})
    deliveries=[]
    for index,response in enumerate(turns):
        variant=response.get('variant') or {};vid=variant.get('id')
        match=next((d for d in diagnostics if d['id']==vid),None)
        saved=next((v for v in variants if v.get('id')==vid),None)
        exact=bool(saved and variant.get('geometries')==saved.get('geometries'))
        if match and response.get('ok') and response.get('preview_paths') and exact and candidate_is_accepted(variant) and match['accepted'] and match['geometry']['passed']:
            deliveries.append(index+1)
    usage=[json.loads(s) for s in (folder/'model-usage.jsonl').read_text(encoding='utf-8').splitlines()] if (folder/'model-usage.jsonl').exists() else []
    result={**entry,'trial':trial,'passed':bool(deliveries) and not error,'first_turn_passed':1 in deliveries and not error,
        'geometry_any_stored':any(d['geometry']['passed'] for d in diagnostics),'saved_variants':diagnostics,
        'response_turns':len(turns),'last_message':(turns[-1] if turns else {}).get('message'),'error':error,
        'requests':len(usage),'usage':usage,'seconds':time.perf_counter()-started}
    result['failure_category']=('passed' if result['passed'] else 'runner_or_budget_error' if error else
        'geometry_correct_but_not_formally_delivered' if result['geometry_any_stored'] else
        'wrong_geometry_saved' if variants else 'no_saved_candidate')
    dump(folder/'result.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.output is None:
        from evaluations.run_live_user_corpus import load_key
        load_key();env,state=isolated_environment('full-production-pilot',True);output=prepare(state)
        print('FROZEN OUTPUT '+str(output),flush=True)
        return subprocess.call([sys.executable,'-m','evaluations.production_contract_pilot','--output',str(output)],env=env,cwd=ROOT)
    output=args.output.resolve();manifest=json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    rows={r['id']:r for r in manifest['cases']};results=[]
    for entry in manifest['schedule']:
        print('START '+json.dumps(entry),flush=True)
        result=run_trial(output,entry,rows[entry['case']]);results.append(result);dump(output/'results.json',results)
        print(json.dumps({k:result[k] for k in ('trial','passed','failure_category','requests')},ensure_ascii=False),flush=True)
        if (output/'budget.json').exists():
            budget=json.loads((output/'budget.json').read_text(encoding='utf-8'))
            if budget.get('stopped') or budget.get('pending'):raise RuntimeError('ledger stopped; remaining trials not executed')
    unchanged=all(tree_hashes(output/'versions'/a)==manifest['versions'][a] for a in ('A','B'))
    dump(output/'completed.json',{'trials':len(results),'frozen_versions_unchanged':unchanged,'finished_utc':datetime.now(timezone.utc).isoformat()})
    if not unchanged:raise RuntimeError('Frozen versions changed')
    return 0


if __name__=='__main__':raise SystemExit(main())
