"""Request-local accounting for structured calls omitted by chat usage."""
from contextlib import contextmanager
from contextvars import ContextVar

_ledger = ContextVar("structured_model_usage", default=None)
KEYS = ("input_tokens", "output_tokens", "total_tokens")


def structured_model_fallback(provider, model):
    ledger = _ledger.get()
    return (ledger or {}).get("model_fallbacks", {}).get(provider + ":" + model)


def remember_structured_model_fallback(provider, model, fallback):
    ledger = _ledger.get()
    if ledger is not None:
        ledger.setdefault("model_fallbacks", {})[provider + ":" + model] = fallback


@contextmanager
def structured_usage_scope(ledger=None):
    ledger = ledger if ledger is not None else {"calls": 0, "missing_usage_calls": 0, **dict.fromkeys(KEYS, 0)}
    token = _ledger.set(ledger)
    try:
        yield ledger
    finally:
        _ledger.reset(token)


def record_structured_usage(response, provider):
    ledger = _ledger.get()
    if ledger is None:
        return
    ledger["calls"] += 1
    raw = response.get("usageMetadata") if provider == "gemini" else response.get("usage")
    fields = ("promptTokenCount", "candidatesTokenCount", "totalTokenCount") if provider == "gemini" else (
        ("input_tokens", "output_tokens", "total_tokens") if provider in {"openai", "anthropic"} else
        ("prompt_tokens", "completion_tokens", "total_tokens"))
    try:
        if not isinstance(raw, dict) or fields[0] not in raw or fields[1] not in raw:
            raise ValueError("missing usage")
        values = [int(raw[fields[0]]), int(raw[fields[1]])]
        values.append(int(raw.get(fields[2], sum(values))))
        if any(v < 0 for v in values):
            raise ValueError("negative usage")
    except (TypeError, ValueError, OverflowError):
        ledger["missing_usage_calls"] += 1
        return
    for key, value in zip(KEYS, values):
        ledger[key] += value


def merge_structured_usage(result):
    ledger = _ledger.get()
    if not ledger or not ledger["calls"]:
        return
    prior = result.get("structured_usage") or {}
    usage = result.get("usage") or {}
    result["usage"] = {k: int(usage.get(k, 0) or 0) - int(prior.get(k, 0) or 0) + ledger[k] for k in KEYS}
    result["structured_usage"] = {**ledger, "complete": ledger["missing_usage_calls"] == 0}


def usage_scoped_events(events):
    # Starlette may advance successive yields in different worker contexts.
    # Bind and reset on every next(), retaining only this request's ledger.
    ledger = {"calls": 0, "missing_usage_calls": 0, **dict.fromkeys(KEYS, 0)}
    while True:
        with structured_usage_scope(ledger):
            try:
                event = next(events)
            except StopIteration:
                return
        yield event
