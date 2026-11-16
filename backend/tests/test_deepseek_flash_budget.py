import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('budget',Path(__file__).parent/'manual/deepseek_flash_budget.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def payload():return {'model':'deepseek-flash','thinking':{'type':'disabled'},'max_tokens':128,'messages':[]}
def reply():return {'model':'deepseek-flash','usage':{'prompt_tokens':20,'completion_tokens':5}}

def test_reserve_and_actual_settlement():
    b=m.Budget();b.reserve(payload());b.settle(reply())
    assert b.calls==1 and b.input==20 and b.output==5 and b.pending is None

@pytest.mark.parametrize('field,value',[('calls',32),('input',499999),('output',128000),('cost',m.Decimal('2'))])
def test_limits_prevent_emission(field,value):
    b=m.Budget();setattr(b,field,value)
    with pytest.raises(m.BudgetStop):b.reserve(payload())
    assert b.pending is None

def test_missing_usage_stops_and_keeps_reservation():
    b=m.Budget();b.reserve(payload())
    with pytest.raises(m.BudgetStop):b.settle({'model':'deepseek-flash'})
    with pytest.raises(m.BudgetStop):b.reserve(payload())

def test_pending_and_wrong_model_fail_closed():
    b=m.Budget();bad=payload();bad['model']='deepseek-chat'
    with pytest.raises(m.BudgetStop):b.reserve(bad)
    assert b.stopped
    with pytest.raises(m.BudgetStop):b.reserve(payload())
    b=m.Budget()
    b.reserve(payload())
    with pytest.raises(m.BudgetStop):b.reserve(payload())

def test_usage_exceeding_reservation_stops():
    b=m.Budget();b.reserve(payload());r=reply();r['usage']['completion_tokens']=1000
    with pytest.raises(m.BudgetStop):b.settle(r)
    assert b.stopped
