# -*- coding: utf-8 -*-
"""D1 P0 dispatch-layer executable replay (offline, zero model calls).

Calls ``verify_semantic_requirements`` on the pre-fix and post-fix acceptance
snapshots with one minimal closed heart-shaped polyline. A line trace records
which acceptance branches actually executed, so the replay can state whether
the capital-A geometry checker was reached instead of inferring it from code
reading.

Read-only against both backend trees. No network, no model request, no A9
re-run, no S1 start. Geometry supplied here is a synthetic replay fixture,
not a persisted run artifact.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import sys

CASES = {
    "A1": "生成一个闭合爱心轮廓，宽度4米，高度4米",
    "A9": "生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米",
    "C10": "生成一个爱心和一个五角星，爱心在左，五角星在右",
    "C26": "生成一个大写字母A的轮廓，高3米宽2米",
}

# Normalized heart outline (0..1): two upper lobes, central notch, lower tip.
# Scaled to 4000 mm so the heart feature gate can pass on the replay fixture.
HEART_NORM = [
    (0.20, 0.90),
    (0.50, 0.62),
    (0.80, 0.90),
    (0.95, 0.50),
    (0.75, 0.20),
    (0.50, 0.00),
    (0.25, 0.20),
    (0.05, 0.50),
]

# Anchor line numbers verified by direct Read of each snapshot file.
ANCHORS = {
    "pre_fix": {
        "heart_block_entry": 199,
        "heart_block_body": (201, 215),
        "dispatch_kind": 253,
        "house_branch": 254,
        "letter_else_entry": 275,
        "letter_triangle_check": 292,
    },
    "post_fix": {
        "heart_block_entry": 199,
        "heart_block_body": (201, 215),
        "non_target_early_return": 239,
        "house_branch": 262,
        "letter_elif_entry": 283,
        "letter_triangle_check": 300,
    },
}

LETTER_RANGES = {
    "pre_fix": (275, 319),
    "post_fix": (283, 324),
}


def heart_geometry():
    return [
        {
            "id": "replay-heart-1",
            "type": "polyline",
            "closed": True,
            "selected": True,
            "vertices": [
                {"x": round(x * 4000.0, 3), "y": round(y * 4000.0, 3)}
                for x, y in HEART_NORM
            ],
        }
    ]


def _in_range(line, rng):
    return rng[0] <= line <= rng[1]


def run_snapshot(root: pathlib.Path, label: str) -> dict:
    for mod in list(sys.modules):
        if mod.startswith("app"):
            del sys.modules[mod]
    sys.path.insert(0, str(root))
    from app.cad_semantic_acceptance import (  # noqa: WPS433
        semantic_requirements,
        verify_semantic_requirements,
    )

    mod = sys.modules["app.cad_semantic_acceptance"]
    mod_hash = hashlib.sha256(pathlib.Path(mod.__file__).read_bytes()).hexdigest()
    anchors = ANCHORS[label]
    letter_rng = LETTER_RANGES[label]
    out = {
        "snapshot": label,
        "module_file": "app/cad_semantic_acceptance.py",
        "module_sha256": mod_hash,
        "replay_fixture": "single closed heart-shaped polyline, 4000 mm box; synthetic, not persisted",
        "cases": {},
    }

    for cid, text in CASES.items():
        traced = set()

        def tracer(frame, event, _arg, traced=traced):
            if event == "line" and frame.f_code.co_filename == mod.__file__:
                traced.add(frame.f_lineno)
            return tracer

        err = None
        result = None
        sys.settrace(tracer)
        try:
            result = verify_semantic_requirements(text, heart_geometry())
        except Exception as exc:  # StructureContractError or any replay failure
            err = exc
        finally:
            sys.settrace(None)

        details = getattr(err, "details", None) or {}
        measurements = details.get("measurements") or {}
        heart_body = range(*anchors["heart_block_body"])
        out["cases"][cid] = {
            "input": text,
            "requirements_kinds": [r.get("kind") for r in semantic_requirements(text)],
            "heart_check_executed": anchors["heart_block_entry"] in traced,
            "heart_block_body_entered": any(l in traced for l in heart_body),
            "letter_checker_reached": any(_in_range(l, letter_rng) for l in traced),
            "letter_entry_line": (
                anchors.get("letter_else_entry")
                or anchors.get("letter_elif_entry")
            ),
            "anchors_hit": {k: (v in traced if isinstance(v, int) else any(l in traced for l in range(*v)))
                            for k, v in anchors.items()},
            "raised": type(err).__name__ if err else None,
            "error_message": str(err) if err else None,
            "raised_check": details.get("check"),
            "measurements": measurements,
            "signature_observed_triangular_regions_empty": (
                measurements.get("observed_triangular_regions") == []
            ),
            "returned_result": result,
            "traced_lines": sorted(traced),
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="D1 P0 dispatch-layer replay (offline)")
    parser.add_argument("--pre-fix-root", required=True)
    parser.add_argument("--post-fix-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    doc = {
        "schema": "d1.p0.dispatch-replay.v1",
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "zero_real_model_calls": True,
        "zero_network": True,
        "note": "Executable replay of verify_semantic_requirements only; not a real end-to-end run.",
        "snapshots": [
            run_snapshot(pathlib.Path(args.pre_fix_root), "pre_fix"),
            run_snapshot(pathlib.Path(args.post_fix_root), "post_fix"),
        ],
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"out": str(out), "cases": len(CASES)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
