"""Traceability and fail-closed tests for the internal FEATURE-CONTRACT sidecar.

The sidecar reuses the real requirement contract and source index; these tests
wire declarations to real ledger facts/evidence, then exercise every negative
guard. No model call, no geometry algorithm, no candidate pass/fail decision.
"""
from app.cad_requirement_ledger import project_requirement_ledger
from app.cad_feature_contract import (
    BINDING_SCHEMA,
    build_feature_contracts,
    build_feature_source_index,
    real_source_facts,
)

ORIGINAL = "生成一个平行排列的矩形，宽度4米，高度3米，中心在(2,3)"


def _bundle():
    ledger = project_requirement_ledger(ORIGINAL)
    bundle = build_feature_source_index(ledger)
    return ledger, bundle["contract"], bundle["source_index"]


def _width_fact(contract):
    return next(f for f in real_source_facts(contract) if f["field"] == "width")


def _base_declaration(contract, source_index, **overrides):
    fact = _width_fact(contract)
    source_id = fact["source_id"]
    evidence = fact["evidence"]
    declaration = {
        "feature_id": "fc-width-1",
        "feature_class": "boundary_extremum",
        "source_class": "explicit",
        "source_refs": [source_id],
        "evidence": {
            "source_ref": source_id,
            "start": evidence["start"],
            "end": evidence["end"],
            "text": evidence["text"],
            "source_revision": source_index["contract_version"],
        },
        "target_ref": "step-1:outline",
        "acceptance_scope": "mandatory",
        "conclusion": True,
        "measurement": {
            "status": "undetermined",
            "metrics": {},
            "tolerance_ref": "distance.center_distance.default",
        },
    }
    declaration.update(overrides)
    return declaration


def _codes(result):
    return {error["code"] for error in result["errors"]}


# --------------------------------------------------------------------------- #
# Positive traceability against the real ledger
# --------------------------------------------------------------------------- #


def test_explicit_declaration_resolves_to_real_source_entry_and_evidence():
    ledger, contract, source_index = _bundle()
    fact = _width_fact(contract)
    entry = source_index["entries"][fact["source_id"]]

    # The index entry is the real ledger source, not a second fact ledger.
    assert entry["source_type"] == "explicit"
    assert entry["source_status"] == "valid"
    assert entry["original_text"] == next(s["text"] for s in ledger["sources"]
                                          if s["source_id"] == fact["source_id"])

    declaration = _base_declaration(contract, source_index)
    result = build_feature_contracts(contract, source_index, [declaration])

    assert result["valid"] is True
    record = result["records"][0]
    assert record["valid"] is True
    assert record["source_refs"] == [fact["source_id"]]
    # Span and text agree with the immutable source slice.
    source_text = entry["original_text"]
    ev = record["evidence"]
    assert source_text[ev["start"]:ev["end"]] == ev["text"] == fact["evidence"]["text"]
    assert ev["source_revision"] == source_index["contract_version"]

    binding = result["bindings"][0]
    assert binding["schema"] == BINDING_SCHEMA
    assert binding["contract_id"] == record["feature_id"]
    assert binding["target_ref"] == "step-1:outline"
    # Shadow only: no candidate decision field is produced.
    assert result["shadow_only"] is True
    assert "decision" not in result


def test_authorized_derived_semantic_declaration_is_semantic_only():
    _, contract, source_index = _bundle()
    declaration = _base_declaration(
        contract, source_index,
        feature_id="fc-derived-1",
        source_class="derived_semantic",
        acceptance_scope="semantic_only",
        derivation={
            "rule_id": "shape_outline_features",
            "rule_version": "1",
            "input_refs": [_width_fact(contract)["source_id"]],
            "inference_steps": ["lexical dimension match", "derive outline extremum candidate"],
        },
    )
    result = build_feature_contracts(contract, source_index, [declaration])
    assert result["valid"] is True
    record = result["records"][0]
    assert record["acceptance_scope"] == "semantic_only"
    assert record["source_class"] == "derived_semantic"


def test_requirement_and_fact_ids_are_stable_across_repair_turn_snapshot():
    before = project_requirement_ledger(ORIGINAL)
    # Repair turn: the user source text is unchanged; feedback is not a user
    # follow-up. Rebuild the snapshot and prove IDs do not change spuriously.
    after = project_requirement_ledger(ORIGINAL, previous=before)

    facts_before = real_source_facts(before["requirement_contract"])
    facts_after = real_source_facts(after["requirement_contract"])
    assert [f["fact_id"] for f in facts_before] == [f["fact_id"] for f in facts_after]

    req_before = [item["requirement_id"] for item in before["evidence_items"]]
    req_after = [item["requirement_id"] for item in after["evidence_items"]]
    assert req_before == req_after

    bundle_before = build_feature_source_index(before)
    bundle_after = build_feature_source_index(after)
    assert bundle_before["source_index"]["contract_version"] == \
        bundle_after["source_index"]["contract_version"]

    # The same source fact wires to the same stable feature evidence in both turns.
    fact = facts_before[0]
    for bundle in (bundle_before, bundle_after):
        declaration = _base_declaration(bundle["contract"], bundle["source_index"])
        result = build_feature_contracts(bundle["contract"], bundle["source_index"], [declaration])
        assert result["valid"] is True
        assert result["records"][0]["evidence"]["source_revision"] == \
            bundle["source_index"]["contract_version"]
        assert result["records"][0]["source_refs"] == [fact["source_id"]]


# --------------------------------------------------------------------------- #
# Negative guards (fail-closed)
# --------------------------------------------------------------------------- #


