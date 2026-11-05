from __future__ import annotations

from pathlib import Path
import json
import tempfile
from typing import Any, Callable

from .answer_validation import validate_agent_answer
from .conversation_memory import ConversationMemoryStore
from .cad_edit_contract import build_cad_edit_contract
from .cad_edit_gate import build_cad_edit_preflight
from .cad_target_resolver import bind_resolved_target, resolve_cad_target
from .cad_import import parse_dxf
from .geometry_diff import build_path_impact
from .incremental_cad import (
    edit_candidate_geometries,
    parse_incremental_edit,
    resolve_incremental_correction,
    resolve_incremental_followup,
)


DEFAULT_CORPUS_PATH = (
    Path(__file__).resolve().parents[1] / "evaluations" / "real_user_questions.json"
)
DEFAULT_CAD_CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "evaluations"
    / "cad_edit_chinese_commands.json"
)


def load_evaluation_corpus(path: Path | None = None) -> dict[str, Any]:
    source = path or DEFAULT_CORPUS_PATH
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("agent evaluation corpus must contain a cases list")
    return payload


def _tool_names(tools: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("function", {}).get("name", ""))
        for item in tools
        if isinstance(item, dict)
    }


def _route_case(
    case: dict[str, Any],
    route_intent: Callable[[str, str], dict[str, Any]],
    select_tools: Callable[..., list[dict[str, Any]]],
    resolve_intent: Callable[..., dict[str, Any]] | None,
) -> dict[str, Any]:
    expected = case["expected"]
    mode = case.get("mode", "base")
    if case.get("full_resolution") and resolve_intent is not None:
        route = resolve_intent(case["message"], mode, [])
    else:
        route = route_intent(case["message"], mode)
    tools = set()
    if not route.get("clarification_required"):
        tools = _tool_names(select_tools(case["message"], mode=mode))
    required_domains = set(expected.get("requested_domains", []))
    actual_domains = set(route.get("requested_data_domains", []))
    checks = {
        "intent": route.get("name") == expected["intent"],
        "operation": route.get("operation") == expected["operation"],
        "confirmation": bool(route.get("safety_confirmation_required"))
        == bool(expected.get("confirmation_required")),
        "clarification": bool(route.get("clarification_required"))
        == bool(expected.get("clarification_required")),
        "requested_domains": required_domains.issubset(actual_domains),
        "required_tools": set(expected.get("required_tools", [])).issubset(tools),
        "forbidden_tools": not set(expected.get("forbidden_tools", [])).intersection(tools),
    }
    return {
        "case_id": case["id"],
        "category": case["category"],
        "passed": all(checks.values()),
        "checks": checks,
        "actual": {
            "route": route,
            "selected_tools": sorted(tools),
        },
    }


def _reference_case(case: dict[str, Any], root: Path) -> dict[str, Any]:
    store = ConversationMemoryStore(root / f"{case['id']}.json")
    conversation_id = f"evaluation:{case['id']}"
    for seed in case.get("memory", []):
        store.remember(conversation_id, seed.get("message", ""), seed.get("result", {}))
    resolution = store.resolve(conversation_id, case["message"])
    expected = case["expected"]
    target = resolution.get("target") if isinstance(resolution.get("target"), dict) else {}
    checks = {
        "resolved": bool(resolution.get("resolved")) == bool(expected.get("resolved")),
        "ambiguous": bool(resolution.get("ambiguous")) == bool(expected.get("ambiguous")),
        "target_type": target.get("type") == expected.get("target_type"),
        "target_id": target.get("id") == expected.get("target_id"),
    }
    if expected.get("ambiguous"):
        checks["clarification"] = bool(resolution.get("question"))
    return {
        "case_id": case["id"],
        "category": case["category"],
        "passed": all(checks.values()),
        "checks": checks,
        "actual": {
            "resolved": resolution.get("resolved", False),
            "ambiguous": resolution.get("ambiguous", False),
            "target": target or None,
            "clarification_question": resolution.get("question"),
        },
    }


def _answer_case(case: dict[str, Any]) -> dict[str, Any]:
    corrected, validation = validate_agent_answer(
        case["answer"],
        case.get("route", {}),
        case.get("context", {}),
        case.get("tool_results", []),
        case.get("pending_action"),
        set(case.get("knowledge_source_ids", [])),
    )
    expected = case["expected"]
    issue_codes = {
        str(item.get("code"))
        for item in validation.get("issues", [])
        if isinstance(item, dict)
    }
    checks = {
        "issue_codes": set(expected.get("issue_codes", [])).issubset(issue_codes),
        "message_changed": bool(validation.get("message_changed"))
        == bool(expected.get("message_changed")),
        "required_text": all(
            text in corrected for text in expected.get("required_text", [])
        ),
        "forbidden_text": not any(
            text in corrected for text in expected.get("forbidden_text", [])
        ),
    }
    return {
        "case_id": case["id"],
        "category": case["category"],
        "passed": all(checks.values()),
        "checks": checks,
        "actual": {
            "answer": corrected,
            "validation_status": validation.get("status"),
            "issue_codes": sorted(issue_codes),
        },
    }


