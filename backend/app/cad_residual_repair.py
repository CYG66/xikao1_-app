"""Unified, measured CAD residual records and bounded repair policy.

P3 does not generate geometry and does not infer an expected value that no
verifier measured.  It consumes the existing verifier/acceptance evidence,
normalises numeric excess over tolerance, keeps discrete/topological states
separate, and exposes a repair scope + feedback payload for the existing
generation-recovery protocol.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from typing import Any, Iterable

SCHEMA = "cad.residual-vector.v1"
RECORD_SCHEMA = "cad.residual-record.v1"

NUMERIC = "numeric"
DISCRETE = "discrete"
TOPOLOGY = "topology"
UNVERIFIABLE = "unverifiable"

_PARAMETER_PREDICATES = {
    "width", "height", "radius", "diameter", "length", "area", "distance",
    "center_distance", "angle", "degrees", "spacing", "gap", "scale",
}
_POSITION_PREDICATES = {"center", "position", "location", "offset"}
_CONNECTION_PREDICATES = {"continuity", "closure_connection", "endpoint", "junction"}
_CURVE_PREDICATES = {"curve_type", "curve_identity", "bezier", "spline"}
_STRUCTURE_PREDICATES = {"entity_count", "object_count", "topology", "containment",
                         "connectivity", "self_intersection", "object_identity",
                         "identity", "object_id_uniqueness", "segment_count",
                         "shape_preservation"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _finite(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and math.isfinite(number) else None


def normalized_numeric_residual(measured: float, expected: float,
                                tolerance: float) -> float:
    """Return excess over tolerance, in tolerance units.

    r_i = max(0, |m_i - e_i| / tau_i - 1)
    This value is dimensionless and may be compared across numeric facts.  A
    non-positive tolerance cannot be normalised; callers must use an absolute
    difference instead and record ``tolerance=0`` explicitly.
    """
    if tolerance <= 0:
        return 0.0 if abs(measured - expected) <= 0 else abs(measured - expected)
    return max(0.0, abs(measured - expected) / tolerance - 1.0)


def _predicate_kind(predicate: str) -> str:
    word = str(predicate or "").lower()
    if any(token in word for token in _STRUCTURE_PREDICATES):
        return "structure_replan"
    if any(token in word for token in _CURVE_PREDICATES):
        return "component_replan"
    if any(token in word for token in _CONNECTION_PREDICATES):
        return "control_point_repair"
    if any(token in word for token in _POSITION_PREDICATES):
        return "object_placement"
    return "parameter_repair"


def _make_record(
    *,
    requirement_id: str,
    predicate: str,
    expected: Any,
    measured: Any,
    tolerance: float | None,
    unit: str | None,
    residual_type: str,
    verification_status: str = "measured",
    object_ids: Iterable[Any] | None = None,
    geometry_ids: Iterable[Any] | None = None,
    plan_step_ids: Iterable[Any] | None = None,
    source: str = "backend_measurement",
    mandatory: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    object_ids = [str(v) for v in (object_ids or []) if v is not None]
    geometry_ids = [v for v in (geometry_ids or []) if v is not None]
    plan_step_ids = [str(v) for v in (plan_step_ids or []) if v is not None]
    expected_value = deepcopy(expected)
    measured_value = deepcopy(measured)
    delta = None
    residual = None
    passed = None
    normalised = None

    if residual_type == NUMERIC:
        e = _finite(expected)
        m = _finite(measured)
        if e is None or m is None:
            residual_type = UNVERIFIABLE
            verification_status = "unverified"
        else:
            delta = abs(m - e)
            tau = _finite(tolerance) if tolerance is not None else None
            if tau is None or tau < 0:
                residual_type = UNVERIFIABLE
                verification_status = "unverified"
                reason = reason or "numeric_tolerance_missing"
            else:
                normalised = normalized_numeric_residual(m, e, tau)
                residual = normalised
                passed = delta <= tau
    elif residual_type in {DISCRETE, TOPOLOGY}:
        if measured is None or verification_status == "unverified":
            residual_type = UNVERIFIABLE
            verification_status = "unverified"
            residual = None
            passed = None
        else:
            equal = expected == measured
            passed = bool(equal)
            residual = 0.0 if equal else 1.0
    else:
        residual_type = UNVERIFIABLE
        if verification_status in {"measured", None}:
            verification_status = "unverified"
        passed = None

    scope = {
        "strategy": ("diagnose_or_clarify" if residual_type == UNVERIFIABLE
                     else _predicate_kind(predicate)),
        "object_ids": list(object_ids),
        "geometry_ids": list(geometry_ids),
        "plan_step_ids": list(plan_step_ids),
        "scope_reason": reason or "direct_measurement",
    }
    return {
        "schema": RECORD_SCHEMA,
        "requirement_id": str(requirement_id),
        "predicate": str(predicate),
        "object_ids": object_ids,
        "geometry_ids": geometry_ids,
        "plan_step_ids": plan_step_ids,
        "expected": expected_value,
        "measured": measured_value,
        "tolerance": tolerance,
        "delta": delta,
        "unit": unit,
        "residual_type": residual_type,
        "verification_status": verification_status,
        "normalized_residual": normalised,
        "passed": passed,
        "mandatory": bool(mandatory),
        "source": source,
        "repair_scope": scope,
        "reason": reason,
    }


def numeric_residual(*, requirement_id: str, predicate: str, expected: float,
                     measured: float, tolerance: float, unit: str = "mm",
                     source: str = "backend_measurement", mandatory: bool = False,
                     **scope) -> dict[str, Any]:
    return _make_record(requirement_id=requirement_id, predicate=predicate,
                        expected=expected, measured=measured,
                        tolerance=tolerance, unit=unit,
                        residual_type=NUMERIC, source=source,
                        mandatory=mandatory, **scope)


def discrete_residual(*, requirement_id: str, predicate: str, expected: Any,
                      measured: Any, unit: str | None = None,
                      residual_type: str = DISCRETE,
                      source: str = "backend_measurement",
                      mandatory: bool = False, **scope) -> dict[str, Any]:
    return _make_record(requirement_id=requirement_id, predicate=predicate,
                        expected=expected, measured=measured, tolerance=None,
                        unit=unit, residual_type=residual_type, source=source,
                        mandatory=mandatory, **scope)


def unverifiable_residual(*, requirement_id: str, predicate: str,
                          reason: str, source: str = "backend_measurement",
                          **scope) -> dict[str, Any]:
    return _make_record(requirement_id=requirement_id, predicate=predicate,
                        expected=None, measured=None, tolerance=None,
                        unit=None, residual_type=UNVERIFIABLE,
                        verification_status="not_checked", source=source,
                        reason=reason, **scope)


def _record_key(record: dict[str, Any]) -> tuple:
    return (str(record.get("requirement_id") or ""),
            str(record.get("predicate") or ""),
            str(record.get("unit") or ""),
            str(record.get("predicate_axis") or ""))


def merge_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        key = _record_key(record)
        merged[key] = deepcopy(record)
    return sorted(merged.values(), key=_record_key)


def residual_vector(records: Iterable[dict[str, Any]], *,
                    source: str = "backend_measurement",
                    protected_output_refs: Iterable[str] | None = None) -> dict[str, Any]:
    items = merge_records(records)
    numeric = [r for r in items if r["residual_type"] == NUMERIC
               and r["verification_status"] == "measured"]
    discrete = [r for r in items if r["residual_type"] == DISCRETE]
    topology = [r for r in items if r["residual_type"] == TOPOLOGY]
    unverified = [r for r in items if r["residual_type"] == UNVERIFIABLE]
    failing_numeric = [r for r in numeric if r["passed"] is False]
    failing_discrete = [r for r in discrete + topology if r["passed"] is False]
    scope = {}
    for record in failing_numeric + failing_discrete:
        repair = record.get("repair_scope") or {}
        for ref in repair.get("plan_step_ids") or []:
            scope.setdefault(repair.get("strategy") or "parameter_repair", set()).add(ref)
    return {
        "schema": SCHEMA,
        "source": source,
        "records": items,
        "record_count": len(items),
        "numeric_count": len(numeric),
        "discrete_count": len(discrete) + len(topology),
        "unverifiable_count": len(unverified),
        "failing_numeric_count": len(failing_numeric),
        "failing_discrete_count": len(failing_discrete),
        "continuous_score": sum(float(r.get("normalized_residual") or 0.0)
                                for r in failing_numeric),
        "max_normalized_residual": max(
            [float(r.get("normalized_residual") or 0.0) for r in failing_numeric]
            or [0.0]),
        "discrete_failures": [deepcopy(r) for r in failing_discrete],
        "unverifiable": [deepcopy(r) for r in unverified],
        "repair_targets": {k: sorted(v) for k, v in scope.items()},
        "protected_output_refs": sorted(set(protected_output_refs or [])),
        "authority": "backend_measured_geometry",
        "real_model_calls": 0,
    }


def _step_ids_for_ref(plan: dict[str, Any] | None, output_ref: str | None,
                      assertion_id: str | None = None) -> list[str]:
    if not isinstance(plan, dict):
        return []
    steps = plan.get("steps") or []
    if output_ref:
        return [str(s.get("step_id")) for s in steps
                if isinstance(s, dict) and s.get("output_ref") == output_ref
                and s.get("step_id")]
    if assertion_id:
        for assertion in plan.get("assertions") or []:
            if isinstance(assertion, dict) and assertion.get("assertion_id") == assertion_id:
                target = assertion.get("target_ref")
                return [str(s.get("step_id")) for s in steps
                        if isinstance(s, dict) and s.get("output_ref") == target
                        and s.get("step_id")]
    return []


def _measure_bounds_mm(bounds: dict[str, Any] | None) -> tuple[float, float] | None:
    if not isinstance(bounds, dict):
        return None
    values = [_finite(bounds.get(k)) for k in ("min_x", "max_x", "min_y", "max_y")]
    if any(v is None for v in values):
        return None
    return (values[1] - values[0], values[3] - values[2])


def _assertion_records(failure: dict[str, Any], plan: dict[str, Any] | None,
                       scale: float, *, source: str,
                       mandatory: bool = False) -> list[dict[str, Any]]:
    assertion = failure.get("expected_assertion") or {}
    if not isinstance(assertion, dict):
        return []
    kind = str(assertion.get("kind") or "")
    target = assertion.get("target_ref")
    assertion_id = str(assertion.get("assertion_id") or failure.get("assertion_id") or "")
    geometry_ids = failure.get("geometry_ids") or []
    step_ids = _step_ids_for_ref(plan, target, assertion_id)
    common = {
        "requirement_id": f"assertion:{assertion_id or kind or 'unknown'}",
        "source": source,
        "mandatory": mandatory,
        "geometry_ids": geometry_ids,
        "plan_step_ids": step_ids,
        "reason": "model_assertion_failed" if not mandatory else "source_requirement_failed",
    }
    records: list[dict[str, Any]] = []
    if kind == "bounds_size":
        measured = _measure_bounds_mm(failure.get("measured_bounds_mm"))
        if measured:
            width, height = measured
            records.append(numeric_residual(
                predicate="width", expected=float(assertion.get("width") or 0.0) * scale,
                measured=width, tolerance=float(assertion.get("tolerance") or 0.0) * scale,
                unit="mm", **common))
            records.append(numeric_residual(
                predicate="height", expected=float(assertion.get("height") or 0.0) * scale,
                measured=height, tolerance=float(assertion.get("tolerance") or 0.0) * scale,
                unit="mm", **common))
    elif kind == "entity_count":
        records.append(discrete_residual(
            predicate="entity_count", expected=int(assertion.get("equals") or 0),
            measured=len(geometry_ids), unit="count", residual_type=TOPOLOGY,
            **common))
    elif kind == "closed":
        records.append(discrete_residual(
            predicate="closure", expected=True, measured=False,
            unit="state", **common))
    elif kind == "area":
        measured_area = _finite(failure.get("measured_area"))
        if measured_area is not None:
            records.append(numeric_residual(
                predicate="area", expected=float(assertion.get("area") or 0.0) * scale * scale,
                measured=measured_area, tolerance=float(assertion.get("tolerance") or 0.0) * scale * scale,
                unit="mm2", **common))
    elif kind == "radial_pattern":
        details = failure.get("details") or {}
        observed = details.get("observed_radial_peaks")
        if observed is None:
            observed = details.get("observed_lobes")
        if observed is not None:
            records.append(discrete_residual(
                predicate="radial_lobes", expected=int(assertion.get("lobes") or 0),
                measured=int(observed), unit="count", residual_type=TOPOLOGY,
                **common))
    return records


def collect_construction_error_residuals(error: dict[str, Any] | None,
                                         plan: dict[str, Any] | None = None,
                                         scale: float = 1000.0) -> list[dict[str, Any]]:
    details = (error or {}).get("details") or {}
    records: list[dict[str, Any]] = []
    for failure in details.get("failures") or []:
        if isinstance(failure, dict):
            records.extend(_assertion_records(failure, plan, scale,
                                               source="model_assertion"))
    for conflict in details.get("identity_conflicts") or []:
        if not isinstance(conflict, dict):
            continue
        steps = []
        for member in conflict.get("members") or []:
            for source_step in member.get("source_steps") or []:
                if isinstance(source_step, dict) and source_step.get("step_id"):
                    steps.append(str(source_step["step_id"]))
        records.append(discrete_residual(
            requirement_id=f"identity:{conflict.get('object_id') or 'unknown'}",
            predicate="object_identity", expected="distinct_object_ids",
            measured="shared_object_id", unit="identity",
            residual_type=TOPOLOGY, source="logical_graph_validation",
            geometry_ids=conflict.get("geometry_refs") or [],
            plan_step_ids=steps,
            reason="identity_conflict"))
    for validation in details.get("validation_errors") or []:
        if not isinstance(validation, dict):
            continue
        if str(validation.get("code") or "") not in {
                "invalid_object_ids", "duplicate_object_id"}:
            continue
        records.append(discrete_residual(
            requirement_id="identity:object_ids",
            predicate="object_id_uniqueness", expected="unique",
            measured="duplicate", unit="state",
            residual_type=TOPOLOGY, source="logical_graph_validation",
            plan_step_ids=[],
            reason=str(validation.get("code") or "invalid_object_ids")))
    expected_count = details.get("expected_count")
    actual_count = details.get("actual_count")
    if expected_count is not None and actual_count is not None:
        records.append(discrete_residual(
            requirement_id=str(details.get("source_requirement_id")
                               or "construction:object_count"),
            predicate="object_count", expected=int(expected_count),
            measured=int(actual_count), unit="count", residual_type=TOPOLOGY,
            source="source_acceptance", mandatory=True,
            geometry_ids=details.get("geometry_ids") or [],
            plan_step_ids=[],
            reason="source_object_count_mismatch"))
    if details.get("expected_mm") is not None and details.get("measured_mm") is not None:
        records.append(numeric_residual(
            requirement_id=str(details.get("source_requirement_id") or "construction:dimension"),
            predicate=str(details.get("field") or "dimension"),
            expected=float(details["expected_mm"]), measured=float(details["measured_mm"]),
            tolerance=float(details.get("tolerance_mm") or 0.5), unit="mm",
            source="source_acceptance", mandatory=True,
            reason="source_dimension_mismatch"))
    return records


def _walk_checks(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if "checks" in value and isinstance(value["checks"], list):
            for check in value["checks"]:
                if isinstance(check, dict):
                    yield check
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                yield from _walk_checks(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_checks(item)


def collect_source_acceptance_residuals(
    source_acceptance: dict[str, Any] | None,
    plan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(source_acceptance, dict):
        return []
    records: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for check in _walk_checks(source_acceptance):
        status = str(check.get("status") or "")
        if status not in {"failed", "unverified", "review_required", "partial"}:
            continue
        requirement_id = str(check.get("source_requirement_id")
                             or check.get("requirement_id")
                             or check.get("name")
                             or "source:unknown")
        predicate = str(check.get("field") or check.get("name")
                        or check.get("predicate") or "source_requirement")
        expected = check.get("expected_mm", check.get("expected"))
        measured = check.get("actual_mm", check.get("actual", check.get("measured")))
        tolerance = check.get("tolerance_mm", check.get("tolerance"))
        unit = check.get("unit") or ("mm" if "expected_mm" in check or "actual_mm" in check else None)
        key = (requirement_id, predicate, str(unit or ""))
        if key in seen:
            continue
        seen.add(key)
        target = check.get("target_ref") or check.get("output_ref")
        common = {
            "geometry_ids": check.get("geometry_ids") or [],
            "plan_step_ids": _step_ids_for_ref(plan, target),
            "source": "source_acceptance",
            "mandatory": status == "failed",
        }
        if expected is not None and measured is not None and tolerance is not None:
            records.append(numeric_residual(
                requirement_id=requirement_id, predicate=predicate,
                expected=float(expected), measured=float(measured),
                tolerance=float(tolerance), unit=unit or "mm",
                reason=str(check.get("reason") or "source_check_failed"), **common))
        elif status == "failed":
            records.append(discrete_residual(
                requirement_id=requirement_id, predicate=predicate,
                expected=check.get("expected", True),
                measured=check.get("measured", False), unit=unit,
                reason=str(check.get("reason") or "source_check_failed"), **common))
        else:
            records.append(unverifiable_residual(
                requirement_id=requirement_id, predicate=predicate,
                reason=str(check.get("reason") or "source_verifier_unavailable"),
                **common))
    for item in source_acceptance.get("unknown_requirements") or []:
        if not isinstance(item, dict):
            continue
        requirement_id = str(item.get("requirement_id")
                             or item.get("source_requirement_id") or "source:unknown")
        key = (requirement_id, "source_requirement_verification", "")
        if key in seen:
            continue
        seen.add(key)
        records.append(unverifiable_residual(
            requirement_id=requirement_id,
            predicate="source_requirement_verification",
            reason=str(item.get("reason") or "not_measured"),
            source="source_acceptance"))
    return records


def build_residual_vector(
    *,
    construction_error: dict[str, Any] | None = None,
    source_acceptance: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    scale: float = 1000.0,
    source: str = "backend_measurement",
    protected_output_refs: Iterable[str] | None = None,
) -> dict[str, Any]:
    records = collect_construction_error_residuals(construction_error, plan, scale)
    records.extend(collect_source_acceptance_residuals(source_acceptance, plan))
    if protected_output_refs is None and isinstance(plan, dict):
        protected = [str(s.get("output_ref")) for s in plan.get("steps") or []
                     if isinstance(s, dict) and s.get("output_ref")]
    else:
        protected = protected_output_refs
    return residual_vector(records, source=source,
                           protected_output_refs=protected)


def repair_feedback(vector_or_records: dict[str, Any] | Iterable[dict[str, Any]],
                    plan: dict[str, Any] | None = None,
                    max_records: int = 12) -> dict[str, Any]:
    vector = (vector_or_records if isinstance(vector_or_records, dict)
              and vector_or_records.get("schema") == SCHEMA
              else residual_vector(vector_or_records))
    actionable = [r for r in vector.get("records") or []
                  if r.get("passed") is False or r.get("residual_type") == UNVERIFIABLE]
    actionable = actionable[:max_records]
    targets: set[str] = set()
    protected: set[str] = set()
    rows = []
    for record in actionable:
        scope = record.get("repair_scope") or {}
        targets.update(scope.get("plan_step_ids") or [])
        geometry = record.get("geometry_ids") or []
        if record.get("passed") is False and record.get("residual_type") == NUMERIC:
            instruction = "修正该参数的数值，使实测进入容差范围"
        elif record.get("residual_type") == DISCRETE:
            instruction = "按期望状态替换离散类型或身份，不做毫米级伪造"
        elif record.get("residual_type") == TOPOLOGY:
            instruction = "重规划对象数量或拓扑组成，保留无关部件"
        else:
            instruction = "当前验证器无法测量，先诊断或澄清，不得伪造残差"
        rows.append({
            "requirement_id": record.get("requirement_id"),
            "predicate": record.get("predicate"),
            "expected": record.get("expected"),
            "measured": record.get("measured"),
            "tolerance": record.get("tolerance"),
            "delta": record.get("delta"),
            "unit": record.get("unit"),
            "type": record.get("residual_type"),
            "strategy": scope.get("strategy"),
            "plan_step_ids": scope.get("plan_step_ids") or [],
            "geometry_ids": geometry,
            "instruction": instruction,
            "verification_status": record.get("verification_status"),
        })
    if isinstance(plan, dict):
        step_to_output = {
            str(s.get("step_id")): str(s.get("output_ref"))
            for s in plan.get("steps") or []
            if isinstance(s, dict) and s.get("step_id") and s.get("output_ref")
        }
        all_step_ids = set(step_to_output)
        editable_output = sorted({step_to_output[s] for s in targets if s in step_to_output})
        protected = {step_to_output[s] for s in all_step_ids - targets if s in step_to_output}
        editable_steps = sorted(targets)
        protected_steps = sorted(all_step_ids - targets)
    else:
        editable_output = sorted(targets)
        protected_steps = []
        editable_steps = sorted(targets)
    prompt_lines = ["结构化几何残差（只修下列目标，禁止重写无关部件）："]
    for row in rows:
        prompt_lines.append(json.dumps(row, ensure_ascii=False))
    prompt_lines.append("连续修复须逐项复验；5%阈值只判断进展，不代表正式验收通过。"
                        "不得删除约束、放宽容差或修改用户需求来取得进展。")
    return {
        "schema": "cad.residual-repair-feedback.v1",
        "summary": {
            "continuous_score": vector.get("continuous_score"),
            "max_normalized_residual": vector.get("max_normalized_residual"),
            "failing_numeric_count": vector.get("failing_numeric_count"),
            "failing_discrete_count": vector.get("failing_discrete_count"),
            "unverifiable_count": vector.get("unverifiable_count"),
        },
        "records": rows,
        "editable_step_ids": editable_steps,
        "protected_step_ids": protected_steps,
        "editable_output_refs": editable_output,
        "protected_output_refs": sorted(protected),
        "must_not": ["delete_constraints", "widen_tolerance", "change_user_requirement",
                     "modify_unrelated_objects", "fabricate_measurement"],
        "prompt_text": "\n".join(prompt_lines),
    }


def feedback_text(base: str, vector_or_records: Any,
                  plan: dict[str, Any] | None = None) -> str:
    """Append the structured residual block to the existing repair prompt."""
    feedback = repair_feedback(vector_or_records, plan)
    return (str(base or "") + "\n" + feedback["prompt_text"]
            + "\n可编辑输出步骤：" + json.dumps(
                feedback["editable_output_refs"], ensure_ascii=False)
            + "\n必须保持的输出步骤：" + json.dumps(
                feedback["protected_output_refs"], ensure_ascii=False)
            + "\n禁止：" + json.dumps(feedback["must_not"], ensure_ascii=False))


def _as_vector(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("schema") == SCHEMA:
        return value
    if isinstance(value, dict) and isinstance(value.get("residual_vector"), dict):
        return value["residual_vector"]
    if isinstance(value, list):
        return residual_vector(value)
    if isinstance(value, dict) and "records" in value:
        return value
    return residual_vector([])


def evaluate_residual_progress(before: Any, after: Any,
                               improvement_threshold: float = 0.05) -> dict[str, Any]:
    prev = _as_vector(before)
    curr = _as_vector(after)
    before_records = {_record_key(r): r for r in prev.get("records") or []}
    after_records = {_record_key(r): r for r in curr.get("records") or []}

    regressions = []
    for key, old in before_records.items():
        if (old.get("mandatory") and old.get("passed") is True
                and key in after_records and after_records[key].get("passed") is False):
            regressions.append(deepcopy(after_records[key]))
    new_failures = []
    for key, new in after_records.items():
        if new.get("passed") is False and (
                key not in before_records or before_records[key].get("passed") is not False):
            new_failures.append(deepcopy(new))

    score_before = float(prev.get("continuous_score") or 0.0)
    score_after = float(curr.get("continuous_score") or 0.0)
    if score_before > 0:
        relative_improvement = max(0.0, (score_before - score_after) / score_before)
    else:
        # No excess residual existed before: nothing can improve.  A later
        # non-zero score is a new failure, not progress.
        relative_improvement = 0.0
    discrete_before = int(prev.get("failing_discrete_count") or 0)
    discrete_after = int(curr.get("failing_discrete_count") or 0)
    unverified_before = int(prev.get("unverifiable_count") or 0)
    unverified_after = int(curr.get("unverifiable_count") or 0)
    # A failure that merely stops being measured is not a repair.  Require the
    # amount of unverifiable evidence not to grow before calling it progress.
    discrete_improved = (discrete_after < discrete_before
                         and unverified_after <= unverified_before)

    numeric_improved = (relative_improvement >= improvement_threshold
                        and unverified_after <= unverified_before)
    reasons = []
    if regressions:
        reasons.append("previously passed mandatory requirement regressed")
        decision, progress = "block", "regression"
    elif numeric_improved:
        reasons.append("continuous excess residual improved by >= 5%")
        decision, progress = "allow", "improved"
    elif discrete_improved:
        reasons.append("discrete/topological failure count decreased")
        decision, progress = "allow", "improved"
    else:
        reasons.append("no effective residual improvement")
        decision, progress = "allow", "no_improvement"
        if new_failures:
            reasons.append("new failing residual appeared without effective improvement")
    return {
        "decision": decision,
        "progress": progress,
        "effective_improvement": progress == "improved",
        "relative_improvement": relative_improvement,
        "score_before": score_before,
        "score_after": score_after,
        "discrete_before": discrete_before,
        "discrete_after": discrete_after,
        "regressions": regressions,
        "new_failures": new_failures,
        "reasons": reasons,
        "threshold": improvement_threshold,
        "threshold_scope": "continuous_excess_residual_only",
    }


def _progress_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("progress") or "")
    return str(value or "")


def two_consecutive_no_improvement(decisions: Iterable[str]) -> bool:
    values = [_progress_name(value) for value in decisions]
    return len(values) >= 2 and values[-2:] == ["no_improvement", "no_improvement"]


def repair_budget_state(decisions: Iterable[str], repair_count: int,
                        max_repairs: int = 2) -> dict[str, Any]:
    values = list(decisions)
    stalled = two_consecutive_no_improvement(values)
    return {
        "repair_count": repair_count,
        "max_repairs": max_repairs,
        "repair_stalled": stalled,
        "allow_next_repair": repair_count < max_repairs and not stalled,
        "third_repair_allowed": False,
    }
