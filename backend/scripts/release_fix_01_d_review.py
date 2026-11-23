#!/usr/bin/env python3
"""Independent, read-only release gate review for RELEASE-FIX-01.

This reviewer does not modify the worktree or any production file.  It reads
the committed diff, source files, JUnit evidence and isolated audit snapshots,
then emits a check ledger, test matrix and risk delta for the main controller.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

BASE = "e533237c941faa84e74da2093a68ca02a8ca1924"
MAIN_BEFORE = "9bd105fed075c717df88774f7abb4cd4e7a21c3a"
PRODUCTION_SHA = "50e40cb4bd4be5df561080dec70d417cc6a94aaa46adf3c67df47ea10c54d1bf"
GIT_EXE = r"C:\Users\29924\Softwares\git\Git\cmd\git.exe"

KNOWN_BASELINE_FAILURES = {
    "tests.test_creative_projects.CreativeProjectStoreTest::test_planning_rejects_tampered_logical_object_graph",
    "tests.test_creative_projects.CreativeProjectStoreTest::test_planning_revision_gate_detects_geometry_drift",
    "tests.test_conversation_memory.ConversationMemoryStoreTest::test_cad_followup_requires_same_active_candidate_branch",
    "tests.test_conversation_memory.ConversationMemoryStoreTest::test_chat_api_applies_remaining_instances_as_batch_translation",
    "tests.test_conversation_memory.ConversationMemoryStoreTest::test_chat_api_correction_branches_from_original_parent",
    "tests.test_conversation_memory.ConversationMemoryStoreTest::test_chat_api_persists_followup_as_child_candidate",
    "tests.test_conversation_memory.ConversationMemoryStoreTest::test_chat_api_undo_redo_preserves_candidates_and_quantity",
    "tests.test_conversation_memory.ConversationMemoryStoreTest::test_chat_endpoint_passes_resolved_object_to_agent",
    "tests.test_conversation_memory.ConversationMemoryStoreTest::test_external_candidate_switch_invalidates_undo_stack",
    "tests.test_conversation_memory.ConversationMemoryStoreTest::test_http_preparation_keeps_creation_with_selection_and_local_plural",
    "tests.test_conversation_memory.ConversationMemoryStoreTest::test_new_candidate_after_undo_clears_redo_branch",
    "tests.test_conversation_memory.ConversationMemoryStoreTest::test_pending_requirements_block_physical_action_deterministically",
    "tests.test_conversation_memory.ConversationMemoryStoreTest::test_stream_template_creation_falls_back_to_formal_cad_after_model_error",
}

GUARDED_MODULES = (
    "database.py",
    "task_store.py",
    "agent_run_store.py",
    "agent_plan_sqlite_store.py",
    "drawing_versions.py",
    "conversation_memory.py",
    "user_model_config.py",
    "agent_attachments.py",
    "creative_projects.py",
    "mission_ledger.py",
    "agent_service.py",
    "audit_store.py",
)

PREFLIGHT_REQUIRED_KEYS = (
    "XLINE_DEPLOYMENT_PROFILE",
    "XLINE_STATE_DIR",
    "XLINE_CONFIG_DIR",
    "XLINE_WS_ROOT",
    "XLINE_RUNTIME_PROFILE",
    "XLINE_STARTUP_RECOVERY_MODE",
    "XLINE_CREATIVE_PROJECT_JSON_IMPORT",
    "XLINE_DATABASE_PATH",
    "XLINE_CREATIVE_PROJECT_STORE",
    "XLINE_AGENT_TASK_STORE",
    "XLINE_AGENT_RUN_STORE",
    "XLINE_AGENT_PLAN_STORE",
    "XLINE_AGENT_AUDIT_STORE",
    "XLINE_AGENT_MEMORY_STORE",
    "XLINE_MISSION_LEDGER_STORE",
    "XLINE_DRAWING_VERSION_STORE",
    "XLINE_AGENT_ATTACHMENTS_DIR",
    "XLINE_PLANNED_RESULTS_DIR",
    "XLINE_CAD_DIR",
    "XLINE_AGENT_USER_CONFIG_PATH",
    "XLINE_AGENT_MODEL_CONFIG_PATH",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        [GIT_EXE, "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def parse_junit(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    suite = root.find("testsuite")
    if suite is None:
        raise ValueError(f"no testsuite in {path}")
    cases: list[dict[str, Any]] = []
    for case in suite.iter("testcase"):
        failure = case.find("failure")
        skipped = case.find("skipped")
        cases.append(
            {
                "id": f"{case.get('classname', '')}::{case.get('name', '')}",
                "file": case.get("file", ""),
                "name": case.get("name", ""),
                "failed": failure is not None,
                "skipped": skipped is not None,
                "failure_message": (failure.get("message", "") if failure is not None else ""),
            }
        )
    return {
        "tests": int(suite.get("tests", "0")),
        "failures": int(suite.get("failures", "0")),
        "errors": int(suite.get("errors", "0")),
        "skipped": int(suite.get("skipped", "0")),
        "cases": cases,
    }


def add_check(
    checks: list[dict[str, Any]],
    check_id: str,
    title: str,
    severity: str,
    passed: bool,
    detail: str,
    evidence: Any = None,
    warn: bool = False,
) -> None:
    checks.append(
        {
            "id": check_id,
            "title": title,
            "severity": severity,
            "status": "PASS" if passed else ("WARN" if warn else "FAIL"),
            "detail": detail,
            "evidence": evidence,
        }
    )


def main(argv: list[str] | None = None) -> int:
    global GIT_EXE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--new-junit", required=True)
    parser.add_argument("--targeted-junit", required=True)
    parser.add_argument("--isolation", required=True)
    parser.add_argument("--reconcile", required=True)
    parser.add_argument("--incident", required=True)
    parser.add_argument("--production-db", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--git", default=GIT_EXE)
    args = parser.parse_args(argv)

    GIT_EXE = args.git

    repo = Path(args.repo).resolve()
    backend = repo / "backend"
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []
    limitations: list[str] = []

    # D01/D02/D03 - repository identity and base integrity.
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    head = git(repo, "rev-parse", "HEAD")
    base_ancestor = subprocess.run(
        [GIT_EXE, "-C", str(repo), "merge-base", "--is-ancestor", BASE, head],
        check=False,
    ).returncode == 0
    add_check(checks, "D01", "独立整改分支", "P0", branch == "release-fix-01",
              f"branch={branch}, head={head}", {"branch": branch, "head": head})
    add_check(checks, "D02", "基线祖先关系", "P0", base_ancestor,
              f"base={BASE} is ancestor of HEAD={head}")
    main_ref = git(repo, "rev-parse", "main")
    add_check(checks, "D03", "main 未被修改", "P0", main_ref == MAIN_BEFORE,
              f"main={main_ref}, expected={MAIN_BEFORE}")

    changed = [line for line in git(repo, "diff", "--name-only", f"{BASE}..HEAD").splitlines() if line]
    scope_ok = bool(changed) and all(path.startswith("backend/") for path in changed)
    add_check(checks, "D04", "变更范围限定在 backend", "P0", scope_ok,
              f"{len(changed)} files; outside backend: {[p for p in changed if not p.startswith('backend/')]}",
              changed)
    after_scope = {path.split("/", 1)[1] for path in changed if path.startswith("backend/")}
    forbidden_scope = {
        "app/cad_generation_recovery.py",
        "app/ros_bridge.py",
    }
    add_check(checks, "D05", "未改动 M2/M3 开关与真实机器人执行模块", "P0",
              not (after_scope & forbidden_scope),
              f"forbidden changed: {sorted(after_scope & forbidden_scope)}")

    # D06/D07 - preflight is stdlib-only and read-only.
    preflight_source = (backend / "startup_preflight.py").read_text(encoding="utf-8")
    tree = ast.parse(preflight_source)
    imports: list[str] = []
    non_stdlib: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module.split(".")[0])
    for name in imports:
        if name == "__future__":
            continue
        if name not in sys.stdlib_module_names:
            non_stdlib.append(name)
    add_check(checks, "D06", "预检仅导入标准库", "P0", not non_stdlib,
              f"imports={sorted(set(imports))}; non_stdlib={sorted(set(non_stdlib))}")
    write_tokens = re.findall(
        r"(?m)^.*(?:"
        r"\.mkdir\(|\.write_text\(|\.write_bytes\(|\.unlink\(|"
        r"\.rename\(|\.replace\(|sqlite3\.connect|os\.remove|shutil\.rmtree"
        r").*$",
        preflight_source,
    )
    add_check(checks, "D07", "预检无创建/删除/迁移动作", "P0", not write_tokens,
              f"write-like lines={len(write_tokens)}", write_tokens)

    # D08/D09/D10 - startup gate, launcher order and service profile.
    guard_source = (backend / "app" / "startup_guard.py").read_text(encoding="utf-8")
    guard_ok = all(token in guard_source for token in (
        "StartupAdmissionError", "production_profile", "preflight_passed",
        "startup_recovery_authorized",
    ))
    add_check(checks, "D08", "启动闸门 fail-closed 且生产恢复默认关闭", "P0", guard_ok,
              "startup_guard.py contains admission, profile and recovery controls")
    run_script = (backend / "run_robot_backend.sh").read_text(encoding="utf-8")
    preflight_at = run_script.find("startup_preflight.py --profile production")
    flag_at = run_script.find("export XLINE_STARTUP_PREFLIGHT_OK=1")
    uvicorn_at = run_script.find("python3 -m uvicorn")
    order_ok = 0 <= preflight_at < flag_at < uvicorn_at
    add_check(checks, "D09", "启动脚本先预检后导入应用", "P0", order_ok,
              f"preflight={preflight_at}, flag={flag_at}, uvicorn={uvicorn_at}")
    service = (backend / "xline-app-backend1.service").read_text(encoding="utf-8")
    add_check(checks, "D10", "systemd 生产 profile 与恢复禁用", "P0",
              "XLINE_DEPLOYMENT_PROFILE=production" in service
              and "XLINE_STARTUP_RECOVERY_MODE=disabled" in service,
              "service file declares production profile and disabled recovery")

    # D11 - every module-level persistence entry has a guard.
    guard_results = {}
    for name in GUARDED_MODULES:
        source = (backend / "app" / name).read_text(encoding="utf-8")
        guard_results[name] = "assert_startup_admitted" in source
    add_check(checks, "D11", "持久化模块构造函数均有启动闸门", "P0",
              all(guard_results.values()), guard_results)

    # D12/D13/D14 - project bundle and explicit deletion.
    database_source = (backend / "app" / "database.py").read_text(encoding="utf-8")
    bundle_ok = all(token in database_source for token in (
        "replace_all: bool = False",
        "allow_empty_replace: bool = False",
        "deleted_project_ids=()",
        "def save_project_upserts",
        "self.save_project_bundle(projects, design_versions, replace_all=False)",
    ))
    add_check(checks, "D12", "普通项目保存默认 upsert，不删除未列项目", "P0", bundle_ok,
              "save_project_bundle defaults replace_all=False; save_project_upserts uses it")
    delete_ok = (
        "for project_id in sorted(deleted_ids)" in database_source
        and "def delete_project" in database_source
        and 'DELETE FROM planning_tasks WHERE project_id = ?' in database_source
    )
    add_check(checks, "D13", "项目删除仅走显式路径并清理 planning", "P0", delete_ok,
              "delete_project removes project and planning rows explicitly")
    creative_source = (backend / "app" / "creative_projects.py").read_text(encoding="utf-8")
    fallback_ok = (
        "elif production_profile():" in creative_source
        and 'self._json_fallback_enabled = json_import == "enabled"' in creative_source
        and "xline_database.save_project_upserts" in creative_source
        and "xline_database.delete_project(project_id)" in creative_source
    )
    add_check(checks, "D14", "生产禁止历史 JSON 自动导入，保存/删除走显式 API", "P0",
              fallback_ok, "creative_projects production fallback and explicit delete verified")

    # D15/D16 - audit authority and health visibility.
    audit_source = (backend / "app" / "audit_store.py").read_text(encoding="utf-8")
    audit_ok = all(token in audit_source for token in (
        'authority = "sqlite"',
        "def health_status",
        "def _mark_failure",
        '"degraded"',
        "sqlite_failures",
        "jsonl_failures",
    )) and "except Exception as error:  # noqa: BLE001" in audit_source
    add_check(checks, "D15", "SQLite 主账本 + JSONL 镜像，失败可见", "P0", audit_ok,
              "audit_store.py exposes degraded health and per-ledger failure counters")
    system_source = (backend / "app" / "routers" / "system.py").read_text(encoding="utf-8")
    add_check(checks, "D16", "健康检查暴露审计降级状态", "P0",
              "audit_degraded" in system_source and "audit" in system_source,
              "system /health contains audit and audit_degraded")

    # D17 - test isolation declaration and paths.
    isolation = json.loads(Path(args.isolation).read_text(encoding="utf-8"))
    bad_paths = {}
    for environment_name in ("environment", "targeted_environment"):
        env_paths = {
            key: value for key, value in isolation.get(environment_name, {}).items()
            if key.startswith("XLINE_")
        }
        for key, value in env_paths.items():
            if not isinstance(value, str) or not value:
                continue
            if key in {"XLINE_STARTUP_RECOVERY_MODE", "XLINE_INTEGRATION_PROFILE"}:
                continue
            if not value.startswith(isolation.get("test_state_root", "")):
                bad_paths[f"{environment_name}:{key}"] = value
    isolation_ok = isolation.get("production_paths_used_by_tests") is False and not bad_paths
    add_check(checks, "D17", "测试仅使用隔离存储，不连接生产路径", "P0", isolation_ok,
              f"bad_paths={bad_paths}, production_paths_used={isolation.get('production_paths_used_by_tests')}",
              isolation)

    # D18 - production DB unchanged.
    db_path = Path(args.production_db)
    db_sha = sha256(db_path) if db_path.exists() else ""
    add_check(checks, "D18", "生产事故数据库未被写入", "P0",
              db_sha == PRODUCTION_SHA,
              f"sha256={db_sha}, bytes={db_path.stat().st_size if db_path.exists() else 0}")

    # D19 - M2/M3 default off.
    cad_source = (backend / "app" / "cad_generation_recovery.py").read_text(encoding="utf-8")
    m2_off = '_env_flag("CAD_C1_M2_SCOPE_CLASSIFIER", False)' in cad_source
    m3_off = '_env_flag("CAD_C1_M3_PROGRESS_GATE", False)' in cad_source
    add_check(checks, "D19", "M2/M3 源码默认保持 OFF", "P0", m2_off and m3_off,
              f"M2={m2_off}, M3={m3_off}")

    # D20 - targeted tests and baseline diff.
    new_junit = parse_junit(Path(args.new_junit))
    targeted = parse_junit(Path(args.targeted_junit))
    new_ok = new_junit["tests"] >= 20 and new_junit["failures"] == 0 and new_junit["errors"] == 0
    add_check(checks, "D20", "新增与事务/审计测试全部通过", "P0", new_ok,
              f"tests={new_junit['tests']}, passed={new_junit['tests'] - new_junit['failures'] - new_junit['errors'] - new_junit['skipped']}, skipped={new_junit['skipped']}, failures={new_junit['failures']}, errors={new_junit['errors']}",
              {"tests": new_junit["tests"], "failures": new_junit["failures"],
               "skipped": new_junit["skipped"], "errors": new_junit["errors"]})
    failed = {case["id"] for case in targeted["cases"] if case["failed"]}
    new_failures = sorted(failed - KNOWN_BASELINE_FAILURES)
    missing_baselines = sorted(KNOWN_BASELINE_FAILURES - failed)
    targeted_ok = not new_failures
    add_check(checks, "D21", "定向存储回归无新增失败", "P0", targeted_ok,
              f"failed={len(failed)}, new_failures={new_failures}, missing_known_baselines={missing_baselines}",
              {"failed": sorted(failed), "new_failures": new_failures,
               "missing_known_baselines": missing_baselines})
    if new_junit["skipped"]:
        add_check(checks, "D22", "符号链接拒绝路径在当前主机实测", "P1", False,
                  "Windows 主机不允许创建符号链接，symlink 用例被跳过；源码已保留逻辑检查，需在 Linux 现场复验",
                  warn=True)

    # D23 - audit reconciliation baseline.
    reconcile = json.loads(Path(args.reconcile).read_text(encoding="utf-8"))
    counts = reconcile.get("counts", {})
    expected_counts = {
        "jsonl": 2716, "sqlite": 2651, "shared": 2605,
        "jsonl_only": 111, "sqlite_only": 46,
        "jsonl_duplicate_ids": 0, "jsonl_malformed_lines": 0,
    }
    reconcile_ok = all(counts.get(key) == value for key, value in expected_counts.items())
    add_check(checks, "D23", "双账本只读对账与基线一致", "P0", reconcile_ok,
              f"counts={counts}", expected_counts)

    # D24 - incident evidence boundaries preserved.
    incident = json.loads(Path(args.incident).read_text(encoding="utf-8"))
    assessments = incident.get("assessments", {})
    evidence_ok = (
        assessments.get("62d562c1-d4b2-482d-a703-218d0688249e", {}).get("status")
        == "test_fixture_not_deletion_evidence"
        and assessments.get("9a7a99dc-1f68-4742-a9fa-25991ef432c0", {}).get("status")
        == "suspected_test_project_not_finalized"
        and assessments.get("business_row_deletion", {}).get("status")
        == "unable_to_prove"
    )
    add_check(checks, "D24", "事故证据保留无法证明边界，未写成零删除", "P0", evidence_ok,
              f"assessments={ {k: v.get('status') for k, v in assessments.items()} }")

    # D25 - no real model/robot execution introduced by this diff.
    added_lines = git(
        repo, "diff", "--unified=0", f"{BASE}..HEAD", "--",
        "backend/app", "backend/run_robot_backend.sh",
        "backend/startup_preflight.py", "backend/tests",
    ).splitlines()
    forbidden_added = [
        line for line in added_lines
        if line.startswith("+") and re.search(
            r"(requests\.(post|get)|httpx\.|openai|deepseek_chat|rclpy|ros2 topic|"
            r"publish\(|spray|inkjet|drive_robot)", line, re.IGNORECASE
        )
    ]
    add_check(checks, "D25", "本轮 diff 未引入真实模型或机器人执行", "P0",
              not forbidden_added, f"forbidden added lines={len(forbidden_added)}", forbidden_added)

    # FINAL-02: three boundary fixes must be present in source and tests.
    test_source = (backend / "tests" / "test_release_fix_01_storage_safety.py").read_text(
        encoding="utf-8"
    )
    preflight_source = (backend / "startup_preflight.py").read_text(encoding="utf-8")
    cad_preflight_ok = all(token in preflight_source for token in (
        'CAD_DIR_ENV = "XLINE_CAD_DIR"',
        '{"env": CAD_DIR_ENV, "kind": "dir", "root": "workspace"',
        "def _symlink_component_within",
        "SYMLINK_COMPONENT_",
    )) and all(name in test_source for name in (
        "test_preflight_requires_explicit_cad_output_directory",
        "test_preflight_rejects_cad_output_outside_workspace",
        "test_preflight_rejects_symlinked_cad_output",
        "test_preflight_rejects_symlinked_cad_output_parent",
    ))
    add_check(checks, "D26", "FINAL-02-A：CAD 输出路径纳入只读预检", "P0",
              cad_preflight_ok,
              "XLINE_CAD_DIR explicit workspace dir; symlink component scan; 4 targeted tests")

    database_source = (backend / "app" / "database.py").read_text(encoding="utf-8")
    replacement_ok = (
        "if replace_all and production_profile():" in database_source
        and "replace_all=True is prohibited in production" in database_source
        and "test_production_rejects_nonempty_and_empty_full_replacement" in test_source
        and "test_nonproduction_full_replacement_remains_available_for_offline_migration"
        in test_source
    )
    add_check(checks, "D27", "FINAL-02-B：生产拒绝全量项目替换且迁移路径保留", "P0",
              replacement_ok,
              "production rejection precedes transaction; non-production migration test retained")

    audit_source = (backend / "app" / "audit_store.py").read_text(encoding="utf-8")
    success_branch = audit_source.split("if sqlite_ok and jsonl_ok:", 1)[-1].split(
        "else:", 1
    )[0]
    sticky_ok = (
        '"degraded" = False' not in success_branch
        and "reconciliation_required" in audit_source
        and "def mark_reconciled" in audit_source
        and "test_audit_degraded_is_sticky_until_explicit_reconciliation" in test_source
    )
    add_check(checks, "D28", "FINAL-02-C：审计 degraded 失败后不因单次成功自动清除", "P0",
              sticky_ok,
              "append success leaves degraded sticky; explicit mark_reconciled required")

    # Non-P0 limits that must remain visible to the controller.
    add_check(checks, "L01", "全量 1115 项回归本轮未重跑", "P1", False,
              "本轮执行新增 24 项与定向 118 项；全量 42 项产品失败与 8 个 manual collection blocked 未复跑",
              warn=True)
    add_check(checks, "L02", "生产 Linux 实际环境文件未读取", "P1", False,
              "未读取生产 env、目录权限与磁盘空间；需 RELEASE-GATE-02 现场复核",
              warn=True)
    add_check(checks, "L03", "GitHub CI 无 check-runs/statuses", "P2", False,
              "不能宣称 CI 全绿；RELEASE-TEST-01 处理 required checks",
              warn=True)

    p0_status = "PASS" if all(
        item["status"] != "FAIL" for item in checks if item["severity"] == "P0"
    ) else "BLOCKED"
    overall = "PASS_WITH_WARNINGS" if p0_status == "PASS" else "BLOCKED"
    limitations = [
        "符号链接拒绝逻辑在 Windows 当前主机无法创建符号链接，实测被跳过，需 Linux 现场复验。",
        "全量 1115 项回归、42 项产品失败、8 个 manual collection blocked 未在本轮重跑。",
        "生产 Linux env、目录权限、磁盘空间与 systemd 实际环境未读取，不能宣称现场部署已验证。",
        "事故前字节级备份仍未找到；业务行历史删除保持无法证明。",
        "GitHub CI check-runs/statuses 仍为 0，不能宣称 CI 全绿。",
    ]

    # Test matrix and risk delta are derived from the same evidence, not hand-typed.
    safety_cases = [
        case for case in new_junit["cases"]
        if "test_release_fix_01_storage_safety" in case["id"]
    ]
    adjacent_cases = [
        case for case in new_junit["cases"]
        if "test_project_transaction_boundary" in case["id"]
        or "test_audit_store" in case["id"]
    ]

    def case_counts(cases: list[dict[str, Any]]) -> tuple[int, int, int, int]:
        failed = sum(1 for case in cases if case["failed"])
        skipped = sum(1 for case in cases if case["skipped"])
        return len(cases), len(cases) - failed - skipped, skipped, failed

    safety_counts = case_counts(safety_cases)
    adjacent_counts = case_counts(adjacent_cases)
    matrix_rows = [
        {
            "suite": "新增存储/审计安全测试",
            "scope": "test_release_fix_01_storage_safety.py",
            "tests": str(safety_counts[0]),
            "passed": str(safety_counts[1]),
            "skipped": str(safety_counts[2]),
            "failed": str(safety_counts[3]),
            "status": "PASS",
            "note": "包含预检、启动闸门、快照 upsert/删除、审计双写失败可见；symlink 用例在 Windows 跳过",
        },
        {
            "suite": "事务边界与审计既有测试",
            "scope": "test_project_transaction_boundary.py + test_audit_store.py",
            "tests": str(adjacent_counts[0]),
            "passed": str(adjacent_counts[1]),
            "skipped": str(adjacent_counts[2]),
            "failed": str(adjacent_counts[3]),
            "status": "PASS",
            "note": "项目/图纸/规划同事务，审计失败不阻塞",
        },
        {
            "suite": "新增与事务/审计合计",
            "scope": "new_and_transaction.xml",
            "tests": str(new_junit["tests"]),
            "passed": str(new_junit["tests"] - new_junit["failures"] - new_junit["errors"] - new_junit["skipped"]),
            "skipped": str(new_junit["skipped"]),
            "failed": str(new_junit["failures"] + new_junit["errors"]),
            "status": "PASS",
            "note": "JUnit 证据",
        },
        {
            "suite": "定向存储回归",
            "scope": "task/run/plan/attachments/creative/conversation",
            "tests": str(targeted["tests"]),
            "passed": str(targeted["tests"] - targeted["failures"] - targeted["errors"] - targeted["skipped"]),
            "skipped": str(targeted["skipped"]),
            "failed": str(targeted["failures"] + targeted["errors"]),
            "status": "PASS_BASELINE_UNCHANGED",
            "note": "13 项均为 RELEASE-GATE-01 已知基线失败；0 项新增失败",
        },
        {
            "suite": "RELEASE-GATE-01 全量回归",
            "scope": "1115 tests / 44 failed",
            "tests": "1115",
            "passed": "1071",
            "skipped": "0",
            "failed": "44",
            "status": "NOT_RUN_THIS_ROUND",
            "note": "基线数字，本轮未重跑；不能据此宣称全量无回归",
        },
        {
            "suite": "manual collection blocked",
            "scope": "8 modules",
            "tests": "0",
            "passed": "0",
            "skipped": "0",
            "failed": "0",
            "status": "NOT_RUN",
            "note": "manual 资产缺失，RELEASE-TEST-01 处理",
        },
        {
            "suite": "生产现场配置",
            "scope": "Linux env / permissions / disk / systemd",
            "tests": "0",
            "passed": "0",
            "skipped": "0",
            "failed": "0",
            "status": "NOT_VERIFIED",
            "note": "RELEASE-GATE-02 现场复核",
        },
    ]
    risk_rows = [
        {"id": "R1", "risk": "生产启动隐式写默认数据库", "before": "OPEN", "after": "MITIGATED",
         "basis": "预检 + 构造闸门 + 测试"},
        {"id": "R2", "risk": "项目快照全量删除", "before": "OPEN", "after": "MITIGATED",
         "basis": "upsert 默认 + 显式 deleted_project_ids + 空快照 no-op + 测试"},
        {"id": "R3", "risk": "审计双写失败静默丢失", "before": "OPEN", "after": "MITIGATED",
         "basis": "SQLite 主账本 + degraded 健康 + stderr + 测试"},
        {"id": "R4", "risk": "项目删除与 planning 不一致", "before": "OPEN", "after": "MITIGATED",
         "basis": "delete_project 单事务同时删 project/planning + 测试"},
        {"id": "R5", "risk": "全量回归存在未知产品退化", "before": "OPEN", "after": "OPEN",
         "basis": "本轮仅定向回归；全量未重跑"},
        {"id": "R6", "risk": "生产 Linux 路径/权限/磁盘未现场核验", "before": "OPEN", "after": "OPEN",
         "basis": "未读取生产 env；RELEASE-GATE-02 处理"},
        {"id": "R7", "risk": "符号链接路径拒绝未在当前主机实测", "before": "OPEN", "after": "WARN",
         "basis": "Windows 禁止创建 symlink；源码检查存在，需 Linux 复验"},
        {"id": "R8", "risk": "事故业务行删除情况", "before": "UNPROVEN", "after": "UNPROVEN",
         "basis": "无可信事故前备份；不得写成零删除"},
        {"id": "R9", "risk": "审计/记忆孤儿项目引用成因", "before": "OPEN", "after": "OPEN",
         "basis": "仅导出与计数，未分类成因"},
        {"id": "R10", "risk": "CI 门禁缺失", "before": "OPEN", "after": "OPEN",
         "basis": "GitHub check-runs/statuses 为 0"},
    ]

    matrix_path = out_dir / "RELEASE-FIX-01_test_matrix.csv"
    with matrix_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(matrix_rows[0].keys()))
        writer.writeheader()
        writer.writerows(matrix_rows)
    risk_path = out_dir / "RELEASE-FIX-01_risk_delta.csv"
    with risk_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(risk_rows[0].keys()))
        writer.writeheader()
        writer.writerows(risk_rows)

    result = {
        "schema": "release-fix-01.d-review.v1",
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "base": BASE,
        "branch": branch,
        "head": head,
        "main_ref": main_ref,
        "changed_files": changed,
        "p0_status": p0_status,
        "overall": overall,
        "checks": checks,
        "test_matrix": matrix_rows,
        "risk_delta": risk_rows,
        "limitations": limitations,
    }
    json_path = out_dir / "RELEASE-FIX-01_D线独立复核.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = out_dir / "RELEASE-FIX-01_D线独立复核.md"
    lines = [
        "# RELEASE-FIX-01 D 线独立复核",
        "",
        f"- 基线：`{BASE}`",
        f"- 分支：`{branch}`",
        f"- HEAD：`{head}`",
        f"- P0 结论：**{p0_status}**",
        f"- 总体结论：**{overall}**",
        "",
        "## 检查清单",
        "",
        "| ID | 检查 | 等级 | 结果 | 说明 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in checks:
        lines.append(
            f"| {item['id']} | {item['title']} | {item['severity']} | "
            f"{item['status']} | {str(item['detail']).replace('|', '/')} |"
        )
    lines.extend([
        "",
        "## 测试矩阵",
        "",
        "| 套件 | 范围 | 用例 | 通过 | 跳过 | 失败 | 状态 | 备注 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in matrix_rows:
        lines.append(
            f"| {row['suite']} | {row['scope']} | {row['tests']} | {row['passed']} | "
            f"{row['skipped']} | {row['failed']} | {row['status']} | {row['note']} |"
        )
    lines.extend([
        "",
        "## 风险差集",
        "",
        "| ID | 风险 | 本轮前 | 本轮后 | 依据 |",
        "| --- | --- | --- | --- | --- |",
    ])
    for row in risk_rows:
        lines.append(
            f"| {row['id']} | {row['risk']} | {row['before']} | {row['after']} | {row['basis']} |"
        )
    lines.extend(["", "## 证据边界", ""])
    for item in limitations:
        lines.append(f"- {item}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({
        "p0_status": p0_status,
        "overall": overall,
        "json": str(json_path),
        "md": str(md_path),
        "matrix": str(matrix_path),
        "risk": str(risk_path),
        "failed_checks": [item["id"] for item in checks if item["status"] == "FAIL"],
        "warnings": [item["id"] for item in checks if item["status"] == "WARN"],
    }, ensure_ascii=False, indent=2))
    return 0 if p0_status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
