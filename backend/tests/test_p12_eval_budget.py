import json, os, subprocess, sys, threading, time
from pathlib import Path
import pytest

from tests.manual.eval_budget_store import BudgetLedger, EvaluationBudgetStop
from app.eval_token_bound import input_token_upper_bound

def payload(): return {'model':'deepseek-flash','messages':[{'role':'user','content':'x'}], 'max_tokens':10}

def reserve(ledger, request_id, **extra):
    return ledger.reserve(run_id='r',case_id='c',request_id=request_id,payload=payload(),max_output_tokens=10,
                          expected_model='deepseek-flash',provider='deepseek',
                          target_url='https://api.deepseek.com/chat/completions',**extra)

def settle(ledger, prompt_tokens=1, completion_tokens=1, model='deepseek-flash'):
    ledger.settle(response={'model':model,'choices':[{'finish_reason':'stop'}],
        'usage':{'prompt_tokens':prompt_tokens,'completion_tokens':completion_tokens}},
        expected_model='deepseek-flash')

def test_input_token_bound_is_a_byte_bound():
    bound=input_token_upper_bound(payload())
    assert bound['upper_bound'] >= bound['body_bytes']
    assert bound['upper_bound'] > bound['body_bytes'] // 4
    assert bound['basis'].startswith('utf8-byte')

def test_exact_limit_rejects_33rd(tmp_path, monkeypatch):
    monkeypatch.setenv('P12_MAX_REQUESTS','32')
    ledger=BudgetLedger(tmp_path/'budget.json')
    for i in range(32):
        reserve(ledger,str(i)); settle(ledger)
    with pytest.raises(EvaluationBudgetStop):
        reserve(ledger,'33')
    assert ledger.snapshot()['used']['requests']==32

def test_concurrent_reservations_keep_one_pending_then_serial_fills_budget(tmp_path, monkeypatch):
    monkeypatch.setenv('P12_MAX_REQUESTS','4')
    ledger=BudgetLedger(tmp_path/'budget.json'); results=[]; barrier=threading.Barrier(8)
    def one(i):
        barrier.wait()
        try:
            reserve(ledger,str(i))
            # Hold the reservation long enough for the other workers to hit
            # the single-pending gate; this is the concurrency contract, not a
            # hidden retry loop.
            time.sleep(0.25)
            settle(ledger); results.append('settled')
        except EvaluationBudgetStop as error:
            results.append(str(error))
    ts=[threading.Thread(target=one,args=(i,)) for i in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert results.count('settled')==1, results
    assert len([r for r in results if r=='ledger_stopped_or_pending'])==7, results
    assert ledger.snapshot()['used']['requests']==1
    # The concurrent phase proves one effective pending.  The serial phase
    # proves the remaining budget is exactly usable and never overrun.
    for i in range(3):
        reserve(ledger,f's{i}'); settle(ledger)
    assert ledger.snapshot()['used']['requests']==4
    with pytest.raises(EvaluationBudgetStop):
        reserve(ledger,'fifth')
    assert ledger.snapshot()['used']['requests']==4

def test_duplicate_settlement_is_rejected(tmp_path, monkeypatch):
    ledger=BudgetLedger(tmp_path/'budget.json')
    reserve(ledger,'x'); settle(ledger)
    with pytest.raises(EvaluationBudgetStop):
        settle(ledger)
    assert ledger.snapshot()['used']['requests']==1

def test_unknown_usage_stops_and_restart_does_not_reset(tmp_path, monkeypatch):
    ledger=BudgetLedger(tmp_path/'budget.json')
    reserve(ledger,'x')
    with pytest.raises(EvaluationBudgetStop): ledger.settle(response={'model':'deepseek-flash','choices':[]})
    assert ledger.snapshot()['used']['requests']==1
    restarted=BudgetLedger(tmp_path/'budget.json')
    assert restarted.snapshot()['stopped'] is True
    with pytest.raises(EvaluationBudgetStop): reserve(restarted,'y')

def test_model_prescreen_rejects_unapproved_model(tmp_path, monkeypatch):
    ledger=BudgetLedger(tmp_path/'budget.json')
    with pytest.raises(EvaluationBudgetStop):
        ledger.reserve(run_id='r',case_id='c',request_id='x',
            payload={'model':'deepseek-chat','messages':[],'max_tokens':10},max_output_tokens=10,
            expected_model='deepseek-flash',provider='deepseek',
            target_url='https://api.deepseek.com/chat/completions')
    assert ledger.snapshot()['stopped'] is True
    assert ledger.snapshot()['used']['requests']==0

def test_model_response_mismatch_stops_and_counts_request(tmp_path, monkeypatch):
    ledger=BudgetLedger(tmp_path/'budget.json')
    reserve(ledger,'x')
    with pytest.raises(EvaluationBudgetStop): settle(ledger,model='deepseek-chat')
    s=ledger.snapshot(); assert s['stopped'] is True and s['used']['requests']==1
    assert any(e['event']=='model_mismatch_stop' for e in s['events'])

def test_usage_above_reservation_stops(tmp_path, monkeypatch):
    ledger=BudgetLedger(tmp_path/'budget.json')
    reserve(ledger,'x')
    with pytest.raises(EvaluationBudgetStop): settle(ledger,prompt_tokens=10_000,completion_tokens=10)
    s=ledger.snapshot(); assert s['stopped'] is True and s['used']['input_tokens']==10_000

def test_worker_budget_boundary_uses_mock_provider(tmp_path):
    root=Path(__file__).resolve().parents[1]; out=tmp_path/'worker'; out.mkdir()
    (out/'projects.json').write_text('{"projects":[]}',encoding='utf-8')
    budget=tmp_path/'budget.json'; env=os.environ.copy(); env.update({
        'P12_EVAL_BUDGET_PATH':str(budget),'P12_EVAL_MOCK_PROVIDER':'1','P12_EVAL_RUN_ID':'smoke','P12_EVAL_MODE':'1',
        'P12_MAX_REQUESTS':'1','DEEPSEEK_MODEL':'deepseek-flash','DEEPSEEK_CAD_PLANNING_MODEL':'deepseek-flash',
        'DEEPSEEK_BASE_MODEL':'deepseek-flash','DEEPSEEK_ADVANCED_MODEL':'deepseek-flash',
        'P12_EXPECTED_MODEL':'deepseek-flash','P12_EXPECTED_PROVIDER':'deepseek',
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
