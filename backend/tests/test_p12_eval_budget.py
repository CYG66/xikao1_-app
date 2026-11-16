import json, os, subprocess, sys, threading
from pathlib import Path
import pytest

from tests.manual.eval_budget_store import BudgetLedger, EvaluationBudgetStop

def payload(): return {'model':'deepseek-flash','messages':[{'role':'user','content':'x'}], 'max_tokens':10}

def test_exact_limit_rejects_33rd(tmp_path, monkeypatch):
    monkeypatch.setenv('P12_MAX_REQUESTS','32')
    ledger=BudgetLedger(tmp_path/'budget.json')
    for i in range(32):
        ledger.reserve(run_id='r',case_id='c',request_id=str(i),payload=payload(),max_output_tokens=10)
        ledger.settle(response={'model':'deepseek-flash','choices':[{'finish_reason':'stop'}],
            'usage':{'prompt_tokens':1,'completion_tokens':1}})
    with pytest.raises(EvaluationBudgetStop):
        ledger.reserve(run_id='r',case_id='c',request_id='33',payload=payload(),max_output_tokens=10)
    assert ledger.snapshot()['used']['requests']==32

def test_concurrent_reservations_are_atomic(tmp_path, monkeypatch):
    monkeypatch.setenv('P12_MAX_REQUESTS','4')
    ledger=BudgetLedger(tmp_path/'budget.json'); results=[]
    def one(i):
        try:
            ledger.reserve(run_id='r',case_id='c',request_id=str(i),payload=payload(),max_output_tokens=10)
            ledger.settle(response={'model':'deepseek-flash','choices':[{'finish_reason':'stop'}],
                'usage':{'prompt_tokens':1,'completion_tokens':1}}); results.append(True)
        except EvaluationBudgetStop: results.append(False)
    ts=[threading.Thread(target=one,args=(i,)) for i in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sum(results)==4 and ledger.snapshot()['used']['requests']==4

def test_unknown_usage_stops_and_restart_does_not_reset(tmp_path, monkeypatch):
    ledger=BudgetLedger(tmp_path/'budget.json')
    ledger.reserve(run_id='r',case_id='c',request_id='x',payload=payload(),max_output_tokens=10)
    with pytest.raises(EvaluationBudgetStop): ledger.settle(response={'model':'deepseek-flash','choices':[]})
    restarted=BudgetLedger(tmp_path/'budget.json')
    assert restarted.snapshot()['stopped'] is True
    with pytest.raises(EvaluationBudgetStop): restarted.reserve(run_id='r',case_id='c',request_id='y',payload=payload(),max_output_tokens=10)

def test_worker_budget_boundary_uses_mock_provider(tmp_path):
    root=Path(__file__).resolve().parents[1]; out=tmp_path/'worker'; out.mkdir()
    (out/'projects.json').write_text('{"projects":[]}',encoding='utf-8')
    budget=tmp_path/'budget.json'; env=os.environ.copy(); env.update({
        'P12_EVAL_BUDGET_PATH':str(budget),'P12_EVAL_MOCK_PROVIDER':'1','P12_EVAL_RUN_ID':'smoke','P12_EVAL_MODE':'1',
        'P12_MAX_REQUESTS':'1','DEEPSEEK_MODEL':'deepseek-flash','DEEPSEEK_CAD_PLANNING_MODEL':'deepseek-flash',
        'DEEPSEEK_BASE_MODEL':'deepseek-flash','DEEPSEEK_ADVANCED_MODEL':'deepseek-flash',
    })
    req={'operation':'budget_probe','case_id':'smoke','step':1,'body':{}}
    p=subprocess.run([sys.executable,str(root/'tests/manual/cad_widget_live_worker.py'),'--output',str(out)],
        input=json.dumps(req,ensure_ascii=False),text=True,encoding='utf-8',capture_output=True,env=env,timeout=60)
    assert p.returncode==0, p.stderr
    d=json.loads(budget.read_text(encoding='utf-8')); assert d['used']['requests']==1
    line=(out/'model-usage.jsonl').read_text(encoding='utf-8').strip(); assert 'finish_reason' in line and 'usage' in line

def test_evaluation_worker_without_budget_makes_zero_requests(tmp_path):
    root=Path(__file__).resolve().parents[1]; out=tmp_path/'missing'; out.mkdir()
    env=os.environ.copy(); env.update({'P12_EVAL_MODE':'1','P12_EVAL_MOCK_PROVIDER':'1'})
    req={'operation':'budget_probe','case_id':'missing','step':1,'body':{}}
    p=subprocess.run([sys.executable,str(root/'tests/manual/cad_widget_live_worker.py'),'--output',str(out)],
        input=json.dumps(req),text=True,encoding='utf-8',capture_output=True,env=env,timeout=30)
    assert p.returncode != 0 and 'evaluation_budget_unavailable' in p.stderr
    assert not (out/'model-usage.jsonl').exists()
