"""Internal FEATURE-CONTRACT sidecar: source-traceable geometric feature declarations.

Phase 1 scope (shadow only):
- This module records feature contracts, bindings and measurements alongside the
  existing plan. It never blocks or releases a candidate; a failed feature contract
  is a shadow conclusion only.
- It does NOT enter ``CadConstructionPlan v1`` assertion/constraint unions and does
  NOT modify the public HTTP schema. Feature Contract / Binding / Measurement have
  an independent lifecycle.
- It reuses :func:`requirement_contract` and :func:`build_requirement_source_index`;
  no second dimension/user-source fact ledger is built here.

Source classes (mutually exclusive, never upgraded between classes):
- ``explicit``: user-stated requirement; may carry mandatory acceptance and H3 user
  source authorization.
- ``derived_semantic``: produced by a versioned, authorized semantic rule; may enter
  independent semantic acceptance only; cannot impersonate explicit or replace H3
  user source authorization.
- ``model_assumption``: non-authoritative assumption; advisory only, never mandatory.
"""
from __future__ import annotations

from typing import Any

from .cad_requirement_contract import (
    build_requirement_source_index,
    requirement_contract,
)

FEATURE_CLASSES = {
    "boundary_extremum",
    "cusp",
    "notch",
    "mirror_symmetry",
    "continuity",
}

SOURCE_CLASSES = {"explicit", "derived_semantic", "model_assumption"}
ACCEPTANCE_SCOPES = {"mandatory", "semantic_only", "advisory"}
MEASUREMENT_STATUSES = {"measured", "undetermined", "not_applicable"}

#: Scope each source class is allowed to declare. Classes never upgrade:
#: derived_semantic cannot reach mandatory; model_assumption cannot leave advisory.
_ALLOWED_SCOPES = {
    "explicit": {"mandatory", "semantic_only", "advisory"},
    "derived_semantic": {"semantic_only", "advisory"},
    "model_assumption": {"advisory"},
}

#: Versioned registry of semantic rules authorized to produce derived_semantic
#: features. A derived declaration whose rule/version is absent here fails closed.
AUTHORIZED_DERIVATION_RULES: dict[str, dict[str, Any]] = {
    "shape_outline_features": {
        "versions": {"1": {"authorized": True}},
    },
}

BINDING_SCHEMA = "cad.feature-binding.v1"
CONTRACT_SCHEMA = "cad.feature-contract.v1"
MEASUREMENT_SCHEMA = "cad.feature-measurement.v1"


def build_feature_source_index(ledger: dict[str, Any]) -> dict[str, Any]:
    """Reuse the existing requirement contract and immutable source index.

    Accepts either a project ledger (carrying ``requirement_contract``) or a raw
    contract dict. Does not recompute facts or build a second source ledger.
    """
    contract = ledger.get("requirement_contract") if isinstance(ledger, dict) else None
    if contract is None:
        contract = ledger
    source_index = build_requirement_source_index(contract)
    return {"contract": contract, "source_index": source_index}


def _error(code: str, feature_id: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "feature_id": feature_id, "message": message, **details}