def _cad_edit_case(case: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a Chinese CAD command without calling an LLM or a robot."""
    expected = case.get("expected", {})
    message = str(case.get("message") or "")
    parsed = parse_incremental_edit(message)
    if expected.get("must_parse") is False:
        checks = {"must_reject": parsed is None}
        return _cad_case_result(case, checks, None, None, None, "")
    checks: dict[str, bool] = {
        "parsed": parsed is not None,
    }
    actual_contract: dict[str, Any] | None = None
    target: list[dict[str, Any]] | None = None
    preflight: dict[str, Any] | None = None
    error = ""
    if parsed is not None:
        try:
            actual_contract = build_cad_edit_contract(parsed, source_text=message)
        except (TypeError, ValueError) as exc:
            error = str(exc)
        checks["contract_valid"] = (actual_contract is not None) == bool(
            expected.get("contract_valid", True)
        )
        checks.update({
            "operation": parsed.get("operation") == expected.get("operation"),
            "coordinate_frame": parsed.get("coordinate_frame", "drawing")
            == expected.get("coordinate_frame", "drawing"),
        })
        expected_selector = expected.get("selector")
        if isinstance(expected_selector, dict):
            actual_selector = parsed.get("selector")
            checks["selector"] = isinstance(actual_selector, dict) and all(
                actual_selector.get(key) == value
                for key, value in expected_selector.items()
            )
        if actual_contract is not None:
            actual_target = actual_contract.get("target") or {}
            expected_ids = expected.get("instance_ids")
            if expected_ids is not None:
                checks["target_ids"] = sorted(actual_target.get("instance_ids") or []) == sorted(expected_ids)
            expected_geometry_ids = expected.get("geometry_ids")
            if expected_geometry_ids is not None:
                checks["target_geometry_ids"] = sorted(actual_target.get("geometry_ids") or []) == sorted(expected_geometry_ids)
            parameters = actual_contract.get("parameters") or {}
            for key in (
                "dx_mm", "dy_mm", "angle_degrees", "factor", "value_mm",
                "pivot", "direction", "distance_mm", "placement", "alignment",
            ):
                if key in expected:
                    checks[f"parameter_{key}"] = parameters.get(key) == expected[key]
    if expected.get("parse_only"):
        return _cad_case_result(case, checks, actual_contract, None, None, error)

    source = case.get("source_geometry")
    if not isinstance(source, list) or parsed is None:
        checks["source_geometry"] = False
        return _cad_case_result(case, checks, actual_contract, None, None, error)
    if actual_contract is None and expected.get("contract_valid", True):
        resolution = resolve_cad_target(parsed, source)
        if resolution.get("status") == "resolved":
            bind_resolved_target(parsed, resolution)
            try:
                actual_contract = build_cad_edit_contract(parsed, source_text=message)
            except (TypeError, ValueError) as exc:
                error = str(exc)
        checks["target_resolution"] = resolution.get("status") == "resolved"
        if actual_contract is not None:
            actual_target = actual_contract.get("target") or {}
            if expected.get("instance_ids") is not None:
                checks["target_ids"] = sorted(actual_target.get("instance_ids") or []) == sorted(expected["instance_ids"])
    target, edit_error = edit_candidate_geometries(source, parsed)
    if target is None:
        checks["geometry_execution"] = False
        error = edit_error or error
    else:
        checks["geometry_execution"] = True
        # Attribute, position and nested-geometry selectors become stable IDs
        # during execution. Validate and report the final authoritative target,
        # not the unresolved parser draft.
        try:
            actual_contract = build_cad_edit_contract(parsed, source_text=message)
            error = ""
        except (TypeError, ValueError) as exc:
            actual_contract = None
            error = str(exc)
        checks["contract_valid"] = (actual_contract is not None) == bool(
            expected.get("contract_valid", True)
        )
        if actual_contract is not None:
            actual_target = actual_contract.get("target") or {}
            if expected.get("instance_ids") is not None:
                checks["target_ids"] = sorted(
                    actual_target.get("instance_ids") or []
                ) == sorted(expected["instance_ids"])
            if expected.get("geometry_ids") is not None:
                checks["target_geometry_ids"] = sorted(
                    actual_target.get("geometry_ids") or []
                ) == sorted(expected["geometry_ids"])
        expected_count = expected.get("result_entity_count")
        if expected_count is not None:
            checks["result_entity_count"] = len(target) == expected_count
        expected_end = expected.get("expected_end")
        if isinstance(expected_end, dict):
            actual_end = next(
                (item.get("end") for item in target if item.get("id") == expected.get("end_geometry_id")),
                None,
            )
            checks["expected_end"] = actual_end == expected_end
        non_target_ids = expected.get("non_target_ids") or []
        if non_target_ids:
            before_by_id = {item.get("id"): item for item in source}
            after_by_id = {item.get("id"): item for item in target}
            checks["non_target_unchanged"] = all(
                before_by_id.get(item_id) == after_by_id.get(item_id)
                for item_id in non_target_ids
            )
        if actual_contract is not None:
            preflight = build_cad_edit_preflight(source, target, actual_contract)
            if "requires_confirmation" in expected:
                checks["requires_confirmation"] = (
                    preflight.get("requires_confirmation") is expected["requires_confirmation"]
                )
            if "requires_replan" in expected:
                checks["requires_replan"] = bool(
                    build_path_impact(source, target).get("requires_replan")
                ) is expected["requires_replan"]
    return _cad_case_result(case, checks, actual_contract, target, preflight, error)


def _cad_case_result(
    case: dict[str, Any],
    checks: dict[str, bool],
    contract: dict[str, Any] | None,
    target: list[dict[str, Any]] | None,
    preflight: dict[str, Any] | None,
    error: str,
) -> dict[str, Any]:
    passed = all(checks.values())
    return {
        "case_id": case["id"],
        "category": case["category"],
        "passed": passed,
        "checks": checks,
        "actual": {
            "contract": contract,
            "target_geometry": target,
            "preflight": preflight,
            "error": error,
        },
    }


def _nested_value(
    payload: dict[str, Any] | None, path: str,
) -> tuple[bool, Any]:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _counterfactual_contract(
    message: str, source: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any] | None, str]:
    parsed = parse_incremental_edit(message)
    if parsed is None:
        return None, "自然语言未解析为 CAD 修改"
    if isinstance(source, list):
        target, error = edit_candidate_geometries(source, parsed)
        if target is None:
            return None, error or "CAD 修改执行失败"
    try:
        return build_cad_edit_contract(parsed, source_text=message), ""
    except (TypeError, ValueError) as exc:
        return None, str(exc)


def _cad_counterfactual_case(case: dict[str, Any]) -> dict[str, Any]:
    """Prove that one language change causes only the declared contract changes."""
    expected = case.get("expected") or {}
    source = case.get("source_geometry")
    source_geometry = source if isinstance(source, list) else None
    base, base_error = _counterfactual_contract(
        str(case.get("base_message") or ""), source_geometry
    )
    variant, variant_error = _counterfactual_contract(
        str(case.get("variant_message") or ""), source_geometry
    )
    base_valid = base is not None
    variant_valid = variant is not None
    checks: dict[str, bool] = {
        "base_valid": base_valid == bool(expected.get("base_valid", True)),
        "variant_valid": variant_valid == bool(expected.get("variant_valid", True)),
    }
    for path, value in (expected.get("base_values") or {}).items():
        exists, observed = _nested_value(base, str(path))
        checks[f"base:{path}"] = exists and observed == value
    for path, value in (expected.get("variant_values") or {}).items():
        exists, observed = _nested_value(variant, str(path))
        checks[f"variant:{path}"] = exists and observed == value
    if base is not None and variant is not None:
        for path in expected.get("changed_paths") or []:
            base_exists, base_value = _nested_value(base, str(path))
            variant_exists, variant_value = _nested_value(variant, str(path))
            checks[f"changed:{path}"] = bool(
                base_exists and variant_exists and base_value != variant_value
            )
        for path in expected.get("unchanged_paths") or []:
            base_exists, base_value = _nested_value(base, str(path))
            variant_exists, variant_value = _nested_value(variant, str(path))
            checks[f"unchanged:{path}"] = bool(
                base_exists and variant_exists and base_value == variant_value
            )
    return {
        "case_id": case["id"],
        "category": case["category"],
        "passed": all(checks.values()),
        "checks": checks,
        "actual": {
            "base_contract": base,
            "variant_contract": variant,
            "base_error": base_error,
            "variant_error": variant_error,
        },
    }


def _cad_followup_case(case: dict[str, Any]) -> dict[str, Any]:
    expected = case.get("expected", {})
    previous = case.get("previous_contract")
    instances = case.get("available_instance_ids")
    if case.get("followup_type") == "correction":
        resolved = resolve_incremental_correction(case["message"], previous, instances)
    else:
        resolved = resolve_incremental_followup(case["message"], previous, instances)
    expected_text = expected.get("resolved_text")
    checks = {
        "resolution": resolved == expected_text,
        "must_resolve": (resolved is not None) == bool(expected.get("must_resolve", True)),
    }
    parsed = parse_incremental_edit(resolved) if resolved else None
    if expected.get("operation") is not None:
        checks["operation"] = parsed is not None and parsed.get("operation") == expected["operation"]
    return {
        "case_id": case["id"],
        "category": case["category"],
        "passed": all(checks.values()),
        "checks": checks,
        "actual": {"resolved_text": resolved, "parsed": parsed},
    }


def _cad_dxf_case(case: dict[str, Any]) -> dict[str, Any]:
    root = Path(str(case.get("_corpus_root") or "")).resolve()
    source = (root / str(case.get("file") or "")).resolve()
    expected = case.get("expected", {})
    within_root = source == root or root in source.parents
    checks: dict[str, bool] = {
        "fixture_path": within_root and source.is_file(),
    }
    payload: dict[str, Any] = {}
    warnings: list[str] = []
    error = ""
    if checks["fixture_path"]:
        try:
            payload, warnings = parse_dxf(source, str(case.get("unit") or "auto"))
        except (RuntimeError, ValueError, OSError) as exc:
            error = str(exc)
    geometries = payload.get("lines") if isinstance(payload.get("lines"), list) else []
    analysis = payload.get("cad_analysis") if isinstance(payload.get("cad_analysis"), dict) else {}
    ids = [item.get("id") for item in geometries if isinstance(item, dict)]
    checks.update({
        "parsed": bool(payload),
        "entity_count": len(geometries) == expected.get("entity_count"),
        "unique_ids": len(ids) == len(set(ids)) == len(geometries),
        "entity_types": set(expected.get("entity_types", [])).issubset({
            str(item.get("type")) for item in geometries if isinstance(item, dict)
        }),
        "layer_confirmation": bool(analysis.get("layer_roles_confirmed"))
        == bool(expected.get("layer_roles_confirmed")),
        "printing_geometry_count": int(analysis.get("printing_geometry_count") or 0)
        == int(expected.get("printing_geometry_count") or 0),
    })
    return {
        "case_id": case["id"],
        "category": case["category"],
        "passed": all(checks.values()),
        "checks": checks,
        "actual": {
            "file": source.name,
            "cad_analysis": analysis,
            "warnings": warnings,
            "error": error,
        },
    }


def run_policy_evaluation(
    route_intent: Callable[[str, str], dict[str, Any]],
    select_tools: Callable[..., list[dict[str, Any]]],
    resolve_intent: Callable[..., dict[str, Any]] | None = None,
    corpus_path: Path | None = None,
) -> dict[str, Any]:
    """Run deterministic, read-only agent acceptance checks."""
    corpus = load_evaluation_corpus(corpus_path)
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="xline-agent-evaluation-") as temporary:
        root = Path(temporary)
        for case in corpus["cases"]:
            case = {**case, "_corpus_root": str((corpus_path or DEFAULT_CORPUS_PATH).parent)}
            if case.get("kind") in {"cad_edit", "cad_counterfactual"} and case.get("source_fixture"):
                fixture = (corpus.get("fixtures") or {}).get(case["source_fixture"])
                case = {**case, "source_geometry": fixture}
            kind = case.get("kind")
            if kind == "route":
                result = _route_case(
                    case, route_intent, select_tools, resolve_intent
                )
            elif kind == "reference":
                result = _reference_case(case, root)
            elif kind == "answer":
                result = _answer_case(case)
            elif kind == "cad_edit":
                result = _cad_edit_case(case)
            elif kind == "cad_counterfactual":
                result = _cad_counterfactual_case(case)
            elif kind == "cad_followup":
                result = _cad_followup_case(case)
            elif kind == "cad_dxf":
                result = _cad_dxf_case(case)
            else:
                result = {
                    "case_id": case.get("id", "unknown"),
                    "category": case.get("category", "invalid"),
                    "passed": False,
                    "checks": {"supported_kind": False},
                    "actual": {"kind": kind},
                }
            results.append(result)

    passed = sum(1 for item in results if item["passed"])
    categories: dict[str, dict[str, int | bool]] = {}
    for item in results:
        summary = categories.setdefault(item["category"], {"passed": 0, "total": 0})
        summary["total"] = int(summary["total"]) + 1
        summary["passed"] = int(summary["passed"]) + int(item["passed"])
    for summary in categories.values():
        summary["ok"] = summary["passed"] == summary["total"]

    return {
        "ok": passed == len(results),
        "schema_version": "2.1",
        "corpus_version": corpus.get("version", "unknown"),
        "evaluation_type": "deterministic_real_user_acceptance",
        "external_api_called": False,
        "robot_control_called": False,
        "read_only": True,
        "passed": passed,
        "total": len(results),
        "categories": categories,
        "results": results,
    }
