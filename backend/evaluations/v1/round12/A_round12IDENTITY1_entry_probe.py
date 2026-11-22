"""Zero-model probe for R-IDENTITY-1 source-side entry identifiers.

Checks requirement_id, expected_category, clause index, evidence occurrences
and the source-slice provenance check. No real model, no network.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.cad_structure_contract import _object_requirement_inventory

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

REPEATED = "生成两个立方体和两个立方体"

INCOMPLETE = "画三个立方体和两个怪东西"

failures = []
report = {"generate": [], "none": [], "repeated": [], "incomplete": []}

for text, noun, qty in GENERATE:
    inv = _object_requirement_inventory(text)
    entries = inv["object_requirements"]
    ok = (
        inv["object_requirements_state"] == "complete"
        and inv["logical_object_count"] == qty
        and len(entries) == 1
        and entries[0]["object_noun"] == noun
        and entries[0]["quantity"] == qty
        and entries[0]["requirement_id"] == "request-0:object-1:object"
        and entries[0]["expected_category"] == "object"
        and entries[0]["source_clause_index"] is not None
        and text[entries[0]["evidence_span"][0]:entries[0]["evidence_span"][1]] == entries[0]["evidence"]
        and entries[0]["evidence_occurrences"] == [entries[0]["evidence_span"]]
    )
    report["generate"].append({"text": text, "result": inv, "ok": ok})
    if not ok:
        failures.append(("generate", text, inv))

for text in NONE_CASES:
    inv = _object_requirement_inventory(text)
    ok = (inv["object_requirements_state"] == "none"
          and not inv["object_requirements"] and inv["logical_object_count"] is None)
    report["none"].append({"text": text, "result": inv, "ok": ok})
    if not ok:
        failures.append(("none", text, inv))

inv = _object_requirement_inventory(REPEATED)
entries = inv["object_requirements"]
ids = [e["requirement_id"] for e in entries]
occurrences = [e["evidence_occurrences"] for e in entries]
spans = [e["evidence_span"] for e in entries]
full = [[2, 7], [8, 13]]
repeated_ok = (
    inv["object_requirements_state"] == "complete"
    and inv["logical_object_count"] == 4
    and len(entries) == 2
    and len(set(ids)) == 2
    and occurrences == [full, full]
    and spans == full
    and all(REPEATED[span[0]:span[1]] == e["evidence"] for e, span in zip(entries, spans))
)
report["repeated"] = {"text": REPEATED, "result": inv, "ok": repeated_ok}
if not repeated_ok:
    failures.append(("repeated", REPEATED, inv))

inv = _object_requirement_inventory(INCOMPLETE)
incomplete_ok = (inv["object_requirements_state"] == "incomplete"
                 and inv["logical_object_count"] is None)
report["incomplete"] = {"text": INCOMPLETE, "result": inv, "ok": incomplete_ok}
if not incomplete_ok:
    failures.append(("incomplete", INCOMPLETE, inv))

report["failures"] = failures
print(json.dumps(report, ensure_ascii=False, indent=2))
if failures:
    sys.exit(1)
