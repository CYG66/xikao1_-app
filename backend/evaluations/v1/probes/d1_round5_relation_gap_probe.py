"""Round-5 relation-label gap probe: B ``equivalent`` vs C ``identical`` vocabulary.

Zero model calls, no network. Reproduces the adapter contract gap observed
during the D integration run: C's M3 gate treats a determined-equivalent pair
only when the injected evaluator returns relation ``identical``; B's
``trajectory_equivalent`` returns relation ``equivalent``. A faithful,
untranslated adapter therefore releases the proven-stall positive case.

Writes a small JSON snapshot documenting both adapter modes and the verdict
each produces.

Usage:
    python d1_round5_relation_gap_probe.py --combo-backend <combo/backend> \
        --combo-probes <combo probes> --d-probes <D probes> --out <json>
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import pathlib
import sys
import tempfile
from types import SimpleNamespace

PI = math.pi


def _circle(r=1.5, n=120):
    return [(2 + r * math.cos(PI * 2 * k / n),
             3 + r * math.sin(PI * 2 * k / n)) for k in range(n + 1)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--combo-backend", required=True)
    ap.add_argument("--combo-probes", required=True)
    ap.add_argument("--d-probes", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    root = pathlib.Path(tempfile.mkdtemp(prefix="xline-d1-relation-"))
    sys.path.insert(0, str(pathlib.Path(args.d_probes)))
    from d1_round4_isolation_collector import prepare_isolation_env  # noqa: PLC0415
    prepare_isolation_env(root, "RELATION")
    sys.path.insert(0, str(pathlib.Path(args.combo_backend)))
    sys.path.insert(0, str(pathlib.Path(args.combo_probes)))

    from app import cad_generation_recovery as rec  # noqa: PLC0415
    import b_round5_geometry_contract as gc  # noqa: PLC0415

    geom = [{"id": "o", "type": "polyline", "closed": True, "points": _circle()}]

    def invalid():
        return {"construction_error": {"code": "structure_requirement_failed",
                "details": {"check": "o", "failed_features": ["cusp"],
                             "measured_features": {"cusp": False}}},
                "plan": {"steps": []}, "trial_result": {"geometries": geom}}

    def _points(spec):
        return [tuple(p) for g in (spec or {}).get("geometries", []) for p in g.get("points", [])]

    def faithful(a, b, tol):
        ra = gc.trajectory_equivalent(
            SimpleNamespace(points=_points(a), closed=True),
            SimpleNamespace(points=_points(b), closed=True), tol or 1e-6)
        return {"equivalent": ra.equivalent, "undetermined": ra.undetermined,
                "relation": ra.relation, "reversed": ra.reversed,
                "checks": ra.checks, "fail_reasons": ra.fail_reasons}

    def mapped(a, b, tol):
        v = faithful(a, b, tol)
        v["relation"] = "identical" if v["relation"] == "equivalent" else v["relation"]
        return v

    outcomes = {}
    for mode, adapter in (("faithful_no_translation", faithful),
                          ("mapped_equivalent_to_identical", mapped)):
        rec.set_geometry_evaluator(adapter)
        outcomes[mode] = rec.evaluate_repair_progress(invalid(), invalid())

    report = {
        "schema": "cad.d1.round5.relation-gap.v1",
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "gap": "B trajectory_equivalent relation='equivalent'; C gate checks relation=='identical' "
               "before accepting equivalent=True. Untranslated adapter releases the stall case.",
        "outcomes": {
            mode: {"decision": o["decision"], "progress": o["progress"],
                   "geometry": o["geometry"]}
            for mode, o in outcomes.items()
        },
        "required_fix": "Align vocabulary on one side: C accepts B's 'equivalent' label, "
                        "or the production adapter normalizes relation to 'identical' before wiring.",
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    print(json.dumps({k: v["decision"] for k, v in report["outcomes"].items()},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
