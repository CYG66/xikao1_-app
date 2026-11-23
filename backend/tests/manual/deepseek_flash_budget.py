"""Fail-closed isolated test accounting. No provider calls in this module."""
from decimal import Decimal
import json


class BudgetStop(RuntimeError):pass


class Budget:
    def __init__(self):
        self.calls=0;self.input=0;self.output=0;self.cost=Decimal('0');self.pending=None;self.stopped=False

    def reserve(self,payload):
        if self.stopped or self.pending is not None:raise BudgetStop('stopped_or_unsettled_request')
        if payload.get('model')!='deepseek-flash' or payload.get('thinking')!={'type':'disabled'}:
            self.stopped=True
            raise BudgetStop('unexpected_model_or_thinking')
        upper=len(json.dumps(payload,ensure_ascii=False).encode('utf-8'))+4096
        maximum=payload.get('max_tokens')
        if type(maximum) is not int or not 1<=maximum<=8192:
            self.stopped=True;raise BudgetStop('invalid_output_reservation')
        cost=(Decimal(upper)*Decimal('.30')+Decimal(maximum)*Decimal('1.20'))/1000000
        if self.calls>=32 or self.input+upper>500000 or self.output+maximum>128000 or self.cost+cost>2:
            self.stopped=True
            raise BudgetStop('budget_would_be_exceeded')
        self.calls+=1;self.pending=(upper,maximum,cost)
        return {'reserved_input':upper,'reserved_output':maximum,'reserved_cost_usd':str(cost)}

    def settle(self,response):
        if self.pending is None:raise BudgetStop('no_reservation')
        usage=response.get('usage') or {};i=usage.get('prompt_tokens');o=usage.get('completion_tokens')
        hit=usage.get('prompt_cache_hit_tokens',0)
        if (type(i) is not int or type(o) is not int or type(hit) is not int or
            min(i,o,hit)<0 or hit>i or i>self.pending[0] or o>self.pending[1]
            or response.get('model')!='deepseek-flash'):
            self.stopped=True;raise BudgetStop('unverifiable_usage_or_model')
        # Peak rates reserve an upper bound; exact tariff is separately recorded.
        self.input+=i;self.output+=o
        self.cost+=(Decimal(i-hit)*Decimal('.30')+Decimal(hit)*Decimal('.006')+Decimal(o)*Decimal('1.20'))/1000000
        self.pending=None
        return self.snapshot()

    def fail_unknown(self):self.stopped=True

    def snapshot(self):return {'requests':self.calls,'input_tokens':self.input,'output_tokens':self.output,
        'peak_rate_cost_upper_usd':str(self.cost),'unsettled':self.pending is not None,'stopped':self.stopped}
