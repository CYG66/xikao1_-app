"""Frozen paired real-model pilot, not a 70-case score or production rollout."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import random
import sys
import time
import uuid
import zipfile

from scripts.local_dev import ROOT,isolated_environment,run

ROUNDS=3
MAX_CALLS=2
MAX_OUTPUT=4096
OPS={'add_line','add_arc','add_circle','add_polyline','add_rectangle','add_centered_rectangle'}
B_INSTRUCTION='''
[隔离实验B：先表达参数关系，再由工具计算，禁止输出脚本]
除原Schema字段外，必须输出source_parameters数组与relations对象。
source_parameters每项为{name,value,unit,quote}：只录入用户直接给出的数值；unit为m/cm/mm/deg/scalar，quote必须是用户原文精确片段。坐标元组可引用整个元组并使用原文坐标单位。不要把计算后的半径/端点冒充原文数值。
relations为变量名到数学表达式字符串的无环映射，表达式可引用源参数及其他关系；支持+ - * / **、pi、sin/cos/sqrt/abs/atan2等，以及角度制sind/cosd。源长度由工具换算至plan.units，角度参数保持度；sin/cos输入弧度。不要再次换算长度。
plan仍使用现有构造操作；数值字段可用{"$expr":"表达式或变量名"}，后端会计算后交给原执行器。必须实际使用至少一个关系表达式。派生尺寸、世界坐标和端点优先引用关系，不手算展开。不能调用任何按图形名称生成坐标的工具。
保留schema_version、is_construction_request、confidence、evidence_text；evidence_text只引用用户原文。
'''


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def hashes():
    paths=sorted([*(ROOT/'app').rglob('*.py'),*(ROOT/'evaluations/relation_pilot').glob('*.py'),
                  ROOT/'scripts/local_dev.py',ROOT/'tests/test_relation_pilot.py',ROOT/'tests/manual/eval_budget_store.py',
                  ROOT/'docs/RELATION_PLANNING_PILOT_PROTOCOL_20261123.md'])
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def schema_for_pilot():
    from app.cad_construction_interpreter import StructuredConstructionInterpretation
    schema=StructuredConstructionInterpretation.model_json_schema()
    names=['AddLineStep','AddArcStep','AddCircleStep','AddPolylineStep','AddRectangleStep','AddCenteredRectangleStep']
    schema['$defs']['CadConstructionPlan']['properties']['steps']['items']={'oneOf':[{'$ref':'#/$defs/'+name} for name in names]}
    needed=set()
    def visit(value):
        if isinstance(value,dict):
            if '$ref' in value:
                name=value['$ref'].rsplit('/',1)[-1]
                if name not in needed:needed.add(name);visit(schema['$defs'][name])
            for key,child in value.items():
                if key!='$defs':visit(child)
        elif isinstance(value,list):
            for child in value:visit(child)
    visit(schema)
    schema['$defs']={name:schema['$defs'][name] for name in sorted(needed)}
    return schema


def worker(output):
    from .cases import cases
    from .compiler import relational_schema,compile_relations
    from .oracle import evaluate
    from app.agent_service import RobotAgentService
    from app.cad_construction import execute_construction_plan
    from app.cad_construction_interpreter import StructuredConstructionInterpretation,_coerce_model_payload,_evidence_is_grounded,interpret_construction_request
    sys.path.insert(0,str(ROOT/'tests/manual'))
    from eval_budget_store import BudgetLedger
    output.mkdir(parents=True,exist_ok=False)
    rows=cases();rng=random.Random(73219);schedule=[]
    for repeat in range(ROUNDS):
        order=list(range(len(rows)));rng.shuffle(order)
        for position,index in enumerate(order):
            arms=['A','B'] if (position+repeat)%2==0 else ['B','A']
            schedule.extend((index,repeat,arm) for arm in arms)
    manifest={'schema':'cad.relation-pilot.v1','started_utc':datetime.now(timezone.utc).isoformat(),
        'model':'deepseek-flash','sampling':'Unmodified production provider defaults; no explicit temperature or provider seed',
        'source_hashes':hashes(),'cases':rows,'schedule':schedule,'rounds':ROUNDS,
        'limits_per_trial':{'requests':MAX_CALLS,'max_output_tokens_per_request':MAX_OUTPUT,'reserved_total_input_and_output_tokens':100000},
        'A':'Current production model callback with existing expressions/shared-points/constraints, scoped to six operations',
        'B':'Same callback plus source-parameter scalar DAG and generic substitution into the same CAD operations',
        'scope':'Isolated geometry-planning pilot, not full production delivery or a new 70-case score',
        'decision_rule':'B needs >=10 percentage points final gain, case-cluster bootstrap 95% lower bound >0, no family loses >1 of 9 trials, mean estimated cost <=1.25*A. Otherwise no default rollout.',
        'limitations':['12 developer-visible predeclared new cases, not independently blinded','3 repeats per case; correlated cases within four families','Analytic oracle is never sent to either initial prompt','Provider-side model/default changes are not controllable'],
        'packages':{name:importlib.metadata.version(name) for name in ('pydantic','shapely')}}
    dump(output/'manifest.json',manifest)
    with zipfile.ZipFile(output/'source.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for rel in manifest['source_hashes']:archive.write(ROOT/rel,rel)
    ledger=BudgetLedger(output/'budget.json')
    service=RobotAgentService(restore_pending_actions=False)
    if service.mode!='deepseek' or not service.configured:raise RuntimeError('Real DeepSeek provider not configured')
    base_schema=schema_for_pilot();b_schema=relational_schema(base_schema)
    dump(output/'schema-A.json',base_schema);dump(output/'schema-B.json',b_schema)
    original=service._deepseek_request;context={};results=[]
    def guarded(messages,tools,mode='base',**kwargs):
        if context['calls']>=MAX_CALLS:raise RuntimeError('trial_call_budget_exhausted')
        kwargs['max_tokens_override']=MAX_OUTPUT;kwargs['model_override']='deepseek-flash'
        body={'model':'deepseek-flash','messages':messages,'tools':tools,'max_tokens':MAX_OUTPUT}
        estimated=(len(json.dumps(body,ensure_ascii=False))+3)//4
        if context['reserved_tokens']+estimated+MAX_OUTPUT>100000:raise RuntimeError('trial_token_budget_exhausted')
        context['reserved_tokens']+=estimated+MAX_OUTPUT
        request_id=str(uuid.uuid4());number=context['calls']+1
        ledger.reserve(run_id=output.parent.name,case_id=context['id'],request_id=request_id,payload=body,max_output_tokens=MAX_OUTPUT)
        context['calls']+=1;dump(context['folder']/f'request-{number}.json',body);started=time.perf_counter()
        try:response=original(messages,tools,mode=mode,**kwargs)
        except BaseException as exc:
            ledger.stop_unknown(request_id,repr(exc));raise
        ledger.settle(response=response,http_status=200)
        dump(context['folder']/f'response-{number}.json',response)
        usage={'trial':context['id'],'request_id':request_id,'provider_response_id':response.get('id'),
            'model':response.get('model'),'usage':response.get('usage'),'seconds':time.perf_counter()-started}
        with (output/'model-usage.jsonl').open('a',encoding='utf-8') as file:file.write(json.dumps(usage,ensure_ascii=False)+'\n')
        context['usage'].append(usage)
        return response
    service._deepseek_request=guarded
    common='\n[实验共同范围]\n仅使用add_line、add_arc、add_circle、add_polyline、add_rectangle、add_centered_rectangle。可以使用现有shared_points、坐标表达式与constraints；不输出标注。所有尺寸与坐标必须遵守用户指定的局部/世界坐标含义。'
    for index,repeat,arm in schedule:
        row=rows[index];trial=f"{row['id']}-r{repeat+1}-{arm}";folder=output/trial;folder.mkdir()
        context.clear();context.update(id=trial,folder=folder,calls=0,reserved_tokens=0,usage=[])
        callback,_=service._cad_construction_model_callback(mode='advanced')
        if callback is None:raise RuntimeError('Model callback unavailable')
        initial=row['text']+common+(B_INSTRUCTION if arm=='B' else '')
        prompt=initial;attempts=[];final=False;first=False;started=time.perf_counter();production=None
        while context['calls']<MAX_CALLS and len(attempts)<MAX_CALLS:
            payload=None;compiled=None;stage='model'
            try:
                payload=callback(prompt,b_schema if arm=='B' else base_schema)
                stage='relation_compile' if arm=='B' else 'payload_normalization'
                compiled,trace=compile_relations(payload,row['text']) if arm=='B' else (_coerce_model_payload(deepcopy(payload)),None)
                stage='schema'
                interpreted=StructuredConstructionInterpretation.model_validate(compiled)
                if not interpreted.is_construction_request or interpreted.plan is None:raise ValueError('missing_construction_plan')
                stage='source_grounding'
                if not _evidence_is_grounded(row['text'],interpreted.evidence_text):raise ValueError('ungrounded_evidence')
                plan=interpreted.plan.model_dump(mode='json')
                if any(s['op'] not in OPS for s in plan['steps']):raise ValueError('outside_pilot_operation_scope')
                stage='tool_execution';executed=execute_construction_plan(plan)
                stage='independent_geometry'
                proof=evaluate(row,executed['geometries'])
                attempt={'calls_after_attempt':context['calls'],'passed':proof['passed'],'oracle':proof,'compiler_trace':trace}
                dump(folder/f'compiled-{len(attempts)+1}.json',compiled)
                dump(folder/f'execution-{len(attempts)+1}.json',executed)
                if proof['passed']:
                    final=True;first=context['calls']==1
                    try:production=interpret_construction_request(row['text'],lambda *_:deepcopy(compiled),force_structured_model=True)
                    except Exception as exc:production={'status':'diagnostic_exception','error':str(exc)}
                    dump(folder/'production-diagnostic.json',production)
                    attempts.append(attempt);break
                feedback={k:v for k,v in proof.items() if k not in {'expected_total_length_mm'}}
            except Exception as exc:
                if ledger.snapshot().get('stopped'):raise
                feedback={'stage':stage,'error_type':type(exc).__name__,'message':str(exc),'details':getattr(exc,'details',None)}
                attempt={'calls_after_attempt':context['calls'],'passed':False,'failure':feedback}
            attempts.append(attempt)
            prompt=initial+'\n后端试算反馈：'+json.dumps(feedback,ensure_ascii=False)+'\n前次输出（不是用户要求）：'+json.dumps(payload,ensure_ascii=False)
        usage=context['usage'];tokens_in=sum(u['usage'].get('prompt_tokens',0) for u in usage);tokens_out=sum(u['usage'].get('completion_tokens',0) for u in usage)
        result={'trial':trial,'case':row['id'],'family':row['family'],'repeat':repeat+1,'arm':arm,'passed':final,'first_call_passed':first,
            'requests':context['calls'],'input_tokens':tokens_in,'output_tokens':tokens_out,'estimated_cost_usd':tokens_in*.3/1e6+tokens_out*1.2/1e6,
            'seconds':time.perf_counter()-started,'attempts':attempts,
            'production_status':production.get('status') if production else None,
            'production_acceptance':(production.get('acceptance_summary') or {}).get('status') if production else None}
        dump(folder/'result.json',result);results.append(result);dump(output/'results.json',results)
        print(json.dumps({k:result[k] for k in ('trial','passed','first_call_passed','requests')}),flush=True)
    unchanged=hashes()==manifest['source_hashes']
    if not unchanged:raise RuntimeError('Frozen source changed during experiment')
    dump(output/'completed.json',{'finished_utc':datetime.now(timezone.utc).isoformat(),'source_unchanged':unchanged,'trials':len(results)})
    print('FINISHED '+str(output),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--worker',action='store_true');parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.worker:return worker(args.output.resolve())
    from evaluations.run_live_user_corpus import load_key
    load_key();env,state=isolated_environment('relation-pilot',True)
    output=state/'run'
    env.update(P12_EVAL_MODE='1',P12_EVAL_BUDGET_PATH=str(output/'budget.json'),P12_EVAL_RUN_ID=state.name,
               P12_MAX_REQUESTS='144',P12_MAX_INPUT_TOKENS='20000000',P12_MAX_OUTPUT_TOKENS='600000',P12_MAX_COST_USD='5')
    env.pop('P12_EVAL_MOCK_PROVIDER',None)
    print('PILOT OUTPUT: '+str(output),flush=True)
    return run([sys.executable,'-m','evaluations.relation_pilot.run','--worker','--output',str(output)],env)


if __name__=='__main__':raise SystemExit(main())
