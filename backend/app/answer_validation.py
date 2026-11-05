from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any


DOMAIN_LABELS = {
    "runtime": "运行连接",
    "motion": "底盘运动",
    "localization": "定位",
    "energy": "能源",
    "printer": "喷码机",
    "obstacles": "障碍物",
    "mission": "任务",
}

DOMAIN_WORDS = {
    "runtime": ("小车", "后端", "ros", "连接", "在线", "离线"),
    "motion": ("速度", "轮速", "底盘", "运动"),
    "localization": ("定位", "位置", "坐标", "全站仪", "ln150"),
    "energy": ("电量", "电池", "电压", "电流", "温度", "能源"),
    "printer": ("喷墨", "喷码", "喷头", "墨量"),
    "obstacles": ("障碍", "避障", "距离传感器"),
    "mission": ("任务", "执行阶段", "进度", "划线"),
}

FACT_MARKERS = (
    "当前", "实时", "现在", "剩余", "为", "是", "正常", "异常", "有效",
    "无效", "在线", "离线", "已连接", "未连接", "正在", "%", " m/s", "℃",
)

UNCERTAINTY_MARKERS = (
    "无法确认", "不能确认", "未知", "缺失", "未收到", "已过期", "数据过期",
    "没有实时", "尚无", "不可作为当前事实", "是否",
)

COMPLETION_PATTERN = re.compile(
    r"(?<!未)(?:已完成|已经完成|执行成功|操作成功|已成功|已经打开|已经关闭|"
    r"已启动|已停止|已连接|已切换|已恢复)"
)

DEVELOPMENT_REPORT_PATTERN = re.compile(
    r"(?:专项测试|回归测试|单元测试|测试用例|测试套件|断言(?:失败|通过|问题)|"
    r"候选链(?:上下文|断言)|\d+\s*(?:passed|failed|subtests?)\b|"
    r"后续(?:还)?需要单独(?:修复|处理)|未将其归因于本次)",
    re.IGNORECASE,
)


def _hide_development_report_sentences(message: str) -> tuple[str, list[str]]:
    """Keep engineering verification notes out of the operator chat UI."""
    parts = re.split(r"(?<=[。！？；\n])", message)
    kept: list[str] = []
    removed: list[str] = []
    for part in parts:
        value = part.strip()
        if value and DEVELOPMENT_REPORT_PATTERN.search(value):
            removed.append(value)
            continue
        kept.append(part)
    return "".join(kept).strip(), removed


def format_agent_answer_for_display(message: str) -> tuple[str, bool]:
    """Remove model/debug formatting that should never reach an operator UI."""
    original = message
    blocks = re.split(r"\n\s*\n", message.replace("\r\n", "\n"))
    visible_blocks: list[str] = []
    for block in blocks:
        compact = block.strip()
        lowered = compact.lstrip("（(").strip()
        internal_correction = lowered.startswith((
            "先更正", "更正上一轮", "纠正上一轮", "内部说明", "来源说明",
        )) or (
            re.search(r"\bK\d+\b", compact) is not None
            and any(marker in compact for marker in ("实际是", "不能作为", "说成"))
        )
        if compact and not internal_correction:
            visible_blocks.append(compact)

    visible = "\n\n".join(visible_blocks)
    visible = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", visible)
    visible = re.sub(r"(?m)^\s*>\s?", "", visible)
    visible = re.sub(r"\*\*(.*?)\*\*", r"\1", visible, flags=re.DOTALL)
    visible = re.sub(r"__(.*?)__", r"\1", visible, flags=re.DOTALL)
    visible = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", visible)
    visible = re.sub(r"`([^`\n]+)`", r"\1", visible)
    visible = re.sub(r"\s*\[K\d+\]", "", visible)
    visible = re.sub(r"\s+(?:与|和)\s*([。；，])", r"\1", visible)
    visible = re.sub(
        r"(?i)\b(?:[a-z]:\\|/home/|/opt/|/var/)[^\s，。；、（）()]+",
        "项目文件",
        visible,
    )
    visible = re.sub(
        r"(?i)\b(?:xline_ws3|backend|test1)/[a-z0-9_./-]+",
        "项目资料",
        visible,
    )
    visible = re.sub(r"(?i)(?<![\w])/(?:api|ws)/[a-z0-9_./{}-]+", "对应功能接口", visible)
    visible = re.sub(r"[ \t]+\n", "\n", visible)
    visible = re.sub(r"\n{3,}", "\n\n", visible).strip()
    return visible, visible != original.strip()


