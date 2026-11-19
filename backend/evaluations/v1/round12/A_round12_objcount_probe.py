"""Zero-model probe for source-side object-count inventory (R-02-COUNT).

Runs explicit_composition against the approved must-generate / must-not-generate
fixtures and prints the contract inventory fields. No real model, no network.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.cad_structure_contract import explicit_composition, object_inventory_sidecar

GENERATE = [
    ("两个立方体并排，画等轴投影", "立方体", 2),
]

NONE_CASES = [
    "一个立方体有 12 条棱",
    "8 个齿的齿轮轮廓",
    "长度 20 mm",
    "角度 90 度",
    "3 条平行横线",
    "正五边形",
    "外径 2 米",
    "边长 50 毫米",
]

INCOMPLETE_CASES = [
    "画三个立方体和两个怪东西",
]

EXISTING_PRIMITIVE_CASES = [
    "生成两个相交圆组成的轮廓",
]


def summarize(text):
    legacy = explicit_composition(text)
    sidecar = object_inventory_sidecar(text)
    if legacy is None and sidecar is None:
        return {"contract": None, "state": "none", "entries": [], "count": None}
    contract = {**(legacy or {}), **(sidecar or {})}
    return {
        "kind": contract.get("kind"),
        "state": contract.get("object_requirements_state") or "none",
        "entries": contract.get("object_requirements") or [],
        "count": contract.get("logical_object_count"),
        "counts": contract.get("counts"),
        "names": contract.get("names"),
    }


def main():
    report = {"generate": [], "none": [], "incomplete": [], "existing_primitive": []}
    failures = []

    for text, noun, qty in GENERATE:
        result = summarize(text)
        ok = (result["state"] == "complete" and result["count"] == qty
              and len(result["entries"]) == 1
              and result["entries"][0]["object_noun"] == noun
              and result["entries"][0]["quantity"] == qty)
        report["generate"].append({"text": text, "result": result, "ok": ok})
        if not ok:
            failures.append(("generate", text, result))

    for text in NONE_CASES:
        result = summarize(text)
        ok = result["state"] == "none" and not result["entries"] and result["count"] is None
        report["none"].append({"text": text, "result": result, "ok": ok})
        if not ok:
            failures.append(("none", text, result))

    for text in INCOMPLETE_CASES:
        result = summarize(text)
        ok = result["state"] == "incomplete" and result["count"] is None
        report["incomplete"].append({"text": text, "result": result, "ok": ok})
        if not ok:
            failures.append(("incomplete", text, result))

    for text in EXISTING_PRIMITIVE_CASES:
        result = summarize(text)
        ok = result["state"] == "none" and result["counts"] == {"circle": 2}
        report["existing_primitive"].append({"text": text, "result": result, "ok": ok})
        if not ok:
            failures.append(("existing_primitive", text, result))

    report["failures"] = failures
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
