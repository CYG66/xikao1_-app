import json
from urllib.request import Request

import pytest

from app import eval_request_guard
from app.eval_request_guard import (
    EvalRequestBlocked,
    ModelAuthorizationError,
    begin_eval_request,
    deny_eval_get,
    reset_eval_guard,
    settle_eval_response,
    configure_eval_guard,
)
from tests.manual.eval_budget_store import BudgetLedger, EvaluationBudgetStop


def eval_env(monkeypatch, tmp_path, *, authorized=True, requests=8):
    monkeypatch.setenv('P12_EVAL_MODE','1')
    monkeypatch.setenv('P12_EVAL_FORMAL_HTTP','1')
    monkeypatch.setenv('P12_EXPECTED_PROVIDER','deepseek')
    monkeypatch.setenv('P12_EXPECTED_MODEL','deepseek-flash')
    monkeypatch.setenv('P12_MAX_REQUESTS',str(requests))
    monkeypatch.setenv('P12_MAX_INPUT_TOKENS','1000000')
    monkeypatch.setenv('P12_MAX_OUTPUT_TOKENS','100000')
    monkeypatch.setenv('P12_MAX_COST_USD','100')
    if authorized:
        monkeypatch.setenv('P12_REAL_MODEL_AUTHORIZED','1')
    else:
        monkeypatch.delenv('P12_REAL_MODEL_AUTHORIZED',raising=False)
    ledger=BudgetLedger(tmp_path/'budget.json')
    configure_eval_guard(ledger)
    return ledger

def body(model='deepseek-flash', **extra):
    return {'model':model,'messages':[{'role':'user','content':'x'}],'max_tokens':10,**extra}

def begin(ledger, **overrides):
    values={'provider':'deepseek','model':'deepseek-flash',
            'target_url':'https://api.deepseek.com/chat/completions',
            'payload':body(),'max_output_tokens':10}
    values.update(overrides)
    return begin_eval_request(**values)

def teardown_function():
    reset_eval_guard()

def test_default_denies_without_real_authorization(tmp_path, monkeypatch):
    ledger=eval_env(monkeypatch,tmp_path,authorized=False)
    with pytest.raises(EvalRequestBlocked) as error: begin(ledger)
    assert 'real_model_not_authorized' in str(error.value)
    assert ledger.snapshot()['used']['requests']==0

def test_denies_without_budget_context(monkeypatch):
    monkeypatch.setenv('P12_EVAL_MODE','1')
    monkeypatch.setenv('P12_EVAL_FORMAL_HTTP','1')
    monkeypatch.setenv('P12_REAL_MODEL_AUTHORIZED','1')
    reset_eval_guard()
    with pytest.raises(EvalRequestBlocked) as error: begin(None)
    assert 'evaluation_budget_unavailable' in str(error.value)

def test_denies_non_formal_entry(tmp_path, monkeypatch):
    ledger=eval_env(monkeypatch,tmp_path)
    monkeypatch.delenv('P12_EVAL_FORMAL_HTTP',raising=False)
    with pytest.raises(EvalRequestBlocked) as error: begin(ledger)
    assert 'evaluation_formal_entry_required' in str(error.value)

def test_denies_unapproved_provider_model_and_target(tmp_path, monkeypatch):
    ledger=eval_env(monkeypatch,tmp_path)
    with pytest.raises(ModelAuthorizationError): begin(ledger,provider='openai',model='deepseek-flash',
        target_url='https://api.openai.com/v1/responses')
    reset_eval_guard(); ledger=BudgetLedger(tmp_path/'b2.json'); configure_eval_guard(ledger)
    with pytest.raises(ModelAuthorizationError): begin(ledger,model='deepseek-chat')
    reset_eval_guard(); ledger=BudgetLedger(tmp_path/'b3.json'); configure_eval_guard(ledger)
    with pytest.raises(ModelAuthorizationError): begin(ledger,target_url='https://evil.example/chat/completions')

def test_begin_reserves_and_response_model_must_match(tmp_path, monkeypatch):
    ledger=eval_env(monkeypatch,tmp_path)
    reservation=begin(ledger)
    assert reservation.input_upper_bound > 0
    with pytest.raises(ModelAuthorizationError):
        settle_eval_response(reservation, {'model':'deepseek-chat','usage':{'prompt_tokens':1,'completion_tokens':1}}, http_status=200)
    snapshot=ledger.snapshot()
    assert snapshot['stopped'] is True and snapshot['used']['requests']==1
    assert any(event['event']=='model_mismatch_stop' for event in snapshot['events'])

def test_response_model_match_settles_exactly_once(tmp_path, monkeypatch):
    ledger=eval_env(monkeypatch,tmp_path)
    reservation=begin(ledger)
    settle_eval_response(reservation, {'model':'deepseek-flash','usage':{'prompt_tokens':1,'completion_tokens':1}}, http_status=200)
    with pytest.raises(EvalRequestBlocked): settle_eval_response(reservation, {'model':'deepseek-flash','usage':{'prompt_tokens':1,'completion_tokens':1}})
    assert ledger.snapshot()['used']['requests']==1

