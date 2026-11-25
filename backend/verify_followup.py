# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from app.incremental_cad import resolve_incremental_followup

prev = {"operation": "translate", "target_instance_id": 2, "parameters": {"dx_mm": 2000, "dy_mm": 0}}
r1 = resolve_incremental_followup("把刚才选中的图形向左移动1米", prev, [1, 2, 3])
r2 = resolve_incremental_followup("把之前选中的图形向上移动50厘米", prev, [1, 2, 3])
r3 = resolve_incremental_followup(
    "再把它向上移动50厘米",
    {"operation": "translate", "target_instance_id": 3, "parameters": {"dx_mm": 1000, "dy_mm": 0}},
    [1, 2, 3],
)
print("just_selected ->", repr(r1))
print("just_picked ->", repr(r2))
print("repeat_it ->", repr(r3))
