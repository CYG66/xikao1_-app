"""Persistent, fail-closed budget ledger for offline/live evaluation tools.

P1.3 changes:
- input reservations use a conservative upper bound, not ``bytes // 4``;
- the frozen provider/model pair is checked before and after the request;
- every actual send attempt, including failures, increments the request count;
- a model mismatch or usage above the reservation stops the run permanently.
"""
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
import json, os, threading, time, uuid
from pathlib import Path

_LOCAL_LOCKS: dict[str, threading.RLock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()


def _local_lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCAL_LOCKS_GUARD:
        return _LOCAL_LOCKS.setdefault(key, threading.RLock())

class EvaluationBudgetStop(RuntimeError):
    """Fatal evaluation stop; must not degrade into a normal case failure."""

    eval_fatal = True


class EvaluationPersistenceError(EvaluationBudgetStop):
    """Ledger write failed; the run must stay blocked after restart."""

    eval_fatal = True


LIMITS = {
    'requests': int(os.getenv('P12_MAX_REQUESTS','32')),
    'input_tokens': int(os.getenv('P12_MAX_INPUT_TOKENS','500000')),
    'output_tokens': int(os.getenv('P12_MAX_OUTPUT_TOKENS','128000')),
    'cost_usd': float(os.getenv('P12_MAX_COST_USD','2')),
}

# Conservative authorized-model pricing.  Values are deliberately above the
# published deepseek-flash rates used by the earlier runner; raising them can
# only stop the run earlier, never hide spend.
INPUT_PRICE_PER_M = float(os.getenv('P12_INPUT_PRICE_PER_M','0.60'))
OUTPUT_PRICE_PER_M = float(os.getenv('P12_OUTPUT_PRICE_PER_M','2.40'))

def _estimate_tokens(value):
    """Compatibility wrapper around the strict byte/protocol bound."""
    try:
        from app.eval_token_bound import input_token_upper_bound
        return int(input_token_upper_bound(value)['upper_bound'])
    except Exception:
        raw=json.dumps(value,ensure_ascii=False).encode('utf-8')
        return len(raw) + 32*(len(value.get('messages') or [])+len(value.get('tools') or [])+2) + 128

def _price(inp, out):
    return inp/1_000_000*INPUT_PRICE_PER_M + out/1_000_000*OUTPUT_PRICE_PER_M


def _usage_tokens(usage):
    """Return (input, output, status); never coerce missing usage to zero."""

    if not isinstance(usage, dict):
        return None, None, 'missing'
    raw_in = usage.get('prompt_tokens', usage.get('input_tokens'))
    raw_out = usage.get('completion_tokens', usage.get('output_tokens'))
    if raw_in is None or raw_out is None:
        return None, None, 'missing'
    if isinstance(raw_in, bool) or isinstance(raw_out, bool):
        return None, None, 'invalid'
    try:
        inp = int(raw_in)
        out = int(raw_out)
    except (TypeError, ValueError, OverflowError):
        return None, None, 'invalid'
    if inp < 0 or out < 0:
        return None, None, 'invalid'
    return inp, out, 'known'


class BudgetLedger:
    def __init__(self,path):
        self.limits=deepcopy(LIMITS)
        for key,env in [('requests','P12_MAX_REQUESTS'),('input_tokens','P12_MAX_INPUT_TOKENS'),('output_tokens','P12_MAX_OUTPUT_TOKENS')]:
            if os.getenv(env): self.limits[key]=int(os.getenv(env))
        if os.getenv('P12_MAX_COST_USD'): self.limits['cost_usd']=float(os.getenv('P12_MAX_COST_USD'))
        self.path=Path(path); self.lock_path=self.path.with_suffix(self.path.suffix+'.lock')
        self.fail_closed_path=self.path.with_suffix(self.path.suffix+'.fail-closed')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if not self.path.exists():
            self._write({'schema':'p1.3-eval-budget.v1','limits':deepcopy(self.limits),
                         'used':{'requests':0,'input_tokens':0,'output_tokens':0,
                                 'cost_usd':0.0,'unconfirmed_cost_upper_bound_usd':0.0},
                         'stopped':False,'pending':None,'events':[]})
    @contextmanager
    def _locked(self):
        # The OS file lock is cross-process; the local RLock also serializes
        # threads in this process (msvcrt.locking is not a thread mutex on
        # every Windows build).  Both are required for one effective pending.
        with _local_lock_for(self.path):
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
    def _ensure_not_fail_closed(self):
        if self.fail_closed_path.exists():
            raise EvaluationPersistenceError(
                'ledger_persistence_previously_failed'
            )
    def _read(self):
        self._ensure_not_fail_closed()
        return json.loads(self.path.read_text(encoding='utf-8'))
    def _write(self,d):
        tmp=self.path.with_suffix(self.path.suffix+'.tmp-'+uuid.uuid4().hex)
        try:
            tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
            os.replace(tmp,self.path)
        except Exception as error:
            # A write failure must poison this ledger across restarts.  The
            # marker is best-effort but is checked before every reserve/settle.
            try:
                self.fail_closed_path.write_text(
                    json.dumps({'schema':'p1.3-eval-budget-fail-closed.v1',
                                'error':f'{type(error).__name__}: {error}'}),
                    encoding='utf-8',
                )
            except Exception:
                pass
            try:
                tmp.unlink()
            except Exception:
                pass
            raise EvaluationPersistenceError(
                f'ledger_persist_failed:{type(error).__name__}: {error}'
            ) from error
    def reserve(self, *, run_id, case_id, request_id, payload, max_output_tokens,
               expected_model=None, provider=None, target_url=None,
               input_token_upper_bound=None):
        inp=int(input_token_upper_bound) if input_token_upper_bound is not None else _estimate_tokens(payload)
        out=int(max_output_tokens)
        if out<1: raise EvaluationBudgetStop('invalid_output_reservation')
        if expected_model is not None and str((payload or {}).get('model') or '') != str(expected_model):
            with self._locked():
                d=self._read()
                d['stopped']=True; d['pending']=None
                d['events'].append({'event':'model_prescreen_rejected','request_id':request_id,
                                    'expected_model':expected_model,'payload_model':(payload or {}).get('model')})
                self._write(d)
            raise EvaluationBudgetStop('model_not_authorized')
        with self._locked():
            d=self._read(); u=d['used']; l=d['limits']
            if d.get('stopped') or d.get('pending'): raise EvaluationBudgetStop('ledger_stopped_or_pending')
            cost=_price(inp,out)
            if (u['requests']+1>l['requests'] or u['input_tokens']+inp>l['input_tokens']
                or u['output_tokens']+out>l['output_tokens'] or u['cost_usd']+cost>l['cost_usd']):
                d['stopped']=True; d['events'].append({'event':'reserve_rejected','request_id':request_id,
                    'requested':{'input_tokens':inp,'output_tokens':out,'cost_usd':cost},
                    'used':deepcopy(u),'limits':deepcopy(l)})
                self._write(d); raise EvaluationBudgetStop('budget_would_be_exceeded')
            reservation={'input_tokens':inp,'output_tokens':out,'cost_usd':cost}
            d['pending']={'run_id':run_id,'case_id':case_id,'request_id':request_id,'reservation':reservation,
                          'expected_model':expected_model,'provider':provider,'target_url':target_url,
                          'started_at':time.time()}
            d['events'].append({'event':'reserved','run_id':run_id,'case_id':case_id,'request_id':request_id,
                                'reservation':reservation,'expected_model':expected_model,
                                'provider':provider,'target_url':target_url})
            self._write(d); return reservation
    def settle(self, *, response, http_status=None, error=None, retry=False,
               expected_model=None, reserved_input_tokens=None, reserved_output_tokens=None):
        with self._locked():
            d=self._read(); p=d.get('pending')
            if not p: raise EvaluationBudgetStop('missing_pending_reservation')
            reservation=p.get('reservation') or {}
            expected=expected_model if expected_model is not None else p.get('expected_model')
            response=response if isinstance(response,dict) else {}
            usage=response.get('usage')
            model=response.get('model')
            choices=response.get('choices') or []
            finish=(choices[0].get('finish_reason') if choices and isinstance(choices[0],dict) else None)
            # A send attempt always consumes a request slot, including failed
            # or unverifiable attempts.  This prevents retry/failure bypasses.
            d['used'].setdefault('unconfirmed_cost_upper_bound_usd',0.0)
            d['used']['requests']+=1
            inp,out,usage_status=_usage_tokens(usage)
            reserved_cost=float(reservation.get('cost_usd') or 0.0)
            usage_cost=_price(inp,out) if usage_status=='known' else None
            model_text=str(model) if model is not None else None
            model_authorized=bool(expected is not None and model_text is not None
                                  and model_text==str(expected))
            model_unauthorized=bool(expected is not None and model_text is not None
                                    and model_text!=str(expected))
            if usage_status=='known':
                # Even a rejected model response may already have been billed.
                # Record verified usage before raising.
                d['used']['input_tokens']+=inp
                d['used']['output_tokens']+=out
            # Four distinct cost classes are kept explicit.  A fixed
            # authorized-model price is always an estimate, never a supplier
            # invoice; an unauthorized/unlabelled response is accounted at the
            # full reservation upper bound instead of being treated as a
            # verified actual bill.
            if usage_status=='known' and model_authorized:
                cost=usage_cost
                cost_class='authorized_model_estimate'
            elif usage_status=='known' and model_unauthorized:
                cost=max(usage_cost or 0.0, reserved_cost)
                cost_class='unauthorized_model_upper_bound'
            else:
                cost=reserved_cost
                cost_class='unconfirmed_upper_bound'
            d['used']['cost_usd']+=cost
            if cost_class!='authorized_model_estimate':
                d['used']['unconfirmed_cost_upper_bound_usd']+=cost
            cost_status='settled' if usage_status=='known' else 'unverifiable'
            cost_evidence={
                'cost_status':cost_status,
                'cost_class':cost_class,
                'cost_basis':'authorized_model_list_price',
                'unconfirmed_cost_upper_bound_usd':(
                    cost if cost_class!='authorized_model_estimate' else 0.0
                ),
                'supplier_invoice_verified':False,
            }
            if error is None and http_status is None:
                # A settled response without an observed HTTP status cannot be
                # audited.  Fail closed even when usage is present, because the
                # response may be a transport fallback or an unlabelled retry.
                d['stopped']=True; d['pending']=None
                d['events'].append({'event':'missing_http_status_stop','request_id':p['request_id'],
                                    'http_status':None,'http_status_status':'unknown',
                                    'usage':usage,'model':model,
                                    'usage_status':usage_status,'cost_usd':cost,
                                    'finish_reason':finish,
                                    'reservation':reservation,**cost_evidence})
                self._write(d); raise EvaluationBudgetStop('missing_http_status')
            if expected is not None and model is not None and str(model)!=str(expected):
                d['stopped']=True
                d['events'].append({'event':'model_mismatch_stop','request_id':p['request_id'],
                                    'expected_model':expected,'actual_model':model,'usage':usage,
                                    'usage_status':usage_status,'cost_usd':cost,
                                    'http_status':http_status,
                                    'http_status_status':('known' if http_status is not None else 'unknown'),
                                    'reservation':reservation,**cost_evidence})
                d['pending']=None
                self._write(d)
                raise EvaluationBudgetStop('model_not_authorized')
            if (error is not None or not isinstance(usage,dict) or not model):
                d['stopped']=True; d['pending']=None
                d['events'].append({'event':'settle_unknown_stop','request_id':p['request_id'],
                                    'http_status':http_status,
                                    'http_status_status':('known' if http_status is not None else 'unknown'),
                                    'error':str(error) if error else None,'usage':usage,
                                    'usage_status':usage_status,'cost_usd':cost,
                                    'model':model,'finish_reason':finish,
                                    'reservation':reservation,**cost_evidence})
                self._write(d); raise EvaluationBudgetStop('unverifiable_usage_or_model')
            if usage_status!='known':
                d['stopped']=True; d['pending']=None
                d['events'].append({'event':'invalid_usage_stop','request_id':p['request_id'],
                                    'usage':usage,'usage_status':usage_status,
                                    'http_status':http_status,
                                    'http_status_status':('known' if http_status is not None else 'unknown'),
                                    'cost_usd':cost,
                                    'reservation':reservation,**cost_evidence})
                self._write(d); raise EvaluationBudgetStop('invalid_usage')
            reserved_in=int(reserved_input_tokens if reserved_input_tokens is not None else reservation.get('input_tokens',0))
            reserved_out=int(reserved_output_tokens if reserved_output_tokens is not None else reservation.get('output_tokens',0))
            if inp>reserved_in or out>reserved_out:
                d['stopped']=True; d['pending']=None
                d['events'].append({'event':'usage_exceeded_reservation','request_id':p['request_id'],
                                    'usage':usage,'reserved':{'input_tokens':reserved_in,'output_tokens':reserved_out},
                                    'cost_usd':cost,'http_status':http_status,
                                    'http_status_status':('known' if http_status is not None else 'unknown'),
                                    'reservation':reservation,**cost_evidence})
                self._write(d); raise EvaluationBudgetStop('usage_exceeded_reservation')
            d['pending']=None; d['events'].append({'event':'settled','run_id':p['run_id'],'case_id':p['case_id'],
                'request_id':p['request_id'],'http_status':http_status,
                'http_status_status':('known' if http_status is not None else 'unknown'),
                'model':model,'finish_reason':finish,
                'usage':usage,'cost_usd':cost,'retry':retry,
                'reservation':reservation,**cost_evidence})
            self._write(d)
    def stop_unknown(self,request_id,error,http_status=None,response=None):
        try:self.settle(response=response,http_status=http_status,error=error)
        except EvaluationPersistenceError: raise
        except EvaluationBudgetStop: pass
    def stop_run(self,reason):
        """Terminally close the run without discarding an unsettled reservation."""
        with self._locked():
            d=self._read()
            d['stopped']=True
            d['events'].append({'event':'run_stopped','reason':str(reason),
                                'pending':d.get('pending')})
            self._write(d)
    def snapshot(self):
        with self._locked(): return self._read()
