"""Frozen corpus -> real provider via HTTP handler -> measured gates + UI fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import shutil
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app.cad_source_acceptance import verify_scoped_primitives
from tests.manual.cad_acceptance_metrics import summarize
from tests.manual.cad_harness_acceptance import (
    evaluate_edit_formal_delivery,
    evaluate_formal_delivery,
    evaluate_no_change_delivery,
)


def persisted_project(folder,project_id):
    path=Path(folder)/'projects.json'
    if not path.exists():return {}
    data=json.loads(path.read_text(encoding='utf-8'))
    return next((p for p in data.get('projects',[]) if str(p.get('id'))==str(project_id)),{})


def geometry_checks_passed(checks,variant):
    keys={'assembly_coverage','assembly_count','source_geometry','edit_ownership',
          'edit_exact_displacement','edit_whole_target'}
    observed=[checks[key] for key in keys if key in checks]
    return bool((variant or {}).get('geometries')) and (all(observed) if observed else True)



def verify_recording(case,folder):
    results=[json.loads((folder/f'step-{i}.json').read_text(encoding='utf-8')) for i in (1,2,3)]
    requests=[json.loads((folder/f'request-{i}.json').read_text(encoding='utf-8')) for i in (1,2,3)]
    variant=results[-1].get('variant') or {}
    checks={'candidate':results[-1].get('ok') is True and bool(variant),
            'first_turn_clarification':bool(results[0].get('clarification')),
            'same_project':len({r.get('project_id') for r in results})==1,
            'preview_count':len(results[-1].get('preview_paths') or [])==case['expected_preview_count']}
    objects=variant.get('logical_objects') or [];ledger=variant.get('requirement_ledger') or {}
    checks['frozen_input_matches']=[r.get('message') for r in requests]==case['messages']
    manifest=folder/'ui-fixture.json'
    checks['ui_fixture_matches']=manifest.exists() and json.loads(manifest.read_text(encoding='utf-8'))==case
    checks['source_text_matches']=[s.get('text') for s in ledger.get('sources') or []]==case['messages'][:2]
    checks['exact_geometry_count']=len(variant.get('geometries') or [])==case['expected_preview_count']
    checks['source_turns']=len(ledger.get('sources') or [])==2
    checks['source_separation']=all(s.get('origin')=='user' for s in ledger.get('sources') or [])
    checks['assembly_coverage']=bool(objects) and all(o.get('assembly_id') and o.get('assembly_label') for o in objects)
    checks['assembly_count']=len({o.get('assembly_id') for o in objects})==case['expected_assemblies']
    checks['export_ownership']=(results[-1].get('drawing_json') or {}).get('logical_objects')==objects
    try:checks['source_geometry']=len(verify_scoped_primitives(case['messages'][1],variant.get('geometries') or [],objects)['checks'])==case['expected_preview_count']
    except ValueError:checks['source_geometry']=False
    if case.get('test_modify'):
        response=json.loads((folder/'step-4.json').read_text(encoding='utf-8'))
        if response.get('pending_action'):
            pending_id=response['pending_action']['id']
            response=json.loads((folder/'step-5.json').read_text(encoding='utf-8'))
            approval=json.loads((folder/'request-5.json').read_text(encoding='utf-8'))
            checks['explicit_edit_confirmation']=response.get('ok') is True and approval.get('approved') is True and approval.get('action_id')==pending_id
        revised=response.get('variant') or {}
        checks['edit_saved']=response.get('ok') is True and bool(revised) and revised.get('id')!=variant.get('id')
        checks['edit_preview_records']=bool(response.get('preview_paths')) and all(isinstance(p,dict) and p.get('geometry_id') for p in response.get('preview_paths',[]))
        ownership=lambda os:[(o['object_id'],o.get('assembly_id'),o['geometry_refs']) for o in os]
        checks['edit_ownership']=ownership(objects)==ownership(revised.get('logical_objects') or [])
        revised_ledger=revised.get('requirement_ledger') or {}
        checks['edit_source_preserved']=len(revised_ledger.get('sources') or [])==3
        checks['old_acceptance_not_reused']=revised_ledger.get('geometry_acceptance',{}).get('status')=='not_checked'
        def coords(g):return [g[k] for k in ('center','start','end') if k in g]+list(g.get('vertices') or [])
        edit_request=json.loads((folder/'request-4.json').read_text(encoding='utf-8'))
        selection=edit_request['drawing_selection']
        selected=selection['geometry_ids']
        expected_ids={gid for o in objects if o.get('assembly_id')==objects[0].get('assembly_id') for gid in o['geometry_refs']} if objects else set()
        checks['edit_whole_target']=set(selected)==expected_ids and selection.get('variant_id')==variant.get('id') and selection.get('project_id')==results[-1].get('project_id')
        actual={g['id']:g for g in revised.get('geometries') or []}
        checks['edit_exact_displacement']=checks['edit_saved'] and all(g['id'] in actual and len(coords(g))==len(coords(actual[g['id']])) and all(
            abs(b['x']-a['x']-(1000 if g['id'] in selected else 0))<.1 and abs(b['y']-a['y'])<.1
            for a,b in zip(coords(g),coords(actual[g['id']]))) for g in variant.get('geometries') or [])
    final_response=results[-1];final_variant=variant
    if case.get('test_modify'):
        final_response=response;final_variant=revised
    project=persisted_project(folder,results[-1].get('project_id'))
    base=variant
    flags={'geometry_checks':geometry_checks_passed(checks,final_variant)}
    if final_response.get('cad_edit_outcome')=='already_satisfied':
        checks.pop('edit_saved',None);checks.pop('edit_preview_records',None)
        formal=evaluate_no_change_delivery(final_response,base_variant=base,
            persisted_project=project,expected_project_id=results[-1].get('project_id'))
        checks['no_change_verified']=formal['formal_delivery_ok'] is True
    elif case.get('test_modify'):
        formal=evaluate_edit_formal_delivery(final_response,base_variant=base,project=project,
            persisted_project=project,expected_project_id=results[-1].get('project_id'),
            expected_variant_id=final_variant.get('id'),geometry_checks=flags['geometry_checks'])
    else:
        formal=evaluate_formal_delivery(final_response,project=project,persisted_project=project,
            expected_project_id=results[-1].get('project_id'),
            expected_variant_id=final_variant.get('id'),geometry_checks=flags['geometry_checks'])
    checks['formal_delivery']=formal['formal_delivery_ok'] is True
    legacy_checks={key:value for key,value in checks.items()
                   if key not in {'formal_delivery','no_change_verified'}}
    report={'case':case['id'],'passed':all(checks.values()),
        'legacy_passed':all(legacy_checks.values()),'checks':checks,'frontend':'not_run',
        'generation_ok':formal['generation_ok'],'geometry_ok':formal['geometry_ok'],
        'formal_evaluable':formal['formal_evaluable'],
        'formal_delivery_ok':formal['formal_delivery_ok'],
        'diagnostic_status':formal['diagnostic_status'],
        'formal_reason':formal['formal_reason'],'formal_evidence':formal['evidence']}
    (folder/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def run(case,root):
    folder=root/case['id'];folder.mkdir(parents=True,exist_ok=True)
    history=[];project_id=None;results=[]
    for step,message in enumerate(case['messages'],1):
        started=time.monotonic()
        body={'message':message,'mode':'advanced','conversation_id':'product-'+case['id'],'history':history}
        if project_id:body['project_id']=project_id
        process=subprocess.run([sys.executable,str(Path(__file__).with_name('cad_widget_live_worker.py')),'--output',str(folder)],
            input=json.dumps({'operation':'chat','step':step,'body':body},ensure_ascii=False),text=True,encoding='utf-8',capture_output=True,timeout=480)
        if process.returncode:raise RuntimeError(process.stderr[-2000:])
        (folder/f'timing-{step}.json').write_text(json.dumps({'elapsed_seconds':time.monotonic()-started}),encoding='utf-8')
        result=json.loads(process.stdout);results.append(result)
        project_id=result.get('project_id') or (result.get('project') or {}).get('id') or project_id
        history.extend([{'role':'user','content':message},{'role':'assistant','content':result.get('message','')}])
        print(json.dumps({'case':case['id'],'turn':step,'ok':result.get('ok'),'message':result.get('message')},ensure_ascii=False),flush=True)
    (folder/'ui-fixture.json').write_text(json.dumps(case,ensure_ascii=False,indent=2),encoding='utf-8')
    project=next(p for p in json.loads((folder/'projects.json').read_text(encoding='utf-8'))['projects'] if p['id']==project_id)
    variants=project.get('variants') or [];checks={}
    final_response=results[-1];final_variant=variants[-1] if variants else {}
    checks['same_project']=len({r.get('project_id') for r in results})==1
    checks['preview_count']=len(results[-1].get('preview_paths') or [])==case['expected_preview_count']
    checks['candidate']=bool(variants) and results[-1].get('ok') is True
    checks['first_turn_clarification']=bool(results[0].get('clarification')) and not bool(results[0].get('preview_paths'))
    if variants:
        variant=variants[-1];objects=variant.get('logical_objects') or []
        checks['assembly_coverage']=bool(objects) and all(o.get('assembly_id') and o.get('assembly_label') for o in objects)
        checks['assembly_count']=len({o.get('assembly_id') for o in objects})==case['expected_assemblies']
        ledger=variant['construction_record'].get('requirement_ledger') or {}
        checks['source_turns']=len(ledger.get('sources') or [])==2
        checks['source_separation']=all(s.get('origin')=='user' for s in ledger.get('sources') or [])
        checks['export_ownership']=(results[-1].get('drawing_json') or {}).get('logical_objects')==objects
        try:
            acceptance=verify_scoped_primitives(case['messages'][1],variant['geometries'])
            checks['source_geometry']=len(acceptance['checks'])==case['expected_preview_count']
        except ValueError:checks['source_geometry']=False
        if case.get('test_modify') and checks['assembly_coverage']:
            assembly=objects[0]['assembly_id']
            ids=sorted({gid for o in objects if o['assembly_id']==assembly for gid in o['geometry_refs']})
            body={'message':'将选中的图形向右移动1米','mode':'advanced','conversation_id':'product-'+case['id'],
                  'project_id':project_id,'history':history,'drawing_selection':{'scope':'group','geometry_ids':ids,'project_id':project_id,'variant_id':variant['id']}}
            process=subprocess.run([sys.executable,str(Path(__file__).with_name('cad_widget_live_worker.py')),'--output',str(folder)],
                input=json.dumps({'operation':'chat','step':4,'body':body},ensure_ascii=False),text=True,encoding='utf-8',capture_output=True,timeout=240)
            if process.returncode:raise RuntimeError(process.stderr[-2000:])
            edit=json.loads(process.stdout);revised=edit.get('variant') or {}
            if edit.get('pending_action'):
                approval={'action_id':edit['pending_action']['id'],'approved':True}
                process=subprocess.run([sys.executable,str(Path(__file__).with_name('cad_widget_live_worker.py')),'--output',str(folder)],
                    input=json.dumps({'operation':'confirm','step':5,'body':approval}),text=True,encoding='utf-8',capture_output=True,timeout=240)
                if process.returncode:raise RuntimeError(process.stderr[-2000:])
                edit=json.loads(process.stdout);revised=edit.get('variant') or {}
                checks['explicit_edit_confirmation']=edit.get('ok') is True
            final_response=edit;final_variant=revised
            checks['edit_saved']=edit.get('ok') is True and revised.get('id')!=variant['id'] and bool(revised.get('geometries'))
            checks['edit_ownership']=revised.get('logical_objects')==variant.get('logical_objects') or (
                [(o['object_id'],o.get('assembly_id'),o['geometry_refs']) for o in revised.get('logical_objects',[])]==
                [(o['object_id'],o.get('assembly_id'),o['geometry_refs']) for o in objects])
            checks['edit_source_preserved']=len((revised.get('requirement_ledger') or {}).get('sources',[]))==3
            checks['old_acceptance_not_reused']=(revised.get('requirement_ledger') or {}).get('geometry_acceptance',{}).get('status')=='not_checked'
            # Independent coordinate oracle: translate selected members only.
            def coords(g):
                return [g[k] for k in ('center','start','end') if k in g]+list(g.get('vertices') or [])
            actual={g['id']:g for g in revised.get('geometries',[])}
            checks['edit_exact_displacement']=checks['edit_saved'] and all(
                g['id'] in actual and len(coords(g))==len(coords(actual[g['id']])) and all(
                    abs(b['x']-a['x']-(1000 if g['id'] in ids else 0))<.1 and abs(b['y']-a['y'])<.1
                    for a,b in zip(coords(g),coords(actual[g['id']]))) for g in variant['geometries'])
    persisted=persisted_project(folder,project_id)
    base=variants[0] if variants else {}
    geometry_ok=geometry_checks_passed(checks,final_variant)
    if final_response.get('cad_edit_outcome')=='already_satisfied':
        checks.pop('edit_saved',None);checks.pop('edit_preview_records',None)
        formal=evaluate_no_change_delivery(final_response,base_variant=base,
            persisted_project=persisted,expected_project_id=project_id)
        checks['no_change_verified']=formal['formal_delivery_ok'] is True
    elif case.get('test_modify'):
        formal=evaluate_edit_formal_delivery(final_response,base_variant=base,project=persisted,
            persisted_project=persisted,expected_project_id=project_id,
            expected_variant_id=final_variant.get('id'),geometry_checks=geometry_ok)
    else:
        formal=evaluate_formal_delivery(final_response,project=persisted,persisted_project=persisted,
            expected_project_id=project_id,expected_variant_id=final_variant.get('id'),
            geometry_checks=geometry_ok)
    checks['formal_delivery']=formal['formal_delivery_ok'] is True
    legacy_checks={key:value for key,value in checks.items()
                   if key not in {'formal_delivery','no_change_verified'}}
    report={'case':case['id'],'passed':all(checks.values()),
        'legacy_passed':all(legacy_checks.values()),'checks':checks,'frontend':'not_run',
        'generation_ok':formal['generation_ok'],'geometry_ok':formal['geometry_ok'],
        'formal_evaluable':formal['formal_evaluable'],
        'formal_delivery_ok':formal['formal_delivery_ok'],
        'diagnostic_status':formal['diagnostic_status'],
        'formal_reason':formal['formal_reason'],'formal_evidence':formal['evidence']}
    (folder/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--cases',nargs='*')
    parser.add_argument('--verify-only',action='store_true')
    parser.add_argument('--repeat',type=int,default=1,help='Repeat real-model corpus in isolated directories')
    parser.add_argument('--app',action='store_true',help='Replay real recorded responses through production App widgets')
    parser.add_argument('--live-app',action='store_true',help='Use another real DeepSeek run from the App instead of replay')
    parser.add_argument('--flutter',default=shutil.which('flutter') or 'D:/flutter/bin/flutter.bat')
    args=parser.parse_args();corpus=Path(__file__).resolve().parents[2]/'evaluations/cad_product_acceptance_v1.json'
    if args.repeat<1:parser.error('--repeat must be positive')
    if args.live_app and not args.app:parser.error('--live-app requires --app')
    if args.repeat>1:
        statuses=[]
        for index in range(args.repeat):
            command=[sys.executable,__file__,'--output',str(Path(args.output)/f'round-{index+1}'),'--flutter',args.flutter]
            if args.cases:command+=['--cases',*args.cases]
            for flag,enabled in [('--verify-only',args.verify_only),('--app',args.app),('--live-app',args.live_app)]:
                if enabled:command.append(flag)
            statuses.append(subprocess.run(command).returncode)
        sys.exit(0 if not any(statuses) else 1)
    raw=corpus.read_bytes();cases=json.loads(raw)['cases'];root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=True)
    selected=[c for c in cases if not args.cases or c['id'] in args.cases]
    reports=[]
    for case in selected:
        try:
            if not args.verify_only:run(case,root)
            report=verify_recording(case,root/case['id'])
        except Exception as exc:
            folder=root/case['id'];folder.mkdir(parents=True,exist_ok=True)
            report={'case':case['id'],'passed':False,'checks':{},'frontend':'not_run','runner_error':str(exc)}
        if args.app and report['passed']:
            command=[args.flutter,'test','test/live_cad_preview_test.dart',
                '--dart-define=CAD_LIVE_FIXTURE_DIR='+str(root/case['id']),'--reporter','expanded']
            if args.live_app:
                command += ['--dart-define=CAD_REAL_MODEL_WORKER='+str(Path(__file__).with_name('cad_widget_live_worker.py')),
                    '--dart-define=CAD_REAL_MODEL_OUTPUT='+str(root/('app-live-'+case['id']))]
            process=subprocess.run(command,cwd=Path(__file__).resolve().parents[3]/'xikao1_-app',capture_output=True,text=True,encoding='utf-8',timeout=540)
            (root/case['id']/'app-test.log').write_text(process.stdout+process.stderr,encoding='utf-8')
            report['frontend']='live_passed' if args.live_app and process.returncode==0 else 'replay_passed' if process.returncode==0 else 'failed'
            report['passed']=report['passed'] and process.returncode==0
            if process.returncode!=0:
                report['formal_delivery_ok']=False
                report['diagnostic_status']='frontend_failed'
                report['formal_reason']=[*(report.get('formal_reason') or []),'frontend_failed']
        reports.append(report)
        (root/case['id']/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False),flush=True)
    (root/'summary.json').write_text(json.dumps({'corpus_sha256':hashlib.sha256(raw).hexdigest(),'reports':reports,'all_passed':all(r['passed'] for r in reports)},ensure_ascii=False,indent=2),encoding='utf-8')
    (root/'metrics.json').write_text(json.dumps(summarize(root,reports),ensure_ascii=False,indent=2),encoding='utf-8')
    sys.exit(0 if reports and all(r['passed'] for r in reports) else 1)
