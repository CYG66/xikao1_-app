"""Zero-cost C1 integration probe: detect A1/B1 hookup symbols on the checked-out tree.

This probe does NOT call any real model interface and does not persist any
candidate. It only reports which production hookup symbols are present so the
C1 service-level Mock cases can be labelled ``passed`` / ``failed_dep_pending``.

Run from the backend directory:
    <xikao-python> evaluations/v1/probes/c1_integration_probe.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def _module_present(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _a1_symbol_present() -> bool:
    if not _module_present("app.cad_plan_component_repair"):
        return False
    try:
        from app.cad_plan_component_repair import ComponentRepairError  # noqa: F401
    except ImportError:
        return False
    return True


def _b1_module_present() -> bool:
    return (
        _module_present("app.cad_topology_safety")
        or _module_present("app.cad_curve_intersection")
    )


def main() -> int:
    a1_available = _a1_symbol_present()
    b1_module = _b1_module_present()

    report = {
        "schema": "cad.c1-integration-probe.v1",
        "real_model_calls": 0,
        "project_persistence": False,
        "dependencies": {
            "A1": {
                "branch": "v1/a1-constraint-inheritance",
                "commits": [
                    "0ed2288ca068534d86e1afddc93f592b7ef35e35",
                    "d8cb85f68db08b90beb4872ccfc9fdf93d8735d9",
                ],
                "ComponentRepairError_available_on_C": a1_available,
                "status": "available" if a1_available else "failed_dep_pending",
            },
            "B1": {
                "branch": "v1/b1-topology",
                "commit": "not_committed",
                "HEAD": "a4f2af7bbfe86509c7a900adbd6b366e12f598a5",
                "modules_observed_on_B_draft": ["cad_topology_safety"],
                "cad_topology_safety_available_on_C": b1_module,
                "status": "available" if b1_module else "failed_dep_pending",
            },
        },
        "cases": [
            {
                "case": "test_c1_service_component_repair_failure_maps_to_structured_local_error",
                "depends_on": "A1",
                "expected_state_if_dependency_missing": "failed_dep_pending",
            },
            {
                "case": "test_c1_service_merged_repair_keeps_inherited_junction_fields",
                "depends_on": "A1",
                "expected_state_if_dependency_missing": "failed_dep_pending",
            },
            {
                "case": "test_c1_service_topology_failure_is_structured_not_silent_success",
                "depends_on": "baseline-existing-executor",
                "expected_state_if_dependency_missing": "environment_blocked",
            },
            {
                "case": "test_c1_service_curve_contact_details_present",
                "depends_on": "B1",
                "expected_state_if_dependency_missing": "failed_dep_pending",
            },
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
