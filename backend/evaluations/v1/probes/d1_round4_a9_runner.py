"""D1 round-4 isolated production runner for the single authorized case A9.

Discipline:
- Real production chain: RobotAgentService.chat -> resolve_intent ->
  _chat_impl -> _formal_cad_construction (real prompts, repair strategy and
  candidate persistence). No Mock of the model call.
- Isolated project / plan / owner / per-owner config in a temp directory; the
  global production default config is not edited.
- Budget guards use peak worst-case Flash prices; settle from real usage.
- Raw responses are redacted before serialization; no key/Authorization is
  written to disk.

One-shot: if the ledger already records a settled A9 structured call, the
runner refuses to run again to avoid duplicate billing.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import sys
import tempfile
import time
from typing import Any

FLASH = "deepseek-flash"
CASE_ID = "A9"
PROMPT = "生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米"
EXPECTED_ROUTE = "construction_scope"

PEAK_INPUT_MISS = 0.30 / 1_000_000
PEAK_INPUT_HIT = 0.006 / 1_000_000
PEAK_OUTPUT = 1.20 / 1_000_000
INPUT_ESTIMATE_TOKENS = 10_000
DEFAULT_MAX_TOKENS = 8192

LIMITS = {
    "max_cases": 5,
    "max_requests": 30,
    "max_input_tokens": 300_000,
    "max_output_tokens": 60_000,
    "max_cost_usd": 1.00,
}


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def is_peak(dt: datetime.datetime) -> bool:
    # Mon-Fri 01:00-04:00 and 06:00-10:00 UTC; Chinese public holidays are not
    # modeled here, so any boundary-crossing request is billed peak.
    if dt.weekday() >= 5:
        return False
    h = dt.hour
    return (1 <= h < 4) or (6 <= h < 10)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).lower() in {"api_key", "authorization", "key", "api-keys"}:
                out[k] = "<redacted>"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def settle_usage(usage: dict[str, Any]) -> dict[str, float | int | None]:
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    hit = int(usage.get("prompt_cache_hit_tokens") or 0)
    miss = prompt - hit if hit > 0 else prompt
    input_cost = miss * PEAK_INPUT_MISS + hit * PEAK_INPUT_HIT
    output_cost = completion * PEAK_OUTPUT
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cache_hit_tokens": hit,
        "cache_miss_tokens": miss,
        "input_cost_usd": round(input_cost, 10),
        "output_cost_usd": round(output_cost, 10),
        "total_cost_usd": round(input_cost + output_cost, 10),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True)
    ap.add_argument("--registry", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    backend = pathlib.Path(args.backend).resolve()
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = pathlib.Path(args.ledger)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))

    # One-shot guard: do not re-bill an already settled A9 case.
    existing = [c for c in ledger.get("cases", []) if c.get("case_id") == CASE_ID]
    if existing and existing[-1].get("settled"):
        print("A9 already settled; refusing duplicate run.")
        return 3

    iso = pathlib.Path(tempfile.gettempdir()) / "xline-d1-round4"
    iso.mkdir(parents=True, exist_ok=True)

    # Isolation + flash overrides must be set before importing the app package.
    os.environ["XLINE_AGENT_PROVIDER"] = "deepseek"
    os.environ["DEEPSEEK_CAD_PLANNING_MODEL"] = FLASH
    os.environ["DEEPSEEK_BASE_MODEL"] = FLASH
    os.environ["DEEPSEEK_ADVANCED_MODEL"] = FLASH
    os.environ["XLINE_CREATIVE_PROJECT_STORE"] = str(iso / "projects.json")
    os.environ["XLINE_AGENT_PLAN_STORE"] = str(iso / "agent_plans.sqlite3")
    os.environ["XLINE_AGENT_USER_CONFIG_PATH"] = str(iso / "users.json")
    os.environ["XLINE_AGENT_MEMORY_STORE"] = str(iso / "conversation_memory.json")
    os.environ["XLINE_AGENT_RUN_STORE"] = str(iso / "agent_runs.json")

    registry = json.loads(pathlib.Path(args.registry).read_text(encoding="utf-8"))
    reg_cases = registry["cases"] if isinstance(registry, dict) and "cases" in registry else registry
    reg = next(c for c in reg_cases if c.get("case_id") == CASE_ID)
    prompt_sha = sha256_text(PROMPT)
    assert prompt_sha == reg["input_sha256"], "frozen input hash mismatch; aborting"

    sys.path.insert(0, str(backend))

    from app import agent_service  # noqa: E402
    from app.request_context import agent_user_scope  # noqa: E402
    from app.structured_usage import structured_usage_scope  # noqa: E402
    from app.structured_usage import record_structured_usage as original_record  # noqa: E402

    owner = "d1-round4-a9"
    raw_responses: list[dict[str, Any]] = []

    def spy_record(response: dict[str, Any], provider: str) -> None:
        original_record(response, provider)
        usage = response.get("usage") or {}
        raw_responses.append(
            redact(
                {
                    "captured_at_utc": utc_now().isoformat(timespec="seconds"),
                    "provider": provider,
                    "id": response.get("id"),
                    "model": response.get("model"),
                    "finish_reason": (
                        (response.get("choices") or [{}])[0].get("finish_reason")
                        if response.get("choices")
                        else None
                    ),
                    "usage": usage,
                }
            )
        )

    agent_service.record_structured_usage = spy_record

    ledger_usage = {
        "calls": 0,
        "missing_usage_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }

    precheck: dict[str, Any] = {}
    result: dict[str, Any] = {}
    route: dict[str, Any] = {}
    error: dict[str, Any] | None = None
    started = time.perf_counter()

    with agent_user_scope(owner):
        service = agent_service.RobotAgentService(restore_pending_actions=False)

        # Pre-release model guards (no network yet).
        precheck["service_config"] = {
            "mode": service.mode,
            "model_legacy": service.model,
            "base_model": service.base_model,
            "advanced_model": service.advanced_model,
            "cad_planning_model": service.cad_planning_model,
            "configured": bool(service.configured),
            "api_key_configured": bool(service.api_key),
        }
        if not (
            service.cad_planning_model == FLASH
            and service.base_model == FLASH
            and service.advanced_model == FLASH
            and service.configured
        ):
            precheck["guard_abort"] = "model override or configuration not flash/configured"
            _write_outputs(out_dir, ledger, ledger_path, CASE_ID, PROMPT, prompt_sha, EXPECTED_ROUTE,
                           reg, precheck, {}, {}, None, [], iso, 0.0, error)
            print(json.dumps({"aborted": precheck["guard_abort"]}, ensure_ascii=False))
            return 4

        # Case-level worst-case envelope: first plan + 2 bounded retries +
        # max_repairs=2 repair rounds, each <= 8192 output tokens.
        max_requests_case = 5
        reserve_per = (
            INPUT_ESTIMATE_TOKENS * PEAK_INPUT_MISS + DEFAULT_MAX_TOKENS * PEAK_OUTPUT
        )
        envelope_cost = max_requests_case * reserve_per
        envelope_input = max_requests_case * INPUT_ESTIMATE_TOKENS
        envelope_output = max_requests_case * DEFAULT_MAX_TOKENS
        precheck["budget_envelope"] = {
            "max_requests_case": max_requests_case,
            "reserve_per_request_usd": round(reserve_per, 10),
            "envelope_cost_usd": round(envelope_cost, 10),
            "envelope_input_tokens": envelope_input,
            "envelope_output_tokens": envelope_output,
            "limits": LIMITS,
            "within_limits": (
                envelope_cost <= LIMITS["max_cost_usd"]
                and envelope_input <= LIMITS["max_input_tokens"]
                and envelope_output <= LIMITS["max_output_tokens"]
                and max_requests_case <= LIMITS["max_requests"]
            ),
        }
        if not precheck["budget_envelope"]["within_limits"]:
            precheck["guard_abort"] = "case envelope exceeds hard limits"
            _write_outputs(out_dir, ledger, ledger_path, CASE_ID, PROMPT, prompt_sha, EXPECTED_ROUTE,
                           reg, precheck, {}, {}, None, [], iso, 0.0, error)
            return 4

        with structured_usage_scope(ledger_usage):
            try:
                route = service.resolve_intent(PROMPT, "advanced", [])
                result = service.chat(PROMPT, [], mode="advanced", route=route)
            except Exception as exc:  # noqa: BLE001 - record and stop, no retry
                error = {"type": type(exc).__name__, "message": str(exc)[:500]}

    elapsed = round(time.perf_counter() - started, 3)

    # Settle from real recorded responses; fall back to ledger usage if raw
    # response capture missed a call.
    settled = []
    total_cost = 0.0
    total_in = 0
    total_out = 0
    for raw in raw_responses:
        usage = raw.get("usage") or {}
        s = settle_usage(usage)
        total_cost += s["total_cost_usd"]
        total_in += s["prompt_tokens"]
        total_out += s["completion_tokens"]
        settled.append({
            "request_id": raw.get("id") or "not_available",
            "model": raw.get("model") or "not_available",
            "finish_reason": raw.get("finish_reason"),
            "peak_band": is_peak(datetime.datetime.fromisoformat(raw["captured_at_utc"])),
            **s,
        })

    if ledger_usage["calls"] > 0 and not settled:
        total_in = ledger_usage["input_tokens"]
        total_out = ledger_usage["output_tokens"]
        total_cost = (total_in * PEAK_INPUT_MISS + total_out * PEAK_OUTPUT)

    # Independent readback from the isolated project store.
    readback: dict[str, Any] = {}
    try:
        from app.creative_projects import get_creative_project_store  # noqa: E402
        store = get_creative_project_store()
        pid = str(result.get("project_id") or "")
        if pid:
            readback = redact(store.get(pid) or {})
    except Exception as exc:  # noqa: BLE001
        readback = {"readback_error": f"{type(exc).__name__}: {str(exc)[:200]}"}

    state = classify_state(result, error, settled, ledger_usage)

    record = _build_record(
        case_id=CASE_ID, prompt=PROMPT, prompt_sha=prompt_sha,
        expected_route=EXPECTED_ROUTE, registry=reg, precheck=precheck,
        route=route, result=result, error=error, elapsed=elapsed,
        settled=settled, ledger_usage=ledger_usage, readback=readback,
        state=state, total_cost=total_cost, total_in=total_in, total_out=total_out,
        iso=iso,
    )

    _write_outputs(out_dir, ledger, ledger_path, CASE_ID, PROMPT, prompt_sha, EXPECTED_ROUTE,
                   reg, precheck, record, result, error, raw_responses, iso,
                   total_cost, error, settled=settled, total_in=total_in,
                   total_out=total_out, state=state, readback=readback, elapsed=elapsed)

    print(json.dumps({
        "state": state,
        "requests": ledger_usage["calls"],
        "input_tokens": total_in,
        "output_tokens": total_out,
        "cost_usd": round(total_cost, 6),
        "provider_attempted": ledger_usage["calls"] > 0,
    }, ensure_ascii=False, indent=2))
    return 0


def classify_state(result: dict[str, Any], error: dict[str, Any] | None,
                   settled: list[dict[str, Any]], ledger_usage: dict[str, int]) -> str:
    if error:
        return "blocked"
    if result.get("clarification_required"):
        return "clarified"
    variant = result.get("variant") or {}
    summary = variant.get("acceptance_summary") or result.get("acceptance_summary") or {}
    status = summary.get("status")
    review = summary.get("review_required") is True
    if status == "passed" and not review:
        if ledger_usage["calls"] <= 1:
            return "first_plan_pass"
        return "model_retry_pass"
    if review:
        return "review_required"
    if status == "unresolved_topology":
        return "unresolved_topology"
    return "failed"


def _build_record(**kw: Any) -> dict[str, Any]:
    variant = kw["result"].get("variant") or {}
    geometries = variant.get("geometries") or []
    topology = variant.get("topology") or {}
    summary = variant.get("acceptance_summary") or kw["result"].get("acceptance_summary") or {}
    return {
        "case_id": kw["case_id"],
        "original_input": kw["prompt"],
        "input_sha256": kw["prompt_sha"],
        "expected_route": kw["expected_route"],
        "actual_route": redact(kw["route"]),
        "provider_attempted": kw["ledger_usage"]["calls"] > 0,
        "model": kw["precheck"]["service_config"]["cad_planning_model"],
        "request_count": kw["ledger_usage"]["calls"],
        "requests": kw["settled"],
        "elapsed_seconds": kw["elapsed"],
        "result_ok": bool(kw["result"].get("ok")),
        "result_message": str(kw["result"].get("message") or "")[:500],
        "error_code": kw["result"].get("error_code"),
        "failure_category": kw["result"].get("failure_category"),
        "acceptance_summary": redact(summary),
        "variant_id": str(variant.get("id") or "not_available"),
        "geometry_count": len(geometries),
        "geometry_hash": canonical_hash(geometries),
        "topology": redact(topology),
        "logical_objects": redact(variant.get("logical_objects") or []),
        "project_readback": kw["readback"],
        "state": kw["state"],
        "usage": {
            "input_tokens": kw["total_in"],
            "output_tokens": kw["total_out"],
            "cost_usd": round(kw["total_cost"], 10),
            "missing_usage_calls": kw["ledger_usage"]["missing_usage_calls"],
        },
        "failure_root_cause": kw["error"],
        "registry_acceptance_rules": kw["registry"].get("acceptance_rules"),
    }


def _write_outputs(out_dir: pathlib.Path, ledger: dict[str, Any], ledger_path: pathlib.Path,
                   case_id: str,
                   prompt: str, prompt_sha: str, expected_route: str, reg: dict[str, Any],
                   precheck: dict[str, Any], record: dict[str, Any], result: dict[str, Any],
                   error: Any, raw_responses: list[dict[str, Any]], iso: pathlib.Path,
                   total_cost: float, error2: Any, **extra: Any) -> None:
    record = record or {}
    case_entry = {
        "case_id": case_id,
        "original_input": prompt,
        "input_sha256": prompt_sha,
        "expected_route": expected_route,
        "state": record.get("state") or extra.get("state") or "blocked",
        "settled": bool(extra.get("settled")) or bool(record.get("usage", {}).get("cost_usd") is not None),
        "usage": record.get("usage") or {
            "input_tokens": extra.get("total_in", 0),
            "output_tokens": extra.get("total_out", 0),
            "cost_usd": round(extra.get("total_cost", total_cost), 10),
        },
        "requests": record.get("requests") or extra.get("settled") or [],
        "failure_root_cause": error or error2,
    }
    ledger["cases"] = [c for c in ledger.get("cases", []) if c.get("case_id") != case_id]
    ledger["cases"].append(case_entry)
    totals = ledger.setdefault("totals", {})
    totals["requests"] = int(totals.get("requests", 0)) + len(case_entry["requests"])
    totals["input_tokens"] = int(totals.get("input_tokens", 0)) + int(case_entry["usage"]["input_tokens"])
    totals["output_tokens"] = int(totals.get("output_tokens", 0)) + int(case_entry["usage"]["output_tokens"])
    totals["cost_usd"] = round(float(totals.get("cost_usd", 0.0)) + float(case_entry["usage"]["cost_usd"]), 10)

    case_path = out_dir / f"{case_id}_case_record.json"
    case_path.write_text(
        json.dumps({"precheck": precheck, "record": record, "result_redacted": redact(result)},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    raw_path = out_dir / f"{case_id}_raw_responses.jsonl"
    with raw_path.open("w", encoding="utf-8") as fh:
        for raw in raw_responses:
            fh.write(json.dumps(raw, ensure_ascii=False) + "\n")

    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
