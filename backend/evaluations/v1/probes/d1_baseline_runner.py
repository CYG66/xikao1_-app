"""D1 reproducible baseline runner and unified failure classifier (read-only).

Scope (D-line, round D1-1):
- Re-runs the five D0 specialized pytest suites against the frozen HEAD.
- Re-runs the full collect-only audit to enumerate collection-blocked modules.
- Reads committed D0 registry / replay / benchmark assets (no regeneration).
- Re-executes the in-process A9/S1/junction reconstruction fixtures only.

Hard guards:
- Forces provider to local; strips model API keys from the child environment.
- Does not call any live model; does not write projects, candidates or stores.
- Does not modify production code, D0 frozen assets, frozen inputs or assertions.
- JUnit XML and transient state live in a system temp dir, not the repository.

Reproducible entry (run from ``backend/``):

    python evaluations/v1/probes/d1_baseline_runner.py

Optional flags:
    --out PATH        write snapshot JSON to PATH (default: d1_baseline_snapshot.json
                      next to this script)
    --suite ID        run only one of the five suites by id
    --no-collect      skip the full collect-only audit
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

BACKEND = Path(__file__).resolve().parents[3]
V1 = BACKEND / "evaluations" / "v1"
PROBES = V1 / "probes"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(PROBES) not in sys.path:
    sys.path.insert(0, str(PROBES))

# Five D0 specialized suites, identified from D0_可信基线审计报告.md section 6.1
# and section 11.1 ("五个专项测试"). Relative paths are pytest node roots under
# backend/.
SUITES: list[dict[str, str]] = [
    {
        "suite_id": "S1-requirement-contract",
        "module": "tests/test_cad_requirement_contract.py",
        "d0_ref": "D0 audit report 6.1 / 11.1; H2 requirement contract",
    },
    {
        "suite_id": "S2-plan-component-repair",
        "module": "tests/test_cad_plan_component_repair.py",
        "d0_ref": "D0 audit report 6.1 / 11.1; A1 constraint inheritance",
    },
    {
        "suite_id": "S3-final-source-contract",
        "module": "tests/test_cad_final_source_contract.py",
        "d0_ref": "D0 audit report 6.1 / 11.1; H3 final source contract",
    },
    {
        "suite_id": "S4-construction-interpreter",
        "module": "tests/test_cad_construction_interpreter.py",
        "d0_ref": "D0 audit report 6.1 / 11.1; construction interpreter rule path",
    },
    {
        "suite_id": "S5-candidate-visibility-gate",
        "module": "tests/test_candidate_visibility_gate.py",
        "d0_ref": "D0 audit report 6.1 / 11.1; candidate visibility gate",
    },
]

STRIPPED_KEYS = ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ARK_API_KEY", "MODEL_API_KEY")

# ---------------------------------------------------------------------------
# Unified failure classification (D1 taxonomy). Top-level classes:
#   collection_blocked     collection phase blocked; tests never entered execution
#   environment_blocked    dependency / import / network / runtime env blocker
#   not_run                skipped, xfail-untriggered, or never triggered
#   logic_failure          assertion / expected-value mismatch
#   error_mapping_failure  exception type or error-code / semantic mismatch
# ---------------------------------------------------------------------------

NETWORK_EXC = ("ConnectionError", "TimeoutError", "httpx.ConnectError",
               "httpx.ConnectTimeout", "httpx.ReadTimeout", "URLError",
               "socket.timeout", "ProxyError")
IMPORT_EXC = ("ModuleNotFoundError", "ImportError", "SyntaxError")


def _exc_name(text: str) -> str:
    m = re.search(r"^E\s+([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception))", text, re.MULTILINE)
    return m.group(1).split(".")[-1] if m else ""


def classify_testcase(tag: str, message: str, text: str) -> dict[str, str]:
    """Map a JUnit testcase outcome to the D1 failure class."""
    blob = f"{message}\n{text}"
    exc = _exc_name(text) or _exc_name(message)
    if tag == "skipped":
        return {"failure_class": "not_run", "sub_class": "skipped"}
    if tag == "error":
        if any(k in blob for k in NETWORK_EXC):
            return {"failure_class": "environment_blocked", "sub_class": "network_or_timeout"}
        if any(k in blob for k in IMPORT_EXC):
            return {"failure_class": "environment_blocked", "sub_class": "import_or_dependency"}
        if "FileNotFoundError" in blob:
            return {"failure_class": "environment_blocked", "sub_class": "missing_local_asset"}
        return {"failure_class": "environment_blocked", "sub_class": "setup_or_runtime_env"}
    # tag == "failure"
    if "DID NOT RAISE" in blob or "DID NOT MATCH" in blob or "raised " in blob and "instead of" in blob:
        return {"failure_class": "error_mapping_failure", "sub_class": "expected_exception_mismatch"}
    if exc and exc not in ("AssertionError",):
        return {"failure_class": "error_mapping_failure", "sub_class": "unexpected_exception"}
    if "AssertionError" in blob or re.search(r"\bassert\b", blob):
        return {"failure_class": "logic_failure", "sub_class": "assertion_failure"}
    return {"failure_class": "logic_failure", "sub_class": "assertion_failure"}


def classify_collection_error(module: str, text: str) -> dict[str, str]:
    exc = _exc_name(text)
    norm = text.replace("\\\\", "/").replace("\\", "/")
    if "tests.manual" in norm or "tests/manual" in norm:
        sub = "missing_manual_asset"
    elif any(k in text for k in IMPORT_EXC):
        sub = "import_or_dependency"
    elif "FileNotFoundError" in text:
        sub = "missing_local_asset"
    else:
        sub = "collection_other"
    return {"failure_class": "collection_blocked", "sub_class": sub, "exception": exc}


def _clean_module(raw: str) -> str:
    return raw.split()[0] if raw.split() else raw.strip()


# ---------------------------------------------------------------------------
# Environment / git metadata
# ---------------------------------------------------------------------------

def _git(args: list[str], root: Path) -> str:
    out = subprocess.run(
        ["C:\\Users\\29924\\Softwares\\git\\Git\\cmd\\git.exe", "-C", str(root.parent), *args],
        capture_output=True, text=True, check=False,
    )
    return out.stdout.strip()


def env_guard() -> dict[str, Any]:
    present = {k: ("present" if os.environ.get(k) else "absent") for k in STRIPPED_KEYS}
    return {
        "forced_provider": "local",
        "stripped_keys": present,
        "deepseek_key_present": bool(os.environ.get("DEEPSEEK_API_KEY")),
        "openai_key_present": bool(os.environ.get("OPENAI_API_KEY")),
    }


def guarded_env() -> dict[str, str]:
    env = dict(os.environ)
    env["XLINE_AGENT_PROVIDER"] = "local"
    for key in STRIPPED_KEYS:
        env.pop(key, None)
    return env


def package_versions() -> dict[str, str]:
    versions: dict[str, str] = {"python": sys.version.split()[0]}
    for pkg in ("pytest", "httpx", "fastapi", "pydantic", "shapely", "ezdxf", "numpy", "scipy"):
        try:
            mod = __import__(pkg)
            versions[pkg] = getattr(mod, "__version__", "unknown")
        except ImportError:
            versions[pkg] = "missing"
    return versions


# ---------------------------------------------------------------------------
# Pytest execution + JUnit parsing
# ---------------------------------------------------------------------------

def run_pytest(module: str, junit_path: Path, backend: Path) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "pytest", module, "-q", "--disable-warnings",
           f"--junitxml={junit_path}"]
    started = time.perf_counter()
    proc = subprocess.run(cmd, cwd=backend, env=guarded_env(),
                          capture_output=True, text=True, errors="replace")
    wall_ms = round((time.perf_counter() - started) * 1000, 1)
    result: dict[str, Any] = {
        "module": module,
        "command": " ".join(cmd),
        "exit_code": proc.returncode,
        "wall_elapsed_ms": wall_ms,
        "stdout_tail": proc.stdout.strip().splitlines()[-3:],
        "stderr_tail": proc.stderr.strip().splitlines()[-3:],
    }
    if not junit_path.exists():
        result["counts"] = {"tests": 0, "passed": 0, "failed": 0, "errors": 0,
                            "skipped": 0, "collection_blocked": 0,
                            "environment_blocked": 0, "not_run": 0}
        result["classification"] = {"collection_blocked": 1}
        result["cases"] = []
        return result

    tree = ET.parse(junit_path)
    root = tree.getroot()
    suite = root.find("testsuite")
    if suite is None:
        suite = root
    tests = int(suite.get("tests", 0))
    failures = int(suite.get("failures", 0))
    errors = int(suite.get("errors", 0))
    skipped = int(suite.get("skipped", 0))
    pytest_time_s = float(suite.get("time", 0.0))

    cases: list[dict[str, Any]] = []
    breakdown: dict[str, int] = {}
    for tc in suite.iter("testcase"):
        name = tc.get("name", "")
        classname = tc.get("classname", "")
        failure = tc.find("failure")
        error = tc.find("error")
        skipped_el = tc.find("skipped")
        if skipped_el is not None:
            tag, message, text = "skipped", skipped_el.get("message", ""), (skipped_el.text or "")
        elif error is not None:
            tag, message, text = "error", error.get("message", ""), (error.text or "")
        elif failure is not None:
            tag, message, text = "failure", failure.get("message", ""), (failure.text or "")
        else:
            tag, message, text = "passed", "", ""
        if tag == "passed":
            cls = {"failure_class": "passed", "sub_class": "passed"}
        else:
            cls = classify_testcase(tag, message, text)
        breakdown[cls["failure_class"]] = breakdown.get(cls["failure_class"], 0) + 1
        cases.append({
            "node": f"{classname}::{name}",
            "outcome": tag,
            "failure_class": cls["failure_class"],
            "sub_class": cls["sub_class"],
            "message": (message or "").strip()[:300],
        })

    passed = tests - failures - errors - skipped
    counts = {
        "tests": tests,
        "passed": passed,
        "failed": failures,
        "errors": errors,
        "skipped": skipped,
        "collection_blocked": breakdown.get("collection_blocked", 0),
        "environment_blocked": breakdown.get("environment_blocked", 0),
        "not_run": breakdown.get("not_run", 0),
        "logic_failure": breakdown.get("logic_failure", 0),
        "error_mapping_failure": breakdown.get("error_mapping_failure", 0),
    }
    result["counts"] = counts
    result["pytest_time_s"] = round(pytest_time_s, 3)
    result["classification"] = breakdown
    result["cases"] = cases
    return result


def run_collect_only(backend: Path) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q",
           "--continue-on-collection-errors"]
    started = time.perf_counter()
    proc = subprocess.run(cmd, cwd=backend, env=guarded_env(),
                          capture_output=True, text=True, errors="replace")
    wall_ms = round((time.perf_counter() - started) * 1000, 1)
    blob = proc.stdout + "\n" + proc.stderr

    collected = re.search(r"(\d+) tests collected", blob)
    errors = re.search(r"(\d+) errors", blob)
    collected_n = int(collected.group(1)) if collected else None
    errors_n = int(errors.group(1)) if errors else 0

    # Per-module error blocks: "ERROR collecting <module>" ... "E   <Exc>: ..."
    blocked_by_module: dict[str, dict[str, Any]] = {}

    def _record(module: str, text: str, detail: str) -> None:
        module = _clean_module(module)
        entry = classify_collection_error(module, text)
        entry["module"] = module
        entry["detail"] = detail[:300]
        if module not in blocked_by_module:
            blocked_by_module[module] = entry
        elif detail and not blocked_by_module[module]["detail"]:
            blocked_by_module[module].update(entry)
            blocked_by_module[module]["detail"] = detail[:300]

    blocks = re.split(r"ERROR collecting\s+", blob)
    for block in blocks[1:]:
        module = block.splitlines()[0].strip()
        m = re.search(r"E\s+(.+)", block)
        detail = m.group(1).strip() if m else ""
        _record(module, block, detail)
    # Short-summary fallback for modules without a full block.
    for line in blob.splitlines():
        m = re.match(r"ERROR\s+(tests/\S+\.py)(?:\s+-\s+(.*))?", line)
        if m:
            _record(m.group(1), m.group(2) or "", m.group(2) or "")
    blocked = [blocked_by_module[k] for k in sorted(blocked_by_module)]

    return {
        "command": " ".join(cmd),
        "exit_code": proc.returncode,
        "wall_elapsed_ms": wall_ms,
        "tests_collected": collected_n,
        "collection_errors": errors_n,
        "blocked_modules": blocked,
    }


# ---------------------------------------------------------------------------
# Case diagnosis (reads committed D0 assets; in-process fixtures only)
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def case_diagnosis() -> dict[str, Any]:
    replay = _load_json(V1 / "mock_replay_results.json")
    registry = _load_json(V1 / "case_registry.json")
    bench55 = _load_json(PROBES / "rule_benchmark_extended55.json")
    bench6 = _load_json(PROBES / "rule_benchmark_core6.json")

    records = {r["case_id"]: r for r in replay.get("records", [])}

    diagnosis: list[dict[str, Any]] = []
    for cid in ("A9", "S1", "A9-JUNCTION", "M1"):
        rec = records.get(cid)
        if rec is None:
            continue
        diagnosis.append({
            "case_id": cid,
            "evidence_mode": rec.get("evidence_mode"),
            "final_outcome": rec.get("final_outcome"),
            "failure_category": rec.get("failure_category"),
            "model_called": rec.get("model", {}).get("called"),
            "project_persistence": rec.get("version", {}).get("project_persistence"),
            "source": "committed D0 mock_replay_results.json",
            "notes": rec.get("notes"),
        })

    # In-process reconstructed fixtures (no D0 asset regeneration).
    import d0_geometry_probe as geo  # type: ignore
    a9 = geo.run_plan(geo.a9_plan())
    s1 = geo.run_plan(geo.s1_plan())
    junction = geo.junction_repair_probe()
    diagnosis.append({
        "case_id": "A9-RECON-FIXTURE",
        "evidence_mode": "reconstructed_fixture",
        "final_outcome": "failed" if a9["status"] == "failed" else a9["status"],
        "failure_category": "self_intersection" if a9["status"] == "failed" else None,
        "error_code": (a9.get("error") or {}).get("code"),
        "self_intersection_count": 1 if a9["status"] == "failed" else 0,
        "plan_sha256": geo.canonical_sha256(geo.a9_plan()),
        "source": "in-process d0_geometry_probe a9_plan/run_plan",
        "outcome_scope": "reconstructed_fixture_geometry_only",
    })
    sq = (s1.get("curve_quality") or [None])[0]
    diagnosis.append({
        "case_id": "S1-RECON-FIXTURE",
        "evidence_mode": "reconstructed_fixture",
        "final_outcome": s1["status"],
        "failure_category": None,
        "geometry_hash": s1.get("geometry_hash"),
        "c1": (sq or {}).get("c1"),
        "max_tangent_delta_deg": (sq or {}).get("maximum_tangent_delta_deg"),
        "self_intersection_count": (sq or {}).get("self_intersection_count"),
        "plan_sha256": geo.canonical_sha256(geo.s1_plan()),
        "source": "in-process d0_geometry_probe s1_plan/run_plan",
        "outcome_scope": "reconstructed_fixture_geometry_only",
    })
    diagnosis.append({
        "case_id": "A9-JUNCTION-MOCK",
        "evidence_mode": "mock",
        "final_outcome": "failed" if junction["junction_constraints_preserved"] is False else "passed",
        "failure_category": "constraint_loss" if junction["junction_constraints_preserved"] is False else None,
        "junction_constraints_preserved": junction["junction_constraints_preserved"],
        "before_plan_sha256": junction["before_plan_sha256"],
        "source": "in-process d0_geometry_probe junction_repair_probe",
    })

    # Generic structural analogs (closed outline ~ A9; open anchor chain ~ S1).
    analog_ids = ["irregular_closed_boundary", "free_polygon_outline", "z_axis_route"]
    by_id = {r["case_id"]: r for r in bench55.get("results", [])}
    for aid in analog_ids:
        rec = by_id.get(aid)
        if rec is None:
            continue
        failed_checks = [k for k, v in (rec.get("checks") or {}).items() if v is False]
        diagnosis.append({
            "case_id": aid,
            "analog_of": "A9" if aid in ("irregular_closed_boundary", "free_polygon_outline") else "S1",
            "category": rec.get("category"),
            "evidence_mode": "rule_parser_zero_cost",
            "final_outcome": "passed" if rec.get("passed") else "failed",
            "failure_category": None if rec.get("passed") else (
                "clarification_required" if rec.get("status") == "clarification_required"
                else "benchmark_expectation_mismatch"),
            "status": rec.get("status"),
            "failed_checks": failed_checks,
            "provider_attempted_result_level": rec.get("provider_attempted"),
            "provider": rec.get("provider"),
            "outcome_scope": "benchmark_interpretation_only",
            "source": "committed D0 rule_benchmark_extended55.json",
        })

    return {
        "registry_cases": len(registry.get("cases", [])),
        "replay_summary": replay.get("summary"),
        "benchmark_core6_summary": bench6.get("summaries", {}).get("rules"),
        "benchmark_extended55_summary": bench55.get("summaries", {}).get("rules"),
        "diagnosis": diagnosis,
    }


def canonical_sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="D1 baseline runner + classifier")
    parser.add_argument("--out", default=str(PROBES / "d1_baseline_snapshot.json"))
    parser.add_argument("--suite", default=None, help="run a single suite by id")
    parser.add_argument("--no-collect", action="store_true")
    parser.add_argument("--backend", default=str(BACKEND),
                        help="target backend root (read-only); defaults to this D worktree")
    parser.add_argument("--label", default="D0-a4f2af7", help="target label for the snapshot")
    parser.add_argument("--target-ref", default=None, help="claimed target commit SHA")
    parser.add_argument("--no-diagnosis", action="store_true",
                        help="skip D0 case diagnosis (use when targeting another worktree)")
    args = parser.parse_args()

    backend = Path(args.backend)
    tmp = Path(tempfile.mkdtemp(prefix="d1_pytest_"))
    suites_out: list[dict[str, Any]] = []
    for idx, suite in enumerate(SUITES, start=1):
        if args.suite and suite["suite_id"] != args.suite:
            continue
        junit = tmp / f"d1_suite_{idx}.xml"
        suites_out.append({"suite_id": suite["suite_id"], "d0_ref": suite["d0_ref"],
                            **run_pytest(suite["module"], junit, backend)})

    collect = None if args.no_collect else run_collect_only(backend)
    diagnosis = None if args.no_diagnosis else case_diagnosis()

    snapshot = {
        "schema": "cad.d1.baseline-snapshot.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "round": "D1-1 frozen baseline forensics + failure classification skeleton",
        "label": args.label,
        "target_backend": str(backend),
        "git": {
            "head_sha": _git(["rev-parse", "HEAD"], backend),
            "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"], backend),
            "status_short": _git(["status", "--short"], backend),
            "claimed_target_ref": args.target_ref,
        },
        "environment": {
            "python_executable": sys.executable,
            "versions": package_versions(),
            "guard": env_guard(),
        },
        "guards": {
            "live_model_calls": 0,
            "project_or_candidate_writes": False,
            "production_code_modified": False,
            "d0_assets_regenerated": False,
        },
        "suites": suites_out,
        "collect_only": collect,
        "cases": diagnosis,
    }

    out_path = Path(args.out)
    # Hash the canonical payload excluding the hash field itself; the stored
    # file pretty-prints, so snapshot_sha256 is verified against the canonical form.
    snapshot["snapshot_sha256"] = canonical_sha256(
        {k: v for k, v in snapshot.items() if k != "snapshot_sha256"})
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "schema": snapshot["schema"],
        "head_sha": snapshot["git"]["head_sha"],
        "suites": [{s["suite_id"]: s["counts"]} for s in suites_out],
        "collect_only": None if collect is None else {
            "tests_collected": collect["tests_collected"],
            "collection_errors": collect["collection_errors"],
        },
        "snapshot": str(out_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
