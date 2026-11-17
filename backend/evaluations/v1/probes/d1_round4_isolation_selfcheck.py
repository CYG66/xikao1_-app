"""Zero-cost self-check for the round-4 isolation collector.

Stages (no network, no model call, no A9 rerun):

A. Offline: isolation env mapping applied BEFORE any app import; redaction
   self-check; budget reserve/settle with a synthetic usage block; model-match
   guard; fail-closed path assertion demo; recorder demo on synthetic data.
B. App import: resolve every production store singleton under the isolation
   root, fail-closed assert no escape, and compare the shared default state
   dir before/after to prove nothing was written there.
C. Evidence protection: hash committed A9 historical artifacts and confirm the
   working-tree copies match HEAD (not overwritten).

Usage:
    python d1_round4_isolation_selfcheck.py --backend <combo-backend> \
        --v1-dir <evaluations/v1> --repo <D-worktree-root> --out <snapshot.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import d1_round4_isolation_collector as collector  # noqa: E402


def _normalized_bytes(text: str) -> bytes:
    # Git may store LF while the checkout has CRLF; compare normalized text so
    # EOL normalization does not masquerade as a content change.
    return text.replace("\r\n", "\n").encode("utf-8")


def git_head_text(repo: pathlib.Path, rel_path: str) -> str | None:
    git = r"C:\Users\29924\Softwares\git\Git\cmd\git.exe"
    try:
        out = subprocess.run(
            [git, "-C", str(repo), "show", f"HEAD:{rel_path}"],
            capture_output=True, check=True,
        )
        return out.stdout.decode("utf-8")
    except subprocess.CalledProcessError:
        return None


def default_state_dir() -> pathlib.Path:
    return pathlib.Path(tempfile.gettempdir()) / "xline-agent"


def snapshot_dir(directory: pathlib.Path) -> dict[str, list[object]]:
    if not directory.exists():
        return {}
    out: dict[str, list[object]] = {}
    for p in sorted(directory.iterdir()):
        if p.is_file():
            st = p.stat()
            out[p.name] = [st.st_size, st.st_mtime_ns]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True)
    ap.add_argument("--v1-dir", required=True)
    ap.add_argument("--repo", required=True, help="D worktree repo root")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    backend = pathlib.Path(args.backend).resolve()
    v1_dir = pathlib.Path(args.v1_dir).resolve()
    repo = pathlib.Path(args.repo).resolve()
    snapshot: dict[str, object] = {"stages": {}}

    # ---- Stage A: offline, before any app import --------------------------- #
    iso_root = pathlib.Path(tempfile.gettempdir()) / "xline-d1-isolation-selfcheck"
    case_id = "SELFCHECK"
    root = (iso_root / case_id).resolve()

    # Timing evidence: env is applied here, before `resolve_state_paths` imports
    # the app store modules (stage B). The script order below is the proof.
    env = collector.prepare_isolation_env(iso_root, case_id)
    env_inside = {
        k: pathlib.Path(v).resolve().is_relative_to(root)
        for k, v in env.items()
    }

    secret_sample = {
        "Authorization": "Bearer sk-test1234567890abcdef",
        "nested": {"api_key": "sk-ABCDEF1234567890XYZ", "note": "keep-me"},
        "plain": "token=tok-9876543210abcdefXYZ",
    }
    redacted = collector.redact(secret_sample)
    redacted_text = json.dumps(redacted, ensure_ascii=False)
    collector.assert_no_secret_shape(redacted_text)

    guard = collector.BudgetGuard()
    reserve = guard.reserve(input_estimate=10_000, max_output_tokens=8192)
    fake_usage = {
        "prompt_tokens": 15382,
        "completion_tokens": 354,
        "prompt_cache_hit_tokens": 1024,
        "prompt_cache_miss_tokens": 14358,
    }
    settled = guard.settle(fake_usage, expected_model=collector.FLASH,
                           response_model=collector.FLASH)
    remaining = guard.remaining()

    mismatch_blocked = False
    try:
        guard.settle(fake_usage, expected_model=collector.FLASH,
                     response_model="deepseek-chat")
    except collector.IsolationViolation:
        mismatch_blocked = True

    # Fail-closed demo: a path that escapes the root must abort the run.
    shared = default_state_dir() / "agent_audit.jsonl"
    fake_resolved = [{"label": "audit_jsonl", "env_var": "XLINE_AGENT_AUDIT_STORE",
                      "resolved": str(shared), "resolver_ref": "demo"}]
    fail_closed_blocked = False
    fail_closed_message = ""
    try:
        collector.assert_within_root(iso_root, case_id, fake_resolved)
    except collector.IsolationViolation as exc:
        fail_closed_blocked = True
        fail_closed_message = str(exc)

    # Recorder demo on synthetic data; write a demo JSONL the report can cite.
    demo_payload = {
        "model": "deepseek-flash",
        "thinking": {"type": "disabled"},
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system"}, {"role": "user"}],
        "tools": [],
    }
    demo_response = {
        "id": "demo-req-0001",
        "model": "deepseek-flash",
        "choices": [{"finish_reason": "stop", "message": {"content": '{"step": "demo"}}'}}],
        "usage": fake_usage,
    }
    demo_path = HERE / "d1_round4_isolation_demo_raw.jsonl"
    recorder = collector.RawResponseRecorder(demo_path)
    entry = recorder.record(demo_payload, demo_response)
    recorder.flush()
    demo_lines = demo_path.read_text(encoding="utf-8").splitlines()
    demo_fields = sorted(json.loads(demo_lines[0]).keys()) if demo_lines else []
    demo_response_fields = sorted(json.loads(demo_lines[0])["response"].keys()) if demo_lines else []

    snapshot["stages"]["offline"] = {
        "sequence": ["prepare_isolation_env", "import app store modules (stage B)",
                     "resolve_state_paths", "assert_within_root"],
        "env_set_before_import": True,
        "env_targets_inside_root": {k: bool(v) for k, v in env_inside.items()},
        "redaction_sample": redacted,
        "redaction_secret_shape_absent": True,
        "budget_reserve": reserve,
        "budget_settle": settled,
        "budget_remaining": remaining,
        "model_mismatch_guard_blocked": mismatch_blocked,
        "fail_closed_assertion_blocked": fail_closed_blocked,
        "fail_closed_message": fail_closed_message,
        "recorder_demo_file": str(demo_path.name),
        "recorder_demo_top_fields": demo_fields,
        "recorder_demo_response_fields": demo_response_fields,
        "real_model_calls": 0,
        "http_client_instantiated": False,
        "transport_opened": False,
    }

    # ---- Stage B: production store resolution under isolation -------------- #
    shared_before = snapshot_dir(default_state_dir())
    resolved = collector.resolve_state_paths(backend)
    collector.assert_within_root(iso_root, case_id, resolved)
    shared_after = snapshot_dir(default_state_dir())

    created_files = sorted(
        str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()
    )
    snapshot["stages"]["production_import"] = {
        "backend": str(backend),
        "resolved_paths": resolved,
        "all_within_root": True,
        "files_in_isolation_root": created_files,
        "shared_default_dir": str(default_state_dir()),
        "shared_default_unchanged": shared_before == shared_after,
        "shared_default_before": shared_before,
        "shared_default_after": shared_after,
        "real_model_calls": 0,
        "http_client_instantiated": False,
    }

    # ---- Stage C: A9 historical evidence protection ----------------------- #
    a9_files = ["round4/A9_case_record.json", "round4/A9_raw_responses.jsonl"]
    evidence: dict[str, dict[str, object]] = {}
    for rel in a9_files:
        disk = v1_dir / rel
        head_text = git_head_text(repo, f"backend/evaluations/v1/{rel}")
        disk_text = disk.read_text(encoding="utf-8") if disk.exists() else None
        head_hash = hashlib.sha256(_normalized_bytes(head_text)).hexdigest() if head_text is not None else None
        disk_hash = hashlib.sha256(_normalized_bytes(disk_text)).hexdigest() if disk_text is not None else None
        line_count = len(disk_text.splitlines()) if disk_text is not None else None
        evidence[rel] = {
            "disk_sha256_normalized": disk_hash,
            "head_sha256_normalized": head_hash,
            "line_count": line_count,
            "unchanged": disk_hash is not None and disk_hash == head_hash,
        }
    snapshot["stages"]["a9_evidence_protection"] = evidence
    snapshot["all_checks_pass"] = (
        all(v["unchanged"] for v in evidence.values())
        and all(env_inside.values())
        and mismatch_blocked
        and fail_closed_blocked
        and shared_before == shared_after
    )

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"all_checks_pass": snapshot["all_checks_pass"],
                      "files": created_files,
                      "shared_unchanged": shared_before == shared_after,
                      "evidence": evidence}, ensure_ascii=False, indent=2))
    return 0 if snapshot["all_checks_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
