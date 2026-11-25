"""Six frozen production HTTP cases; real, logged, single-attempt provider transport."""
import argparse
from copy import deepcopy
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import urllib.request
from unittest.mock import patch
from deepseek_flash_budget import Budget, BudgetStop

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--preflight',type=Path,required=True)
    p.add_argument('--case', action='append', choices=['T1','T2','T3','T4','T5','T6'])
    p.add_argument('--offline-preflight',action='store_true')
    p.add_argument('--fixture-history',type=Path,default=Path(r'D:\xikao\.local-ai-test\c2-flash-controlled-20261106'))
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    approved=json.loads((args.preflight/'preflight.json').read_text(encoding='utf-8'))
    if approved['status']!='compatibility_probes_passed_formal_cases_not_started':raise RuntimeError('preflight_not_passed')
    budget=Budget();previous=approved['budget'];budget.calls=previous['requests'];budget.input=previous['input_tokens'];budget.output=previous['output_tokens'];budget.cost=Decimal(previous['peak_rate_cost_upper_usd'])
    key='offline-preflight-no-network' if args.offline_preflight else os.getenv('DEEPSEEK_API_KEY')
    if not key:
        path=ROOT/'.local-ai-test/deepseek-api-key.clixml'
        command="$s=Import-Clixml -LiteralPath '"+str(path).replace("'","''")+"'; [Console]::Write(([System.Net.NetworkCredential]::new('', $s)).Password)"
        key=subprocess.check_output(['powershell','-NoProfile','-NonInteractive','-Command',command],text=True).strip()
    os.environ.update(DEEPSEEK_API_KEY=key,XLINE_AGENT_PROVIDER='deepseek',DEEPSEEK_MODEL='deepseek-flash',
        DEEPSEEK_BASE_MODEL='deepseek-flash',DEEPSEEK_ADVANCED_MODEL='deepseek-flash',DEEPSEEK_CAD_PLANNING_MODEL='deepseek-flash',
        XLINE_RUNTIME_PROFILE='virtual_sim',XLINE_DATABASE_PATH=str(out/'test.db'),
        XLINE_CREATIVE_PROJECT_STORE=str(out/'unused-projects.json'),XLINE_AGENT_RUN_STORE=str(out/'runs.json'),
        XLINE_AGENT_TASK_STORE=str(out/'tasks.json'),XLINE_AGENT_AUDIT_STORE=str(out/'audit.jsonl'),
        XLINE_AGENT_MEMORY_STORE=str(out/'conversation-memory.json'),
        XLINE_AGENT_PLAN_STORE=str(out/'plans.sqlite'),XLINE_CAD_DIR=str(out/'cad'))
    import app.creative_projects as cp
    import app.agent_http_service as http
    from app.agent_service import robot_agent
    from app.schemas import AgentChatRequest,AgentConfirmRequest
    from app.routers.agent import agent_confirm
    from app.cad_candidate_state import candidate_is_accepted
    from app.cad_construction import execute_construction_plan
    plan=json.loads((ROOT/'evaluations/cad_copy_deepseek_validation_plan.json').read_text(encoding='utf-8'))
    if args.case:
        plan['cases']=[case for case in plan['cases'] if case['id'] in set(args.case)]
    current={'case':'','turn':0};offline_attempts=[]
    def transport(payload):
        if args.offline_preflight:
            offline_attempts.append(current.copy())
            raise RuntimeError('offline_preflight_model_request_blocked')
        if payload.get('stream'):raise BudgetStop('unexpected_stream_transport')
        reservation=budget.reserve(payload);number=budget.calls
        dump(out/f'call-{number}-request.json',{'context':current.copy(),'payload':payload,'reservation':reservation})
        dump(out/'budget.json',budget.snapshot())
        try:
            req=urllib.request.Request('https://api.deepseek.com/chat/completions',
                data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=90) as response:
                raw=response.read();status=response.status;headers=dict(response.headers)
            parsed=json.loads(raw)
            dump(out/f'call-{number}-response.json',{'headers':headers,'response':parsed})
            budget.settle(parsed);dump(out/'budget.json',budget.snapshot())
            print('provider',number,current,parsed.get('usage'),flush=True)
            return None,SimpleNamespace(status=status,read=io.BytesIO(raw).read,close=lambda:None)
        except BaseException:
            budget.fail_unknown();dump(out/'budget.json',budget.snapshot());raise
    results=[]
    with patch.object(robot_agent,'_deepseek_response',side_effect=transport):
        for case in plan['cases']:
            if budget.stopped:break
            if args.offline_preflight and case['id']=='T6':continue
            folder=out/case['id']
            if case['id']=='T6':
                folder.mkdir();store=cp.CreativeProjectStore(folder/'projects.json')
            current.update(case=case['id'],turn=0)
            case_calls_before=budget.calls
            project=None;variant=None;history=[];turns=[];source=None;copied_id=None;status='failed';reason=None
            initial_selection=None
            if case['id']!='T6':
                from flash_copy_fixture import load_circle_fixture
                store,project,variant,initial_selection=load_circle_fixture(args.fixture_history/case['id'],folder)
                source=deepcopy(variant['geometries'][0])
            cp._project_store=store
            try:
                for index,message in enumerate(case['messages'],1):
                    if budget.stopped:raise BudgetStop('previous_call_unsettled_or_failed')
                    current['turn']=index;before_calls=budget.calls
                    before=deepcopy(variant);before_count=len((store.get(project['id']) or {}).get('variants',[])) if project else 0
                    if variant:
                        if not candidate_is_accepted(variant):reason='P0_review_required_baseline';break
                        store.begin_design_iteration(project['id'],variant['id'])
                    body={'message':message,'mode':'advanced','conversation_id':out.name+'-'+case['id'],
                        'client_id':'flash-c2-'+case['id'],'history':history}
                    if project:body['project_id']=project['id']
                    if variant:body['variant_id']=variant['id']
                    if index==1 and initial_selection:body['drawing_selection']=initial_selection
                    dump(folder/f'request-{index}.json',body)
                    response=http.agent_chat(AgentChatRequest.model_validate(body))
                    initial_response=deepcopy(response)
                    pending=response.get('pending_action')
                    if pending:
                        if pending.get('name')!='apply_cad_candidate_edit':raise RuntimeError('non_CAD_confirmation_blocked')
                        response=agent_confirm(AgentConfirmRequest(action_id=pending['id'],approved=True,client_id=body['client_id']))
                    dump(folder/f'response-{index}.json',response)
                    history.extend([{'role':'user','content':message},{'role':'assistant','content':response.get('message','')}])
                    if response.get('project_id'):project=store.get(response['project_id'])
                    if isinstance(response.get('variant'),dict) and response['variant'].get('geometries'):variant=response['variant']
                    after_count=len((store.get(project['id']) or {}).get('variants',[])) if project else 0
                    turn={'message':message,'provider_calls':budget.calls-before_calls,'response':response,
                        'initial_response':initial_response,'before_variant':before,'after_variant':deepcopy(variant),
                        'version_count_before':before_count,'version_count_after':after_count}
                    turns.append(turn)
                    if response.get('clarification_required') or response.get('target_clarification'):
                        reason='target_clarification';break
                    if args.offline_preflight:
                        status='preflight_edit_path_passed' if variant and variant['id']!=(before or {}).get('id') else 'blocked'
                        reason=None if status=='preflight_edit_path_passed' else 'no_new_copy'
                        break
                    if case['id']=='T6' and index==1:
                        if budget.calls==before_calls:reason='creation_not_model_mediated';break
                        if not variant or not candidate_is_accepted(variant):reason='P0_draft_or_no_accepted_creation';break
                        gs=variant['geometries']
                        if len(gs)!=1 or gs[0].get('type')!='circle' or abs(gs[0]['radius']-1000)>.5:reason='initial_creation_geometry_mismatch';break
                        source=deepcopy(gs[0]);continue
                    if before and variant:
                        added=[g for g in variant['geometries'] if g['id'] not in {v['id'] for v in before['geometries']}]
                        if added:
                            if len(added)!=1:reason='copy_count_mismatch';break
                            copied_id=added[0]['id']
                    if response.get('ok') is not True:
                        if case['id']=='T5' and index==3 and variant and variant['geometries']==[source]:status='passed';reason='deleted_reference_rejected';break
                        reason='production_response_not_ok';break
                else:
                    gs=(variant or {}).get('geometries',[]);byid={g['id']:g for g in gs}
                    if case['id']=='T5':reason='deleted_reference_not_rejected'
                    elif copied_id is None:reason='copy_missing'
                    else:
                        original_ok=byid.get(source['id'])==source
                        radius_ok=abs(byid[copied_id]['radius']-500)<.5
                        if case['id']=='T3':original_ok=abs(byid[source['id']]['radius']-800)<.5;radius_ok=byid[copied_id]==turns[0]['after_variant']['geometries'][-1]
                        if original_ok and radius_ok:
                            status='passed';reason=None
                            if case['id']=='T4' and not (turns[-1]['version_count_before']==turns[-1]['version_count_after'] and
                                (turns[-1]['response'].get('cad_edit_result') or {}).get('status')=='no_change'):
                                status='failed';reason='no_change_contract_failed'
                        else:reason='independent_geometry_mismatch'
            except Exception as exc:reason=type(exc).__name__+': '+str(exc)
            record={'case':case['id'],'status':status,'reason':reason,'turns':turns,
                'provider_calls':budget.calls-case_calls_before}
            dump(folder/'result.json',record);results.append(record)
            print(case['id'],status,reason,flush=True)
    dump(out/'summary.json',{'model':'deepseek-flash','thinking':{'type':'disabled'},'budget':budget.snapshot(),
        'pricing_source':'https://api-docs.deepseek.com/quick_start/pricing/',
        'cost_note':'Peak-rate cost upper bound, includes compatibility probes; not final account invoice.',
        'mode':'offline_preflight' if args.offline_preflight else 'live','offline_model_attempts':offline_attempts,
        'new_model_calls':budget.calls-previous['requests'],'results':results,'not_run':[c['id'] for c in plan['cases'] if c['id'] not in {r['case'] for r in results}]})


if __name__=='__main__':main()
