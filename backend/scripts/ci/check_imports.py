"""Offline import gate for the XLine backend (RELEASE-TEST-01).

Purpose
-------
Verify that the backend application modules can be *imported* in a clean CI
environment after dependency installation.  This gate performs **pure import
checks only**: it never starts the FastAPI app, never opens a real database,
never calls a model provider or a device, and never performs any network I/O.

Exit codes
----------
0  All listed modules imported successfully.
1  At least one module failed to import (or the module list could not be
   resolved).  There is deliberately no ``continue-on-error`` path: a broken
   import must fail the job.

Usage
-----
    python scripts/ci/check_imports.py [--root BACKEND_ROOT]

The script adds ``BACKEND_ROOT`` to ``sys.path`` itself, so it does not depend
on the caller setting ``PYTHONPATH``.
"""
from __future__ import annotations

import argparse
import importlib
import sys
import traceback
from pathlib import Path

# Modules grouped by subsystem.  Names must match ``app.<module>`` (or the
# root-level ``startup_preflight`` module).  Keep this list aligned with the
# runtime entry points exercised by the regression jobs.
MODULE_GROUPS: dict[str, list[str]] = {
    "entrypoint": [
        "app.main",
        "app.config",
        "app.state",
        "startup_preflight",
    ],
    "stores-and-safety": [
        "app.database",
        "app.audit_store",
        "app.startup_guard",
        "app.drawing_store",
        "app.creative_projects",
        "app.task_store",
        "app.agent_run_store",
        "app.agent_plan_store",
        "app.agent_plan_sqlite_store",
    ],
    "agent-runtime": [
        "app.agent_service",
        "app.agent_service_context",
        "app.agent_service_policy",
        "app.agent_plan_orchestrator",
        "app.agent_plan_runtime",
        "app.agent_plan_recovery",
        "app.agent_failure_policy",
        "app.agent_interruption_policy",
        "app.model_providers",
        "app.model_request_gateway",
        "app.deepseek_transport",
        "app.answer_validation",
    ],
    "routers": [
        "app.routers.system",
        "app.routers.projects",
        "app.routers.drawings",
        "app.routers.agent",
        "app.routers.rosbridge",
        "app.routers.device",
        "app.routers.missions",
    ],
    "cad-core": [
        "app.cad_assertions",
        "app.cad_construction",
        "app.cad_edit_contract",
        "app.cad_edit_plan",
        "app.cad_edit_preview",
        "app.cad_edit_gate",
        "app.cad_topology_safety",
        "app.cad_counterfactual_guard",
        "app.cad_requirement_contract",
        "app.cad_structure_contract",
        "app.cad_feature_contract",
    ],
}


def _iter_modules() -> list[tuple[str, str]]:
    for group, modules in MODULE_GROUPS.items():
        for module in modules:
            yield group, module


def check_imports(backend_root: Path) -> dict[str, object]:
    sys.path.insert(0, str(backend_root))
    results: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []

    for group, module in _iter_modules():
        try:
            importlib.import_module(module)
            results.append({"group": group, "module": module, "status": "ok"})
            print(f"[OK]   {group:<18} {module}")
        except Exception as exc:  # noqa: BLE001 - import gate must record any failure
            detail = f"{type(exc).__name__}: {exc}"
            results.append({"group": group, "module": module, "status": "fail"})
            failures.append({"group": group, "module": module, "detail": detail})
            print(f"[FAIL] {group:<18} {module} -> {detail}")
            traceback.print_exc()

    summary = {
        "backend_root": str(backend_root),
        "total": len(results),
        "ok": sum(item["status"] == "ok" for item in results),
        "failed": len(failures),
        "failures": failures,
        "results": results,
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline backend import gate.")
    default_root = Path(__file__).resolve().parents[2]
    parser.add_argument("--root", type=Path, default=default_root,
                        help="Backend root directory (defaults to two levels up from this script).")
    args = parser.parse_args()

    backend_root = args.root.resolve()
    if not (backend_root / "app").is_dir():
        print(f"ERROR: backend root does not look like a backend directory: {backend_root}")
        return 1

    summary = check_imports(backend_root)
    print("-" * 72)
    print(f"import gate: {summary['ok']}/{summary['total']} modules ok, "
          f"{summary['failed']} failed")

    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