def compact_agent_answer(message: str) -> tuple[str, bool]:
    """Remove conversational filler and exact repetition without dropping safety facts."""
    original = message.strip()
    compact = re.sub(
        r"^(?:(?:好的[，,。]?|当然(?:可以)?[，,。]?|没问题[，,。]?|"
        r"根据(?:你|您)(?:提供的)?(?:信息|描述)[，,]?|"
        r"我来为你(?:分析|说明)一下[：:]?)\s*)+",
        "",
        original,
    )
    compact = re.sub(
        r"(?:\n|\s)*(?:希望以上(?:内容|建议)对你有帮助|如有其他问题请随时告诉我)[。！!]?$",
        "",
        compact,
    )

    seen_blocks: set[str] = set()
    blocks: list[str] = []
    for block in re.split(r"\n\s*\n", compact):
        value = block.strip()
        key = re.sub(r"\s+", "", value)
        if not value or key in seen_blocks:
            continue
        seen_blocks.add(key)
        blocks.append(value)
    compact = "\n\n".join(blocks).strip()
    return compact, compact != original


def _issue(code: str, domain: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "domain": domain, "message": message, **details}


def _drop_blocked_claims(message: str, blocked: list[str]) -> tuple[str, list[str]]:
    parts = re.split(r"(?<=[。！？\n])", message)
    kept: list[str] = []
    removed: list[str] = []
    for part in parts:
        lowered = part.lower()
        related = any(
            any(word in lowered for word in DOMAIN_WORDS.get(domain, ()))
            for domain in blocked
        )
        is_claim = any(marker in lowered for marker in FACT_MARKERS) or bool(
            re.search(r"-?\d+(?:\.\d+)?\s*(?:v|a|m/s)\b", lowered)
        )
        is_cautious = any(marker in lowered for marker in UNCERTAINTY_MARKERS)
        if related and is_claim and not is_cautious:
            removed.append(part.strip())
        else:
            kept.append(part)
    return "".join(kept).strip(), removed


def _replace_number(
    message: str,
    pattern: str,
    actual: int | float | None,
    suffix: str,
    domain: str,
    issues: list[dict[str, Any]],
) -> str:
    if actual is None:
        return message

    def replacement(match: re.Match[str]) -> str:
        observed = float(match.group("value"))
        expected = float(actual)
        if abs(observed - expected) <= max(0.01, abs(expected) * 0.001):
            return match.group(0)
        issues.append(_issue(
            "numeric_fact_mismatch",
            domain,
            f"回答中的数值 {observed:g}{suffix} 与实时数据 {expected:g}{suffix} 不一致。",
            observed=observed,
            expected=expected,
            unit=suffix,
        ))
        prefix = match.groupdict().get("prefix") or ""
        formatted = f"{expected:g}"
        return f"{prefix}{formatted}{suffix}"

    return re.sub(pattern, replacement, message, flags=re.IGNORECASE)


def _correct_fresh_numeric_facts(
    message: str,
    requested: list[str],
    context: dict[str, Any],
    issues: list[dict[str, Any]],
) -> str:
    telemetry = context.get("telemetry")
    if not isinstance(telemetry, dict):
        return message
    corrected = message
    if "energy" in requested:
        energy = telemetry.get("energy") if isinstance(telemetry.get("energy"), dict) else {}
        corrected = _replace_number(
            corrected,
            r"(?P<prefix>(?:(?:当前|剩余)\s*)?(?:电量|电池电量)(?:为|是|[:：])?\s*)"
            r"(?P<value>\d+(?:\.\d+)?)\s*%",
            energy.get("battery_percent"),
            "%", "energy", issues,
        )
        corrected = _replace_number(
            corrected, r"(?P<prefix>电压(?:为|是|[:：])?\s*)(?P<value>-?\d+(?:\.\d+)?)\s*[vV]",
            energy.get("voltage"), "V", "energy", issues,
        )
        corrected = _replace_number(
            corrected, r"(?P<prefix>电流(?:为|是|[:：])?\s*)(?P<value>-?\d+(?:\.\d+)?)\s*[aA]",
            energy.get("current"), "A", "energy", issues,
        )
        corrected = _replace_number(
            corrected, r"(?P<prefix>温度(?:为|是|[:：])?\s*)(?P<value>-?\d+(?:\.\d+)?)\s*℃",
            energy.get("temperature"), "℃", "energy", issues,
        )
    if "motion" in requested:
        drive = telemetry.get("drive") if isinstance(telemetry.get("drive"), dict) else {}
        corrected = _replace_number(
            corrected,
            r"(?P<prefix>(?:线)?速度(?:为|是|[:：])?\s*)(?P<value>-?\d+(?:\.\d+)?)\s*m/s",
            drive.get("linear_velocity"), "m/s", "motion", issues,
        )
    return corrected


