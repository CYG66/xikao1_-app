"""Recorded provider failure -> real DeepSeek repair -> production commit.

The first construction response is explicitly replayed, not a new generation.
Only the repair response is live. Stores and hardware are isolated per run.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def recorded_response(folder,step=3,index=None):
    rows=[json.loads(line) for line in (folder/'model-responses.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    candidates=[]
    for row in rows:
        try:payload=json.loads(row.get('response',''))
        except (ValueError,TypeError):continue
        if (row.get('step')==step and isinstance(payload,dict)
                and payload.get('schema_version')=='cad.construction-interpretation.v1'
                and payload.get('plan') and (index is not None or 0<=payload.get('confidence',1)<.75)):candidates.append(payload)
    if index is not None:
        if not 1<=index<=len(candidates):raise ValueError('Recorded response index is out of range')
        return candidates[index-1]
    if len(candidates)!=1:raise ValueError('Expected exactly one recorded low-confidence construction response')
    return candidates[0]


def single(root,source,recorded_step=3,recorded_index=None,project_step=2):
    if (root/'repair-report.json').exists():raise ValueError('Use a fresh output directory to preserve previous evidence')
    root.mkdir(parents=True,exist_ok=True)
    os.environ.update(XLINE_RUNTIME_PROFILE='virtual_sim',XLINE_AGENT_PROVIDER='deepseek',
        XLINE_AGENT_TASK_STORE=str(root/'tasks.json'),XLINE_AGENT_AUDIT_STORE=str(root/'audit.jsonl'),
        XLINE_AGENT_RUN_STORE=str(root/'agent-runs.json'),XLINE_AGENT_PLAN_STORE=str(root/'agent-plans.sqlite'),
        XLINE_CAD_DIR=str(root/'cad'),XLINE_DATABASE_PATH=str(root/'test.db'))
    from app.agent_service import RobotAgentService
    from app.creative_projects import CreativeProjectStore
    from app.cad_construction import construction_geometry_bounds
    service=RobotAgentService(restore_pending_actions=False)
    if service.mode!='deepseek' or not service.configured:raise RuntimeError('Real DeepSeek must be configured')
    frozen=recorded_response(source,recorded_step,recorded_index)
    original=json.loads((source/f'step-{project_step}.json').read_text(encoding='utf-8-sig'))['project']
    store=CreativeProjectStore(root/'projects.json')
    project=store.create(original['name'],original['original_prompt'],
        requirements=deepcopy(original['requirements']),constraints=deepcopy(original.get('constraints') or {}),missing_parameters=[])
    dump(root/'frozen-response.json',frozen)
    dump(root/'project-before.json',project)
    original_factory=service._cad_construction_model_callback
    original_review=service._structured_review_text
    calls=[];live_responses=[]
    def observe(*args,**kwargs):
        response=original_review(*args,**kwargs)
        live_responses.append(response)
        with (root/'live-model-responses.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'origin':'live_deepseek_repair','response':response},ensure_ascii=False)+'\n')
        return response
    service._structured_review_text=observe
    def factory(**kwargs):
        callback,state=original_factory(**kwargs)
        if callback is None:raise RuntimeError('No live construction callback configured')
        def wrapped(text,schema):
            origin='recorded_previous_response' if not calls else 'live_deepseek_repair'
            calls.append(origin)
            if len(calls)>2:raise AssertionError('Exceeded one construction repair')
            dump(root/f'construction-input-{len(calls)}.json',{'origin':origin,'text':text})
            if origin=='recorded_previous_response':
                # Simulate the historical provider event so production recovery
                # owns the failure; no HTTP request is counted for this replay.
                state['provider_attempted']=True
                return deepcopy(frozen)
            if '后端试算反馈：' not in text:raise AssertionError('Repair must receive backend diagnostics')
            return callback(text,schema)
        return wrapped,state
    from app.structured_usage import structured_usage_scope, merge_structured_usage
    with structured_usage_scope(),patch('app.agent_service.get_creative_project_store',return_value=store),patch.object(service,'_cad_construction_model_callback',side_effect=factory):
        result=service.generate_project_candidate(project['id'])
        merge_structured_usage(result)
    dump(root/'step-1.json',{'type':'result',**result})
    dump(root/'ui-fixture.json',{'messages':['确认需求并生成CAD候选，只预览，不执行小车。'],'expected_assemblies':1})
    restored=CreativeProjectStore(root/'projects.json').get(project['id'])
    variant=result.get('variant') or {}
    recovery=(variant.get('construction_record') or {}).get('recovery') or (result.get('construction_interpretation') or {}).get('recovery') or {}
    checks={'same_project':result.get('project_id')==project['id'],
        'one_recorded_attempt_one_live_repair':calls==['recorded_previous_response','live_deepseek_repair'],
        'live_provider_response_received':bool(live_responses),
        'one_repair_recorded':recovery.get('repair_count')==1,
        'recorded_failure_not_accepted':bool(recovery.get('attempts')) and recovery['attempts'][0]['status']=='invalid',
        'candidate_saved':len(restored['variants'])==1 and bool(variant),
        'source_followups_preserved':restored['requirements'].get('source_followups')==original['requirements'].get('source_followups')}
    if frozen.get('confidence',1)<.75:
        checks['recorded_low_confidence_not_accepted']=checks['recorded_failure_not_accepted']
    measurements={}
    if variant:
        objects=variant['logical_objects'];bounds=construction_geometry_bounds(variant['geometries'])
        checks['unique_part_ids']=len({o['object_id'] for o in objects})==len(objects)
        checks['shared_whole']=len({o.get('assembly_id') for o in objects})==1 and all(o.get('assembly_id') for o in objects)
        checks['actual_2_by_3_m']=abs(bounds['max_x']-bounds['min_x']-2000)<=.5 and abs(bounds['max_y']-bounds['min_y']-3000)<=.5
        from shapely.geometry import LineString
        from shapely.ops import unary_union
        paths=[]
        for g in variant['geometries']:
            if g['type']=='line':points=[(g[k]['x'],g[k]['y']) for k in ('start','end')]
            elif g['type']=='polyline':
                points=[(p['x'],p['y']) for p in g['vertices']]
                if g.get('closed'):points.append(points[0])
            else:continue
            paths.append(LineString(points))
        expected=unary_union([LineString([(-1000,0),(0,3000),(1000,0)]),LineString([(-500,1500),(500,1500)])])
        actual=unary_union(paths)
        error=expected.hausdorff_distance(actual) if len(paths)==len(variant['geometries']) else None
        missing=expected.difference(actual.buffer(.5)).length if paths else expected.length
        extra=actual.difference(expected.buffer(.5)).length if paths else 0
        from app.cad_stroke_acceptance import stroke_requirements
        from app.cad_semantic_acceptance import verify_semantic_requirements
        source_text=original['original_prompt']+'\n'+'\n'.join(original['requirements'].get('source_followups') or [])
        if stroke_requirements(source_text):
            checks['source_stroke_coordinates']=error is not None and error<=.5 and missing<=.5 and extra<=.5
        else:
            semantic=verify_semantic_requirements(source_text,variant['geometries'])
            checks['source_semantic_structure']=bool(semantic.get('checks')) and not semantic.get('review_required')
        measurements=({'bounds_mm':bounds,'source_stroke_error_mm':error,'missing_length_mm':missing,'extra_length_mm':extra}
                      if stroke_requirements(source_text) else {'bounds_mm':bounds,'semantic_acceptance':semantic})
    report={'method':'recorded historical failure plus one live provider repair; not two fresh generations',
        'recorded_source':str(source),'recorded_response_sha256':hashlib.sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest(),
        'construction_attempt_origins':calls,'live_response_count':len(live_responses),
        'checks':checks,'passed':all(checks.values()),'measurements':measurements,
        'recovery':recovery,'reply':result.get('message'),'usage':result.get('usage'),
        'recorded_step':recorded_step,'recorded_index':recorded_index,'app_widget_replay':'not_run'}
    dump(root/'repair-report.json',report)
    print(json.dumps({'root':str(root),'passed':report['passed'],'checks':checks,'reply':result.get('message')},ensure_ascii=False),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--source',required=True)
    parser.add_argument('--runs',type=int,default=2);parser.add_argument('--single',action='store_true')
    parser.add_argument('--recorded-step',type=int,default=3);parser.add_argument('--recorded-index',type=int)
    parser.add_argument('--project-step',type=int,default=2);args=parser.parse_args()
    output=Path(args.output).resolve();source=Path(args.source).resolve()
    if not 1<=args.runs<=5:parser.error('--runs must be between 1 and 5')
    if args.single:single(output,source,args.recorded_step,args.recorded_index,args.project_step)
    else:
        output.mkdir(parents=True,exist_ok=True);reports=[]
        for n in range(1,args.runs+1):
            folder=output/f'run-{n}'
            command=[sys.executable,__file__,'--single','--source',str(source),'--output',str(folder),
                     '--recorded-step',str(args.recorded_step),'--project-step',str(args.project_step)]
            if args.recorded_index is not None:command+=['--recorded-index',str(args.recorded_index)]
            response=subprocess.run(command,
                text=True,encoding='utf-8',capture_output=True,timeout=360)
            print(response.stdout,flush=True)
            if response.returncode:raise RuntimeError(response.stderr[-2000:])
            reports.append(json.loads((folder/'repair-report.json').read_text(encoding='utf-8')))
        dump(output/'summary.json',{'method':'Recorded failure plus live repair; separate isolated process per run',
            'runs':reports,'passed':sum(r['passed'] for r in reports),'attempted':len(reports)})
