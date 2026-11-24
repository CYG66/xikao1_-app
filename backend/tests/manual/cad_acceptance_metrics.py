"""Honest metrics from recorded runs; missing usage/cost stays unknown."""
import json
from pathlib import Path


def summarize(root, reports):
    durations = []
    tokens = []
    categories = {}
    first_success = []
    unassessable = []
    formal_pass = 0
    full_e2e_pass = 0
    evaluable = 0
    generation_ok = 0
    geometry_ok = 0
    legacy_pass = 0
    formal_failures = {}
    for report in reports:
        if report.get("formal_evaluable") is True:
            evaluable += 1
            if report.get("formal_delivery_ok") is True:
                formal_pass += 1
            else:
                for reason in report.get("formal_reason") or []:
                    formal_failures[reason] = formal_failures.get(reason, 0) + 1
        else:
            unassessable.append(report.get("case"))
        if report.get("generation_ok") is True:
            generation_ok += 1
        if report.get("geometry_ok") is True:
            geometry_ok += 1
        if report.get("legacy_passed", report.get("passed")) is True:
            legacy_pass += 1
        if report.get("passed") is True:
            full_e2e_pass += 1
        folder = Path(root) / report["case"]
        for path in sorted(folder.glob("timing-*.json")):
            durations.append(json.loads(path.read_text(encoding="utf-8"))["elapsed_seconds"])
        for path in sorted(folder.glob("step-*.json")):
            result = json.loads(path.read_text(encoding="utf-8"))
            usage = result.get("usage") or {}
            if usage.get("total_tokens", 0) > 0:
                tokens.append(usage["total_tokens"])
            recovery = (result.get("construction_commit") or result.get("construction_interpretation") or {}).get("recovery")
            if recovery:
                first_success.append(recovery["attempts"][0]["status"] == "ready")
                for attempt in recovery["attempts"]:
                    if attempt.get("category"):
                        categories[attempt["category"]] = categories.get(attempt["category"], 0) + 1
    count = len(reports)
    return {
        "schema": "cad.acceptance-metrics.v2",
        "case_count": count,
        "evaluable_count": evaluable,
        "unassessable_count": len(unassessable),
        "unassessable_cases": unassessable,
        "generation_ok_count": generation_ok,
        "geometry_ok_count": geometry_ok,
        "formal_delivery_pass_count": formal_pass,
        "formal_delivery_rate": formal_pass / evaluable if evaluable else None,
        "full_e2e_pass_count": full_e2e_pass,
        "full_e2e_pass_rate": full_e2e_pass / count if count else None,
        "end_to_end_pass_rate": formal_pass / evaluable if evaluable else None,
        "legacy_pass_count": legacy_pass,
        "legacy_pass_rate": legacy_pass / count if count else None,
        "first_plan_success_rate": sum(first_success) / len(first_success) if first_success else None,
        "measured_request_count": len(durations),
        "total_elapsed_seconds": sum(durations) if durations else None,
        "reported_total_tokens": sum(tokens) if tokens else None,
        "cost": None,
        "formal_failure_categories": formal_failures,
        "failure_categories": categories,
        "omission_rate": None,
        "false_acceptance_rate": None,
        "limitations": [
            "Formal delivery rate uses only evaluable reports; missing visibility/binding evidence is listed as unassessable, never as success.",
            "Full E2E pass additionally requires every recorded legacy/UI check; it uses all cases as denominator and is reported separately from formal delivery.",
            "Legacy pass count is retained for comparison and is not a formal delivery rate.",
            "No inferred zero cost or zero omissions. Labeled negative cases are required to estimate false acceptance.",
        ],
    }
