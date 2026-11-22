# -*- coding: utf-8 -*-
"""D1 P0 forensic probe: A1/A9/C10/C26 semantic-contamination evidence freeze.

Read-only against the persisted 70-case run and the frozen round4 A9 record.
Makes NO real model call, NO network request, and does not modify frozen inputs.
Writes only D-tree evaluation artifacts under evaluations/v1/round7/.

Snapshot roots (passed in by constant, resolved locally):
  RUN   : persisted corpus run (cad-eval-20261117/run)
  BACKEND : backend that served that run (xikao/backend)
  D_TREE  : v1/d1-evaluation worktree (frozen round4 record lives here)
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import datetime

PROBE_DIR = pathlib.Path(__file__).resolve().parent
V1_DIR = PROBE_DIR.parent
OUT_DIR = V1_DIR / "round7"
ROUND4_RECORD = V1_DIR / "round4" / "A9_case_record.json"

# External persisted-artifact roots are supplied by CLI flags / environment
# variables so this probe never hardcodes local absolute paths in the repo.
RUN: pathlib.Path | None = None
BACKEND: pathlib.Path | None = None
CORPUS: pathlib.Path | None = None
BEFORE_FIX: pathlib.Path | None = None
A_TREE: pathlib.Path | None = None

CASES = ["A1", "A9", "C10", "C26"]

EXPECTED = {
    "A1": "heart_outline_features",
    "A9": "heart_outline_features",
    "C10": "heart_and_star_two_objects",
    "C26": "straight_capital_a",
}

RELEVANT_MODULES = [
    "agent_service.py",
    "cad_generation_recovery.py",
    "cad_semantic_acceptance.py",
    "cad_source_acceptance.py",
    "cad_creation_intent.py",
    "cad_construction_interpreter.py",
    "cad_structure_contract.py",
    "cad_requirement_contract.py",
]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_json(path: pathlib.Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def backend_digest(app_dir: pathlib.Path) -> tuple[str, int]:
    """Mirror run_user_cad_corpus.py:657-660 aggregate digest."""
    digest = hashlib.sha256()
    files = sorted(app_dir.rglob("*.py"))
    for f in files:
        digest.update(str(f.relative_to(app_dir.parent)).replace("\\", "/").encode())
        digest.update(f.read_bytes())
    return digest.hexdigest(), len(files)


def module_hashes(app_dir: pathlib.Path) -> dict:
    out = {}
    for rel in RELEVANT_MODULES:
        f = app_dir / "app" / rel
        if f.exists():
            out[rel] = {
                "size": f.stat().st_size,
                "sha256": sha256_bytes(f.read_bytes()),
                "mtime": datetime.datetime.fromtimestamp(f.stat().st_mtime)
                .isoformat(timespec="seconds"),
            }
        else:
            out[rel] = {"missing": True}
    return out


def _replay(root: pathlib.Path) -> dict:
    """Replay semantic_requirements on recorded source texts against one backend root.

    Local replay on persisted text, NOT a real run; it cannot prove the
    run-time snapshot behaved this way. Module cache is purged between roots.
    """
    for mod in list(sys.modules):
        if mod.startswith("app"):
            del sys.modules[mod]
    sys.path.insert(0, str(root))
    from app.cad_semantic_acceptance import semantic_requirements  # noqa: WPS433

    results = {}
    for case in CASES:
        rep = load_json(RUN / case / "corpus-report.json") or {}
        s3 = load_json(RUN / case / "step-3.json") or {}
        ledger = (s3.get("project") or {}).get("requirements", {}).get(
            "requirement_ledger", {}
        )
        sources = [s.get("text") for s in ledger.get("sources", []) if s.get("text")]
        joined = "\n".join(sources) if sources else rep.get("messages", [""])[0]
        try:
            reqs = semantic_requirements(joined)
            results[case] = {
                "input_text": joined,
                "output_kinds": [r.get("kind") for r in reqs],
                "replay": True,
                "note": "local replay on persisted text; run-time per-file snapshot unverified",
            }
        except Exception as exc:  # pragma: no cover - forensic record
            results[case] = {"input_text": joined, "error": repr(exc), "replay": True}
    return results


def case_evidence(case: str) -> dict:
    rep = load_json(RUN / case / "corpus-report.json") or {}
    s3 = load_json(RUN / case / "step-3.json") or {}
    s1 = load_json(RUN / case / "step-1.json") or {}
    requests = []
    for n in (1, 2, 3):
        rq = load_json(RUN / case / f"request-{n}.json")
        if rq is not None:
            requests.append(rq)
    usage_lines = []
    usage_path = RUN / case / "model-usage.jsonl"
    if usage_path.exists():
        for line in usage_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                usage_lines.append(json.loads(line))

    ledger = (s3.get("project") or {}).get("requirements", {}).get(
        "requirement_ledger", {}
    )
    facts = [
        {
            "fact_id": f.get("fact_id"),
            "subject": f.get("subject"),
            "field": f.get("field"),
            "value_mm": f.get("value_mm"),
            "status": f.get("status"),
        }
        for f in (ledger.get("requirement_contract", {}).get("facts") or [])
    ]
    sources = [s.get("text") for s in ledger.get("sources", []) if s.get("text")]
    route = (s3.get("agent_context") or {}).get("route") or {}
    rec = (s3.get("construction_interpretation") or {}).get("recovery") or {}
    if not rec.get("attempts"):
        # C26: recovery attempts are recorded in step-1 (step-3 is review-only)
        rec = (s1.get("construction_interpretation") or {}).get("recovery") or {}
    attempts_source_step = 3 if (
        s3.get("construction_interpretation") or {}
    ).get("recovery", {}).get("attempts") else 1
    attempts = []
    for a in rec.get("attempts") or []:
        err = a.get("error") or {}
        details = err.get("details") or {}
        attempts.append(
            {
                "attempt": a.get("attempt"),
                "status": a.get("status"),
                "category": a.get("category"),
                "error_code": err.get("code"),
                "check": details.get("check"),
                "message": err.get("message"),
                "measurements": details.get("measurements"),
                "plan_labels": [
                    st.get("semantic", {}).get("assembly_label")
                    for st in (a.get("plan") or {}).get("steps", [])
                ],
            }
        )

    # case-id leakage scan over every model-facing body field
    body_blob = json.dumps(
        {"requests": [{"message": r.get("message"), "history": r.get("history")}
                      for r in requests]},
        ensure_ascii=False,
    )
    body_tokens = sorted(set(re.findall(r"\b[A-D]\d{1,2}\b", body_blob)))
    conv_ids = sorted({r.get("conversation_id") for r in requests})

    pt = sum((u.get("usage") or {}).get("prompt_tokens", 0) for u in usage_lines)
    ct = sum((u.get("usage") or {}).get("completion_tokens", 0) for u in usage_lines)
    cached = sum(
        (u.get("usage") or {}).get("prompt_tokens_details", {}).get("cached_tokens", 0)
        for u in usage_lines
    )

    first = attempts[0] if attempts else None
    return {
        "case_id": case,
        "oracle_case": rep.get("oracle_case"),
        "input_verbatim": (rep.get("messages") or [""])[0],
        "recorded_sources": sources,
        "expected_semantic": EXPECTED[case],
        "recorded_requirements_shape": (
            s3.get("project") or {}
        ).get("requirements", {}).get("shape"),
        "route": {
            "name": route.get("name"),
            "operation": route.get("operation"),
            "mode": route.get("mode"),
            "confidence": route.get("confidence"),
            "decision_source": route.get("decision_source"),
        },
        "history_turns": [
            {"role": h.get("role"), "content": h.get("content")}
            for h in (rep.get("history") or [])
        ],
        "request_bodies": requests,
        "case_id_tokens_in_model_body": body_tokens,
        "conversation_ids": conv_ids,
        "requirement_contract_facts": facts,
        "feature_contract_binding": "not_persisted_in_evidence",
        "system_or_developer_prompt": "unverified: not persisted in model-responses.jsonl / agent-runs.json",
        "attempts_source_step": attempts_source_step,
        "attempts": attempts,
        "first_error_layer": (
            {
                "attempt": first.get("attempt"),
                "error_code": first.get("error_code"),
                "check": first.get("check"),
                "layer": "geometry/structural acceptance"
                if first and first.get("check")
                else "model plan / expression validation",
            }
            if first
            else "unverified"
        ),
        "usage": {
            "request_records": len(usage_lines),
            "structured_calls": (s3.get("structured_usage") or {}).get("calls"),
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "cached_tokens": cached,
            "model": next((u.get("model") for u in usage_lines), None),
        },
        "project_id": rep.get("project_id"),
        "passed": rep.get("passed"),
        "has_candidate": rep.get("has_candidate"),
        "app": rep.get("app"),
        "evidence_files": sorted(
            p.name for p in (RUN / case).iterdir() if p.is_file()
        ),
    }


def record_one() -> dict:
    r = load_json(ROUND4_RECORD) or {}
    rec = r.get("record", {})
    usage = rec.get("usage", {})
    return {
        "record_label": "记录① 第四轮独立真实评测 A9（冻结，未重跑）",
        "evidence_paths": [
            "round4/A9_case_record.json",
            "round4/A9_raw_responses.jsonl",
            "D1_round4_A9真实模型受控评测报告.md",
        ],
        "case_id": rec.get("case_id"),
        "input_text": rec.get("original_input"),
        "input_sha256": rec.get("input_sha256"),
        "model": rec.get("model"),
        "request_count": rec.get("request_count"),
        "usage": {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cost_usd": usage.get("cost_usd"),
            "missing_usage_calls": usage.get("missing_usage_calls"),
        },
        "state": rec.get("state"),
        "failure_message": rec.get("result_message"),
        "failure_check": "heart_bilateral_lobes_notch_and_lower_tip",
        "measured_features": {
            "center_notch": True,
            "left_upper_lobe": True,
            "right_upper_lobe": True,
            "lower_tip": False,
        },
        "project_id": (rec.get("project_readback") or {}).get("id"),
        "code_snapshot": {
            "baseline_combo_tree": "f89bf41facfb7032cbb9647250cff6bbdcc6bbb7",
            "d_worktree_head": "4ad73eb038bbdf5a8ded8be5bc3a2feb0a2dcd70",
            "per_file_sha256": "unverified: record does not persist per-file hash; backend/app zero-change vs baseline per round4 report",
        },
        "harness": "probes/d1_round4_a9_runner.py (isolated in-process runner, transport stubbed for forensic probe; real provider on approved run)",
        "runtime_env": "unverified: Python version not persisted in record; service_config deepseek / deepseek-flash",
        "rule_version": "unverified: no semantic-rule version constant recorded",
    }


def record_two(matrix: dict) -> dict:
    row = next(c for c in matrix if c["case_id"] == "A9")
    return {
        "record_label": "记录② 70 例语料中的 A9（本次复盘，未发起新请求）",
        "evidence_paths": ["run/A9/corpus-report.json", "run/A9/step-3.json",
                           "run/A9/request-1..3.json", "run/A9/model-usage.jsonl"],
        "case_id": "A9",
        "oracle_alias": row["oracle_case"],
        "input_text": row["input_verbatim"],
        "input_sha256": sha256_bytes(row["input_verbatim"].encode("utf-8")),
        "model": row["usage"]["model"],
        "request_records": row["usage"]["request_records"],
        "structured_calls": row["usage"]["structured_calls"],
        "usage_tokens": {
            "prompt_tokens": row["usage"]["prompt_tokens"],
            "completion_tokens": row["usage"]["completion_tokens"],
        },
        "state": "failed",
        "failure_checks": [a["check"] for a in row["attempts"]],
        "project_id": row["project_id"],
        "code_snapshot": {
            "manifest_backend_code_sha256": None,  # filled below
            "per_file_sha256": "unverified: manifest stores aggregate digest only; before-fixes preserves acceptance module",
        },
        "harness": "tests/manual/run_user_cad_corpus.py via cad-eval-20261117/launch.py",
        "runtime_env": "unverified: Python version not persisted; launch.py redirects USERPROFILE/HOME to worktree home; model deepseek-flash",
        "rule_version": "unverified: no semantic-rule version constant recorded",
    }


def main() -> None:
    global RUN, BACKEND, CORPUS, BEFORE_FIX, A_TREE
    parser = argparse.ArgumentParser(description="D1 P0 semantic-contamination forensic probe (read-only)")
    parser.add_argument("--run-root", default=os.environ.get("P0_RUN_ROOT"))
    parser.add_argument("--backend", default=os.environ.get("P0_BACKEND"))
    parser.add_argument("--corpus", default=os.environ.get("P0_CORPUS"))
    parser.add_argument("--before-fix", default=os.environ.get("P0_BEFORE_FIX"))
    parser.add_argument("--a-tree", default=os.environ.get("P0_A_TREE"),
                        help="read-only A-line pre-fix worktree root for two-snapshot replay")
    args = parser.parse_args()
    if not (args.run_root and args.backend and args.corpus):
        raise SystemExit("P0_RUN_ROOT / P0_BACKEND / P0_CORPUS (or -- flags) are required")
    RUN = pathlib.Path(args.run_root)
    BACKEND = pathlib.Path(args.backend)
    CORPUS = pathlib.Path(args.corpus)
    BEFORE_FIX = pathlib.Path(args.before_fix) if args.before_fix else None
    A_TREE = pathlib.Path(args.a_tree) if args.a_tree else None

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    corpus_bytes = CORPUS.read_bytes()
    manifest = load_json(RUN / "manifest.json") or {}
    current_digest, file_count = backend_digest(BACKEND)
    recorded_digest = manifest.get("backend_code_sha256")

    matrix = [case_evidence(c) for c in CASES]
    replay_post = _replay(BACKEND)
    replay_pre = _replay(A_TREE) if A_TREE else None
    for row in matrix:
        row["semantic_requirements"] = replay_post[row["case_id"]]
        row["cross_check"] = {
            "post_fix_replay": replay_post[row["case_id"]],
            "pre_fix_replay": replay_pre[row["case_id"]] if replay_pre else "unverified: A-line pre-fix worktree not supplied",
        }

    rec1 = record_one()
    rec2 = record_two(matrix)
    rec2["code_snapshot"]["manifest_backend_code_sha256"] = recorded_digest

    rec1["capital_a_misfire_evidence"] = (
        "无：记录①失败检查为爱心几何特征 heart_bilateral_lobes_notch_and_lower_tip，"
        "measured_features.lower_tip=false；无字母 A 验收报错记录。"
    )
    rec2["capital_a_misfire_evidence"] = (
        "有（落盘验收报错签名）：记录② step 记录命中 straight_capital_a 上部三角区检查，"
        "required_relation=triangle_tip_above_horizontal_base，observed_triangular_regions=[]；"
        "但运行时逐文件哈希 unverified，选类层来源归因 unverified。"
    )

    before_fix_hash = (
        sha256_bytes(BEFORE_FIX.read_bytes()) if BEFORE_FIX.exists() else None
    )

    snapshot = {
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "probe": "probes/d1_p0_semantic_forensic.py",
        "zero_real_model_calls": True,
        "zero_network": True,
        "new_requests": 0,
        "note": "Read-only replay/extraction from persisted artifacts. No A9 re-run, no S1 start.",
        "python": sys.version.split()[0],
        "corpus": {
            "path": "frozen 70-case corpus (supplied via --corpus; local absolute path intentionally not recorded)",
            "size": len(corpus_bytes),
            "sha256": sha256_bytes(corpus_bytes),
            "manifest_source_sha256": manifest.get("sha256"),
        },
        "backend": {
            "run_root": "external persisted backend snapshot (local-only root, intentionally not recorded)",
            "manifest_backend_code_sha256": recorded_digest,
            "recomputed_current_digest": current_digest,
            "aggregate_digest_match": recorded_digest == current_digest,
            "py_file_count": file_count,
            "git_commit": "unverified: xikao/backend has no git commits on its branch",
            "relevant_module_hashes_current": module_hashes(BACKEND),
            "before_fixes_acceptance_module": {
                "path": "before-fixes/cad_semantic_acceptance.py (preserved pre-fix copy)",
                "size": BEFORE_FIX.stat().st_size if BEFORE_FIX.exists() else None,
                "sha256": before_fix_hash,
                "note": "only preserved pre-fix module; other run-time per-file hashes unavailable",
            },
            "a_tree_pre_fix_replay": (
                {
                    "root": "A-line read-only worktree supplied via --a-tree",
                    "acceptance_module_sha256": sha256_bytes(
                        (A_TREE / "app" / "cad_semantic_acceptance.py").read_bytes()
                    ) if A_TREE else None,
                }
                if A_TREE else "unverified: A-line pre-fix worktree not supplied"
            ),
        },
        "environment": {
            "launch_env": {
                "USERPROFILE/HOME": "redirected to cad-eval-20261117/home",
                "P12_EVAL_MODE": "1",
                "P12_MAX_REQUESTS": "600",
                "P12_MAX_INPUT_TOKENS": "20000000",
                "P12_MAX_OUTPUT_TOKENS": "2000000",
                "P12_MAX_COST_USD": "5",
                "DEEPSEEK_MODEL/BASE/ADVANCED/CAD_PLANNING_MODEL": "deepseek-flash",
                "P12_EVAL_MOCK_PROVIDER": "popped",
            },
            "runtime_python_version": "unverified: not persisted in run artifacts",
            "model_configuration": manifest.get("model_configuration"),
        },
        "evidence_audit": load_json(RUN / "evidence-audit.json"),
        "two_a9_records": {"record_1": rec1, "record_2": rec2},
    }

    matrix_doc = {
        "schema": "d1.p0.semantic-matrix.v1",
        "generated_at": snapshot["generated_at"],
        "zero_real_model_calls": True,
        "columns": [
            "case_id", "input_verbatim", "expected_semantic", "recorded_requirements_shape",
            "first_error_layer", "rule_id_version", "case_id_leak", "context_contamination",
            "feature_contract_binding", "evidence_status",
        ],
        "rows": matrix,
        "two_a9_records": {"record_1": rec1, "record_2": rec2},
        "cross_case_contamination": snapshot["evidence_audit"],
    }

    (OUT_DIR / "d1_p0_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (OUT_DIR / "d1_p0_semantic_matrix.json").write_text(
        json.dumps(matrix_doc, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps({
        "matrix_rows": len(matrix),
        "digest_match": snapshot["backend"]["aggregate_digest_match"],
        "output": str(OUT_DIR),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