def _correct_boolean_facts(
    message: str,
    requested: list[str],
    context: dict[str, Any],
    issues: list[dict[str, Any]],
) -> str:
    corrected = message
    telemetry = context.get("telemetry") if isinstance(context.get("telemetry"), dict) else {}

    def replace_conflict(pattern: str, replacement: str, domain: str, expected: bool) -> None:
        nonlocal corrected
        updated, count = re.subn(pattern, replacement, corrected)
        if count:
            issues.append(_issue(
                "boolean_fact_mismatch",
                domain,
                f"回答中的{DOMAIN_LABELS[domain]}状态与实时数据不一致。",
                expected=expected,
            ))
            corrected = updated

    if "runtime" in requested:
        runtime = telemetry.get("runtime") if isinstance(telemetry.get("runtime"), dict) else {}
        online = runtime.get("online") is True
        if online:
            replace_conflict(r"(?:小车|后端)(?:当前)?离线", "小车在线", "runtime", True)
        else:
            replace_conflict(r"(?:小车|后端)(?:当前)?在线", "小车离线", "runtime", False)
    if "localization" in requested:
        localization = telemetry.get("localization") if isinstance(telemetry.get("localization"), dict) else {}
        valid = localization.get("valid") is True
        if valid:
            replace_conflict(r"定位(?:状态)?(?:为|是)?(?:无效|失效)", "定位有效", "localization", True)
        else:
            replace_conflict(r"定位(?:状态)?(?:为|是)?(?:有效|正常)", "定位无效", "localization", False)
    return corrected