def test_negative_1_unknown_source_ref_is_rejected_fail_closed():
    _, contract, source_index = _bundle()
    declaration = _base_declaration(
        contract, source_index,
        source_refs=["no-such-source"],
        evidence={**_base_declaration(contract, source_index)["evidence"],
                  "source_ref": "no-such-source"},
    )
    result = build_feature_contracts(contract, source_index, [declaration])
    assert "fc_unknown_source_ref" in _codes(result)
    record = result["records"][0]
    assert record["valid"] is False
    assert result["bindings"] == []


def test_negative_2_out_of_range_evidence_span_is_rejected():
    _, contract, source_index = _bundle()
    declaration = _base_declaration(
        contract, source_index,
        evidence={**_base_declaration(contract, source_index)["evidence"],
                  "start": 9999, "end": 10000},
    )
    result = build_feature_contracts(contract, source_index, [declaration])
    assert "fc_evidence_span_out_of_range" in _codes(result)
    assert result["records"][0]["valid"] is False


def test_negative_3_evidence_text_mismatch_is_rejected():
    _, contract, source_index = _bundle()
    declaration = _base_declaration(
        contract, source_index,
        evidence={**_base_declaration(contract, source_index)["evidence"],
                  "text": "宽度9米"},
    )
    result = build_feature_contracts(contract, source_index, [declaration])
    assert "fc_evidence_text_mismatch" in _codes(result)
    mismatch = next(e for e in result["errors"] if e["code"] == "fc_evidence_text_mismatch")
    assert mismatch["actual"] == "宽度9米"
    assert result["records"][0]["valid"] is False


def test_negative_4a_derived_without_rule_version_is_rejected():
    _, contract, source_index = _bundle()
    declaration = _base_declaration(
        contract, source_index,
        feature_id="fc-forged-1",
        source_class="derived_semantic",
        acceptance_scope="semantic_only",
        derivation={"rule_id": "shape_outline_features"},
    )
    result = build_feature_contracts(contract, source_index, [declaration])
    assert "fc_derivation_rule_missing" in _codes(result)
    assert result["records"][0]["valid"] is False


def test_negative_4b_unauthorized_derivation_rule_is_rejected():
    _, contract, source_index = _bundle()
    declaration = _base_declaration(
        contract, source_index,
        feature_id="fc-forged-2",
        source_class="derived_semantic",
        acceptance_scope="semantic_only",
        derivation={"rule_id": "unregistered_rule", "rule_version": "9"},
    )
    result = build_feature_contracts(contract, source_index, [declaration])
    assert "fc_derivation_rule_unauthorized" in _codes(result)
    error = next(e for e in result["errors"] if e["code"] == "fc_derivation_rule_unauthorized")
    assert error["rule_id"] == "unregistered_rule"
    assert result["records"][0]["valid"] is False


def test_negative_5_model_assumption_cannot_enter_mandatory_acceptance():
    _, contract, source_index = _bundle()
    declaration = _base_declaration(
        contract, source_index,
        feature_id="fc-assumption-1",
        source_class="model_assumption",
        acceptance_scope="mandatory",
    )
    result = build_feature_contracts(contract, source_index, [declaration])
    assert "fc_assumption_forbidden_mandatory" in _codes(result)
    assert result["records"][0]["valid"] is False


def test_negative_5b_derived_semantic_cannot_be_upgraded_to_mandatory():
    _, contract, source_index = _bundle()
    declaration = _base_declaration(
        contract, source_index,
        feature_id="fc-derived-mandatory",
        source_class="derived_semantic",
        acceptance_scope="mandatory",
        derivation={"rule_id": "shape_outline_features", "rule_version": "1"},
    )
    result = build_feature_contracts(contract, source_index, [declaration])
    assert "fc_derived_cannot_be_mandatory" in _codes(result)
    assert result["records"][0]["valid"] is False


def test_negative_6_multi_target_binding_ambiguity_is_rejected():
    _, contract, source_index = _bundle()
    declaration = _base_declaration(
        contract, source_index,
        target_ref=None,
        target_refs=["step-1:outline", "step-2:outline"],
    )
    result = build_feature_contracts(contract, source_index, [declaration])
    assert "fc_multi_target_ambiguous" in _codes(result)
    assert result["records"][0]["valid"] is False
    assert result["bindings"] == []


def test_negative_7_explicit_derived_conflict_records_explicit_wins_without_overwrite():
    _, contract, source_index = _bundle()
    explicit = _base_declaration(contract, source_index, feature_id="fc-explicit-2",
                                conclusion=True)
    derived = _base_declaration(
        contract, source_index,
        feature_id="fc-derived-2",
        source_class="derived_semantic",
        acceptance_scope="semantic_only",
        conclusion=False,
        derivation={"rule_id": "shape_outline_features", "rule_version": "1"},
    )
    result = build_feature_contracts(contract, source_index, [explicit, derived])

    conflict = next(c for c in result["conflicts"]
                    if c["code"] == "fc_explicit_derived_conflict")
    assert conflict["resolution"] == "explicit_wins_derived_downgraded_to_advisory"
    explicit_record = next(r for r in result["records"] if r["feature_id"] == "fc-explicit-2")
    derived_record = next(r for r in result["records"] if r["feature_id"] == "fc-derived-2")
    # Explicit keeps its conclusion and mandatory scope; derived is downgraded,
    # neither record is silently dropped or overwritten.
    assert explicit_record["conclusion"] is True
    assert explicit_record["acceptance_scope"] == "mandatory"
    assert derived_record["conclusion"] is False
    assert derived_record["acceptance_scope"] == "advisory"
    assert derived_record["conflict"]["explicit_feature_id"] == "fc-explicit-2"
