"""Build the 45-row root-cause matrix for GENERALIZATION-02 A01."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

SOURCE = Path(r"C:\Users\29924\Codes\xikao\cad_e2e_generalization_live_01")
OUTPUT = Path(r"C:\Users\29924\Codes\xikao\cad_core_generalization_02")

OVERRIDES = {
    ("M01", "clause:0:51"): "验收证据聚合错误",
    ("M02", "clause:0:0"): "需求绑定冲突：第一遍按矩形边界测量 L 形",
    ("M02", "clause:0:32"): "对象身份绑定失败：未识别同一轮廓的竖直臂",
    ("M02", "clause:0:60"): "对象身份绑定失败：孔集合未绑定到两个圆",
    ("M03", "clause:0:35"): "对象身份绑定失败：螺栓孔集合未按圆周关系绑定",
    ("M04", "clause:0:71"): "对象身份绑定失败：腔体与管口的空间关系未绑定",
    ("F03", "clause:0:54"): "真实几何错误：首尾 95.289 mm、折转 7.015°",
    ("T02", "clause:0:0"): "对象身份绑定失败：复合圆环被拆成 4 个图元",
    ("T02", "clause:0:54"): "真实几何错误：弧扫角 360°≠600°",
}

KEYWORDS = {
    "hole": ("孔", "管口", "螺栓"),
    "outline": ("轮廓", "外框", "支架", "法兰", "圆环", "十字", "水滴", "回字", "正弦", "中心线"),
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _objects_for(case_id: str, clause: str, variant: dict) -> list[dict]:
    objects = variant.get("logical_objects") or []
    if case_id == "M01" and "圆心分别" in clause:
        return objects
    if case_id == "M03" and ("螺栓" in clause or "孔" in clause):
        return [obj for obj in objects if "螺栓" in str(obj.get("label"))]
    if case_id == "M04" and "管口" in clause:
        return [obj for obj in objects if "管口" in str(obj.get("label"))]
    if case_id == "M02" and "安装孔" in clause:
        return [obj for obj in objects if "安装孔" in str(obj.get("label"))]
    if case_id == "T02":
        return objects
    for words in KEYWORDS.values():
        matched = [obj for obj in objects if any(word in str(obj.get("label")) for word in words)]
        if matched:
            return matched
    return objects


def _diagnose(reason: str, post_status: str) -> str:
    if "无法唯一绑定" in reason:
        return "对象身份绑定失败"
    if "测量器不支持" in reason:
        return "已有测量能力未接通"
    if "通用轮廓未声明" in reason:
        return "需求合同未解析"
    if "最终来源测量未覆盖" in reason:
        return "验收证据聚合错误"
    if "独立测量与来源要求冲突" in reason:
        return "需求绑定冲突"
    if "实际未闭合" in reason:
        return "真实几何错误"
    if "没有可用的独立验证能力" in reason:
        return "缺少通用几何谓词"
    return "其他/待确认"


def main() -> int:
    metrics = _load(SOURCE / "metrics.json")
    replay = _load(OUTPUT / "offline_replay.json")
    post = {
        item["case_id"]: {c["requirement_id"]: c for c in item["clauses"]}
        for item in replay["cases"]
    }
    rows = []
    for case in metrics["cases"]:
        case_id = case["case_id"]
        if not case.get("unverified_requirements"):
            continue
        variant = _load(
            SOURCE / "runs" / "GENERALIZATION-01" / case_id / "service-step-1.json"
        )["variants"][0]
        steps = (variant["construction_record"].get("plan") or {}).get("steps", [])
        for clause in case["unverified_requirements"]:
            rid = clause["requirement_id"]
            text = clause["requirement"]
            diagnosis = OVERRIDES.get(
                (case_id, rid),
                _diagnose(clause.get("reason", ""), clause.get("status", "")),
            )
            objects = _objects_for(case_id, text, variant)
            labels = [
                f"{obj.get('object_id')}（{obj.get('label')}）" for obj in objects
            ]
            geometry_ids = sorted({
                int(ref) for obj in objects for ref in (obj.get("geometry_refs") or [])
            })
            step_ids = [str(step.get("step_id")) for step in steps]
            post_clause = post.get(case_id, {}).get(rid, {})
            checks = (post_clause.get("binding") or {}).get("checks") or []
            evidence = [
                "{predicate}: expected={expected}, actual={actual}, "
                "status={status}".format(
                    predicate=item.get("predicate"),
                    expected=item.get("expected"),
                    actual=item.get("actual"),
                    status=item.get("status"),
                )
                for item in checks
            ]
            rows.append({
                "case_id": case_id,
                "source_span": f"clause:0:{rid.rsplit(':', 1)[-1]}",
                "requirement_id": rid,
                "clause": text,
                "prior_status": clause.get("status"),
                "prior_reason": clause.get("reason"),
                "diagnosis": diagnosis,
                "logical_objects": labels,
                "geometry_ids": geometry_ids,
                "step_ids": step_ids,
                "measurement_evidence": evidence,
                "post_status": post_clause.get("status") or "not_replayed",
                "post_reason": post_clause.get("reason"),
            })

    payload = {
        "schema": "cad.generalization-02.root-cause-matrix.v1",
        "reported_unverified_ratio": "42/47",
        "actual_rows": len(rows),
        "actual_non_verified_ratio": f"{len(rows)}/47",
        "count_anomaly": (
            "metrics 的 unverified_clauses 只统计 unverified/unbound，"
            "未计入 3 条 partial（M01、M02、F03 各 1 条），因此报 42；"
            "逐条列出为 45，真实未验证口径应为 45/47。"
        ),
        "rows": rows,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "root_cause_matrix.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    counts = Counter(row["diagnosis"] for row in rows)
    post_counts = Counter(row["post_status"] for row in rows)
    lines = [
        "# CAD-CORE-GENERALIZATION-02 A01 根因矩阵",
        "",
        "口径：报告 42/47 只统计 unverified/unbound，漏计 3 条 partial；"
        "逐条清单为 **45/47**。",
        "",
        "| 诊断类别 | 条款数 |",
        "| --- | ---: |",
    ]
    lines += [f"| {name} | {count} |" for name, count in counts.most_common()]
    lines += [
        "",
        f"重放后：verified {post_counts.get('verified', 0)}，"
        f"partial {post_counts.get('partial', 0)}，"
        f"unverified/unbound {len(rows) - post_counts.get('verified', 0) - post_counts.get('partial', 0)}。",
        "",
        "| 案例 | 原文位置 | 条款 ID | 原文 | 原子事实/对象 | 几何/步骤 | 诊断 | 测量证据 | 重放后 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['case_id']} | {row['source_span']} | {row['requirement_id']} | {row['clause']} | "
            f"{'、'.join(row['logical_objects'])} | {row['geometry_ids']} / {row['step_ids']} | "
            f"{row['diagnosis']} | {'；'.join(row['measurement_evidence']) or '重放无候选'} | "
            f"{row['post_status']} |"
        )
    (OUTPUT / "root_cause_matrix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(rows), "diagnosis": counts,
                      "post": post_counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