def validate_agent_answer(
    message: str,
    route: dict[str, Any],
    context: dict[str, Any],
    tool_results: list[dict[str, Any]] | None = None,
    pending_action: dict[str, Any] | None = None,
    knowledge_source_ids: set[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Validate factual claims against the same snapshot used for the answer."""
    original = message
    corrected = message
    issues: list[dict[str, Any]] = []
    checks = {
        "freshness": "passed",
        "numeric_consistency": "passed",
        "tool_completion": "passed",
        "source_citations": "passed",
        "display_format": "passed",
        "conciseness": "passed",
    }

    corrected, hidden_development_notes = _hide_development_report_sentences(
        corrected
    )
    if hidden_development_notes:
        if not corrected:
            corrected = "相关功能已检查，请按当前页面提示继续操作。"
        checks["display_format"] = "corrected"
        issues.append(_issue(
            "development_report_hidden",
            "display",
            "已隐藏不适合向用户展示的内部测试与开发说明。",
        ))

    # Geometry inspection payloads are for machine verification and must not
    # become operator-facing chat content when a model echoes a tool response.
    internal_payload = bool(
        re.search(r"\{\s*[\"']ok[\"']\s*:", corrected)
        and any(key in corrected for key in (
            '"geometry_count"', '"preview_path_count"', '"printing_length_m"',
            '"topology"', '"open_chain_count"', '"closed_loop_count"',
        ))
    )
    if internal_payload:
        generated = next((
            item for item in (tool_results or [])
            if isinstance(item, dict)
            and item.get("name") == "persist_candidate_variant"
            and item.get("ok") is True
            and item.get("variant_id")
            and item.get("preview_paths")
        ), None)
        failed = next((
            item for item in (tool_results or [])
            if isinstance(item, dict)
            and item.get("ok") is False
            and item.get("message")
        ), None)
        if generated is not None:
            corrected = "候选方案已生成，右侧已更新图纸预览。请选择方案后继续路径规划。"
        elif failed is not None:
            corrected = "候选方案未生成：" + str(failed["message"])
        else:
            corrected = "候选方案尚未生成。本轮只完成了内部图纸检查，请重新确认生成候选方案。"
        checks["display_format"] = "corrected"
        issues.append(_issue(
            "internal_payload_hidden", "drawing", "已隐藏内部几何检查数据。"
        ))

    # The current product has no verified obstacle sensing. Even fresh virtual
    # telemetry must not be presented as a live clearance measurement.
    parts = re.split(r"([，,。；;\n])", corrected)
    kept: list[str] = []
    unsupported_claim = False
    for index in range(0, len(parts), 2):
        part = parts[index]
        separator = parts[index + 1] if index + 1 < len(parts) else ""
        if (
            any(word in part for word in ("障碍", "避障", "净空"))
            and not any(word in part for word in (
                "未接入", "不支持", "无法检测", "不能检测", "人工确认", "人工检查",
            ))
            and (re.search(r"\d+(?:\.\d+)?\s*(?:米|m)", part) or
                 any(word in part for word in ("最近", "检测到", "无障碍", "避障正常")))
        ):
            unsupported_claim = True
            continue
        kept.append(part + separator)
    if unsupported_claim:
        corrected = "".join(kept).strip(" ，,。；;\n")
        corrected = (corrected + "。" if corrected and not corrected.endswith("。") else corrected)
        corrected += "当前未接入周边障碍检测，运动前请人工确认作业区域。"
        issues.append(_issue(
            "unsupported_obstacle_claim", "obstacles", "已删除未经验证的周边障碍状态。"
        ))
        checks["numeric_consistency"] = "corrected"

    if pending_action is None and re.search(r"请回复[“\"']?确认执行|在下方确认执行", corrected):
        corrected = "尚未创建可确认的操作，请重新提供具体运动参数。"
        issues.append(_issue(
            "missing_pending_action", "motion", "没有待确认工具操作，不能提示用户确认执行。"
        ))
        checks["tool_completion"] = "corrected"

    quality = context.get("quality") if isinstance(context.get("quality"), dict) else {}
    blocked = [str(item) for item in quality.get("blocked_domains", [])]
    requested = [str(item) for item in quality.get("requested_domains", [])]
    if blocked:
        corrected, removed = _drop_blocked_claims(corrected, blocked)
        labels = "、".join(DOMAIN_LABELS.get(item, item) for item in blocked)
        warning = f"无法确认当前{labels}状态：对应实时数据缺失或已过期。"
        if warning not in corrected:
            corrected = f"{warning}\n{corrected}" if corrected else warning
        checks["freshness"] = "corrected" if removed else "blocked"
        issues.append(_issue(
            "stale_or_missing_live_data",
            ",".join(blocked),
            warning,
            removed_claims=removed,
        ))

    fresh_requested = [item for item in requested if item not in blocked]
    corrected = _correct_fresh_numeric_facts(
        corrected, fresh_requested, context, issues
    )
    corrected = _correct_boolean_facts(corrected, fresh_requested, context, issues)
    if any(item["code"] in {"numeric_fact_mismatch", "boolean_fact_mismatch"} for item in issues):
        checks["numeric_consistency"] = "corrected"

    results = tool_results if isinstance(tool_results, list) else []
    claims_generated_candidate = bool(re.search(
        r"候选方案(?:已经|已)?(?:成功)?生成|已生成(?:新的?)?候选方案",
        corrected,
    ))
    generated_candidate = any(
        isinstance(item, dict)
        and item.get("name") == "persist_candidate_variant"
        and item.get("ok") is True
        and bool(item.get("variant_id"))
        and bool(item.get("preview_paths"))
        for item in results
    )
    if (
        claims_generated_candidate
        and route.get("name") == "drawing_design"
        and route.get("operation") in {"create", "modify"}
        and not generated_candidate
    ):
        corrected = "候选方案尚未生成：本轮没有得到新候选和预览，请重新提交修改要求。"
        checks["tool_completion"] = "corrected"
        issues.append(_issue(
            "missing_design_variant_result",
            "drawing",
            "回答声称候选已生成，但没有成功的候选工具结果和预览。",
        ))
    non_success: list[dict[str, Any]] = []
    for item in results:
        verification = item.get("verification") if isinstance(item, dict) else None
        if isinstance(verification, dict) and verification.get("status") != "success":
            non_success.append(verification)
    if (pending_action or non_success) and COMPLETION_PATTERN.search(corrected):
        status = "pending" if pending_action else str(non_success[0].get("status") or "unverified")
        if status == "failed":
            corrected = "操作未完成：真实设备状态验证失败，请查看工具验证结果。"
        elif pending_action:
            corrected = "操作尚未完成：需要用户确认后才会提交执行。"
        elif status == "pending":
            corrected = "操作尚未得到真实设备状态验证，正在等待设备反馈。"
        else:
            corrected = "操作结果尚未得到真实设备状态验证，不能确认已经完成。"
        checks["tool_completion"] = "corrected"
        issues.append(_issue(
            "unverified_completion_claim", "tool", corrected, observed=status
        ))

    allowed_sources = knowledge_source_ids or set()
    cited_sources = set(re.findall(r"\[(K\d+)\]", corrected))
    invalid_sources = sorted(cited_sources - allowed_sources)
    if invalid_sources:
        corrected = re.sub(
            r"\[(?:" + "|".join(re.escape(item) for item in invalid_sources) + r")\]",
            "",
            corrected,
        )
        checks["source_citations"] = "corrected"
        issues.append(_issue(
            "unknown_source_citation",
            "knowledge",
            "回答引用了本轮检索结果中不存在的来源编号。",
            observed=invalid_sources,
            expected=sorted(allowed_sources),
        ))

    corrected, display_changed = format_agent_answer_for_display(corrected)
    if display_changed:
        checks["display_format"] = "normalized"
    corrected, compacted = compact_agent_answer(corrected)
    if compacted:
        checks["conciseness"] = "compacted"

    status = "passed" if not issues else "corrected"
    validation = {
        "schema_version": "1.0",
        "status": status,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "message_changed": corrected != original,
        "checks": checks,
        "issues": issues,
    }
    return corrected, validation
