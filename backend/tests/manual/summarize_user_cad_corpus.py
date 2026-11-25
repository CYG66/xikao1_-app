"""Reconcile raw corpus evidence, current independent oracles and App retests."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tests.manual.run_user_cad_corpus import create_checks,dump

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);args=parser.parse_args()
    root=Path(args.root).resolve();records=[]
    retests=json.loads((root/'app-harness-retests.json').read_text(encoding='utf-8'))['cases']
    manual_names={'heart_visual_semantics','template_semantics_review','independent_semantic_acceptance',
        'house_part_geometry_review','honeycomb_shared_edges_review','letter_stroke_review','projection_topology_review'}
    model_events=0
    for path in sorted(root.glob('*/corpus-report.json')):
        original=json.loads(path.read_text(encoding='utf-8'));case=original['case']
        record={**original,'app':retests.get(case,original.get('app'))}
        if original.get('kind')=='create':
            response=json.loads((path.parent/f"step-{original['candidate_step']}.json").read_text(encoding='utf-8'))
            try:record['checks']=create_checks(case,response,original['messages'])
            except Exception as exc:record['checks']=[{'name':'oracle_runtime','passed':False,'error':str(exc)}]
            record['parser']=((response.get('variant') or {}).get('construction_record') or {}).get('parser')
            record['passed']=all(c['passed'] for c in record['checks'])
        checks=record.get('checks') or []
        failed=[c['name'] for c in checks if not c['passed']]
        if record.get('blocked_by'):record['classification']='blocked_by_creation'
        elif record.get('kind')=='create' and not record.get('has_candidate'):record['classification']='no_candidate'
        elif record.get('kind')=='edit' and not any(c['name']=='new_saved_version' and c['passed'] for c in checks):record['classification']='no_saved_edit_or_clarification'
        elif any(n not in manual_names for n in failed):record['classification']='independent_geometry_check_failed'
        elif failed:record['classification']='requires_semantic_review'
        else:record['classification']='independent_checks_passed'
        record['failed_checks']=failed
        traces=path.parent/'model-responses.jsonl'
        events=[json.loads(line) for line in traces.read_text(encoding='utf-8').splitlines()] if traces.exists() else []
        if original.get('kind')=='edit' and not original.get('blocked_by'):
            manifest=json.loads((path.parent/'ui-fixture.json').read_text(encoding='utf-8'))
            events=[e for e in events if e.get('step',0)>=manifest['selection_before_step']]
        record['structured_model_response_events']=len(events);model_events+=len(events)
        records.append(record)
    creates=[r for r in records if r.get('kind')=='create']
    edits=[r for r in records if r.get('kind')=='edit']
    followups=json.loads((root.parent/(root.name+'-followups')/'summary.json').read_text(encoding='utf-8'))
    target=json.loads((root.parent/(root.name+'-targeted-delete')/'B16/corpus-report.json').read_text(encoding='utf-8'))
    target['app']='replay_passed'
    live={case:json.loads((root.parent/(root.name+'-app-live-'+case)/'acceptance.json').read_text(encoding='utf-8')) for case in ['B2','C6']}
    report={'schema':'cad.user-corpus-audit.v1','corpus':json.loads((root/'manifest.json').read_text(encoding='utf-8')),
        'counts':{'original_cases':len(records),'creation_cases':len(creates),'edit_cases':len(edits),
            'creations_with_saved_candidate':sum(r.get('has_candidate',False) for r in creates),
            'creation_independent_checks_passed':sum(r['passed'] for r in creates),
            'first_pass_saved_and_verified_edits':sum(r.get('passed',False) for r in edits),
            'edits_blocked_by_creation':sum(bool(r.get('blocked_by')) for r in edits),
            'app_response_replays_passed':sum(r.get('app')=='replay_passed' for r in records),
            'app_response_replays_failed':sum(r.get('app')=='failed' for r in records),
            'structured_model_response_events':model_events},
        'scope':{'provider':'real DeepSeek, production strategy selection; deterministic rule hits were not forced through the model',
            'app_replay':'production Flutter widget tree, local HTTP bridge, recorded real responses; edit selections delivered through production selection callback',
            'live_app':'B2 and C6 separately called the real worker/provider from the App; C6 failure retained',
            'device':'No Android tablet/emulator connected. Flutter devices listed Windows, Chrome and Edge only.',
            'hardware':'virtual; no robot execution','production_changes':'none in this testing turn',
            'oracle':'partial independent numeric/structural coverage; manual-review cases are not counted as passed'},
        'confirmed_findings':[
            {'cases':['A8'],'problem':'创建停车位被路由到修改入口，新会话无法生成。'},
            {'cases':['A11','C21','C27'],'problem':'分别将五角星画成圆、十字形画成矩形、立方体投影画成六边形，内容错误仍生成候选。'},
            {'cases':['A9','C2'],'problem':'A9缺少爱心上部凹口；C2闭合样条接缝转角约117.49度，不满足平滑闭合。'},
            {'cases':['C17'],'problem':'蜂窝六边形相互重叠，没有无缝拼接。'},
            {'cases':['C23'],'problem':'每级0.4米乘0.3米被缩成约0.08米乘0.06米，且输出闭合轮廓。'},
            {'cases':['C22'],'problem':'补充要求侧枝长度0.5米，但一条实际为1米，六重对称破坏。'},
            {'cases':['B1','B8','B10','B11','B12','B14','B15','B17','B19','D4'],'problem':'已有几何上下文未可靠用于复制、偏移、镜像、阵列等操作；出现重新索要尺寸、缺稳定实例编号、完整图形降级为线段等阻塞。'},
            {'cases':['B4','D6'],'problem':'原文已有角度，仍追问旋转角度。'},
            {'cases':['B6','B13','B18','D5'],'problem':'补充基点、基准和尺寸后仍未保存修改；D5被重新要求图形类型和关键尺寸。'},
            {'cases':['B4','B11','D6'],'problem':'修改未完成时execution_plan仍可能标为completed/verified；与业务完成状态不一致。'},
            {'cases':['C6'],'problem':'接口首轮曾成功，App直连复测却两次自交失败，模型计划稳定性未通过。'}],
        'reports':records,'followup_edits':followups,'targeted_delete_retest':target,'live_app_tests':live,
        'visual_evidence':[str(root/f'creation-gallery-{i}.png') for i in range(1,5)],
        'oracle_sha256':hashlib.sha256(Path(__file__).with_name('run_user_cad_corpus.py').read_bytes()).hexdigest()}
    dump(root/'acceptance-summary.json',report)
    print(json.dumps(report['counts'],ensure_ascii=False))
