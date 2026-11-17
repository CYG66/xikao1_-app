"""D-owned B1.1 independent topology safety probe (read-only).

Scope (D-line, round D1-1, B1.1 independent re-check):
- Re-runs five scenario families against the B worktree backend:
  T1 narrow large-scale single-segment self-loop;
  T2 ``unresolved`` semantics (source fact + empirical gate behaviour);
  T3 near-touch negative control;
  T4 shared-endpoint adjacent segments (must not be flagged as contact);
  T5 different scale clear curves + one generic analytic tangent positive control.
- Compares the T1 loop against the D0 frozen baseline backend, which has no
  topology-safety module.

Hard guards:
- Forces provider local; strips model API keys; no live model call, no HTTP,
  no project persistence, no candidate write.
- Read-only against the target backend: only imports its modules; no file in
  the target tree is created or modified.
- Fixtures are generic line / Bezier geometry built at runtime; no case id,
  shape name or frozen control-point constant is borrowed from B shipped tests.

Usage (from any cwd):
    python evaluations/v1/probes/d1_b11_topology_probe.py \
        --backend "C:\\Users\\29924\\Codes\\worktrees\\B\\backend" \
        --d0-backend "C:\\Users\\29924\\Codes\\xikao1_-app\\backend" \
        --out evaluations/v1/probes/d1_b11_topology_results.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROBE_DIR = Path(__file__).resolve().parent
D_BACKEND = PROBE_DIR.parents[2]

sys.path.insert(0, str(PROBE_DIR))
import d1_baseline_runner as runner  # noqa: E402

STRIPPED_KEYS = ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ARK_API_KEY", "MODEL_API_KEY")


def _strip_model_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in STRIPPED_KEYS:
        env.pop(key, None)
    env["XLINE_AGENT_PROVIDER"] = "local"
    return env


def _git_head(backend: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(backend), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
            env=_strip_model_env(),
        )
        return out.stdout.strip()
    except Exception as exc:  # pragma: no cover - probe resilience
        return f"unavailable: {type(exc).__name__}"


def _load_backend(backend: Path) -> tuple[Any, Any | None]:
    """Import backend app modules with a clean module cache."""
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    sys.path.insert(0, str(backend))
    from app import cad_construction as cc  # type: ignore
    try:
        from app import cad_topology_safety as topo  # type: ignore
    except ImportError:
        topo = None
    return cc, topo


def _pt(x: float, y: float) -> dict[str, float]:
    return {"x": round(float(x), 9), "y": round(float(y), 9)}


def _line(x0: float, y0: float, x1: float, y1: float) -> dict[str, Any]:
    return {"kind": "line", "start": _pt(x0, y0), "end": _pt(x1, y1)}


def _bezier(points: list[tuple[float, float]]) -> dict[str, Any]:
    return {"kind": "bezier", "control_points": [_pt(x, y) for x, y in points]}


def _plan(step_id: str, segments: list[dict[str, Any]],
          allow_self: bool = False) -> dict[str, Any]:
    return {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [{
            "step_id": step_id,
            "op": "add_composite_path",
            "output_ref": f"{step_id}.path",
            "semantic": {"label": "D1.1 topology probe"},
            "segments": segments,
            "allow_self_intersection": allow_self,
        }],
    }


def _eval_bez(points: list[tuple[float, float]], t: float) -> tuple[float, float]:
    vals = list(points)
    while len(vals) > 1:
        vals = [
            (left[0] + (right[0] - left[0]) * t,
             left[1] + (right[1] - left[1]) * t)
            for left, right in zip(vals, vals[1:])
        ]
    return vals[0]


def _derivative(points: list[tuple[float, float]], t: float) -> tuple[float, float]:
    p0, p1, p2 = points[0], points[1], points[2]
    if len(points) == 3:
        return (
            2 * (1 - t) * (p1[0] - p0[0]) + 2 * t * (p2[0] - p1[0]),
            2 * (1 - t) * (p1[1] - p0[1]) + 2 * t * (p2[1] - p1[1]),
        )
    p3 = points[3]
    a = (3 * (p1[0] - p0[0]), 3 * (p1[1] - p0[1]))
    b = (3 * (p2[0] - p1[0]), 3 * (p2[1] - p1[1]))
    c = (3 * (p3[0] - p2[0]), 3 * (p3[1] - p2[1]))
    return (
        (1 - t) ** 2 * a[0] + 2 * (1 - t) * t * b[0] + t * t * c[0],
        (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * b[1] + t * t * c[1],
    )


def analyze(topo: Any, segments: list[dict[str, Any]], closed: bool = False) -> dict[str, Any]:
    if topo is None:
        return {"module_present": False}
    report = topo.analyze_composite_segments(segments, tolerance=1e-6, closed=closed)
    contacts = [item.as_dict() for item in report.contacts]
    distances = [item["distance"] for item in contacts]
    return {
        "module_present": True,
        "contact_count": len(contacts),
        "unresolved": bool(report.unresolved),
        "min_distance": min(distances) if distances else None,
        "kinds": sorted({item["kind"] for item in contacts}),
        "contacts": contacts,
    }


def gate_run(cc: Any, plan: dict[str, Any]) -> dict[str, Any]:
    step_id = plan["steps"][0]["step_id"]
    try:
        result = cc.execute_construction_plan(plan)
        quality = next(
            (q for q in result.get("curve_quality", []) if q.get("step_id") == step_id),
            None,
        )
        return {"outcome": "passed", "quality": quality}
    except cc.ConstructionPlanError as exc:
        return {"outcome": "rejected", "error_code": getattr(exc, "code", None),
                "details": exc.details or {}}
    except Exception as exc:  # pragma: no cover - record unexpected failure
        return {"outcome": "error", "error_type": type(exc).__name__,
                "message": str(exc)[:300]}


def source_facts(backend: Path) -> list[dict[str, str]]:
    """Read-only extraction of the gate rejection condition and field facts."""
    facts: list[dict[str, str]] = []
    source = backend / "app" / "cad_construction.py"
    text = source.read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(text, start=1):
        stripped = line.strip()
        if stripped.startswith("if ") and "allow_self_intersection" in stripped \
                and ("self_intersection_count" in stripped or "has_contact" in stripped):
            includes_unresolved = "unresolved" in stripped
            facts.append({
                "file": "backend/app/cad_construction.py",
                "line": str(idx),
                "statement": stripped,
                "fact": ("拒绝条件把 safety_report.unresolved 纳入阻断（unresolved 单独可拒绝）。"
                         if includes_unresolved else
                         "拒绝条件只含自交/接触计数，未把 unresolved 纳入拒绝条件。"),
            })
        if '"topology_unresolved": safety_report.unresolved' in stripped:
            facts.append({
                "file": "backend/app/cad_construction.py",
                "line": str(idx),
                "statement": stripped,
                "fact": "unresolved 作为质量回传字段 topology_unresolved 上报。",
            })
    return facts


def build_scenarios() -> list[dict[str, Any]]:
    loop_points = [(0.0, 0.0), (1000.0, 1000.0), (-500.0, 1000.0), (500.0, 0.0)]

    # T3 near-touch: connected 4-segment U chain; non-adjacent seg3/seg0 are
    # separated by 0.012 m (> 2*proximity=2e-6) but must not be flagged.
    near_segments = [
        _line(0.0, 0.0, 2.0, 0.0),
        _line(2.0, 0.0, 2.0, 0.5),
        _line(2.0, 0.5, 0.0, 0.5),
        _line(0.0, 0.5, 0.0, 0.012),
    ]

    # T4 shared-endpoint chain: adjacent pairs share endpoints by construction.
    endpoint_segments = [
        _line(0.0, 0.0, 1.0, 0.0),
        _line(1.0, 0.0, 1.0, 1.0),
        _line(1.0, 1.0, 0.0, 1.0),
    ]

    # T5c generic analytic tangent positive control (arch + tangent line + connector).
    arch = [(-0.8, 0.0), (-0.8, 0.7), (0.8, 0.7), (0.8, 0.0)]
    tau = 0.30
    point = _eval_bez(arch, tau)
    dv = _derivative(arch, tau)
    norm = math.hypot(*dv)
    ux, uy = dv[0] / norm, dv[1] / norm
    length = 1.5
    line_a = (point[0] - length * ux, point[1] - length * uy)
    line_b = (point[0] + length * ux, point[1] + length * uy)
    arch_rev = list(reversed(arch))
    tangent_segments = [
        _line(line_a[0], line_a[1], line_b[0], line_b[1]),
        _line(line_b[0], line_b[1], arch_rev[0][0], arch_rev[0][1]),
        _bezier(arch_rev),
    ]

    return [
        {
            "id": "T1-narrow-large-scale-loop",
            "name": "单段大尺度窄回环（自交 Bezier）",
            "segments": [_bezier(loop_points)],
            "expectation": "曲线级精化可能未收敛；记录 contacts / unresolved / 门控结果。",
        },
        {
            "id": "T3-near-touch-negative",
            "name": "近切触阴性对照（间隙 > 邻近容差）",
            "segments": near_segments,
            "expectation": "contacts=0, unresolved=False, 门控放行，不得误报。",
        },
        {
            "id": "T4-shared-endpoint-adjacent",
            "name": "相邻段共享端点（端点接触不得误报）",
            "segments": endpoint_segments,
            "expectation": "相邻对共享端点不计为接触；contacts=0, unresolved=False。",
        },
        {
            "id": "T5a-clear-small-scale-cubic",
            "name": "小尺度平滑三次 Bezier（clear）",
            "segments": [_bezier([(0.0, 0.0), (0.0, 0.4), (0.4, 0.4), (0.4, 0.0)])],
            "expectation": "contacts=0, unresolved=False。",
        },
        {
            "id": "T5b-clear-large-scale-cubic",
            "name": "大尺度平滑三次 Bezier（clear，10x 比例）",
            "segments": [_bezier([(0.0, 0.0), (0.0, 4.0), (4.0, 4.0), (4.0, 0.0)])],
            "expectation": "contacts=0, unresolved=False。",
        },
        {
            "id": "T5c-analytic-tangent-positive",
            "name": "通用解析切线接触阳性对照（小尺度）",
            "segments": tangent_segments,
            "expectation": "门控拒绝 self_intersecting_composite_path，受影响段含 {0,2}。",
        },
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="D1.1 B1 topology independent probe")
    parser.add_argument("--backend", required=True, type=Path)
    parser.add_argument("--d0-backend", type=Path, default=None)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--label", default="B1-b519740")
    parser.add_argument("--target-ref", default="b519740")
    parser.add_argument("--variant", default="unknown",
                        help="committed / working-tree / other, recorded verbatim")
    args = parser.parse_args()

    env = _strip_model_env()
    for key, value in env.items():
        os.environ[key] = value

    cc, topo = _load_backend(args.backend)
    scenarios = build_scenarios()
    results: list[dict[str, Any]] = []
    critical_evidence: list[str] = []

    for scenario in scenarios:
        segments = scenario["segments"]
        analysis = analyze(topo, segments)
        plan = _plan(scenario["id"], segments)
        gate = gate_run(cc, plan)
        results.append({
            "id": scenario["id"],
            "name": scenario["name"],
            "expectation": scenario["expectation"],
            "analyzer": analysis,
            "gate": gate,
        })

    # T2 unresolved semantics: combine source facts with the T1 empirical row.
    t1 = next(item for item in results if item["id"] == "T1-narrow-large-scale-loop")
    unresolved_empirical = None
    if t1["analyzer"].get("module_present"):
        unresolved_empirical = {
            "unresolved": t1["analyzer"]["unresolved"],
            "contact_count": t1["analyzer"]["contact_count"],
            "gate_outcome": t1["gate"]["outcome"],
            "gate_error_code": t1["gate"].get("error_code"),
        }
        if t1["analyzer"]["unresolved"] and t1["analyzer"]["contact_count"] == 0 \
                and t1["gate"]["outcome"] == "passed":
            critical_evidence.append(
                "T1 实测：unresolved=True、curve_contacts=0，门控在 allow_self_intersection=False "
                "下仍放行；unresolved 未单独阻断。")
        elif t1["analyzer"]["unresolved"]:
            critical_evidence.append(
                "T1 实测：unresolved=True；门控结果见 analyzer/gate 记录。")
        else:
            critical_evidence.append(
                "本轮 T1 未在曲线级触发 unresolved；未解析情形由后续窄回环/预算耗尽用例补充。")

    d0_comparator: dict[str, Any] = {"backend": None, "head_sha": None,
                                    "topology_module_present": None, "gate": None}
    if args.d0_backend and args.d0_backend.exists():
        d0_cc, d0_topo = _load_backend(args.d0_backend)
        d0_comparator["backend"] = str(args.d0_backend)
        d0_comparator["head_sha"] = _git_head(args.d0_backend)
        d0_comparator["topology_module_present"] = d0_topo is not None
        d0_plan = _plan("T1-narrow-large-scale-loop", scenarios[0]["segments"])
        d0_comparator["gate"] = gate_run(d0_cc, d0_plan)

    payload: dict[str, Any] = {
        "schema": "cad.d1.b11-topology.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": sys.executable,
            "provider": "local",
            "stripped_keys": list(STRIPPED_KEYS),
            "real_model_calls": 0,
            "project_persistence": False,
            "candidate_writes": 0,
        },
        "target": {
            "backend": str(args.backend),
            "head_sha": _git_head(args.backend),
            "label": args.label,
            "target_ref": args.target_ref,
            "variant": args.variant,
        },
        "d0_comparator": d0_comparator,
        "source_facts": source_facts(args.backend),
        "scenarios": results,
        "safety_judgement": {
            "unresolved_blocks_rejection_in_gate": any(
                "纳入阻断" in fact["fact"] for fact in source_facts(args.backend)
            ),
            "basis": "以 source_facts 中拒绝条件源码为准；unresolved 是否进入拒绝条件按源码判定。",
            "critical_evidence": critical_evidence,
        },
    }

    digest = runner.canonical_sha256(
        {k: v for k, v in payload.items() if k != "sha256"})
    payload["sha256"] = digest
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "out": str(args.out),
        "sha256": digest,
        "scenarios": len(results),
        "target_head": payload["target"]["head_sha"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
