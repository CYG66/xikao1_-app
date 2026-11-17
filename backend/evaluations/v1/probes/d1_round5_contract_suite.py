"""Round-5 M3 / M2 / FEATURE-CONTRACT verification skeleton (zero-cost).

C's M2/M3 implementation, A's feature-contract proposal and B's criteria are
still landing in parallel. This module does NOT assume their final signatures:
it declares the scenarios, inputs, expected outcomes and field-level
assertions, plus an adapter hook that will bind to production once the
implementation arrives. Until then every case reports
``pending_adapter``; no PASS/FAIL is claimed.

M3 call-count discipline: under ``max_repairs=2`` the simulator records the
actual attempt index and how many follow-up requests were avoided by a real
block. Theoretical savings are never booked as benefit.

Usage:
    python d1_round5_contract_suite.py --v1-dir <evaluations/v1> \
        --out <round5/contract_suite_status.json>
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
from dataclasses import dataclass, field
from typing import Any, Callable

MAX_REPAIRS = 2


# --------------------------------------------------------------------------- #
# Declarative scenarios
# --------------------------------------------------------------------------- #

M3_CASES: list[dict[str, Any]] = [
    {
        "case_id": "M3-EQUIV-PARAM",
        "title": "参数域变化但几何等价 → 识别并阻止后续无效重试",
        "scenario": "后一轮仅改参数区间/采样，几何与上一轮等价；等价分类命中后，"
                    "不发起下一次无效模型请求。",
        "expected": "block_retry",
        "assertions": [
            "等价分类返回 equivalent",
            "后续重试请求被阻止",
            "记录被避免的是第几次请求（attempt 索引）",
        ],
        "adapter": "m3_equivalence_classifier",
    },
    {
        "case_id": "M3-REAL-IMPROVE",
        "title": "几何真正改善 → 不被阻止",
        "scenario": "后一轮控制点/表达式改变并改善失败特征；分类不得误判为等价。",
        "expected": "allow_retry",
        "assertions": ["改善几何不被等价分类拦截", "修复轮可继续"],
        "adapter": "m3_equivalence_classifier",
    },
    {
        "case_id": "M3-FIRST-REPAIR",
        "title": "首轮修复不被阻止",
        "scenario": "首轮失败后的第一次修复属于正常修复预算，不得被等价/去重逻辑拦截。",
        "expected": "allow_retry",
        "assertions": ["attempt 1 修复放行", "不消耗阻止计数"],
        "adapter": "m3_repair_budget",
    },
    {
        "case_id": "M3-UNDETERMINED",
        "title": "undetermined / 缺失几何快照 → 安全放行",
        "scenario": "分类结果为 undetermined 或缺上一轮几何快照时，fail-open 到正常链路，"
                    "不得误阻止；同时留痕待人工/后续判定。",
        "expected": "allow_retry_with_trace",
        "assertions": ["undetermined 不阻止", "缺失快照不阻止", "放行原因留痕"],
        "adapter": "m3_equivalence_classifier",
    },
]

M2_CASES: list[dict[str, Any]] = [
    {
        "case_id": "M2-STRUCTURE-FEEDBACK",
        "title": "结构重规划反馈含预期特征、实测特征、差异、结构标记",
        "scenario": "结构契约拒绝后，回传给规划侧的反馈必须结构化。",
        "expected": "feedback_fields_present",
        "assertions": [
            "expected_features 存在",
            "measured_features 存在",
            "feature_diff（缺失/不符项）存在",
            "structure_check 标记存在",
        ],
        "adapter": "m2_structure_feedback",
    },
    {
        "case_id": "M2-PARAM-REPAIR-NO-FALSE-POSITIVE",
        "title": "不误伤参数修复",
        "scenario": "参数/尺寸类修复不是结构重规划；结构反馈不得把它判为结构失败。",
        "expected": "no_misclassification",
        "assertions": ["参数修复不进入结构拒绝分支"],
        "adapter": "m2_structure_feedback",
    },
    {
        "case_id": "M2-JUNCTION-REPAIR-NO-FALSE-POSITIVE",
        "title": "不误伤连接修复",
        "scenario": "内部连接点/连续性修复不是结构重规划；结构反馈不得误伤。",
        "expected": "no_misclassification",
        "assertions": ["连接修复不进入结构拒绝分支"],
        "adapter": "m2_structure_feedback",
    },
]

CONTRACT_CASES: list[dict[str, Any]] = [
    {
        "case_id": "FC-EXPLICIT-DERIVED-DISTINCT",
        "title": "user_explicit 与 semantic_derived 可区分",
        "scenario": "显式用户要求与语义派生约束在约束来源标记上可区分、可统计。",
        "expected": "source_kind_distinguishable",
        "assertions": ["两类来源标记取值不同", "每条约束带 source_kind"],
        "adapter": "feature_contract_source",
    },
    {
        "case_id": "FC-REFS-TRACEABLE",
        "title": "source_requirement_refs 可追溯",
        "scenario": "计划约束可回溯到需求账本中的来源条目。",
        "expected": "refs_traceable",
        "assertions": ["refs 指向存在的来源 source_id", "无悬空引用"],
        "adapter": "feature_contract_refs",
    },
    {
        "case_id": "FC-ACCEPTANCE-BACKEND-GENERATED",
        "title": "验收条件由后端生成",
        "scenario": "验收条件以后端度量为准，模型不能自行声明通过。",
        "expected": "acceptance_backend_authority",
        "assertions": ["验收状态由后端检查产出", "模型自评不作为通过依据"],
        "adapter": "feature_contract_acceptance",
    },
    {
        "case_id": "FC-NO-CONSTRAINT-DELETION-FORGERY",
        "title": "模型不能删除/伪造/放宽来源约束",
        "scenario": "模型输出不得移除既有来源引用、不得伪造来源、不得放宽验收阈值。",
        "expected": "constraint_integrity_held",
        "assertions": ["既有 refs 不被删除", "伪造来源被拒", "阈值不被模型放宽"],
        "adapter": "feature_contract_integrity",
    },
]


@dataclass
class RepairBudgetSimulator:
    """Tracks repair attempts under max_repairs=2; counts avoided requests."""

    max_repairs: int = MAX_REPAIRS
    attempts: int = 0
    blocked_requests: list[int] = field(default_factory=list)

    def next_attempt_index(self) -> int:
        return self.attempts + 1

    def allow(self, reason: str) -> dict[str, Any]:
        self.attempts += 1
        return {"decision": "allow", "attempt": self.attempts, "reason": reason}

    def block(self, reason: str) -> dict[str, Any]:
        # A block avoids the request that would have run at this attempt index.
        self.blocked_requests.append(self.next_attempt_index())
        return {"decision": "block", "avoided_attempt": self.next_attempt_index(),
                "reason": reason}

    def summary(self) -> dict[str, Any]:
        return {
            "max_repairs": self.max_repairs,
            "attempts_allowed": self.attempts,
            "blocked_requests": self.blocked_requests,
            "avoided_request_count": len(self.blocked_requests),
        }


# Adapter registry: populated once production implementations arrive.
ADAPTERS: dict[str, Callable[..., dict[str, Any]]] = {}


def bind_adapter(name: str, fn: Callable[..., dict[str, Any]]) -> None:
    ADAPTERS[name] = fn


# --------------------------------------------------------------------------- #
# Offline stub decision demo (NOT production verification)
#
# The M3 production classifier has not landed. The stub below encodes only the
# decision matrix we intend to verify later, on self-constructed synthetic
# plans. Its results are bucketed separately as ``offline_stub`` and must not
# be counted as production PASS/FAIL.
# --------------------------------------------------------------------------- #


def _stub_classify(prev: dict[str, Any] | None, curr: dict[str, Any]) -> str:
    if prev is None:
        return "no_snapshot"
    if curr.get("classification") == "undetermined":
        return "undetermined"
    return "equivalent" if prev["geom_sig"] == curr["geom_sig"] else "different"


def _stub_decide(attempt: int, prev: dict[str, Any] | None,
                 curr: dict[str, Any]) -> dict[str, Any]:
    if attempt == 1:
        return {"decision": "allow", "reason": "first_repair_always_allowed"}
    kind = _stub_classify(prev, curr)
    if kind == "equivalent":
        return {"decision": "block", "reason": "equivalent_parametric_change",
                "classification": kind}
    if kind in {"undetermined", "no_snapshot"}:
        return {"decision": "allow", "reason": "safe_pass_through",
                "classification": kind}
    return {"decision": "allow", "reason": "real_improvement", "classification": kind}


def offline_stub_demo() -> dict[str, Any]:
    """Self-constructed positive/negative M3 cases through the stub policy."""
    g1 = "sig-heart-v1"
    g2 = "sig-heart-v2-tip"
    synthetic = [
        {"case_id": "STUB-EQUIV-BLOCK", "attempt": 2,
         "prev": {"geom_sig": g1}, "curr": {"geom_sig": g1, "classification": None},
         "expect": "block"},
        {"case_id": "STUB-IMPROVE-ALLOW", "attempt": 2,
         "prev": {"geom_sig": g1}, "curr": {"geom_sig": g2, "classification": None},
         "expect": "allow"},
        {"case_id": "STUB-FIRST-ALLOW", "attempt": 1,
         "prev": {"geom_sig": g1}, "curr": {"geom_sig": g2, "classification": None},
         "expect": "allow"},
        {"case_id": "STUB-UNDETERMINED-ALLOW", "attempt": 2,
         "prev": {"geom_sig": g1}, "curr": {"geom_sig": g1, "classification": "undetermined"},
         "expect": "allow"},
        {"case_id": "STUB-NO-SNAPSHOT-ALLOW", "attempt": 2,
         "prev": None, "curr": {"geom_sig": g1, "classification": None},
         "expect": "allow"},
    ]
    rows: list[dict[str, Any]] = []
    allowed = 0
    blocked = 0
    for case in synthetic:
        decision = _stub_decide(case["attempt"], case["prev"], case["curr"])
        ok = decision["decision"] == case["expect"]
        if decision["decision"] == "allow":
            allowed += 1
        else:
            blocked += 1
        rows.append({**case, "decision": decision, "matches_expectation": ok})
    return {
        "scope": "offline_stub_only",
        "note": "桩级决策演示，不代表生产 M3 实现已验证；生产适配器到位后须重跑。",
        "cases": rows,
        "call_counts": {
            "allowed_requests": allowed,
            "blocked_requests": blocked,
            "avoided_requests": blocked,
            "max_repairs": MAX_REPAIRS,
        },
        "all_match": all(r["matches_expectation"] for r in rows),
    }


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    adapter = ADAPTERS.get(case["adapter"])
    if adapter is None:
        return {
            **case,
            "status": "pending_adapter",
            "verdict": "not_claimed",
            "note": "生产实现/适配器未到位；本轮不下 PASS/FAIL 结论。",
        }
    result = adapter(case)
    return {**case, "status": "evaluated", "adapter_result": result}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v1-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    groups = {"M3": M3_CASES, "M2": M2_CASES, "FEATURE-CONTRACT": CONTRACT_CASES}
    cases: list[dict[str, Any]] = []
    for group, group_cases in groups.items():
        for case in group_cases:
            evaluated = evaluate_case(case)
            evaluated["group"] = group
            cases.append(evaluated)

    sim = RepairBudgetSimulator()
    payload = {
        "schema": "cad.d1.round5.contract-suite.v1",
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "adapters_wired": sorted(ADAPTERS.keys()),
        "repair_budget_simulator": sim.summary(),
        "offline_stub_demo": offline_stub_demo(),
        "cases": cases,
        "counts": {
            "total": len(cases),
            "pending_adapter": sum(c["status"] == "pending_adapter" for c in cases),
            "evaluated": sum(c["status"] == "evaluated" for c in cases),
        },
    }

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out), "counts": payload["counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