def test_missing_usage_stops_and_restart_is_still_stopped(tmp_path, monkeypatch):
    ledger=eval_env(monkeypatch,tmp_path)
    reservation=begin(ledger)
    with pytest.raises(EvaluationBudgetStop): settle_eval_response(reservation, {'model':'deepseek-flash'}, http_status=200)
    assert ledger.snapshot()['stopped'] is True
    restarted=BudgetLedger(tmp_path/'budget.json'); configure_eval_guard(restarted)
    with pytest.raises(EvaluationBudgetStop): begin(restarted)

def test_missing_http_status_stops_even_with_usage(tmp_path, monkeypatch):
    ledger=eval_env(monkeypatch,tmp_path)
    reservation=begin(ledger)
    with pytest.raises(EvaluationBudgetStop) as error:
        settle_eval_response(reservation, {'model':'deepseek-flash','usage':{'prompt_tokens':1,'completion_tokens':1}})
    assert 'missing_http_status' in str(error.value)
    snapshot=ledger.snapshot()
    assert snapshot['stopped'] is True and snapshot['pending'] is None
    event=next(e for e in snapshot['events'] if e['event']=='missing_http_status_stop')
    assert event['http_status'] is None and event['cost_usd'] is not None

def test_request_limit_is_fail_closed(tmp_path, monkeypatch):
    ledger=eval_env(monkeypatch,tmp_path,requests=1)
    first=begin(ledger)
    settle_eval_response(first, {'model':'deepseek-flash','usage':{'prompt_tokens':1,'completion_tokens':1}}, http_status=200)
    with pytest.raises(EvaluationBudgetStop): begin(ledger)
    assert ledger.snapshot()['used']['requests']==1

def test_deny_eval_get_blocks_test_connection_endpoint(tmp_path, monkeypatch):
    eval_env(monkeypatch,tmp_path)
    with pytest.raises(EvalRequestBlocked): deny_eval_get('https://api.deepseek.com/models')

def test_transport_retry_cannot_double_spend(tmp_path, monkeypatch):
    from app import deepseek_transport
    ledger=eval_env(monkeypatch,tmp_path)
    calls=[]
    class FakeResponse:
        status=200
    class FakeConnection:
        sock=None
        def __init__(self,*a,**kw): pass
        def request(self,*a,**kw):
            calls.append('request')
            raise OSError('synthetic connect failure')
        def close(self): pass
    monkeypatch.setattr(deepseek_transport.http.client,'HTTPSConnection',FakeConnection)
    transport=deepseek_transport.DeepSeekTransport(api_key='synthetic',timeout_for=lambda *_:1.0)
    with pytest.raises(EvaluationBudgetStop): transport.open(body())
    assert calls==['request']
    snapshot=ledger.snapshot()
    assert snapshot['stopped'] is True and snapshot['used']['requests']==1

def test_transport_attaches_one_reservation_per_attempt(tmp_path, monkeypatch):
    from app import deepseek_transport
    ledger=eval_env(monkeypatch,tmp_path)
    seen=[]
    class FakeResponse:
        status=200
    class FakeConnection:
        sock=None
        def __init__(self,*a,**kw): pass
        def request(self,*a,**kw): seen.append('request')
        def getresponse(self): return FakeResponse()
        def close(self): pass
    monkeypatch.setattr(deepseek_transport.http.client,'HTTPSConnection',FakeConnection)
    transport=deepseek_transport.DeepSeekTransport(api_key='synthetic',timeout_for=lambda *_:1.0)
    connection,response=transport.open(body())
    assert seen==['request']
    reservation=response._p12_eval_reservation
    settle_eval_response(reservation, {'model':'deepseek-flash','usage':{'prompt_tokens':1,'completion_tokens':1}}, http_status=200)
    assert ledger.snapshot()['used']['requests']==1


def test_provider_adapter_denies_before_network(tmp_path, monkeypatch):
    from app import model_providers
    eval_env(monkeypatch,tmp_path,authorized=False)
    adapter=model_providers.provider_adapter('deepseek')
    request=adapter.build_tool_request(base_url='https://api.deepseek.com',model='deepseek-flash',
        api_key='synthetic',payload=body())
    called=[]
    monkeypatch.setattr(model_providers.urllib.request,'urlopen',lambda *a,**k: called.append('urlopen'))
    with pytest.raises(EvalRequestBlocked): adapter.send_json(request,timeout=1.0)
    assert called==[]


def test_openai_gateway_denies_before_network(tmp_path, monkeypatch):
    from app import model_request_gateway
    eval_env(monkeypatch,tmp_path,authorized=False)
    called=[]
    monkeypatch.setattr(model_request_gateway.urllib.request,'urlopen',lambda *a,**k: called.append('urlopen'))
    with pytest.raises(EvalRequestBlocked):
        model_request_gateway.request_openai_responses_json(api_key='synthetic',
            payload={'model':'deepseek-flash','input':[],'max_output_tokens':10},timeout=1.0)
    assert called==[]


