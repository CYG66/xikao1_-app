"""Persistent, fail-closed budget ledger for offline/live evaluation tools."""
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
import json, os, tempfile, time, uuid
from pathlib import Path

class EvaluationBudgetStop(RuntimeError): pass

LIMITS = {
    'requests': int(os.getenv('P12_MAX_REQUESTS','32')),
    'input_tokens': int(os.getenv('P12_MAX_INPUT_TOKENS','500000')),
    'output_tokens': int(os.getenv('P12_MAX_OUTPUT_TOKENS','128000')),
    'cost_usd': float(os.getenv('P12_MAX_COST_USD','2')),
}

def _estimate_tokens(value):
    raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    return max(1,(len(raw)+3)//4)

class BudgetLedger:
    def __init__(self,path):
        self.limits=deepcopy(LIMITS)
        for key,env in [('requests','P12_MAX_REQUESTS'),('input_tokens','P12_MAX_INPUT_TOKENS'),('output_tokens','P12_MAX_OUTPUT_TOKENS')]:
            if os.getenv(env): self.limits[key]=int(os.getenv(env))
        if os.getenv('P12_MAX_COST_USD'): self.limits['cost_usd']=float(os.getenv('P12_MAX_COST_USD'))
        self.path=Path(path); self.lock_path=self.path.with_suffix(self.path.suffix+'.lock')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if not self.path.exists():
            self._write({'schema':'p1.2-eval-budget.v1','limits':deepcopy(self.limits),
                         'used':{'requests':0,'input_tokens':0,'output_tokens':0,'cost_usd':0.0},
                         'stopped':False,'pending':None,'events':[]})
    @contextmanager
    def _locked(self):
        # Lock the first byte, using the platform primitive available to the
        # Windows evaluation workers; never mutate the ledger outside it.
        f=open(self.lock_path,'a+b'); f.seek(0); f.write(b'0'); f.flush()
        if os.name=='nt':
            import msvcrt
            f.seek(0); msvcrt.locking(f.fileno(),msvcrt.LK_LOCK,1)
        else:
            import fcntl; fcntl.flock(f.fileno(),fcntl.LOCK_EX)
        try: yield
        finally:
            if os.name=='nt':
                import msvcrt
                f.seek(0); msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl; fcntl.flock(f.fileno(),fcntl.LOCK_UN)
            f.close()
    def _read(self): return json.loads(self.path.read_text(encoding='utf-8'))
    def _write(self,d):
        tmp=self.path.with_suffix(self.path.suffix+'.tmp-'+uuid.uuid4().hex)
        tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(tmp,self.path)
    def reserve(self, *, run_id, case_id, request_id, payload, max_output_tokens):
        inp=_estimate_tokens(payload); out=int(max_output_tokens)
        if out<1: raise EvaluationBudgetStop('invalid_output_reservation')
        with self._locked():
            d=self._read(); u=d['used']; l=d['limits']
            if d.get('stopped') or d.get('pending'): raise EvaluationBudgetStop('ledger_stopped_or_pending')
            cost=(inp/1_000_000*0.30)+(out/1_000_000*1.20)
            if (u['requests']+1>l['requests'] or u['input_tokens']+inp>l['input_tokens']
                or u['output_tokens']+out>l['output_tokens'] or u['cost_usd']+cost>l['cost_usd']):
                d['stopped']=True; d['events'].append({'event':'reserve_rejected','request_id':request_id})
                self._write(d); raise EvaluationBudgetStop('budget_would_be_exceeded')
            reservation={'input_tokens':inp,'output_tokens':out,'cost_usd':cost}
            d['pending']={'run_id':run_id,'case_id':case_id,'request_id':request_id,'reservation':reservation,
                          'started_at':time.time()}
            d['events'].append({'event':'reserved','run_id':run_id,'case_id':case_id,'request_id':request_id,
                                'reservation':reservation})
            self._write(d); return reservation
    def settle(self, *, response, http_status=None, error=None, retry=False):
        with self._locked():
            d=self._read(); p=d.get('pending')
            if not p: raise EvaluationBudgetStop('missing_pending_reservation')
            usage=(response or {}).get('usage') if isinstance(response,dict) else None
            model=(response or {}).get('model') if isinstance(response,dict) else None
            choices=(response or {}).get('choices') if isinstance(response,dict) else []
            finish=(choices[0].get('finish_reason') if choices and isinstance(choices[0],dict) else None)
            if error is not None or not isinstance(usage,dict) or not model:
                d['stopped']=True; d['pending']=None
                d['events'].append({'event':'settle_unknown_stop','request_id':p['request_id'],'http_status':http_status,
                                    'error':str(error) if error else None,'usage':usage,'model':model,'finish_reason':finish})
                self._write(d); raise EvaluationBudgetStop('unverifiable_usage_or_model')
            inp=int(usage.get('prompt_tokens',usage.get('input_tokens'))); out=int(usage.get('completion_tokens',usage.get('output_tokens')))
            if inp<0 or out<0: raise EvaluationBudgetStop('invalid_usage')
            cost=inp/1_000_000*0.30+out/1_000_000*1.20
            d['used']['requests']+=1; d['used']['input_tokens']+=inp; d['used']['output_tokens']+=out; d['used']['cost_usd']+=cost
            d['pending']=None; d['events'].append({'event':'settled','run_id':p['run_id'],'case_id':p['case_id'],
                'request_id':p['request_id'],'http_status':http_status,'model':model,'finish_reason':finish,
                'usage':usage,'cost_usd':cost,'retry':retry})
            self._write(d)
    def stop_unknown(self,request_id,error):
        try:self.settle(response=None,error=error)
        except EvaluationBudgetStop: pass
    def snapshot(self):
        with self._locked(): return self._read()
