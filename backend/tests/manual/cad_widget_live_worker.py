"""Local widget-test bridge to the real service/provider, with isolated stores.

No CAD/model responses are replayed. Hardware connection is virtual; every
chat call uses the actual resolve_intent/chat_stream production methods.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

def load_local_deepseek_key():
    if os.environ.get("DEEPSEEK_API_KEY"):
        return
    credential = Path(__file__).resolve().parents[2] / ".local-ai-test" / "deepseek-api-key.clixml"
    if not credential.exists():
        return
    command = ("$s=Import-Clixml -LiteralPath '" + str(credential).replace("'", "''") + "'; "
               "[Console]::Write(([System.Net.NetworkCredential]::new('', $s)).Password)")
    try:
        value = subprocess.check_output(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], text=True).strip()
    except Exception:
        return
    if value and value != "System.Security.SecureString":
        os.environ["DEEPSEEK_API_KEY"] = value

load_local_deepseek_key()
parser=argparse.ArgumentParser();parser.add_argument("--output",required=True)
args=parser.parse_args();root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=True)
os.environ.update(XLINE_RUNTIME_PROFILE="virtual_sim",XLINE_AGENT_PROVIDER="deepseek",
                  XLINE_AGENT_TASK_STORE=str(root/"tasks.json"),XLINE_AGENT_AUDIT_STORE=str(root/"audit.jsonl"),
                  XLINE_AGENT_RUN_STORE=str(root/"agent-runs.json"),XLINE_AGENT_PLAN_STORE=str(root/"agent-plans.sqlite"),
                  XLINE_CAD_DIR=str(root/"cad"),
                  XLINE_DATABASE_PATH=str(root/"test.db"),
                  # Every production module must resolve the copied project
                  # repository, including modules imported after this point.
                  XLINE_CREATIVE_PROJECT_STORE=str(root/"projects.json"))
evaluation_mode=os.getenv('P12_EVAL_MODE') == '1'
budget_path=os.getenv('P12_EVAL_BUDGET_PATH')
if evaluation_mode and not budget_path:
    raise SystemExit('evaluation_budget_unavailable: worker requires P12_EVAL_BUDGET_PATH')
budget=None
if budget_path:
    from eval_budget_store import BudgetLedger, EvaluationBudgetStop
    budget=BudgetLedger(budget_path)
    if not evaluation_mode:
        raise SystemExit('evaluation_context_invalid')
from app.creative_projects import CreativeProjectStore
from app.conversation_memory import ConversationMemoryStore

request=json.loads(sys.stdin.read())
store=CreativeProjectStore(root/"projects.json")
# Reload after the copied project directory is complete. The worker is the
# first process allowed to enter the HTTP service only after this validation.
store._load()
loaded_projects=store.list(limit=200)
loaded_candidates=[item for item in loaded_projects if item.get("variants")]
if operation := request.get("operation"):
    # Fresh creation starts with an empty repository; copied edit projects
    # must contain exactly one candidate.
    selection = (request.get('body') or {}).get('drawing_selection')
    if operation not in {"list", "get"} and selection and len(loaded_candidates) != 1:
        raise RuntimeError("project repository validation failed: expected one copied candidate")
(root/"project-repository-check.json").write_text(json.dumps({
    "path": str((root/"projects.json").resolve()),
    "project_ids": [str(item.get("id")) for item in loaded_projects],
    "candidate_project_ids": [str(item.get("id")) for item in loaded_candidates],
}, ensure_ascii=False, indent=2), encoding="utf-8")
operation=request.get("operation")
if operation=="list":
    if not store.list():store.create("已有项目", "已有无关项目", requirements={}, missing_parameters=["dimensions"])
    result={"ok":True,"projects":store.list()}
elif operation=="get":
    result={"ok":True,"project":store.get(request["project_id"])}
else:
    from app.agent_service import RobotAgentService
    service=RobotAgentService(restore_pending_actions=operation=="confirm")
    if budget is not None:
        original_request=service._deepseek_request
        def guarded_request(messages, tools, mode='base', **kwargs):
            request_id=str(uuid.uuid4()); max_tokens=int(kwargs.get('max_tokens_override') or service._deepseek_max_tokens(mode))
            payload={'model':kwargs.get('model_override') or service._model_for_agent_mode(mode),
                     'messages':messages,'tools':tools,'mode':mode,'max_tokens':max_tokens}
            budget.reserve(run_id=os.getenv('P12_EVAL_RUN_ID',root.name),case_id=str(request.get('case_id') or root.name),
                           request_id=request_id,payload=payload,max_output_tokens=max_tokens)
            started=__import__('time').time()
            try:
                if os.getenv('P12_EVAL_MOCK_PROVIDER') == '1':
                    response={'id':request_id,'model':'deepseek-flash','choices':[{'message':{'content':'{}'},'finish_reason':'stop'}],
                              'usage':{'prompt_tokens':max(1, len(json.dumps(messages,ensure_ascii=False))//4),
                                       'completion_tokens':10,'prompt_cache_hit_tokens':0}}
                else:
                    response=original_request(messages,tools,mode=mode,**kwargs)
                budget.settle(response=response,http_status=200)
                with (root/'model-usage.jsonl').open('a',encoding='utf-8') as f:
                    f.write(json.dumps({'run_id':os.getenv('P12_EVAL_RUN_ID',root.name),'case_id':request.get('case_id'),
                        'request_id':request_id,'model':response.get('model'),'usage':response.get('usage'),
                        'finish_reason':((response.get('choices') or [{}])[0].get('finish_reason')),
                        'duration_ms':round((__import__('time').time()-started)*1000,1)},ensure_ascii=False)+'\n')
                return response
            except BaseException as exc:
                budget.stop_unknown(request_id,repr(exc)); raise
        service._deepseek_request=guarded_request
    if operation == 'budget_probe':
        response=service._deepseek_request([], [], mode='advanced')
        print(json.dumps({'ok':True,'response':response},ensure_ascii=False),flush=True)
        raise SystemExit(0)
    runtime_store = __import__('app.agent_service', fromlist=['get_creative_project_store']).get_creative_project_store()
    (root/"project-runtime-check.json").write_text(json.dumps({
        "worker_store_path": str(store.path),
        "runtime_store_path": str(runtime_store.path),
        "worker_project_ids": [p["id"] for p in store.list(limit=200)],
        "runtime_project_ids": [p["id"] for p in runtime_store.list(limit=200)],
        "runtime_candidate_ids": [p["id"] for p in runtime_store.list(limit=200) if p.get("variants")],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    # Bind project mutating tools to the copied repository at the service
    # boundary. Models may return an id from the source conversation; the
    # copied candidate is authoritative for this isolated run.
    body=request["body"];step=request["step"]
    (root/f"request-{step}.json").write_text(json.dumps(body,ensure_ascii=False,indent=2),encoding="utf-8")
    original=service._structured_review_text
    def observe(*a,**kw):
        raw=original(*a,**kw)
        with (root/"model-responses.jsonl").open("a",encoding="utf-8") as f:
            f.write(json.dumps({"step":step,"response":raw},ensure_ascii=False)+"\n")
        return raw
    service._structured_review_text=observe
    original_stream=service.chat_stream
    def observe_stream(*a,**kw):
        for event in original_stream(*a,**kw):
            if event.get("type")=="result":
                (root/f"service-step-{step}.json").write_text(json.dumps(event,ensure_ascii=False,indent=2),encoding="utf-8")
            yield event
    service.chat_stream=observe_stream
    import asyncio
    from app.agent_http_service import agent_chat_stream
    from app.routers.agent import agent_confirm
    from app.schemas import AgentChatRequest, AgentConfirmRequest
    memory=ConversationMemoryStore(root/"conversation-memory.json")
    # Keep all module-level aliases on the same copied repository.  The
    # structured tool dispatcher lives in agent_service, while routers and
    # helper modules can retain their own imported alias.
    with (patch("app.agent_service.get_creative_project_store",return_value=store),
          patch("app.agent_http_service.get_creative_project_store",return_value=store),
          patch("app.agent_http_service.robot_agent",service),patch("app.agent_http_service.conversation_memory",memory),
          patch("app.agent_service.conversation_memory",memory)):
        response=None if operation=="confirm" else agent_chat_stream(AgentChatRequest.model_validate(body))
        async def collect():
            chunks=[]
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode("utf-8") if isinstance(chunk,bytes) else chunk)
            return [json.loads(line) for line in "".join(chunks).splitlines() if line.strip()]
        if operation=="confirm":
            result=agent_confirm(AgentConfirmRequest.model_validate(body))
        else:
            events=asyncio.run(collect())
            result=next(e for e in reversed(events) if e.get("type")=="result")
    (root/f"step-{step}.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    from app.state import robot_state
    (root/f"runtime-{step}.json").write_text(json.dumps(robot_state.snapshot(),ensure_ascii=False,indent=2,default=str),encoding="utf-8")
print(json.dumps(result,ensure_ascii=False))