def _validate_evidence(
    evidence: dict[str, Any] | None,
    entries: dict[str, dict[str, Any]],
    contract_version: str,
    feature_id: str,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(evidence, dict):
        return [_error("fc_evidence_missing", feature_id, "evidence block is required")]
    ref = str(evidence.get("source_ref") or "")
    entry = entries.get(ref)
    if entry is None:
        errors.append(_error("fc_unknown_source_ref", feature_id,
                             f"source ref {ref!r} is not in the valid source index",
                             source_ref=ref))
        return errors
    text = str(entry.get("original_text") or "")
    start = evidence.get("start")
    end = evidence.get("end")
    if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end > len(text) or end < start:
        errors.append(_error("fc_evidence_span_out_of_range", feature_id,
                             "evidence span is outside the source text",
                             source_ref=ref, start=start, end=end, source_length=len(text)))
        return errors
    if text[start:end] != str(evidence.get("text") or ""):
        errors.append(_error("fc_evidence_text_mismatch", feature_id,
                             "evidence text does not match the source slice",
                             source_ref=ref, start=start, end=end,
                             expected=text[start:end], actual=evidence.get("text")))
    if evidence.get("source_revision") != contract_version:
        errors.append(_error("fc_source_revision_mismatch", feature_id,
                             "evidence source_revision does not match the current contract revision",
                             source_ref=ref, expected_revision=contract_version,
                             actual_revision=evidence.get("source_revision")))
    return errors


def _validate_derivation(
    source_class: str,
    derivation: dict[str, Any] | None,
    feature_id: str,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if source_class != "derived_semantic":
        return errors
    if not isinstance(derivation, dict) or not derivation.get("rule_id") or not derivation.get("rule_version"):
        errors.append(_error("fc_derivation_rule_missing", feature_id,
                             "derived_semantic requires rule_id and rule_version"))
        return errors
    rule = AUTHORIZED_DERIVATION_RULES.get(str(derivation["rule_id"]))
    version = (rule or {}).get("versions", {}).get(str(derivation["rule_version"]))
    if not rule or not version or not version.get("authorized"):
        errors.append(_error("fc_derivation_rule_unauthorized", feature_id,
                             "derivation rule/version is not in the authorized registry",
                             rule_id=derivation["rule_id"], rule_version=derivation["rule_version"]))
    return errors


def _validate_scope(source_class: str, scope: str, feature_id: str) -> list[dict[str, Any]]:
    if scope not in ACCEPTANCE_SCOPES:
        return [_error("fc_invalid_scope", feature_id, f"unknown acceptance scope {scope!r}")]
    if scope not in _ALLOWED_SCOPES[source_class]:
        code = ("fc_assumption_forbidden_mandatory" if source_class == "model_assumption"
                else "fc_derived_cannot_be_mandatory")
        return [_error(code, feature_id,
                       f"source class {source_class!r} may not declare scope {scope!r}",
                       source_class=source_class, scope=scope)]
    return []


def _normalize_measurement(measurement: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(measurement, dict):
        return {"schema": MEASUREMENT_SCHEMA, "status": "undetermined",
                "metrics": {}, "tolerance_ref": None, "note": None}
    status = measurement.get("status", "undetermined")
    if status not in MEASUREMENT_STATUSES:
        status = "undetermined"
    return {
        "schema": MEASUREMENT_SCHEMA,
        "status": status,
        "metrics": measurement.get("metrics") or {},
        "tolerance_ref": measurement.get("tolerance_ref"),
        "note": measurement.get("note"),
    }


def validate_feature_declaration(
    declaration: dict[str, Any],
    source_index: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    """Validate one feature declaration.

    Returns ``(record, binding, errors)``. On any error the record is still returned
    for evidence, but it is marked invalid and must not enter mandatory acceptance.
    """
    entries = (source_index or {}).get("entries") or {}
    contract_version = (source_index or {}).get("contract_version")
    feature_id = str(declaration.get("feature_id") or "")
    errors: list[dict[str, Any]] = []

    feature_class = declaration.get("feature_class")
    if feature_class not in FEATURE_CLASSES:
        errors.append(_error("fc_invalid_feature_class", feature_id,
                             f"unknown feature class {feature_class!r}"))
    source_class = declaration.get("source_class")
    if source_class not in SOURCE_CLASSES:
        errors.append(_error("fc_invalid_source_class", feature_id,
                             f"unknown source class {source_class!r}"))
    scope = declaration.get("acceptance_scope", "advisory")

    source_refs = list(declaration.get("source_refs") or [])
    if not source_refs:
        errors.append(_error("fc_empty_source_refs", feature_id, "source_refs must be non-empty"))
    unknown_refs = [ref for ref in source_refs if ref not in entries]
    if unknown_refs:
        errors.append(_error("fc_unknown_source_ref", feature_id,
                             "source refs missing from the valid source index",
                             unknown_refs=unknown_refs))

    if source_class in SOURCE_CLASSES:
        errors.extend(_validate_scope(source_class, scope, feature_id))
        errors.extend(_validate_derivation(source_class, declaration.get("derivation"), feature_id))
    errors.extend(_validate_evidence(declaration.get("evidence"), entries,
                                     str(contract_version or ""), feature_id))

    target_ref = declaration.get("target_ref")
    target_refs = declaration.get("target_refs")
    if isinstance(target_refs, list) and len(target_refs) > 1:
        errors.append(_error("fc_multi_target_ambiguous", feature_id,
                             "one feature contract cannot bind multiple targets without a unique source correspondence",
                             target_refs=target_refs))
    if not target_ref and not isinstance(target_refs, list):
        errors.append(_error("fc_missing_target_ref", feature_id, "target_ref is required"))

    record = {
        "schema": CONTRACT_SCHEMA,
        "feature_id": feature_id,
        "feature_class": feature_class,
        "source_class": source_class,
        "source_refs": source_refs,
        "evidence": declaration.get("evidence"),
        "derivation": declaration.get("derivation"),
        "acceptance_scope": scope,
        "measurement": _normalize_measurement(declaration.get("measurement")),
        "conclusion": declaration.get("conclusion"),
        "provenance": {
            "contract_version": contract_version,
            "source_index_schema": (source_index or {}).get("schema"),
            "shadow_only": True,
        },
        "valid": not errors,
    }

    binding: dict[str, Any] | None = None
    if target_ref or (isinstance(target_refs, list) and len(target_refs) == 1):
        binding = {
            "schema": BINDING_SCHEMA,
            "binding_id": f"binding:{feature_id}",
            "contract_id": feature_id,
            "target_ref": target_ref or target_refs[0],
            "reference_ref": declaration.get("reference_ref"),
            "source_refs": source_refs,
        }
    return record, binding, errors


def _detect_conflicts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Record explicit/derived contradictions; explicit wins, derived is downgraded.

    This is a shadow record in phase 1; it never drops the explicit contract and
    never silently overwrites the derived one.
    """
    conflicts: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        if not record.get("valid"):
            continue
        key = (str(record.get("feature_class") or ""), str(record.get("evidence", {}).get("source_ref") or ""))
        by_key.setdefault(key, []).append(record)
    for group in by_key.values():
        explicit = [r for r in group if r["source_class"] == "explicit"]
        derived = [r for r in group if r["source_class"] == "derived_semantic"]
        if not explicit or not derived:
            continue
        for e in explicit:
            for d in derived:
                if e.get("conclusion") is None or d.get("conclusion") is None:
                    continue
                if e["conclusion"] == d["conclusion"]:
                    continue  # corroborating, not a contradiction
                d["acceptance_scope"] = "advisory"
                d["conflict"] = {
                    "code": "fc_explicit_derived_conflict",
                    "explicit_feature_id": e["feature_id"],
                    "explicit_conclusion": e["conclusion"],
                    "derived_conclusion": d["conclusion"],
                    "resolution": "explicit_wins",
                }
                conflicts.append({
                    "code": "fc_explicit_derived_conflict",
                    "explicit_feature_ids": [e["feature_id"]],
                    "derived_feature_ids": [d["feature_id"]],
                    "explicit_conclusion": e["conclusion"],
                    "derived_conclusion": d["conclusion"],
                    "resolution": "explicit_wins_derived_downgraded_to_advisory",
                })
    return conflicts


def build_feature_contracts(
    contract: dict[str, Any],
    source_index: dict[str, Any],
    declarations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate and assemble the shadow feature contract set.

    Returns a shadow report: valid/invalid records, bindings, conflicts and errors.
    No candidate pass/fail decision is produced here.
    """
    records: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for declaration in declarations:
        record, binding, declaration_errors = validate_feature_declaration(declaration, source_index)
        if record["feature_id"] in seen_ids:
            declaration_errors.append(_error("fc_duplicate_feature_id", record["feature_id"],
                                            "feature_id must be unique"))
        seen_ids.add(record["feature_id"])
        errors.extend(declaration_errors)
        record["valid"] = not declaration_errors
        if record["valid"] and binding is not None:
            bindings.append(binding)
        records.append(record)

    conflicts = _detect_conflicts(records)
    return {
        "schema": "cad.feature-contract-set.v1",
        "shadow_only": True,
        "contract_version": source_index.get("contract_version"),
        "records": records,
        "bindings": bindings,
        "conflicts": conflicts,
        "errors": errors,
        "valid": not errors,
    }


def real_source_facts(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose real contract facts for traceability wiring (read-only).

    Each fact carries ``fact_id``, ``source_id`` and its real evidence span/text.
    """
    return [
        {
            "fact_id": fact.get("fact_id"),
            "source_id": fact.get("source_id"),
            "field": fact.get("field"),
            "evidence": fact.get("evidence"),
            "status": fact.get("status"),
        }
        for fact in (contract.get("facts") or [])
    ]
