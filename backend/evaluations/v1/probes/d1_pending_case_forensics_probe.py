"""D1.2 forensics probe: classify the old combo's single pending C1 case.

The pending case ``test_c1_service_curve_contact_details_present`` failed on
the A1.1+C combo ``f71d100`` with ``failed_dep_pending``. This probe records,
read-only:

1. whether the B1.1 topology module resolves in the target backend;
2. the B analyzer's direct output on the same closed four-line bow-tie fixture
   reconstructed from the C test (diagnostic cross-validation only);
3. the four-way verdict (dependency pending / interface mismatch / fixture
   invalid / detection boundary miss) with the observed contact fields.

No production code, frozen input or assertion is modified. No live model call
is made.

Usage:
    python evaluations/v1/probes/d1_pending_case_forensics_probe.py \
        --backend "<combo worktree>\\backend" \
        --out evaluations/v1/probes/d1_pending_case_forensics.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROBE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROBE_DIR))

import d1_baseline_runner as runner  # noqa: E402

# Reconstructed from C fixture ``_bow_tie_plan`` (test_c1_integration_mock.py
# lines 128-152): closed four-line bow tie, diagnostic cross-validation only.
BOW_TIE_SEGMENTS = [
    {"kind": "line", "start": {"x": 0, "y": 0}, "end": {"x": 2, "y": 2}},
    {"kind": "line", "start": {"x": 2, "y": 2}, "end": {"x": 0, "y": 2}},
    {"kind": "line", "start": {"x": 0, "y": 2}, "end": {"x": 2, "y": 0}},
    {"kind": "line", "start": {"x": 2, "y": 0}, "end": {"x": 0, "y": 0}},
]

EXPECTED_FIELDS = ("segment_indices", "parameters", "kind", "distance")


def main() -> int:
    parser = argparse.ArgumentParser(description="D1.2 pending case forensics")
    parser.add_argument("--backend", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    sys.path.insert(0, str(args.backend))
    module_present = (
        importlib.util.find_spec("app.cad_topology_safety") is not None
        or importlib.util.find_spec("app.cad_curve_intersection") is not None
    )

    analyzer_output: dict[str, Any] = {"module_present": module_present}
    verdict: dict[str, Any] = {"candidate": None, "excluded": []}

    if module_present:
        from app.cad_topology_safety import analyze_composite_segments  # noqa: E402

        report = analyze_composite_segments(
            BOW_TIE_SEGMENTS, tolerance=1e-6, closed=True)
        contacts = [c.as_dict() for c in report.contacts]
        analyzer_output["contacts"] = contacts
        analyzer_output["unresolved"] = report.unresolved

        contact = contacts[0] if contacts else None
        missing = [f for f in EXPECTED_FIELDS if contact is None or f not in contact]
        indices_ok = bool(contact and len(contact["segment_indices"]) == 2)
        params_ok = bool(contact and len(contact["parameters"]) == 2)

        if not contacts:
            verdict["candidate"] = "d"
            verdict["reason"] = "B analyzer returned no contact on this fixture."
        elif missing or not indices_ok or not params_ok:
            verdict["candidate"] = "b"
            verdict["reason"] = "Contact schema does not match the C assertion fields."
            verdict["missing_fields"] = missing
        else:
            verdict["candidate"] = "a"
            verdict["reason"] = (
                "B detection returns the expected crossing contact with aligned "
                "fields; the old combo failure was the missing B module guard."
            )
        verdict["excluded"] = [
            {"option": "b", "note": "as_dict keys: segment_indices/parameters/kind/distance"},
            {"option": "c", "note": "Closed four-line bow tie; diagonal pair crosses at (1,1)."},
            {"option": "d", "note": f"contacts_detected={len(contacts)}"},
        ]
    else:
        verdict["candidate"] = "a"
        verdict["reason"] = "Topology module absent; guard fails before assertions run."

    payload: dict[str, Any] = {
        "schema": "cad.d1.pending-forensics.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_backend": str(args.backend),
        "case_node": "tests.test_c1_integration_mock::test_c1_service_curve_contact_details_present",
        "guard_source": {
            "file": "backend/tests/test_c1_integration_mock.py",
            "guard_lines": "45-51 (_b1_curve_intersection_available)",
            "fail_lines": "315-321 (pytest.fail failed_dep_pending)",
            "assertion_lines": "331-340",
        },
        "fixture": {"closed": True, "segments": BOW_TIE_SEGMENTS},
        "analyzer_output": analyzer_output,
        "verdict": verdict,
        "environment": {"versions": runner.package_versions(),
                         "guard": runner.env_guard()},
        "guards": {"live_model_calls": 0, "production_code_modified": False},
    }
    digest = runner.canonical_sha256(
        {k: v for k, v in payload.items() if k != "snapshot_sha256"})
    payload["snapshot_sha256"] = digest
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(json.dumps({"out": str(args.out), "sha256": digest,
                       "verdict": verdict["candidate"],
                       "contacts": analyzer_output.get("contacts")},
                      ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
