# -*- coding: utf-8 -*-
"""第 1-7 项关键代码标记复核（修正断言定位版）：存在性 + 行为断言。"""
import io, json, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = r"D:\xikao\xikao1_-app\backend"
APP = r"D:\xikao\xikao1_-app\backend\app"
FLUT = r"D:\xikao\xikao1_-app\xikao1_-app\lib"

results = []

def check(item, label, ok, detail=""):
    results.append((item, label, bool(ok), detail))

def read(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read()

# ---------- 第1项 ----------
cm = read(rf"{APP}\conversation_memory.py")
check("1", "set_active_cad_target 存在", "set_active_cad_target" in cm)
check("1", "_learn_result 保留 active_target", "applied_cad_edit" in cm)
asv = read(rf"{APP}\agent_service.py")
check("1", "_remember_active_cad_target 存在", "_remember_active_cad_target" in asv)
check("1", "指代绑定读 active_target.scope==instance", 'active_target.get("scope")' in asv)

# ---------- 第2项 ----------
cec = read(rf"{APP}\cad_edit_contract.py")
fn_start = cec.index("def build_cad_edit_contract")
body = cec[fn_start:]
i_logical = body.index('scope="logical_object"')
i_instance = body.index('scope="instance"')
i_geometry = body.index('scope="geometry"')
check("2", "粒度判定顺序 logical_object→instance→geometry", i_logical < i_instance < i_geometry)
cep = read(rf"{APP}\cad_edit_plan.py")
check("2", "plan 含 target_level/target_ids", '"target_level"' in cep and '"target_ids"' in cep)
check("2", "_semantic_target_ids 存在", "_semantic_target_ids" in cep)

# ---------- 第3项 ----------
mp = read(rf"{FLUT}\pages\map_page.dart")
check("3", "候选 group 带 instance_id", "instance_id" in mp and "drawingSelectionCandidates" in mp)
check("3", "点空白取消高亮", "onDrawingSelectionChanged?.call(null)" in mp)
agp = read(rf"{FLUT}\pages\agent_page.dart")
check("3", "agentDrawingSelectionPayload 透传", "agentDrawingSelectionPayload" in agp)
check("3", "_bind_incremental_selection 优先 payload instance_id", 'selection.get("instance_id")' in asv)

# ---------- 第4项 ----------
check("4", "_prepare_drawing_modification 含 plan_summary", '"plan_summary"' in asv)
check("4", "前端 DrawingReviewSummary 修改计划区", "DrawingReviewSummary" in agp and "plan['object_label']" in agp and "label: '修改对象'" in agp)

# ---------- 第5项 ----------
check("5", "前端 _EditChainSteps 组件", "_EditChainSteps" in agp and "edit_chain" in agp)

# ---------- 第6项 ----------
gc = read(rf"{APP}\geometry_catalog.py")
check("6", "_region_label/_layer_names_from_source/_topology_summary", all(s in gc for s in ("_region_label", "_layer_names_from_source", "_topology_summary")))
check("6", "catalog 元素含 layer/region、顶层 topology", all(s in gc for s in ('"layer"', '"region"', '"topology"')))

# ---------- 第7项 ----------
ic = read(rf"{APP}\incremental_cad.py")
check("7", "parse position_ordinal 选择器", '"kind": "position_ordinal"' in ic)
check("7", "whole_group→instances=all", 'edit["instances"] = "all"' in ic)
check("7", "followup 刚才选中指代", '"刚才选中"' in ic)
check("7", "executor position_ordinal 委托", 'if selector.get("kind") == "position_ordinal":' in ic)
rt = read(rf"{APP}\cad_target_resolver.py")
check("7", "resolver instances==all", 'target_spec.get("instances") == "all"' in rt)
check("7", "resolver middle+count 实例层", '"middle_count"' in rt)
check("7", "resolver position_ordinal", '"position_ordinal"' in rt)
check("7", "count 从 logical_object_selector 读", "logical_object_selector" in rt)

corpus_path = rf"{ROOT}\evaluations\cad_edit_chinese_commands.json"
with io.open(corpus_path, "r", encoding="utf-8") as f:
    corpus = json.load(f)
cases = corpus["cases"]
ids = [c["id"] for c in cases]
check("7", "回归集 42 例", len(cases) == 42, f"actual={len(cases)}")
check("7", "case id 唯一", len(ids) == len(set(ids)))
fixtures = corpus["fixtures"]
missing_fx = [c.get("source_fixture") for c in cases if c.get("source_fixture") and c["source_fixture"] not in fixtures]
check("7", "fixture 引用全部有效", not missing_fx, f"missing={missing_fx}")

sys.path.insert(0, ROOT)
from app.incremental_cad import parse_incremental_edit
from app.cad_target_resolver import resolve_cad_target
four = fixtures["four_instances"]
r = resolve_cad_target(parse_incremental_edit("把右边第二个图形向右移动20厘米"), four)
check("7", "行为:右边第二个→[3]", sorted(r.get("instance_ids") or []) == [3], f"got={r.get('instance_ids')}")
r = resolve_cad_target(parse_incremental_edit("把中间两个图形向右移动20厘米"), four)
check("7", "行为:中间两个→[2,3]", sorted(r.get("instance_ids") or []) == [2, 3], f"got={r.get('instance_ids')}")
r = resolve_cad_target(parse_incremental_edit("把整个图形一起向右移动1米"), fixtures["three_instances"])
check("7", "行为:整个图形一起→全部", sorted(r.get("instance_ids") or []) == [1, 2, 3], f"got={r.get('instance_ids')}")

# ---------- 同步清单 ----------
lst = read(r"D:\xikao\xikao1_-app\xikao1_-app\后端最终同步清单.md")
check("清单", "第1-7项条目齐全", all(f"2026-10-03 第{i}项" in lst for i in range(1, 8)))

failed = [r for r in results if not r[2]]
for item, label, ok, detail in results:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] 第{item}项 {label}" + (f" ({detail})" if detail else ""))
print("\nTOTAL", len(results), "FAILED", len(failed))
if failed:
    sys.exit(1)
print("ALL_MARKS_OK")
