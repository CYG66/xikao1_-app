"""Production interpreter for template, rule and structured-model construction.

Every strategy must produce and execute ``cad.construction-plan.v1``.
Evaluation can explicitly bypass deterministic strategies without affecting chat.
"""

from __future__ import annotations
from .cad_length_units import length_factors

from copy import deepcopy
import json
import math
import re


def _coerce_model_payload(value):
    """Accept provider JSON envelopes while keeping schema validation strict."""
    if isinstance(value, dict):
        plan = value.get('plan')
        if isinstance(plan, dict) and 'backend' in plan:
            backend = plan['backend']
            if backend in {'auto', 'builtin', 'solvespace', 'planegcs'}:
                if 'constraint_backend' in plan and plan['constraint_backend'] != backend:
                    raise ValueError('backend 与 constraint_backend 冲突')
                plan['constraint_backend'] = plan.pop('backend')
        return value
    if not isinstance(value, str):
        return value
    text=value.strip()
    if text.startswith('```'):
        text=re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.I|re.S).strip()
    try:
        return json.loads(text)
    except Exception:
        match=re.search(r'\{.*\}', text, flags=re.S)
        if match:
            try:return json.loads(match.group(0))
            except Exception:pass
    return value
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from .agent_skills import parameterize_design
from .cad_standard_templates import template_profile

from .cad_construction import (
    CadConstructionPlan,
    ConstructionPoint,
    ConstructionPlanError,
    construction_geometry_bounds,
    construction_geometry_area,
    construction_plan_json_schema,
    execute_construction_plan,
)
from .cad_sketch_graph import (
    SketchGraphCandidateSet,
    evaluate_sketch_graph_candidates,
)
from .cad_parametric import ParametricError, polar_requirements, verify_polar_requirements
from .cad_creation_intent import has_compound_primitives, local_creation_objects
from .cad_requirement_ledger import requirement_ledger, bind_geometry_acceptance
from .cad_source_acceptance import verify_scoped_primitives, extract_scoped_primitives
from .cad_structure_contract import (
    StructureContractError, reference_contract, explicit_dimensions, validate_structure,
    explicit_composition, validate_explicit_composition, validate_plan_structure,
)


ConstructionModelCallback = Callable[[str, dict[str, Any]], dict[str, Any]]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConstructionClarification(_StrictModel):
    question_key: Literal["shape", "size", "curve_constraints", "standard_spec"]
    question: str = Field(min_length=1, max_length=500)
    recognized_shape: str | None = Field(default=None, min_length=1, max_length=100)


def ground_size_clarification(question: str, source: str) -> tuple[str, list[str]]:
    """Do not turn a model-invented arrangement into a required user input."""
    if re.search(r"布局|排列|间距|间隔|相距|左右|上下|左侧|右侧|上方|下方|对称|居中|在左|在右|距离|连接|相切|包含|重叠", source):
        return question, []
    invented_layout = re.compile(
        r"(?:左右|上下|横向|纵向|左侧|右侧|上方|下方).{0,18}(?:排列|摆放|布置|间距|间隔)|"
        r"(?:两个|多个|各个)对象.{0,18}(?:间距|间隔|距离)"
    )
    parts = re.split(r"(?<=[？?。；;])", question)
    removed = [p for p in parts if invented_layout.search(p)]
    if not removed:
        return question, []
    kept = "".join(p for p in parts if p not in removed).strip()
    return kept or "请补充各对象的实际尺寸及单位。", removed


class StructuredConstructionInterpretation(_StrictModel):
    schema_version: Literal["cad.construction-interpretation.v1"]
    is_construction_request: bool
    plan: CadConstructionPlan | None = None
    evidence_text: list[str] = Field(default_factory=list, max_length=12)
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(ge=0.0, le=1.0)
    clarification: ConstructionClarification | None = None


class StructuredSketchGraphInterpretation(_StrictModel):
    schema_version: Literal["cad.sketchgraph-interpretation.v1"]
    is_construction_request: bool
    candidate_set: SketchGraphCandidateSet | None = None
    evidence_text: list[str] = Field(default_factory=list, max_length=12)
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(ge=0.0, le=1.0)


_NUMBER = r"[-+]?\d+(?:\.\d+)?"
_UNIT = r"(?:毫米|厘米|米|mm|cm|m)"
_POINT = rf"[（(]\s*({_NUMBER})\s*[,，]\s*({_NUMBER})\s*[）)]"
_CONSTRUCTION_MARKERS = ("画", "绘制", "创建", "生成", "添加", "构造")
_NORMALIZATION_MARKER = "\n\n[确定性需求规范化]\n"


def clarify_construction_request(source_text: str) -> dict[str, Any]:
    """Return one actionable CAD question for an incomplete create request.

    This is deliberately deterministic.  The model may later fill the plan,
    but it must not decide whether the user is missing the shape, a size, or a
    curve constraint.  Asking one highest-priority question also keeps a vague
    request from falling through to the generic agent router.
    """
    text = source_text.strip()
    lowered = text.lower()
    shape = next((name for name in (
        "爱心", "心形", "矩形", "长方形", "正方形", "椭圆", "圆弧", "圆",
        "圆弧", "弧线", "样条", "贝塞尔", "多边形", "轮廓", "曲线",
        "线段", "折线",
    ) if name in lowered), None)
    if shape is None:
        from .cad_creation_intent import local_creation_objects
        objects = local_creation_objects(text)
        if objects and re.search(rf"{_NUMBER}\s*{_UNIT}", text, re.I) and re.search(
            r"宽|高|长|半径|直径|角|连接|对称", text
        ):
            shape = "、".join(objects)
    has_size = bool(re.search(
        rf"(?:宽|高|长|外径|内径|直径|半径|边长|尺寸|大小|范围|不超过|最大|最小)"
        rf"[^，。；;]{{0,24}}{_NUMBER}\s*{_UNIT}", text,
        re.IGNORECASE,
    )) or bool(re.search(r"\d+(?:\.\d+)?\s*[x×*]\s*\d+", text)) or bool(
        _requested_area_square_metres(text)
    )
    curved_shape = shape in {"爱心", "心形", "圆弧", "弧线", "样条", "贝塞尔", "轮廓", "曲线"}
    from .cad_coordinate_requirements import coordinate_scale
    coordinates=coordinate_scale(text)
    explicit_point_extent = (
        len(re.findall(_POINT, text)) >= 2
        and bool(re.search(r"坐标单位(?:为|是)?\s*" + _UNIT, text, re.I))
    )
    has_size=has_size or coordinates['has_scale'] or explicit_point_extent
    has_curve_rule = any(token in lowered for token in (
        "对称", "圆弧", "弧线", "贝塞尔", "bezier", "样条", "控制点",
        "平滑", "曲率", "尖点", "闭合", "开口",
    ))
    from .cad_repetition_acceptance import tooth_boundary_requirements
    has_curve_rule = has_curve_rule or tooth_boundary_requirements(text) is not None
    # An explicitly constrained free curve can be planned without an
    # additional bounding-box size.  Endpoints/anchors, segment count and
    # continuity provide the geometric scope; do not reuse primitive-shape
    # width/height requirements for Bezier/spline paths.
    explicit_free_curve_scope = bool(
        curved_shape
        and len(re.findall(_POINT, text)) >= 2
        and any(token in lowered for token in ("贝塞尔", "bezier", "控制点", "连接点", "c1", "g1"))
        and bool(re.search(r"(?:开放式|开口|不闭合|段|连续|自交)", lowered))
    )
    if explicit_free_curve_scope:
        has_size = True

    from .cad_vertex_acceptance import open_straight_path_requirements
    path_source=open_straight_path_requirements(text)
    if path_source.get('coverage')=='complete':
        shape='折线';has_size=True;curved_shape=False
    if shape is None:
        key = "shape"
        question = "你要生成什么图形？请直接说明对象，例如“生成一个闭合爱心轮廓”。"
        example = "新建 CAD 图纸，生成一个闭合爱心轮廓，宽度不超过 5 米，高度不超过 5 米。"
    elif coordinates['defined'] and not coordinates['has_scale'] and not has_size:
        key='size'
        question='已收到控制点或顶点坐标，请说明坐标单位（米、厘米或毫米）；不需要重复提供外包宽高。'
        example='坐标单位为米，使用原文给出的控制点。'
    elif not has_size:
        key = "size"
        question = f"已识别为“{shape}”，还缺少尺寸。请提供最大宽度和高度，或说明直径/半径。"
        example = f"新建 CAD 图纸，生成一个{shape}闭合轮廓，最大宽 5 米、高 5 米。"
    elif curved_shape and not has_curve_rule:
        key = "curve_constraints"
        question = f"已识别为“{shape}”且已收到尺寸。请说明曲线要求：是否闭合、是否左右对称，以及使用圆弧还是 Bézier/样条。"
        example = f"新建 CAD 图纸，生成一个宽高不超过 5 米、左右对称、闭合、由两侧 Bézier 曲线和底部尖点组成的{shape}。"
    else:
        key = "construction_scope"
        question = "已收到图形和尺寸。请确认是否新建一张 CAD 图纸并生成候选方案？"
        example = "确认新建 CAD 图纸并生成候选方案。"

    return {
        "status": "clarification_required",
        "question_key": key,
        "question": question,
        "recognized_shape": shape,
        "recognized_size": has_size,
        "suggested_prompt": example,
        "prompt_template": "新建 CAD 图纸，生成一个【图形】，最大宽【数值+单位】、最大高【数值+单位】，并说明【闭合/对称/曲线类型】。",
    }


def construction_interpretation_json_schema() -> dict[str, Any]:
    """Return the strict wrapper schema expected from an LLM callback."""
    return StructuredConstructionInterpretation.model_json_schema()


def sketch_graph_interpretation_json_schema() -> dict[str, Any]:
    """Return the strict wrapper schema for 2-3 structural alternatives."""
    return StructuredSketchGraphInterpretation.model_json_schema()


def interpret_sketch_graph_candidates(
    source_text: str,
    model_callback: ConstructionModelCallback | None = None,
) -> dict[str, Any]:
    """Interpret one request as 2-3 isolated SketchGraph candidates.

    Unlike ``interpret_construction_request``, this path deliberately does not
    synthesize fake alternatives from one rule plan. A structured model must
    provide genuinely separate plans; deterministic execution then removes
    duplicates and ranks only candidates that pass the geometry gates.
    """
    text = source_text.strip()
    if not text:
        return _failure("empty_request", "请输入要生成的图形。", "sketch_graph")
    if model_callback is None:
        return _failure(
            "structured_model_required",
            "生成多个结构候选需要已配置的结构化模型。",
            "sketch_graph",
            clarification_required=True,
        )

    model_text, normalization_facts = normalize_construction_request(text)
    payload: dict[str, Any] = {}
    repairs: list[dict[str, Any]] = []
    try:
        payload = model_callback(
            model_text, sketch_graph_interpretation_json_schema(),
        )
        payload = deepcopy(payload)
        raw_set = payload.get("candidate_set")
        if isinstance(raw_set, dict):
            # The model sees the full persisted contract snapshot. The graph
            # set's human-readable requirement is the original source, which
            # is bounded by the schema; copying the whole snapshot here can
            # reject otherwise valid candidates before any trial execution.
            raw_set["requirement"] = text.split(
                "\n[CAD_REQUIREMENT_CONTRACT_SNAPSHOT.v1]", 1
            )[0][:4000]
            candidates = raw_set.get("candidates")
            if isinstance(candidates, list):
                for candidate in candidates:
                    if not isinstance(candidate, dict):
                        continue
                    repaired, candidate_repairs = repair_construction_references_once({
                        "plan": candidate.get("plan"),
                    })
                    repaired, area_repairs = normalize_explicit_area_once(
                        repaired, text,
                    )
                    if isinstance(repaired.get("plan"), dict):
                        candidate["plan"] = repaired["plan"]
                    for item in [*candidate_repairs, *area_repairs]:
                        repairs.append({
                            "candidate_id": candidate.get("candidate_id"),
                            **item,
                        })
        interpreted = StructuredSketchGraphInterpretation.model_validate(payload)
    except Exception as exc:
        return {
            **_failure("invalid_model_output", str(exc), "structured_model"),
            "deterministic_repairs": repairs,
            "model_output_diagnostic": {
                "payload_type": type(payload).__name__,
                "keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
                "schema_error": str(exc),
            },
        }

    if not interpreted.is_construction_request or interpreted.candidate_set is None:
        return {
            **_failure(
                "not_construction_request",
                "模型未将输入识别为可生成多个结构候选的 CAD 请求。",
                "structured_model",
                clarification_required=True,
            ),
            "normalization_facts": normalization_facts,
        }
    if not _evidence_is_grounded(text, interpreted.evidence_text):
        return _failure(
            "ungrounded_model_output",
            "模型证据无法回指用户原文，已拒绝候选执行。",
            "structured_model",
            clarification_required=True,
        )
    if interpreted.confidence < 0.75:
        return {
            **_failure(
                "low_confidence",
                "模型对构造要求的理解置信度不足，请补充尺寸或约束。",
                "structured_model",
                clarification_required=True,
            ),
            "normalization_facts": normalization_facts,
        }

    evaluation = evaluate_sketch_graph_candidates(interpreted.candidate_set)
    status = "ready" if evaluation["valid_candidate_count"] else "failed"
    return {
        "schema": "cad.sketchgraph-interpretation-result.v1",
        "status": status,
        "parser": "structured_model",
        "confidence": float(interpreted.confidence),
        "evidence_text": list(interpreted.evidence_text),
        "assumptions": list(interpreted.assumptions),
        "normalization_facts": normalization_facts,
        "deterministic_repairs": repairs,
        "candidate_set": interpreted.candidate_set.model_dump(mode="json"),
        "evaluation": evaluation,
        **(
            {}
            if status == "ready"
            else {"error": {
                "code": "all_candidates_invalid",
                "message": "所有结构候选均未通过确定性几何验证。",
            }}
        ),
    }


def interpret_construction_request(
    source_text: str,
    model_callback: ConstructionModelCallback | None = None,
    *,
    force_structured_model: bool = False,
    _semantic_verifier=None,
    _allow_measured_rotation: bool = True,
    _allow_radial_bounds_repair: bool = True,
    _allow_arc_direction_repair: bool = True,
) -> dict[str, Any]:
    """Interpret and trial-execute one construction request.

    No partial geometry is returned. A rule miss may use exactly one injected
    model call; transport retries belong to the provider adapter, not here.
    """
    text = source_text.strip()
    if not text:
        return _failure("empty_request", "请输入要生成的图形。", "rules")
    original_requirement = text.split("\n后端试算反馈：", 1)[0]
    # The production path always supplies the persisted contract snapshot.
    # Deterministic parsing still needs the user source inside that snapshot;
    # otherwise punctuation in the JSON wrapper (notably coordinate commas)
    # can make a complete command look unsupported.  Keep the full snapshot as
    # the model input, but use its immutable original_prompt for source rules.
    snapshot_marker = "[CAD_REQUIREMENT_CONTRACT_SNAPSHOT.v1]"
    if snapshot_marker in original_requirement:
        snapshot_tail = original_requirement.split(snapshot_marker, 1)[1].strip()
        json_start = snapshot_tail.find("{")
        try:
            snapshot, snapshot_end = json.JSONDecoder().raw_decode(snapshot_tail[json_start:]) if json_start >= 0 else (None, 0)
        except (TypeError, ValueError):
            snapshot = None
        if isinstance(snapshot, dict):
            original = str(snapshot.get("original_prompt") or "").strip()
            requirements = snapshot.get("requirements") if isinstance(snapshot.get("requirements"), dict) else snapshot
            followups = requirements.get("source_followups") if isinstance(requirements, dict) else None
            if original:
                sources = [original] + [str(item).strip() for item in (followups or []) if str(item).strip()]
                # Persisted confirmed dimensions may predate the follow-up
                # ledger.  Bind them only when there is one subject; a local
                # component size must never become a whole-drawing size.
                from .cad_requirement_contract import requirement_contract
                existing_contract = requirement_contract([
                    {'source_id':f'original-{i}', 'text':s} for i,s in enumerate(sources)])
                # A source side/radius is not a bounding width/height. Keep
                # the old missing-dimension fallback for legacy size answers,
                # but never upgrade inferred bounds over these explicit facts.
                nonbounding_size=any(f['field'] in {'side_length','radius','diameter','circumradius'}
                    for f in existing_contract['facts'])
                if nonbounding_size and isinstance(requirements,dict):
                    # The model must see the same authority boundary as the
                    # verifier, not stale inferred bounding fields in JSON.
                    clean_snapshot=deepcopy(snapshot)
                    clean_requirements=clean_snapshot.get('requirements',clean_snapshot)
                    clean_dimensions=clean_requirements.get('dimensions')
                    source_fields={f['field'] for f in existing_contract['facts']}
                    if isinstance(clean_dimensions,dict):
                        for field in ('width','height'):
                            if field not in source_fields:clean_dimensions.pop(field+'_m',None)
                        encoded=snapshot_tail[json_start:json_start+snapshot_end]
                        text=text.replace(encoded,json.dumps(clean_snapshot,ensure_ascii=False),1)
                if (len(local_creation_objects("\n".join(sources))) <= 1 and isinstance(requirements, dict)
                        and not nonbounding_size):
                    dimensions = requirements.get("dimensions")
                    if isinstance(dimensions, dict):
                        source_fields = {fact['field'] for fact in existing_contract['facts']}
                        labels = {"width_m": "宽度", "height_m": "高度", "radius_m": "半径", "diameter_m": "直径"}
                        confirmed = [f"{label}{dimensions[key]}米" for key, label in labels.items()
                                     if key.removesuffix('_m') not in source_fields
                                     and isinstance(dimensions.get(key), (int, float)) and dimensions[key] > 0]
                        if confirmed:
                            # A caption before ':' is parsed as an explicit
                            # component name. These committed global values
                            # belong to the sole original subject instead.
                            sources.append("，".join(confirmed))
                original_requirement = "\n".join(sources)
    from .cad_requirement_contract import requirement_contract
    from .cad_axis_requirements import ellipse_axes
    axis_requirements = ellipse_axes(original_requirement)
    if axis_requirements['status'] == 'conflict':
        return {**_failure('conflicting_axis_dimensions','长轴/短轴或全轴/半轴尺寸存在冲突，请确认。',
                          'source_requirements',clarification_required=True),
                'clarification':{'status':'clarification_required','question_key':'size',
                    'question':'请确认椭圆长轴、短轴的实际全长或半轴长度。'}}
    from .cad_source_acceptance import source_texts
    scalar_contract=requirement_contract([{'source_id':f'request-{i+1}','text':s}
        for i,s in enumerate(source_texts(original_requirement))])
    if not scalar_contract['consistent']:
        if scalar_contract['conflicts']:
            conflict=scalar_contract['conflicts'][0]
            label={'width':'宽度','height':'高度','radius':'半径','circumradius':'外接圆半径','diameter':'直径','side_length':'边长'}[conflict['field']]
            facts=[f for f in scalar_contract['facts'] if f['fact_id'] in conflict['fact_ids']]
            limits='、'.join({'eq':'等于','lte':'不超过','gte':'不小于'}[f['operator']]+f"{f['value_mm']/1000:g}米" for f in facts)
            question=f"{conflict['subject']}的{label}存在冲突：{limits}。请明确要保留或修改哪一条要求。"
        else:question='已给出的尺寸包含非正数或超出数值范围，请更正对应尺寸。'
        clarification={**clarify_construction_request(original_requirement),'question_key':'size','question':question,'suggested_prompt':question}
        return {**_failure('conflicting_user_dimensions',question,'requirement_contract',clarification_required=True),
            'clarification':clarification,'requirement_contract':scalar_contract,'provider_attempted':False}
    from .cad_coordinate_requirements import coordinate_scale
    coordinates=coordinate_scale(original_requirement)
    coordinate_clarification=clarify_construction_request(original_requirement)
    if coordinates['defined'] and not coordinates['has_scale'] and not coordinate_clarification['recognized_size']:
        return {**_failure('missing_coordinate_units',coordinate_clarification['question'],'rules',clarification_required=True),
                'clarification':coordinate_clarification}
    from .cad_semantic_acceptance import semantic_requirements
    user_text='\n'.join(source_texts(original_requirement))
    if ('圆柱体' in user_text and re.search(r'俯视|顶圆',user_text)
            and not re.search(r'正投影|多视图|透视|等轴|等距|俯视图.{0,8}侧视图|侧视图.{0,8}俯视图',user_text)):
        question='请明确圆柱体的投影方式：俯视圆与侧视轮廓两个独立视图，还是能看到顶面的三维效果投影？三维效果还需指定视角或投影约定。'
        return {**_failure('missing_projection_convention',question,'source_requirements',clarification_required=True),
                'clarification':{'status':'clarification_required','question_key':'curve_constraints','question':question,'suggested_prompt':question},
                'provider_attempted':False}
    semantics=semantic_requirements(original_requirement)
    if (semantics and not coordinate_scale(user_text)['has_scale']
            and not re.search(rf'{_NUMBER}\s*{_UNIT}',user_text,re.I)
            and _requested_area_square_metres(user_text) is None
            and not re.search(r'(?:尺寸|大小)(?:随意|由你决定)|自行决定尺寸',user_text)):
        names=local_creation_objects(user_text);name=names[0] if names else '该图形'
        question=f'已识别为{name}。请提供实际整体宽度和高度；模型不会自行编造实际尺寸。'
        return {**_failure('missing_dimensions',question,'source_requirements',clarification_required=True),
            'clarification':{'status':'clarification_required','question_key':'size','question':question,
                'recognized_shape':name,'recognized_size':False,'suggested_prompt':question},'provider_attempted':False}
    structure_contract = reference_contract(original_requirement)
    composition_contract = explicit_composition(original_requirement)
    width_m, height_m = explicit_dimensions(original_requirement)
    if composition_contract and composition_contract.get("kind") == "named_components":
        shared = composition_contract.get("dimensions") or {}
        scoped = composition_contract.get("component_dimensions") or {}
        size_keys = {"radius_m", "circumradius_m", "diameter_m", "side_length_m"}
        shared_sized = (
            all(shared.get(key) is not None for key in ("width_m", "height_m"))
            or any(shared.get(key) is not None for key in size_keys)
        )
        missing_names = []
        for name in composition_contract.get("names") or []:
            local = scoped.get(name) if isinstance(scoped.get(name), dict) else {}
            locally_sized = (
                all(local.get(key) is not None for key in ("width_m", "height_m"))
                or any(local.get(key) is not None for key in size_keys)
            )
            # Accept explicit source-scoped dimensions even when the object
            # inventory uses a harmless noun variant such as 圆形 while the
            # later dimension clause says 圆半径.  This only proves that a
            # size was supplied; measured acceptance still checks the value.
            aliases = {str(name)}
            if str(name) == "圆形":
                aliases.add("圆")
            alias_pattern = "(?:" + "|".join(re.escape(value) for value in aliases) + ")"
            source_sized = bool(
                re.fullmatch(
                    rf"(?:半径|直径|边长)\s*{_NUMBER}\s*{_UNIT}(?:的)?[^\d，。；;]+",
                    str(name), re.I,
                )
                or
                re.search(
                    alias_pattern + rf"[^；;。\n]{{0,24}}(?:半径|直径|边长)\s*{_NUMBER}\s*{_UNIT}",
                    original_requirement,
                )
                or re.search(
                    alias_pattern + rf"[^；;。\n]{{0,36}}宽\s*{_NUMBER}\s*{_UNIT}[^；;。\n]{{0,24}}高\s*{_NUMBER}\s*{_UNIT}",
                    original_requirement,
                )
            )
            locally_sized = locally_sized or source_sized
            if not shared_sized and not locally_sized:
                missing_names.append(str(name))
        user_allows_free_size = bool(re.search(
            r"(?:尺寸|大小)(?:随意|任选|由你决定)|自行决定尺寸|不限定尺寸",
            original_requirement,
        ))
        if missing_names and not user_allows_free_size:
            names = "、".join(missing_names)
            question = f"已识别组成：{names}。请补充这些对象各自的实际尺寸及单位；模型不会自行假设尺寸。"
            return {
                **_failure("missing_component_dimensions", question, "composition_requirements", clarification_required=True),
                "composition_contract": composition_contract,
                "clarification": {
                    "status": "clarification_required",
                    "question_key": "size",
                    "question": question,
                    "recognized_shape": names,
                    "recognized_size": False,
                    "suggested_prompt": question,
                },
                "provider_attempted": False,
            }
    if structure_contract and (width_m is None or height_m is None):
        name = structure_contract["matched_object"]
        question = f"已识别为{name}，将按已核验的制图依据保留全部组成和布局。请提供实际宽度和高度；标准比例不是唯一的实际尺寸。"
        return {**_failure("missing_dimensions", question, "reference_requirements", clarification_required=True),
                "structure_contract": structure_contract,
                "clarification": {"status":"clarification_required", "question_key":"size",
                                  "question":question, "recognized_shape":name, "recognized_size":False,
                                  "suggested_prompt":"实际宽度3米、高度2米。"}}
    compound_model_request = bool(model_callback is not None and has_compound_primitives(text))
    if outline_requirements(text) and not compound_model_request and not re.search(
        rf"{_NUMBER}\s*{_UNIT}", original_requirement, re.I
    ) and _requested_area_square_metres(original_requirement) is None:
        return _failure(
            "missing_outline_dimensions", "已识别轮廓结构，请补充实际尺寸后再生成。",
            "deterministic_rules", clarification_required=True,
        )

    # Path-3 evaluation can deliberately bypass deterministic rules to
    # measure the structured model itself. Production keeps rule-first mode.
    from .cad_template_plan import template_plan_from_text
    from .agent_skills import recognize_drawing_template, recognize_drawing_template_set
    try:
        template_plan = None if force_structured_model or structure_contract or composition_contract else template_plan_from_text(original_requirement)
    except ValueError as exc:
        return _failure("invalid_template_parameters", str(exc), "parameterized_template")
    # A partially covered template request must never fall back to a primitive
    # parser that would silently construct just the remaining circle/rectangle.
    partial_template = template_plan is None and bool(recognize_drawing_template(original_requirement) or recognize_drawing_template_set(original_requirement))
    plan = template_plan or (None if force_structured_model or partial_template or structure_contract or composition_contract or compound_model_request else parse_rule_construction_plan(original_requirement))
    parser = "parameterized_template" if template_plan else "deterministic_rules"
    junction_source_failure = None
    evidence: list[str] = []
    confidence = 1.0
    assumptions: list[str] = []
    deterministic_repairs: list[dict[str, Any]] = []
    normalization_facts: list[str] = []

    if plan is None:
        if model_callback is None:
            return {**_failure(
                "unsupported_or_incomplete_request",
                "当前规则无法完整解析该构造要求，需要补充明确坐标和尺寸，或交给结构化模型解释。",
                parser,
                clarification_required=True,
            ), 'model_required': True}
        parser = "structured_model"
        payload: dict[str, Any] = {}
        model_text, normalization_facts = normalize_construction_request(text)
        from .cad_length_units import planning_unit_contract
        unit_contract=planning_unit_contract(original_requirement)
        model_text+='\n[统一来源单位契约：plan_values按plan.units直接使用一次，不再按原文单位二次换算；仅为原文参数，不是生成坐标。缺失坐标单位不可猜测，其他来源与模型假设不能覆盖此表]\n'+json.dumps(unit_contract,ensure_ascii=False)
        from .cad_primitive_layout_acceptance import cylinder_view_requirements
        cylinder_views=cylinder_view_requirements(original_requirement)
        if cylinder_views:
            model_text+='\n[原文两个独立正投影视图的角色与尺寸关系；不提供生成坐标]\n'+json.dumps(cylinder_views,ensure_ascii=False)
        from .cad_projection_acceptance import projection_requirements
        projection=projection_requirements(original_requirement)
        if projection:
            model_text+='\n[原文投影棱线约束，与独立测量使用同一来源；不提供生成坐标]\n'+json.dumps(projection,ensure_ascii=False)
        from .cad_path_relation_acceptance import perpendicular_arm_requirements
        arm_relations=perpendicular_arm_requirements(original_requirement)
        if arm_relations:
            model_text+='\n[用户尺寸作用域和直角连接关系，非候选坐标或模板]\n'+json.dumps(arm_relations,ensure_ascii=False)
        from .cad_semantic_source_coverage import source_dimension_relation_guidance
        dimension_relations=source_dimension_relation_guidance(original_requirement)
        if dimension_relations:
            model_text+='\n[由现有来源契约确定性求得的尺寸关系；单位mm，非生成器或候选计划；输出须按plan.units转换，后端仍独立实测]\n'+json.dumps(dimension_relations,ensure_ascii=False)
        from .cad_repetition_acceptance import tiling_structure_requirements
        tiling=tiling_structure_requirements(original_requirement)
        if tiling:
            model_text+='\n[原文重复数量、局部尺寸与共边约束；不提供生成坐标]\n'+json.dumps(tiling,ensure_ascii=False)
        from .cad_repetition_acceptance import parallel_strip_requirements
        strips=parallel_strip_requirements(original_requirement)
        if strips:
            model_text+='\n[原文逐条尺寸、数量和间距作用域]\n'+json.dumps(strips,ensure_ascii=False)
        from .cad_repetition_acceptance import tooth_boundary_requirements
        teeth=tooth_boundary_requirements(original_requirement)
        if teeth:
            model_teeth={key[:-3] if key.endswith('_mm') else key:
                value/1000 if key.endswith('_mm') and value is not None else value
                for key,value in teeth.items()}
            model_teeth['units']='m'
            model_text+='\n[原文齿数和径向尺寸，以下长度已统一为米；plan.units=m时直接使用，选择mm时才乘1000。非生成坐标]\n'+json.dumps(model_teeth,ensure_ascii=False)
        from .cad_path_relation_acceptance import path_relation_requirements
        if path_relation_requirements(original_requirement):
            model_text+='\n[用户开放分割路径的连接关系，非候选坐标]\n'+json.dumps({
                'closed':False,'continuous':True,'branch_count':0,
                'curvature_direction_reversals':1,
                'instruction':'先确定整条开放分割线的两个外端点和内部连接点，再规划各曲线段。每个前段终点必须等于下一段起点；圆弧端点按center+radius*(cos(angle),sin(angle))计算，angle字段使用度。分割线不是另一个封闭区域，不能重复描绘外边界。每个步骤object_id独立；同一整体共享assembly_id。两个独立小圆不能用分割线的弧段或其整圆替代。'},ensure_ascii=False)
        if semantics:
            model_text+='\n[原文图形的基本结构关系；不指定字体或建筑细节]\n'+json.dumps(semantics,ensure_ascii=False)
        from .cad_stroke_acceptance import stroke_requirements
        strokes=stroke_requirements(original_requirement)
        if strokes:
            model_text+='\n[原文已明确的笔画端点与连接位置，优先于自行选择字体描边；毫米仅用于验收，输出仍遵守plan.units]\n'+json.dumps(strokes,ensure_ascii=False)
        scoped_requirements=extract_scoped_primitives(original_requirement)
        if scoped_requirements:
            model_text += "\n[后端从用户原文提取的部件约束，尺寸已换算为毫米；输出计划仍遵守plan.units，不能再次把毫米当米]\n"+json.dumps(scoped_requirements,ensure_ascii=False)
            model_text += "\n每个指定部件都必须生成；semantic.label使用部件原名称，所有部件必须明确所属整体assembly_id和assembly_label。"
            from .cad_relation_acceptance import extract_named_relations
            relations=extract_named_relations(original_requirement,[s['subject'] for s in scoped_requirements])
            if relations:
                model_text+='\n[用户明确的部件关系；由后端独立验收，不能只写断言代替实际几何]\n'+json.dumps(relations,ensure_ascii=False)
        if structure_contract:
            model_text += "\n[独立结构契约：来自已核验来源，不得删减组成或改写规则]\n" + json.dumps(structure_contract, ensure_ascii=False)
            model_text += "\n根据最新确认宽高将归一化关系转换为构造计划。基准框可平移，坐标y向上。每个组成是独立闭合路径。已有来源已明确星位、星径和朝向，不得再次索要这些信息，不得用仅外框代替完整对象。"
        if composition_contract:
            model_text += "\n[原文明确组成契约，不得省略或替换组成]\n"+json.dumps(composition_contract,ensure_ascii=False)
        from .cad_requirement_contract import build_requirement_source_index, requirement_contract
        from .cad_source_acceptance import source_texts
        planning_sources = build_requirement_source_index(
            requirement_contract([{'source_id':f'user:{i}','text':s} for i,s in enumerate(source_texts(original_requirement))])
        )
        model_text += "\n[后端只读需求来源索引；source_requirement_refs只能引用这些条目，模型不得创建或修改来源]\n" + json.dumps(planning_sources, ensure_ascii=False)
        from .cad_requirement_contract import junction_intent_guidance
        model_text += '\n[连接意图来源权限；由现有来源校验器计算，不是模型假设]\n' + json.dumps(junction_intent_guidance(planning_sources), ensure_ascii=False)
        try:
            payload = model_callback(
                model_text, _request_construction_schema(text, source_index=planning_sources),
            )
            payload = _coerce_model_payload(deepcopy(payload))
            # Resolve aliases (notably semantic.object_id -> output_ref)
            # before the strict plan model validates graph references.  This
            # is a symbol-table normalization, not a geometry repair.  Doing
            # it later wastes the single bounded model repair on names even
            # when the referenced logical object is unambiguous.
            payload, deterministic_repairs = repair_construction_references_once(payload)
            payload, winding_repairs = bind_sector_winding(payload, original_requirement)
            deterministic_repairs.extend(winding_repairs)
            payload, layout_repairs = compile_composition_plan(
                payload, composition_contract, original_requirement
            )
            payload, chain_repairs = normalize_composite_path_connections_once(
                payload, original_requirement
            )
            profile_repairs = []
            # The reference explicitly requires sharp radial polygons. Keep
            # peak-count assertions, but do not misapply smooth-curve checks.
            if (structure_contract and isinstance(payload.get("plan"), dict)
                and all(c.get("frame") or c["kind"] == "radial_polygon" for c in structure_contract["components"])):
                for assertion in payload["plan"].get("assertions", []):
                    if assertion.get("kind") == "radial_pattern" and assertion.get("profile") != "polygonal":
                        assertion["profile"] = "polygonal"
                        profile_repairs.append({"kind":"source_bound_polygonal_profile",
                                                "assertion_id":assertion.get("assertion_id"),
                                                "reference_id":structure_contract["id"]})
            payload, late_reference_repairs = repair_construction_references_once(payload)
            deterministic_repairs.extend(late_reference_repairs)
            deterministic_repairs.extend(chain_repairs)
            deterministic_repairs.extend(profile_repairs)
            deterministic_repairs.extend(layout_repairs)
            payload, area_repairs = normalize_explicit_area_once(payload, text)
            deterministic_repairs.extend(area_repairs)
            payload, size_repairs = normalize_explicit_outline_size_once(payload, original_requirement)
            deterministic_repairs.extend(size_repairs)
            payload, center_repairs = bind_explicit_outline_center(payload, original_requirement)
            deterministic_repairs.extend(center_repairs)
            from .cad_assertion_authority import reconcile_model_bounds
            payload, authority_repairs = reconcile_model_bounds(payload, original_requirement)
            deterministic_repairs.extend(authority_repairs)
            payload = bind_outline_requirements(payload, text)
            interpreted = StructuredConstructionInterpretation.model_validate(payload)
        except Exception as exc:
            rejected_plan = payload.get("plan") if isinstance(payload, dict) else None
            reference_diagnostic = None
            if isinstance(exc, ValidationError) and isinstance(rejected_plan, dict):
                field_errors = []
                affected = set()
                steps = rejected_plan.get('steps') or []
                for issue in exc.errors(include_url=False, include_context=False):
                    location = list(issue['loc'])
                    field_errors.append({'path': location, 'message': issue['msg'],
                                         'input': issue.get('input')})
                    if 'steps' in location:
                        index = location.index('steps') + 1
                        if index < len(location) and isinstance(location[index], int) and location[index] < len(steps):
                            ref = steps[location[index]].get('output_ref')
                            if ref: affected.add(ref)
                reference_diagnostic = {
                    'code': 'plan_field_validation_failed', 'message': '构造计划字段不合法，必须修正具体字段后才能执行。',
                    'details': {'field_errors': field_errors, 'affected_output_refs': sorted(affected),
                                'repair_instruction': '按原计划单位展开数值表达式；禁止cx、cy、R等未定义变量，乘法必须显式写*。保留其他部件。'},
                }
                from .cad_parametric import construction_expression_errors
                reference_diagnostic['details']['expression_errors']=construction_expression_errors(rejected_plan)
            if isinstance(exc, StructureContractError):
                reference_diagnostic = {
                    'code': 'composition_compile_failed',
                    'message': str(exc),
                    'details': deepcopy(exc.details or {}),
                }
            if isinstance(rejected_plan, dict):
                available = [step.get('output_ref') for step in rejected_plan.get('steps', [])
                             if isinstance(step, dict) and step.get('output_ref')]
                invalid = [item.get('target_ref') for item in rejected_plan.get('assertions', [])
                           if isinstance(item, dict) and item.get('target_ref')
                           and item.get('target_ref') not in available]
                if invalid:
                    reference_diagnostic = {
                        'code':'unresolved_plan_reference',
                        'message':'断言引用未定义的输出；修复引用或补齐真实构造步骤，禁止删除验收要求。',
                        'details':{'invalid_target_refs':invalid,'available_output_refs':available},
                    }
            return {
                **_failure("invalid_model_output", str(exc), parser),
                **({'construction_error':reference_diagnostic} if reference_diagnostic else {}),
                "deterministic_repairs": deterministic_repairs,
                **(
                    {"rejected_plan": deepcopy(rejected_plan)}
                    if isinstance(rejected_plan, dict) else {}
                ),
            }
        if interpreted.is_construction_request and interpreted.clarification is not None:
            clarification = interpreted.clarification
            recognized=clarification.recognized_shape
            source_names=local_creation_objects(original_requirement)
            recognized_names=local_creation_objects("生成"+recognized) if recognized else []
            grounded_shape=(not recognized or recognized in text or
                (len(source_names)>=2 and (
                    recognized_names==source_names
                    or all(name in recognized for name in source_names)
                )))
            if (not _evidence_is_grounded(text, interpreted.evidence_text)
                or not grounded_shape):
                return _failure("ungrounded_model_output", "澄清对象无法回指用户原文", parser)
            from .cad_projection_acceptance import projection_clarification_is_redundant, projection_requirements
            if projection_clarification_is_redundant(original_requirement,clarification.question):
                return {**_failure('confirmed_projection_reasked',
                    '投影约定和尺寸已由原文确认；请使用已确认约束输出构造计划，不得再次询问相同参数。',parser),
                    'requirements_complete':True,'rejected_clarification':clarification.model_dump(),
                    'confirmed_projection_requirements':projection_requirements(original_requirement)}
            confirmed_fields = {f['field'] for f in scalar_contract['facts']
                                if f['status']=='effective' and f['operator']=='eq'}
            if (clarification.question_key == 'curve_constraints'
                    and {'width','height'}.issubset(confirmed_fields)
                    and len(scalar_contract['subjects']) == 1
                    and not re.search(r'控制点|顶点|端点|半径|直径|参数式|函数表达式', original_requirement)
                    and re.search(r'控制点|比例|凹口|尖点|方程|内部', clarification.question)):
                return {
                    **_failure('modeling_choice_required',
                        '整体尺寸已明确；内部曲线比例属于建模选择，请声明假设并输出计划，不能重新索要用户参数。', parser),
                    'requirements_complete': True,
                    'rejected_clarification': clarification.model_dump(),
                }
            # A grounded clarification always outranks a simultaneous plan.
            # Such a plan necessarily depends on assumptions for the missing
            # parameter and must never be executed or turn a normal question
            # into a provider interruption.
            question, removed = (ground_size_clarification(clarification.question, "\n".join(source_texts(original_requirement)))
                                 if clarification.question_key == "size" else (clarification.question, []))
            return {
                **_failure("missing_requirements", question, parser, clarification_required=True),
                "clarification_grounding": {"removed_unsupported_layout_questions": removed},
                "clarification": {**clarification.model_dump(), "question": question, "status": "clarification_required",
                                  "recognized_size": clarify_construction_request(text)["recognized_size"],
                                  "suggested_prompt": question},
            }
        if not interpreted.is_construction_request or interpreted.plan is None:
            from .cad_projection_acceptance import projection_requirements
            confirmed_projection=projection_requirements(original_requirement)
            if confirmed_projection and confirmed_projection['projected_edge_length_mm'] is not None:
                return {**_failure('confirmed_projection_plan_missing',
                    '原文已明确投影构造、完整棱线数量及尺寸；模型未提交计划属于规划失败，不是用户需求缺失。请按已确认约束输出构造计划。',parser),
                    'requirements_complete':True,'confirmed_projection_requirements':confirmed_projection}
            return {
                **_failure(
                "not_construction_request", "模型未将输入识别为 CAD 构造请求。", parser,
                clarification_required=True,
                ),
                "normalization_facts": normalization_facts,
            }
        if not _evidence_is_grounded(text, interpreted.evidence_text):
            return _failure(
                "ungrounded_model_output", "模型证据无法回指用户原文，已拒绝执行。", parser,
                clarification_required=True,
            )
        # Grounded low-confidence plans may be trialled for concrete repair
        # diagnostics. They remain ineligible for a candidate even if the
        # deterministic checks pass. Missing requirements are handled above.
        plan = interpreted.plan
        evidence = list(interpreted.evidence_text)
        confidence = float(interpreted.confidence)
        assumptions = list(interpreted.assumptions)
        # H3.4: model output may only reference the backend-owned, current
        # requirement source index. It cannot create or upgrade source refs.
        from .cad_requirement_contract import build_requirement_source_index, validate_junction_source_refs, requirement_contract
        from .cad_source_acceptance import source_texts
        source_index = build_requirement_source_index(
            requirement_contract([{'source_id':f'user:{i}','text':s} for i,s in enumerate(source_texts(original_requirement))]),
        )
        local_constraints=[]
        for step in plan.steps:
            local_constraints.extend([item.model_dump(mode='python') for item in getattr(step,'junction_constraints',[])])
        if local_constraints:
            source_validation=validate_junction_source_refs(local_constraints, source_index)
            if not source_validation['valid']:
                junction_source_failure = {
                    'source_validation': source_validation, 'allowed_source_index': source_index,
                    'junction_intent_guidance': junction_intent_guidance(source_index),
                    'affected_output_refs': [s.output_ref for s in plan.steps if getattr(s, 'junction_constraints', [])],
                    'repair_instruction': '从只读来源索引中选择语义匹配的source_requirement_refs；不能省略或虚构来源，不能用模型假设授权尖角。保留用户要求和已有几何；修正引用后仍须通过完整验收。',
                }

    try:
        if junction_source_failure is not None:
            raise ConstructionPlanError('invalid_junction_source_refs',
                '局部连接约束引用了无效或语义不匹配的需求来源。',
                details=junction_source_failure)
        # Reject missing/duplicated components before any coordinate execution.
        # Geometry validation below remains authoritative for dimensions and
        # topology; this phase only validates the model's declared inventory.
        preflight_structure = validate_plan_structure(structure_contract, plan)
        if composition_contract:
            preflight_structure = validate_plan_structure(composition_contract, plan) or preflight_structure
        from .cad_repetition_acceptance import validate_repetition_plan
        repetition_preflight = validate_repetition_plan(original_requirement, plan)
        if repetition_preflight:
            preflight_structure = repetition_preflight
        inventory_count=_explicit_line_inventory(original_requirement)
        if inventory_count is not None and (len(plan.steps)!=inventory_count or any(s.op!='add_line' for s in plan.steps)):
            raise ConstructionPlanError('source_inventory_mismatch','来源清单要求独立直线图元，不能用一条多段线或模型数量断言替代。',
                details={'requires_structural_replan':True,'affected_output_refs':[s.output_ref for s in plan.steps],
                    'required_line_steps':inventory_count,'observed_steps':len(plan.steps),'observed_operations':[s.op for s in plan.steps],
                    'repair_instruction':'按用户完整直线清单重新编译独立add_line步骤；数量断言须作用于整图，不能绑定单条棱线并要求等于整图数量。保留用户长度、投影及连接要求，不得添加重复或退化边来凑数。'})
        result = execute_construction_plan(plan)
        from .cad_validation_evidence import ConstructionEvidence
        evidence_context=ConstructionEvidence()
        if re.search(r'平滑|光滑|smooth|切向连续|C1', original_requirement, re.I):
            for quality in result.get('curve_quality', []):
                if quality.get('schema') == 'cad.curve-quality.v1' and quality.get('c1') is not True:
                    raise ConstructionPlanError('smoothness_requirement_failed',
                        '用户要求平滑闭合曲线，但复合路径连接未达到切向连续。',
                        step_id=quality.get('step_id'), details={
                            'affected_output_refs':[quality.get('output_ref')],
                            'measured_continuity':quality.get('c1'),
                            'maximum_tangent_delta_deg':quality.get('maximum_tangent_delta_deg'),
                            'repair_instruction':'仅修复该复合路径的连接控制点，使相邻段达到C1切向连续；保留中心、尺寸和闭合性。'})
        if len(scalar_contract['subjects']) == 1:
            overall = construction_geometry_bounds(result['geometries'])
            for fact in scalar_contract['facts']:
                if (fact['status'] == 'effective' and fact['operator'] == 'eq'
                        and fact['subject'] == scalar_contract['subjects'][0]
                        and fact['field'] in {'width', 'height'}
                        and fact['binding'] == 'single_subject'):
                    axis = 'x' if fact['field'] == 'width' else 'y'
                    actual = overall['max_'+axis] - overall['min_'+axis]
                    if abs(actual-fact['value_mm']) > .5:
                        raise ConstructionPlanError('source_dimension_mismatch',
                            '整体尺寸不符合用户需求，不能将整体尺寸仅用于某一部件。',
                            details={'field': fact['field'], 'actual_mm': actual,
                                     'expected_mm': fact['value_mm'], 'source_evidence': fact['evidence']})
        try:
            polar_acceptance=verify_polar_requirements(polar_requirements(original_requirement), result["geometries"])
        except ParametricError as exc:
            raise ConstructionPlanError("source_requirement_mismatch", str(exc)) from exc
        try:
            structure_validation = validate_structure(structure_contract, result["geometries"], width_m, height_m,evidence_context=evidence_context)
            composition_validation = evidence_context.measure(validate_explicit_composition,composition_contract,result["geometries"],evidence_context=evidence_context)
            source_acceptance = verify_scoped_primitives(original_requirement, result["geometries"],result["logical_objects"],evidence_context=evidence_context)
            from .cad_wave_requirements import verify_wave_requirements
            wave_acceptance=verify_wave_requirements(original_requirement,result['geometries'])
            if wave_acceptance['status']!='not_checked':
                source_acceptance['wave_acceptance']=wave_acceptance
                if wave_acceptance['coverage']=='complete':source_acceptance['coverage']='complete'
            if polar_acceptance:
                source_acceptance['polar_acceptance']=polar_acceptance
                from .cad_polar_source_coverage import verify_polar_source_coverage
                polar_source_acceptance=verify_polar_source_coverage(original_requirement,polar_acceptance)
                if polar_source_acceptance['status']=='passed':
                    source_acceptance['polar_source_acceptance']=polar_source_acceptance
                    source_acceptance['coverage']='complete'
                elif polar_source_acceptance.get('unconsumed_text'):
                    source_acceptance['polar_source_acceptance']=polar_source_acceptance
            from .cad_source_acceptance import verify_final_source_contract
            source_acceptance['final_source_acceptance']=verify_final_source_contract(original_requirement,result['geometries'],result['logical_objects'],evidence_context=evidence_context)
            if source_acceptance['final_source_acceptance'].get('coverage')=='complete':
                source_acceptance['coverage']='complete'
            from .cad_primitive_layout_acceptance import verify_primitive_layout
            primitive_layout_acceptance=verify_primitive_layout(original_requirement,result['geometries'],evidence_context=evidence_context)
            if primitive_layout_acceptance['status']=='passed':
                source_acceptance['primitive_layout_acceptance']=primitive_layout_acceptance
                source_acceptance['coverage']='complete'
            elif primitive_layout_acceptance.get('unconsumed_text'):
                source_acceptance['primitive_layout_acceptance']=primitive_layout_acceptance
            from .cad_source_acceptance import verify_single_round_primitive
            primitive_acceptance = verify_single_round_primitive(original_requirement, result['geometries'])
            if primitive_acceptance['status'] == 'passed':
                source_acceptance['single_primitive_acceptance'] = primitive_acceptance
                source_acceptance['coverage'] = 'complete'
            elif primitive_acceptance.get('unconsumed_text'):
                source_acceptance['single_primitive_acceptance'] = primitive_acceptance
            from .cad_rectangle_acceptance import verify_single_rectangle
            rectangle_acceptance = verify_single_rectangle(original_requirement, result['geometries'],evidence_context=evidence_context)
            if rectangle_acceptance['status'] == 'passed':
                source_acceptance['rectangle_acceptance'] = rectangle_acceptance
                source_acceptance['coverage'] = 'complete'
            elif rectangle_acceptance.get('unconsumed_text'):
                source_acceptance['rectangle_acceptance'] = rectangle_acceptance
            from .cad_vertex_acceptance import verify_vertex_path, verify_open_straight_path
            open_path_acceptance=verify_open_straight_path(original_requirement,result['geometries'],evidence_context=evidence_context)
            if open_path_acceptance['status']=='passed':
                source_acceptance['open_path_acceptance']=open_path_acceptance
                source_acceptance['coverage']='complete'
            elif open_path_acceptance.get('unconsumed_text'):
                source_acceptance['open_path_acceptance']=open_path_acceptance
            vertex_acceptance = verify_vertex_path(original_requirement, result['geometries'])
            if vertex_acceptance['status'] == 'passed':
                source_acceptance['vertex_acceptance'] = vertex_acceptance
                source_acceptance['coverage'] = 'complete'
            from .cad_coordinate_requirements import verify_control_point_curve
            coordinate_acceptance = verify_control_point_curve(original_requirement, result['geometries'])
            if coordinate_acceptance['status'] == 'passed':
                source_acceptance['control_point_acceptance'] = coordinate_acceptance
                source_acceptance['coverage'] = 'complete'
            from .cad_axis_requirements import verify_ellipse_axes
            axis_acceptance = verify_ellipse_axes(original_requirement, result['geometries'])
            if axis_acceptance['status'] == 'passed':
                source_acceptance['axis_acceptance'] = axis_acceptance
                source_acceptance['coverage'] = 'complete'
            from .cad_composition_coverage import verify_composition_coverage
            composition_acceptance = evidence_context.measure(verify_composition_coverage, original_requirement, result['geometries'], evidence_context=evidence_context)
            if composition_acceptance['status'] == 'passed':
                source_acceptance['composition_acceptance'] = composition_acceptance
                source_acceptance['coverage'] = 'complete'
            # These are partial measurements of a Bezier chain, never proof
            # that unrelated clauses or all source requirements were consumed.
            bezier_match = re.search(r'(\d+)\s*段.*?三次\s*Bezier', original_requirement, re.I)
            qualities = result.get('curve_quality') or []
            if bezier_match and len(qualities) == 1:
                quality = qualities[0]
                required = int(bezier_match.group(1))
                actual_segments = len(plan.steps[0].segments) if plan.steps and hasattr(plan.steps[0], 'segments') else None
                checks = source_acceptance.setdefault('checks', [])
                checks.append({'field':'bezier_segment_count','expected':required,'actual':actual_segments,
                               'status':'passed' if actual_segments == required else 'failed',
                               'authority':'backend_measured_plan_and_geometry'})
                checks.append({'field':'bezier_continuity','expected':'C1','actual':quality.get('continuity_required'),
                               'status':'passed' if quality.get('c1') is True else 'failed',
                               'authority':'backend_measured_curve_quality'})
            from .cad_path_relation_acceptance import verify_path_relations
            path_acceptance=verify_path_relations(original_requirement,result['geometries'],evidence_context=evidence_context)
            if path_acceptance['status']!='not_checked':
                source_acceptance['path_relation_acceptance']=path_acceptance
            from .cad_path_relation_acceptance import verify_path_source_coverage
            path_source=verify_path_source_coverage(original_requirement,path_acceptance,result['geometries'])
            if path_source['status']=='passed':
                source_acceptance['path_source_acceptance']=path_source
                source_acceptance['coverage']='complete'
            from .cad_stroke_acceptance import verify_stroke_requirements
            stroke_acceptance=verify_stroke_requirements(original_requirement,result['geometries'])
            if stroke_acceptance['status']!='not_checked':
                source_acceptance['stroke_acceptance']=stroke_acceptance
            from .cad_semantic_acceptance import verify_semantic_requirements
            from .cad_symmetric_divider_acceptance import verify_symmetric_divider_source
            divider_acceptance=evidence_context.measure(verify_symmetric_divider_source,original_requirement,result['geometries'],evidence_context=evidence_context)
            if divider_acceptance['status']=='passed':
                source_acceptance['divider_acceptance']=divider_acceptance
                source_acceptance['coverage']='complete'
            from .cad_radial_attachment_acceptance import verify_radial_attachment_source
            radial_attachment_acceptance=evidence_context.measure(verify_radial_attachment_source,original_requirement,result['geometries'])
            if radial_attachment_acceptance['status']=='passed':
                source_acceptance['radial_attachment_acceptance']=radial_attachment_acceptance
                source_acceptance['coverage']='complete'
            from .cad_circle_group_acceptance import verify_circle_group_source
            circle_group_acceptance=verify_circle_group_source(original_requirement,result['geometries'])
            if circle_group_acceptance['status']=='passed':
                source_acceptance['circle_group_acceptance']=circle_group_acceptance
                source_acceptance['coverage']='complete'
            semantic_acceptance=evidence_context.measure(_semantic_verifier or verify_semantic_requirements,original_requirement,result['geometries'])
            if semantic_acceptance['status']!='not_checked':
                source_acceptance['semantic_acceptance']=semantic_acceptance
            from .cad_semantic_source_coverage import verify_measured_semantic_coverage
            semantic_source_acceptance = verify_measured_semantic_coverage(original_requirement, semantic_acceptance,result['geometries'],evidence_context=evidence_context)
            if semantic_source_acceptance['status'] == 'passed':
                source_acceptance['semantic_source_acceptance'] = semantic_source_acceptance
                source_acceptance['coverage'] = 'complete'
            elif semantic_source_acceptance.get('unconsumed_text'):
                source_acceptance['semantic_source_acceptance'] = semantic_source_acceptance
            from .cad_semantic_source_coverage import verify_periodic_outline_source, verify_semicircular_outline_source
            arch_source = evidence_context.measure(verify_semicircular_outline_source, original_requirement,
                                                   result['geometries'], evidence_context=evidence_context)
            if arch_source['status'] == 'passed':
                source_acceptance['arch_source_acceptance'] = arch_source
                source_acceptance['coverage'] = 'complete'
            elif arch_source.get('unconsumed_text'):
                source_acceptance['arch_source_acceptance'] = arch_source
            periodic_source = evidence_context.measure(verify_periodic_outline_source, original_requirement,
                                                       result['geometries'], evidence_context=evidence_context)
            if periodic_source['status'] == 'passed':
                source_acceptance['periodic_source_acceptance'] = periodic_source
                source_acceptance['coverage'] = 'complete'
            elif periodic_source.get('unconsumed_text'):
                source_acceptance['periodic_source_acceptance'] = periodic_source
            from .cad_semantic_source_coverage import verify_polygonal_outline_source
            polygonal_source=evidence_context.measure(verify_polygonal_outline_source,original_requirement,result['geometries'],evidence_context=evidence_context)
            if polygonal_source['status']=='passed':
                source_acceptance['polygonal_source_acceptance']=polygonal_source
                source_acceptance['coverage']='complete'
            from .cad_stroke_acceptance import verify_stroke_source_coverage
            stroke_source_acceptance=verify_stroke_source_coverage(original_requirement,stroke_acceptance,semantic_acceptance)
            if stroke_source_acceptance['status']=='passed':
                source_acceptance['stroke_source_acceptance']=stroke_source_acceptance
                source_acceptance['coverage']='complete'
            elif stroke_source_acceptance.get('unconsumed_text'):
                source_acceptance['stroke_source_acceptance']=stroke_source_acceptance
            from .cad_projection_acceptance import verify_projection_requirements
            projection_acceptance = evidence_context.measure(verify_projection_requirements,original_requirement,result['geometries'])
            if projection_acceptance['status']!='not_checked':
                source_acceptance['projection_acceptance']=projection_acceptance
            from .cad_projection_acceptance import verify_projection_source_coverage
            projection_source_acceptance=verify_projection_source_coverage(original_requirement,projection_acceptance)
            if projection_source_acceptance['status']=='passed':
                source_acceptance['projection_source_acceptance']=projection_source_acceptance
                source_acceptance['coverage']='complete'
            from .cad_repetition_acceptance import verify_repetition_requirements
            repetition_acceptance=evidence_context.measure(verify_repetition_requirements,original_requirement,result['geometries'])
            if repetition_acceptance['status']!='not_checked':
                source_acceptance['repetition_acceptance']=repetition_acceptance
            from .cad_repetition_source_coverage import verify_repetition_source_coverage
            repetition_source_acceptance=verify_repetition_source_coverage(original_requirement,repetition_acceptance)
            if repetition_source_acceptance['status']=='passed':
                source_acceptance['repetition_source_acceptance']=repetition_source_acceptance
                source_acceptance['coverage']='complete'
            elif repetition_source_acceptance.get('unconsumed_text'):
                source_acceptance['repetition_source_acceptance']=repetition_source_acceptance
        except StructureContractError as exc:
            from .cad_local_repair import build_local_repair_scope
            details = dict(exc.details or {})
            affected_ids = set()
            if isinstance(details.get("geometry_id"), int):
                affected_ids.add(details["geometry_id"])
            affected_ids.update(
                value for value in details.get("geometry_ids", [])
                if isinstance(value, int)
            )
            if affected_ids:
                symbols = result.get("symbol_table") or {}
                affected_refs = sorted(
                    str(ref) for ref, ids in symbols.items()
                    if affected_ids.intersection(value for value in ids if isinstance(value, int))
                )
                if affected_refs:
                    details["affected_output_refs"] = affected_refs
                    details.setdefault(
                        "repair_instruction",
                        "只修复 affected_output_refs 对应的构造步骤；保留其他对象、尺寸、布局、标识和断言。",
                    )
            exc.details = details
            scope=(None if exc.details.get('requires_structural_replan') else
                   build_local_repair_scope(plan.model_dump(mode='json'),result,exc.details))
            if scope:exc.details={**exc.details,'local_repair_scope':scope}
            raise ConstructionPlanError("structure_requirement_failed", str(exc), details=exc.details) from exc
    except ConstructionPlanError as exc:
        details = exc.details or {}
        if exc.code=='assertion_failed':
            # A model assertion must not hide the independently measured
            # source failure until the repair budget is exhausted. This
            # isolated diagnostic cannot return or persist a candidate.
            diagnostic_plan=plan.model_dump(mode='json')
            diagnostic_plan['assertions']=[]
            try:
                diagnostic_trial=execute_construction_plan(diagnostic_plan)
                from .cad_semantic_acceptance import verify_semantic_requirements
                try:
                    (_semantic_verifier or verify_semantic_requirements)(original_requirement,diagnostic_trial['geometries'])
                    from .cad_repetition_acceptance import verify_repetition_requirements
                    verify_repetition_requirements(original_requirement,diagnostic_trial['geometries'])
                    from .cad_projection_acceptance import verify_projection_requirements
                    verify_projection_requirements(original_requirement,diagnostic_trial['geometries'])
                except StructureContractError as source_error:
                    details['independent_source_failure']={
                        'message':str(source_error),'details':source_error.details,
                        'diagnostic_only':True,'candidate_accepted':False}
                    details['repair_instruction']=(details.get('repair_instruction','')+
                        ' 同时修复independent_source_failure中的用户需求偏差；仅更改模型断言不能解决实际几何错误。')
                    source_ids=set((source_error.details or {}).get('geometry_ids') or [])
                    if source_ids:
                        details['affected_output_refs']=sorted(set(details.get('affected_output_refs') or [])|
                            {ref for ref,ids in diagnostic_trial['symbol_table'].items() if source_ids.intersection(ids)})
                    if ((source_error.details or {}).get('requires_structural_replan')
                            and source_ids=={g['id'] for g in diagnostic_trial['geometries']}):
                        details['requires_structural_replan']=True
                        details['repair_instruction']+=' 原文结构诊断覆盖全部输出，必须修复实际连接结构，不能只修改断言。'
                    exc.details=details
            except (ConstructionPlanError,ValueError):
                pass
        if (_allow_arc_direction_repair and exc.code=='rotational_arc_overlaps_period'
                and details.get('opposite_direction_sweep_degrees',361)<=details.get('period_degrees',0)
                and not re.search(r'顺时针|逆时针|clockwise|counterclockwise|起始角|终止角|长弧|优弧|控制点|顶点',original_requirement,re.I)):
            # The endpoint/circle/period constraints leave exactly one arc
            # branch without overlap. Resolve it only when the source did
            # not prescribe a direction, then rerun all geometry acceptance.
            corrected=plan.model_dump(mode='json')
            target=next((s for s in corrected['steps'] if s['step_id']==exc.step_id
                and s['op']=='add_rotational_path' and s.get('constrain_sector_end')),None)
            index=details.get('seed_segment_index')
            if target is not None and isinstance(index,int) and 0<=index<len(target['segments']):
                arc=target['segments'][index]
                if arc.get('kind')=='arc':
                    old=arc.get('clockwise',False);arc['clockwise']=not old
                    verified=interpret_construction_request(source_text,lambda *_:{
                        'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
                        'plan':corrected,'confidence':confidence,'evidence_text':evidence,'assumptions':assumptions,
                    },force_structured_model=True,_allow_arc_direction_repair=False,_semantic_verifier=_semantic_verifier)
                    if verified.get('status')=='ready':
                        verified.setdefault('deterministic_repairs',[]).append({
                            'kind':'resolve_constrained_arc_branch','output_ref':target['output_ref'],
                            'seed_segment_index':index,'from_clockwise':old,'to_clockwise':not old,
                            'constraint_evidence':details,'all_acceptance_reexecuted':True})
                        return verified
        if (_allow_radial_bounds_repair and exc.code=='assertion_failed'
                and re.search(r'astroid|星形线',original_requirement,re.I)
                and not re.search(r'无尖角|没有尖角|平滑|切向连续|C1',original_requirement,re.I)):
            failed=next((a for a in plan.assertions if a.assertion_id==exc.assertion_id
                and a.kind=='radial_pattern' and a.profile=='smooth'),None)
            if failed is not None:
                corrected=plan.model_dump(mode='json')
                corrected['assertions']=[a for a in corrected['assertions'] if a['assertion_id']!=failed.assertion_id]
                try:
                    trial=execute_construction_plan(corrected)
                    from .cad_semantic_acceptance import verify_semantic_requirements
                    proof=(_semantic_verifier or verify_semantic_requirements)(original_requirement,trial['geometries'])
                    if proof.get('coverage')=='astroid_identity_radius_and_four_cusps':
                        verified=interpret_construction_request(source_text,lambda *_:{
                            'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
                            'plan':corrected,'confidence':confidence,'evidence_text':evidence,'assumptions':assumptions,
                        },force_structured_model=True,_allow_radial_bounds_repair=False,_semantic_verifier=_semantic_verifier)
                        if (verified.get('status')=='ready'
                                and verified['trial_result']['geometries']==trial['geometries']):
                            verified.setdefault('deterministic_repairs',[]).append({
                                'kind':'source_curve_identity_replaces_inapplicable_smoothness',
                                'rejected_model_assertion':failed.model_dump(mode='json'),
                                'independent_acceptance':proof,'geometry_unchanged':True,
                                'all_acceptance_reexecuted':True})
                            return verified
                except (ConstructionPlanError,StructureContractError,ValueError):
                    pass
        if (_allow_radial_bounds_repair and exc.code=='assertion_failed'
                and not any(f['field'] in {'width','height'} for f in scalar_contract['facts'])):
            failed=next((a for a in plan.assertions if a.assertion_id==exc.assertion_id
                and a.kind=='bounds_size'),None)
            from .cad_repetition_acceptance import tooth_boundary_requirements,verify_repetition_requirements,branch_structure_requirements
            from .cad_semantic_acceptance import regular_polygon_requirement
            from .cad_wave_requirements import wave_requirements,verify_wave_requirements
            wave_source=wave_requirements(original_requirement)
            projection_source=bool(re.search(r'等轴|等距投影',original_requirement)
                                   and re.search(r'投影棱长',original_requirement))
            polar_source=polar_requirements(original_requirement)
            branch_source=branch_structure_requirements(original_requirement)
            radial_source=(tooth_boundary_requirements(original_requirement)
                           or regular_polygon_requirement(original_requirement) or wave_source or projection_source or polar_source or branch_source)
            if failed is not None and radial_source:
                corrected=plan.model_dump(mode='json')
                corrected['assertions']=[a for a in corrected['assertions'] if a['assertion_id']!=failed.assertion_id]
                try:
                    trial=execute_construction_plan(corrected)
                    if branch_source:
                        from .cad_repetition_source_coverage import verify_repetition_source_coverage
                        proof=verify_repetition_requirements(original_requirement,trial['geometries'])
                        radial_ok=verify_repetition_source_coverage(original_requirement,proof)['status']=='passed'
                    elif polar_source:
                        from .cad_polar_source_coverage import verify_polar_source_coverage
                        proof=verify_polar_requirements(polar_source,trial['geometries'])
                        radial_ok=verify_polar_source_coverage(original_requirement,proof)['status']=='passed'
                    elif projection_source:
                        from .cad_projection_acceptance import verify_projection_requirements,verify_projection_source_coverage
                        proof=verify_projection_requirements(original_requirement,trial['geometries'])
                        radial_ok=verify_projection_source_coverage(original_requirement,proof)['status']=='passed'
                    elif tooth_boundary_requirements(original_requirement):
                        proof=verify_repetition_requirements(original_requirement,trial['geometries'])
                        radial_ok=any(c['name']=='齿形旋转重复关系' for c in proof.get('checks',[]))
                    elif wave_source:
                        proof=verify_wave_requirements(original_requirement,trial['geometries'])
                        radial_ok=proof['status']=='passed'
                    else:
                        from .cad_semantic_acceptance import verify_semantic_requirements
                        proof=(_semantic_verifier or verify_semantic_requirements)(original_requirement,trial['geometries'])
                        radial_ok=proof['status']=='passed'
                    if radial_ok:
                        verified=interpret_construction_request(source_text,lambda *_:{
                            'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
                            'plan':corrected,'confidence':confidence,'evidence_text':evidence,'assumptions':assumptions,
                        },force_structured_model=True,_allow_radial_bounds_repair=False,_semantic_verifier=_semantic_verifier)
                        if (verified.get('status')=='ready'
                                and verified['trial_result']['geometries']==trial['geometries']):
                            verified.setdefault('deterministic_repairs',[]).append({
                                'kind':('source_branch_acceptance_replaces_unrequested_bounds' if branch_source else 'source_polar_acceptance_replaces_unrequested_bounds' if polar_source else 'source_projection_acceptance_replaces_unrequested_bounds' if projection_source else 'source_wave_acceptance_replaces_unrequested_bounds' if wave_source
                                        else 'source_radial_acceptance_replaces_unrequested_bounds'),
                                'rejected_model_assertion':failed.model_dump(mode='json'),
                                'source_evidence':radial_source,'independent_acceptance':proof,
                                'geometry_unchanged':True,'all_acceptance_reexecuted':True})
                            return verified
                except (ConstructionPlanError,StructureContractError,ValueError):
                    pass
        angle = details.get('rotation_degrees_to_required_direction')
        if (_allow_measured_rotation and details.get('authority') == 'backend_measured_geometry'
                and isinstance(angle, (int, float)) and details.get('affected_output_refs')):
            # Execute a measured pose correction on an existing valid curve;
            # never replace its mathematical shape or trust model coordinates.
            rotated = plan.model_dump(mode='json')
            refs = set(details['affected_output_refs'])
            targets = [s for s in rotated['steps'] if s['output_ref'] in refs]
            if targets and all(s['op'] == 'add_parametric_curve' for s in targets):
                import math
                cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
                for step in targets:
                    x, y = step['x_expression'], step['y_expression']
                    step['x_expression'] = f'({cosine:.15g})*({x})-({sine:.15g})*({y})'
                    step['y_expression'] = f'({sine:.15g})*({x})+({cosine:.15g})*({y})'
                rotated['free_outline_layout'] = [v for v in rotated.get('free_outline_layout', []) if v['target_ref'] not in refs]
                verified = interpret_construction_request(source_text, lambda *_: {
                    'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
                    'plan':rotated,'confidence':confidence,'evidence_text':evidence,'assumptions':assumptions,
                }, force_structured_model=True, _allow_measured_rotation=False,_semantic_verifier=_semantic_verifier)
                if verified.get('status') == 'ready':
                    verified.setdefault('deterministic_repairs', []).append({
                        'kind':'measured_curve_rotation','angle_degrees':angle,
                        'output_refs':sorted(refs),'all_acceptance_reexecuted':True})
                    return verified
        # Executor failures carry a step/assertion id rather than a geometry
        # id. Resolve their exact symbolic target too, so a local error does
        # not cause unrelated components to be regenerated on the next turn.
        details = dict(exc.details or {})
        # Feasibility rejects duplicates/zero edges before source structure
        # validation. Still run the existing read-only structural diagnostic;
        # never suppress the original error or persist diagnostic geometry.
        if (exc.code in {'drawing_infeasible','logical_graph_invalid'} and details.get('measured_geometries')
                and not details.get('geometry_evidence_truncated')):
            from .cad_projection_acceptance import verify_projection_requirements
            measured_geometry=details['measured_geometries']
            try:
                verify_projection_requirements(original_requirement,measured_geometry)
            except StructureContractError as structural:
                diagnostic=structural.details or {}
                details['source_structure_diagnostic']={'message':str(structural),**diagnostic}
                ids=set(diagnostic.get('geometry_ids') or [])
                if diagnostic.get('requires_structural_replan') and ids=={g['id'] for g in measured_geometry}:
                    details['requires_structural_replan']=True
                    details['affected_output_refs']=sorted(ref for ref,values in details.get('geometry_refs',{}).items() if ids.intersection(values))
                    details['repair_instruction']=diagnostic.get('repair_instruction',details.get('repair_instruction'))
            exc.details=details
        if not details.get('affected_output_refs'):
            affected = [step.output_ref for step in plan.steps
                        if step.step_id == getattr(exc, 'step_id', None)]
            for assertion in plan.assertions:
                if assertion.assertion_id == getattr(exc, 'assertion_id', None):
                    target = getattr(assertion, 'target_ref', None)
                    if target and not getattr(assertion, 'reference_ref', None):
                        affected.append(target)
            if affected:
                details['affected_output_refs'] = sorted(set(affected))
                details.setdefault('repair_instruction','仅修复指定输出；其他部件、单位、布局及断言由后端保留。')
                exc.details = details
        if (exc.code=='drawing_infeasible' and len(plan.steps)==1
            and plan.steps[0].op=='add_spline'
            and not re.search(r'(?:[2-9二三四五六七八九]\s*[次阶]|\bdegree\b|次数|阶数|\bcubic\b|\bquadratic\b|\bquartic\b|\bquintic\b)',original_requirement,re.I)):
            # Diagnose a small legal parameter range, without replacing the
            # model plan, altering control points or saving any trial output.
            step=plan.steps[0];feasible=[]
            for degree in range(2,min(5,len(step.control_points)-1)+1):
                if degree==step.degree:continue
                trial_plan=plan.model_dump(mode='json');trial_plan['steps'][0]['degree']=degree
                try:execute_construction_plan(trial_plan)
                except (ConstructionPlanError,ValueError):continue
                feasible.append(degree)
            if feasible:
                exc.details={**(exc.details or {}),'spline_degree_diagnostics':{
                    'feasible_degrees':feasible,'control_points_unchanged':True,
                    'persisted':False,'instruction':'原文未指定次数；请使用试算可行的合法次数修正计划，保留全部原控制点。'}}
        return {
            **_failure("trial_execution_failed", exc.message, parser),
            "construction_error": exc.as_dict(),
            "requirements_contract": outline_requirements(text),
            "deterministic_repairs": deterministic_repairs,
            "plan": plan.model_dump(mode="json"),
            "confidence": confidence,
            "assumptions": deepcopy(assumptions),
        }
    except Exception as exc:
        return _failure("invalid_plan", str(exc), parser)

    if confidence < 0.75:
        return {**_failure('low_confidence','模型计划置信度不足，试算通过也不能作为候选保存。',parser),
            'confidence':confidence,'construction_request_recognized':True,
            'rejected_plan':plan.model_dump(mode='json'),'diagnostic_trial_passed':True,
            'normalization_facts':normalization_facts,'persisted':False}

    acceptance_summary = construction_acceptance_summary(
        preflight_structure=preflight_structure,
        structure_contract=structure_contract,
        structure_validation=structure_validation,
        composition_contract=composition_contract,
        composition_validation=composition_validation,
        source_acceptance=source_acceptance,
        trial_result=result,
    )
    if template_plan is not None:
        # Fresh chat and project confirmation use the same registered-template
        # authority. Keep generic source coverage partial; do not fabricate a
        # full-prose proof or override any independently reported uncertainty.
        reports = [source_acceptance] + [v for k, v in source_acceptance.items()
            if k.endswith('_acceptance') and isinstance(v, dict)]
        blockers = any(r.get('review_required') or r.get('unknown_requirements')
            or r.get('status') in {'failed', 'unverified', 'review_required'}
            for r in reports)
        blockers = blockers or any((r or {}).get('review_required') for r in
            (preflight_structure, structure_validation, composition_validation))
        if not blockers:
            from .cad_template_plan import template_trial_acceptance
            acceptance_summary = template_trial_acceptance(result)
    return {
        "schema": "cad.construction-interpretation-result.v1",
        "status": "ready",
        "parser": parser,
        "requirement_ledger": bind_geometry_acceptance(
            requirement_ledger(original_requirement, assumptions=assumptions,
                structure_contract=structure_contract, composition_contract=composition_contract),
            composition_contract, result["geometries"],evidence_context=evidence_context),
        "confidence": confidence,
        "evidence_text": evidence,
        "assumptions": assumptions,
        "deterministic_repairs": deterministic_repairs,
        "normalization_facts": normalization_facts,
        "plan": plan.model_dump(mode="json"),
        "requirements_contract": outline_requirements(text),
        "structure_contract": structure_contract,
        "preflight_structure": preflight_structure,
        "structure_validation": structure_validation,
        "composition_contract": composition_contract,
        "composition_validation": composition_validation,
        "source_acceptance": source_acceptance,
        "acceptance_summary": acceptance_summary,
        "trial_result": result,
        "template_specifications": template_profile(plan),
        **({"project_requirements": parameterize_design(text)} if template_plan else {}),
    }


def construction_acceptance_summary(
    *, preflight_structure, structure_contract, structure_validation,
    composition_contract, composition_validation, source_acceptance,
    trial_result=None,
):
    """Converge preflight uncertainty with post-execution geometry evidence."""
    # Preflight may legitimately be unable to expand a parametric/composite
    # operation. Once execution has produced actual geometry, a passed
    # source-backed structure/composition check resolves that temporary state.
    post_structure_passed = bool(
        (composition_contract and (composition_validation or {}).get("status") == "passed")
        or (structure_contract and (structure_validation or {}).get("status") == "passed")
    )
    preflight_review_required = bool(
        not post_structure_passed
        and (
            (preflight_structure or {}).get("review_required")
            or (preflight_structure or {}).get("status") not in (None, "passed")
        )
    )
    source_acceptance = source_acceptance or {}
    reports = [source_acceptance]
    reports.extend(
        value for key, value in source_acceptance.items()
        if key.endswith("_acceptance") and isinstance(value, dict)
    )
    report_requires_review = any(
        report.get("review_required") is True
        or report.get("status") in {"failed", "unverified", "review_required"}
        for report in reports
    )
    failed_checks = [deepcopy(check) for report in reports for check in report.get('checks', [])
                     if isinstance(check, dict) and check.get('status') == 'failed']
    report_requires_review = report_requires_review or bool(failed_checks)
    review_required = (preflight_review_required or report_requires_review
        or any((report or {}).get('review_required') is True for report in
               (structure_validation,composition_validation)))
    verified_checks = sum(
        1 for report in reports for check in report.get("checks", [])
        if isinstance(check, dict) and check.get("status") == "passed"
    )
    verified_checks += int(
        bool(composition_contract)
        and (composition_validation or {}).get("status") == "passed"
    )
    if verified_checks == 0:
        review_required = True
    verified_checks += int(
        bool(structure_contract)
        and (structure_validation or {}).get("status") == "passed"
    )
    # Executability never establishes source requirement coverage. Partial or
    # missing coverage remains reviewable even when every known check passes.
    coverage_complete = source_acceptance.get('coverage') in {'complete', 'full'}
    unknown_requirements = source_acceptance.get('unknown_requirements', [])
    coverage_complete = coverage_complete and not unknown_requirements
    review_required = review_required or not coverage_complete
    return {
        "status": "review_required" if review_required else "passed",
        "review_required": review_required,
        "authority": "backend_measured_geometry",
        "verified_checks": verified_checks,
        "failed_checks": failed_checks,
        "requirement_coverage": "complete" if coverage_complete else "unknown",
        "unknown_requirements": deepcopy(unknown_requirements) or ([] if coverage_complete else [
            {'source':'source_acceptance','reason':'需求清单或完整覆盖证据缺失'}]),
        "geometry_validity": 'passed' if (trial_result or {}).get('feasibility',{}).get('ok') is True else 'not_checked',
        "constraint_satisfaction": (trial_result or {}).get('constraint_solve',{}).get('status','not_checked'),
        "assertion_status": ('passed' if (trial_result or {}).get('assertions',{}).get('ok') is True
                             and (trial_result or {}).get('assertions',{}).get('count',0)>0 else 'not_checked'),
        "unverified_geometry_ids": source_acceptance.get("unverified_geometry_ids", []),
    }


def bind_component_layout(payload, contract, text):
    """Bind explicit free-outline sizes/order to existing symbolic outputs.

    No missing component is synthesized. Fixed-coordinate/radius requests
    cannot be reinterpreted as free outlines by this normalization.
    """
    if not contract or contract["kind"] != "named_components":
        return payload, []
    source=text.split("\n后端试算反馈：",1)[0]
    from .cad_source_acceptance import source_texts
    raw_source='\n'.join(source_texts(source))
    if re.search(r'(?:圆心|中心|左下角|顶点|端点|控制点)(?:为|在|是)?\s*'+_POINT,raw_source):
        return payload, []
    scoped=contract.get('component_dimensions') or {}
    plan=payload.get('plan')
    if scoped and isinstance(plan,dict) and not re.search(r'坐标固定|固定坐标|固定顶点|固定控制点',source):
        steps=plan.get('steps') or [];matches={}
        for name in contract['names']:
            candidates=[s for s in steps if name in str((s.get('semantic') or {}).get('label') or '')]
            if len(candidates)!=1:return payload,[]
            matches[name]=candidates[0]['output_ref']
        # Explicit placement is independent of curve feasibility. Bind an
        # existing symbolic layout even when the diagnostic geometry trial
        # cannot yet pass; otherwise a model's edge gap can survive a source
        # requirement that explicitly specifies center spacing.
        if contract.get('left_to_right') and contract.get('gap_m') is not None:
            unit_scale = 1000 if plan.get('units') == 'mm' else 1
            previous = None
            for name in contract['names']:
                ref = matches[name]
                item = next((v for v in plan.get('free_outline_layout') or []
                             if v.get('target_ref') == ref), None)
                if item is not None and previous is not None:
                    item.update(right_of_ref=previous, gap=contract['gap_m']*unit_scale,
                                gap_reference=contract['gap_reference'])
                previous = ref
        raw=deepcopy(plan);raw['free_outline_layout']=[]
        trial=_trial_plan_without_assertions(raw)
        if trial:
            byid={g['id']:g for g in trial['geometries']};unit=1000 if plan.get('units','m')=='m' else 1
            layouts=[]
            for name in contract['names']:
                ref=matches[name];gs=[byid[i] for i in trial['symbol_table'].get(ref,[])]
                if len(gs)!=1:return payload,[]
                if gs[0].get('type')!='polyline' or not gs[0].get('closed'):return payload,[]
                b=construction_geometry_bounds(gs);local={**(contract.get('dimensions') or {}),**scoped.get(name,{})}
                # Fixed-radius components must not be resized here.  Preserve
                # their measured bounds as an identity layout and let the
                # independent structure acceptance report a radius mismatch.
                # A bad fixed component must not cancel deterministic sizing
                # of every other, already-correct component.
                item={'target_ref':ref}
                # A fixed radius/circumradius is a geometric identity. Do not
                # convert it into a width/height fit, which can nonuniformly
                # scale a polygon and invalidate its radius after placement.
                if not any(local.get(key) is not None for key in ('radius_m','circumradius_m','diameter_m')):
                    item.update(width=local.get('width_m',(b['max_x']-b['min_x'])/1000)*1000/unit,
                               height=local.get('height_m',(b['max_y']-b['min_y'])/1000)*1000/unit)
                else:
                    item.update(width=(b['max_x']-b['min_x'])/unit,
                               height=(b['max_y']-b['min_y'])/unit)
                if layouts and contract.get('left_to_right') and contract.get('gap_m') is not None:
                    item.update(right_of_ref=layouts[-1]['target_ref'],gap=contract['gap_m']*1000/unit,gap_reference=contract['gap_reference'])
                layouts.append(item)
            plan['free_outline_layout']=layouts
            refs=set(matches.values())
            plan['assertions']=[a for a in plan.get('assertions',[]) if not (a.get('kind')=='bounds_size' and a.get('target_ref') in refs|{None})]
            return payload,[{'kind':'bind_scoped_component_layout','layout':deepcopy(layouts),'fixed_radii_preserved':True}]
    if re.search(r"坐标|控制点|顶点|半径|直径|边长|等比|角度|相切|平行|垂直",source):
        return payload, []
    plan=payload.get("plan")
    dimensions=contract["dimensions"]
    if not isinstance(plan,dict) or plan.get("constraints") or not all(dimensions.get(k) for k in ("width_m","height_m")):
        return payload, []
    steps=plan.get("steps",[])
    if len(steps)!=len(contract["names"]):return payload, []
    if any(s.get('op') not in {'add_polyline','add_composite_path','add_rotational_path','add_parametric_curve','add_rectangle','add_centered_rectangle'} for s in steps):
        return payload,[]
    refs=[]
    for name in contract["names"]:
        matches=[s for s in steps if name in str((s.get("semantic") or {}).get("label") or "")]
        if len(matches)!=1 or matches[0]["output_ref"] in refs:return payload, []
        refs.append(matches[0]["output_ref"])
    layout=[]
    unit_factor=1000 if plan.get("units")=="mm" else 1
    for i,ref in enumerate(refs):
        item={"target_ref":ref,"width":dimensions["width_m"]*unit_factor,"height":dimensions["height_m"]*unit_factor}
        if i and contract.get("left_to_right") and contract.get("gap_m") is not None:
            item.update(right_of_ref=refs[i-1],gap=contract["gap_m"]*unit_factor,gap_reference=contract["gap_reference"])
        layout.append(item)
    plan["free_outline_layout"]=layout
    assertions=plan.setdefault("assertions",[])
    # Replace model-invented global bounds with the explicitly scoped bounds.
    assertions[:]=[a for a in assertions if a.get("kind")!="bounds_size"]
    for i,ref in enumerate(refs):
        assertions.append({"kind":"bounds_size","assertion_id":f"component-size-{i}","target_ref":ref,
                           "width":dimensions["width_m"]*unit_factor,"height":dimensions["height_m"]*unit_factor,"tolerance":.0001*unit_factor})
    return payload,[{"kind":"bind_source_component_layout","layout":deepcopy(layout)}]


def bind_sector_winding(payload, source_text):
    """Resolve unspecified traversal from the seed, not a conflicting model flag."""
    if re.search(r'顺时针|逆时针|clockwise|counterclockwise', source_text, re.I):
        return payload, []
    repairs = []
    for step in (payload.get('plan') or {}).get('steps') or []:
        if (step.get('op') == 'add_rotational_path'
                and step.get('constrain_sector_end') is True
                and step.get('direction', 'auto') != 'auto'):
            repairs.append({'kind': 'derive_sector_winding', 'output_ref': step.get('output_ref'),
                            'from': step['direction'], 'to': 'auto'})
            step['direction'] = 'auto'
    return payload, repairs


def compile_composition_plan(payload, contract, source_text):
    """Compile a model response into one complete composition plan.

    Composition is not a second generator or a template fallback.  The model
    supplies one step for every declared component; this boundary validates
    the complete ``CadConstructionPlan``, binds the user-specified component
    dimensions/layout, and rejects a partial plan before execution.
    """
    if not contract:
        return payload, []
    if isinstance(payload, dict) and isinstance(payload.get('clarification'), dict):
        # A complete composition plan is mandatory for execution, but a
        # grounded clarification is not an execution attempt. A simultaneous
        # assumption-based plan is deliberately ignored by the later
        # clarification branch, so it must not fail composition validation
        # before that safety decision is reached.
        return payload, []
    if not isinstance(payload, dict) or not isinstance(payload.get("plan"), dict):
        raise StructureContractError("组合需求没有返回完整构造计划", {
            "phase": "composition_compile",
            "expected": contract.get("names") or contract.get("counts"),
        })
    # Bind persisted component dimensions/layout before strict validation.
    # Model-authored helper bounds are not authoritative and may contain a
    # sign/arithmetic error; the persisted contract must replace them rather
    # than consume the one bounded geometry-repair attempt.
    payload = deepcopy(payload)
    payload, repairs = bind_component_layout(payload, contract, source_text)
    payload, radial_repairs = bind_named_radial_requirements(
        payload, contract, source_text,
    )
    repairs.extend(radial_repairs)
    plan = CadConstructionPlan.model_validate(payload["plan"])
    steps = list(plan.steps)
    kind = contract.get("kind")
    if kind == "named_components":
        names = [str(name) for name in contract.get("names") or []]
        if len(steps) != len(names):
            component_outputs = {
                name: [step.output_ref for step in steps if name in str(step.semantic.label)]
                for name in names
            }
            raise StructureContractError("组合计划必须为每个独立部件提供一个构造步骤", {
                "phase": "composition_compile",
                "expected_components": names,
                "observed_steps": len(steps),
                "component_outputs": component_outputs,
                "missing_components": [name for name, refs in component_outputs.items() if not refs],
                "duplicated_components": [name for name, refs in component_outputs.items() if len(refs) > 1],
                "observed_outputs": [{"output_ref": step.output_ref, "label": step.semantic.label}
                                     for step in steps],
                "relation_checklist": _composition_relation_checklist(contract, steps, payload["plan"]),
                "repair_instruction": "保留每个独立部件的一份完整构造；位置关系写入布局，不要为移动同一部件再次创建重复轮廓。保留原始需求、补参及正确部件。",
            })
        labels = [str(step.semantic.label) for step in steps]
        missing = [name for name in names if not any(name in label for label in labels)]
        if missing:
            raise StructureContractError("组合计划缺少具名部件步骤", {
                "phase": "composition_compile",
                "missing_components": missing,
                "observed_labels": labels,
                "relation_checklist": _composition_relation_checklist(contract, steps, payload["plan"]),
            })
        checklist = _composition_relation_checklist(contract, steps, payload["plan"])
        if checklist['missing_relations']:
            raise StructureContractError('组合计划缺少需求关系绑定', {
                'phase':'composition_compile','relation_checklist':checklist,
                'repair_instruction':'先补齐关系清单中的布局、尺寸和中心关系，再执行几何；不要用模型假设替代用户关系。'})
    elif kind == "component_count":
        expected = sum(int(value) for value in (contract.get("counts") or {}).values())
        expanded = any(getattr(step, "op", None) == "rectangular_array" for step in steps)
        if not expanded and len(steps) != expected:
            raise StructureContractError("组合计划组成数量与需求不一致", {
                "phase": "composition_compile",
                "expected_count": expected,
                "observed_steps": len(steps),
            })
    payload["plan"] = plan.model_dump(mode="json")
    # Layout binding may rewrite the plan; validate the final IR again so the
    # executor and acceptance layer see exactly the same complete plan.
    payload["plan"] = CadConstructionPlan.model_validate(payload["plan"]).model_dump(mode="json")
    repairs.append({"kind": "compile_composition_plan", "component_contract": deepcopy(contract)})
    return payload, repairs


def _composition_relation_checklist(contract, steps, plan):
    refs={str(s.semantic.label):s.output_ref for s in steps}
    missing=[]
    if contract.get('left_to_right') and contract.get('gap_m') is not None:
        layouts=[]
        for s in steps:
            layouts.append(s.output_ref)
        # compile_composition_plan has already bound this relation into layout;
        # report it as missing only when the plan omitted the binding.
        layouts=plan.get('free_outline_layout') or []
        if not any(v.get('right_of_ref') and v.get('gap') is not None for v in layouts): missing.append('left_to_right_gap')
    if contract.get('center_distance_m') is not None and len(steps)<2:
        missing.append('center_distance')
    return {'components':list(refs.values()),'required':{
        'dimensions':bool(contract.get('dimensions') or contract.get('component_dimensions')),
        'layout':bool(contract.get('left_to_right') and contract.get('gap_m') is not None),
        'center_distance':contract.get('center_distance_m') is not None},
        'missing_relations':missing}


def bind_named_radial_requirements(payload, contract, source_text):
    """Bind explicit per-component peak counts to model-created geometry.

    This compiles a relation from the user's text; it never creates vertices.
    It applies to any named component followed by a peak/petal/lobe count, so
    the same rule covers arbitrary compound drawings rather than a shape name.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("plan"), dict):
        return payload, []
    names = [str(value) for value in (contract or {}).get("names") or []]
    if not names:
        return payload, []
    plan = payload["plan"]
    steps = [step for step in plan.get("steps", []) if isinstance(step, dict)]
    assertions = plan.setdefault("assertions", [])
    if not isinstance(assertions, list):
        return payload, []
    # The canonical construction input appends a JSON requirement snapshot.
    # Relation extractors must only read the verbatim source prefix; scanning
    # serialized contract fields can associate one component's count with an
    # earlier component name.
    text = source_text.split("\n[CAD_REQUIREMENT_CONTRACT_SNAPSHOT.v1]", 1)[0]
    text = text.split("\n后端试算反馈：", 1)[0]
    chinese = "零一二三四五六七八九十"
    repairs = []
    for index, name in enumerate(names):
        match = re.search(
            re.escape(name) + r"[^。；;\n]{0,48}?(\d+|[二三四五六七八九十])\s*个?\s*(尖角|凸瓣|花瓣|波瓣)",
            text,
        )
        if not match:
            continue
        token, feature = match.groups()
        count = int(token) if token.isdigit() else chinese.index(token)
        candidates = [
            step for step in steps
            if name in str((step.get("semantic") or {}).get("label") or "")
            or name == str((step.get("semantic") or {}).get("assembly_label") or "")
        ]
        if len(candidates) != 1:
            continue
        target = candidates[0].get("output_ref")
        if not isinstance(target, str):
            continue
        assertions[:] = [
            item for item in assertions
            if not (
                isinstance(item, dict)
                and item.get("kind") == "radial_pattern"
                and item.get("target_ref") == target
            )
        ]
        assertions.append({
            "kind": "radial_pattern",
            "assertion_id": f"source-radial-{index + 1}",
            "target_ref": target,
            "lobes": count,
            "profile": "polygonal" if feature == "尖角" else "smooth",
        })
        repairs.append({
            "kind": "bind_named_radial_requirement",
            "component": name,
            "target_ref": target,
            "lobes": count,
            "profile": "polygonal" if feature == "尖角" else "smooth",
        })
    return payload, repairs


def _explicit_line_inventory(text):
    match=re.search(r'只画(?:可见及隐藏的)?\s*(\d+)\s*条(?:棱线|直线段)',text)
    return int(match[1]) if match and 2<=int(match[1])<=32 else None


def outline_requirements(source_text: str) -> dict[str, Any] | None:
    """Extract explicit periodic-boundary requirements, never generate points.

    Restrict this contract to the single-outline wording supported by the
    radial verifier. Multiple objects and compound boundaries need their own
    scoped contracts; they must not silently bind to the first plan step.
    """
    text = source_text.split("\n后端试算反馈：", 1)[0]
    repeat = re.search(r"(\d+|[二三四五六七八九十])\s*(?:片花瓣|瓣花|个凸瓣|个波瓣)", text)
    star = re.search(r"(\d+|[二三四五六七八九十])\s*角星", text)
    # A mathematical curve or an explicit formula must not inherit the
    # polygonal-star schema merely because a parenthesis says 四角星.
    if star and re.search(r'星形线|参数式|[xy]\s*=',text,re.I):
        star=None
    if star and len(local_creation_objects(text))<=1 and not has_compound_primitives(re.sub(r"外接圆|内切圆", "尺寸参照", text)) and not re.search(r"红旗|国旗|旗面|内部|外圈|内圈",text):
        repeat = star
    elif not repeat or "轮廓" not in text or not re.search(r"闭合|封闭", text):
        return None
    if re.search(r"多[个条朵]|两[个条朵]|[2-9]\s*[个条朵]|内部|内圈|外圈|多个轮廓", text):
        return None
    token = repeat.group(1)
    return {"schema": "cad.outline-requirements.v1", "entity_count": 1, "closed": True,
            "radial_lobes": int(token) if token.isdigit() else "零一二三四五六七八九十".index(token),
            "profile": "polygonal" if repeat is star else "smooth",
            "evidence_text": repeat.group(0)}


def bind_outline_requirements(payload: dict[str, Any], text: str) -> dict[str, Any]:
    requirement = outline_requirements(text)
    plan = payload.get("plan") if isinstance(payload, dict) else None
    if requirement is None or not isinstance(plan, dict):
        return payload
    steps = plan.get("steps") or []
    if len(steps) != 1 or not isinstance(steps[0], dict) or not steps[0].get("output_ref"):
        raise ValueError("单一闭合重复轮廓必须绑定唯一构造输出，不能将数量要求仅绑定首个图元。")
    target = steps[0]["output_ref"]
    if steps[0].get("op") == "add_rotational_path" and steps[0].get("count") != requirement["radial_lobes"]:
        raise ValueError("旋转重复次数与用户明确要求的结构数量不一致。")
    assertions = plan.setdefault("assertions", [])
    assertions[:] = [a for a in assertions if a.get("kind") != "radial_pattern"]
    required_assertions = [
        {"kind": "entity_count", "assertion_id": "required-outline-count", "target_ref": None, "equals": 1},
        {"kind": "closed", "assertion_id": "required-outline-closure", "target_ref": target},
        {"kind": "radial_pattern", "assertion_id": "requested-radial-pattern", "target_ref": target,
         "lobes": requirement["radial_lobes"], "profile":requirement["profile"]},
    ]
    # Plans may already contain backend-bound assertions after a repair or
    # replay. Reuse equivalent checks, including serialized default fields.
    # A colliding identifier on a different constraint must not erase it.
    identifiers = {a.get('assertion_id') for a in assertions}
    for assertion in required_assertions:
        if any(all(existing.get(key) == value for key, value in assertion.items()
                   if key != 'assertion_id') for existing in assertions):
            continue
        identifier = assertion['assertion_id']
        suffix = 2
        while assertion['assertion_id'] in identifiers:
            assertion['assertion_id'] = f'{identifier}-{suffix}'
            suffix += 1
        assertions.append(assertion)
        identifiers.add(assertion['assertion_id'])
    return payload


def normalize_construction_request(source_text: str) -> tuple[str, list[str]]:
    """Append deterministic facts without replacing the user's wording.

    The normalization layer only converts explicit units and expands topology
    that is already stated by the user.  One documented canonical convention
    is added for symmetric columns along a U boundary so the model does not
    have to invent six independent coordinates.  Evidence is still validated
    against ``source_text`` rather than these generated hints.
    """
    facts: list[str] = []
    if re.search(r'正弦',source_text) and re.search(r'振幅|波幅',source_text):
        facts.append('振幅/波幅是中线到波峰的最大距离，峰谷总高度是其两倍；波距是横向相邻同相位波峰的距离，不是曲线路径弧长。不能把振幅误当成整体高度。')
    from .cad_coordinate_requirements import coordinate_scale
    if coordinate_scale(source_text)['has_scale']:
        facts.append('控制点或顶点坐标及坐标单位已给定，已确定几何尺度，不再索要外包宽高或半径。必须保留原始点及其角色，控制点不能擅自替换为拟合点。')
    if re.search(r'每级\s*宽',source_text):
        facts.append('尺寸作用域：每级宽高是局部台阶尺寸，不能将其用作整条轮廓的外包宽高；保留级数与全部水平、竖直段。允许开放阶梯线或用两条基底边闭合。')
    if re.search(r'六边形',source_text) and re.search(r'无缝|共边',source_text):
        facts.append('拼接关系：每个单元应为独立闭合正六边形，局部边长不变；单元内部不得重叠，所有单元须通过完整公共边连通。不要把多单元拼成自相交路径。')
    from .cad_repetition_acceptance import branch_structure_requirements
    if branch_structure_requirements(source_text):
        facts.append('本请求为开放的直线分支网络，不是闭合边界。使用add_line分别表达主枝和侧枝，不用复合路径拼接分叉，不声明closed或radial_pattern断言；分支数量、旋转对称、侧枝连接及最大半径由后端独立验收。')
    if re.search(r'条对称分支',source_text) and '侧枝' in source_text:
        facts.append('重复关系：主枝连接共同中心；各主枝及其侧枝经相同角度旋转后须逐一对应，侧枝连接主枝，同一主枝的两侧枝须镜面对称。不得只保证图元数量而遗漏连接和等长关系。')
    requirements = outline_requirements(source_text)
    if requirements:
        facts.append(
            f"结构验收契约：最终仅1个连续闭合外轮廓，恰好{requirements['radial_lobes']}个径向凸瓣，轮廓类型为{requirements['profile']}；"
            "使用单一边界步骤，不得用多个独立闭合图元或装饰代替。此契约将在执行后独立验证。"
        )
    requested_area = _requested_area_square_metres(source_text)
    if requested_area is not None:
        facts.append(
            "封闭轮廓目标面积="
            f"{_format_number(requested_area)}平方米；面积是完整尺度约束，"
            "无需再要求宽度或高度。"
        )
    seen_dimensions: set[tuple[str, str]] = set()
    for match in re.finditer(rf"({_NUMBER})\s*({_UNIT})", source_text, re.IGNORECASE):
        original = match.group(0)
        metres = _to_m(match.group(1), match.group(2))
        canonical = _format_number(metres)
        key = (original.casefold(), canonical)
        if key in seen_dimensions:
            continue
        seen_dimensions.add(key)
        facts.append(f"单位换算：{original} = {canonical}米。")

    # 等尺寸："长宽均为5m/宽高都为5米/长和宽都是3米/边长…"——用户明确
    # 同一数值同时约束宽高。转为确定性事实后，结构化模型（链路3）拿到
    # 明确宽高约束，避免把等尺寸表达当作缺失尺寸而低置信拒绝。
    equal = re.search(
        rf"(?:长宽|宽高|长和宽|宽和高|长与宽|宽与高|边长)"
        rf"(?:均|都|都是|均为|都为|是|为)?\s*({_NUMBER})\s*(?:米|m)",
        source_text,
        re.IGNORECASE,
    )
    square_side=bool(equal and equal[0].lstrip().startswith('边长'))
    # A side length is not a bounding-box width/height. Only an explicit
    # square supports that conversion; polygons, tilings and 3D projections
    # retain their local metric and are checked by their existing verifiers.
    if equal and (not square_side or (re.search(r'正方形',source_text)
                                     and not re.search(r'立方体|长方体|投影',source_text))):
        try:
            size = float(equal.group(1))
        except (TypeError, ValueError):
            size = 0.0
        if size > 0:
            facts.append(
                "等尺寸约束：宽="
                f"{_format_number(size)}米，高={_format_number(size)}米"
                "（用户明确长宽均为同一数值，整体外接边界应满足该约束）。"
            )

    repeated = re.search(
        rf"创建\s*(\d+)\s*个相连的(.+?)，每个.*?宽\s*({_NUMBER})\s*({_UNIT})"
        rf".*?深\s*({_NUMBER})\s*({_UNIT})",
        source_text,
    )
    if repeated:
        count = int(repeated.group(1))
        width = _to_m(repeated.group(3), repeated.group(4))
        depth = _to_m(repeated.group(5), repeated.group(6))
        gap = 0.0 if re.search(r"(?:不留缝|无缝|间距为?\s*0)", source_text) else None
        if gap is not None:
            total_width = count * width + max(0, count - 1) * gap
            facts.append(
                "相连矩形阵列："
                f"数量={count}，单体宽={_format_number(width)}米，"
                f"单体深={_format_number(depth)}米，净间距=0米，"
                f"列节距={_format_number(width)}米，总宽={_format_number(total_width)}米；"
                "每个矩形必须是独立具名逻辑对象。"
            )
            behind = re.search(rf"后方\s*({_NUMBER})\s*({_UNIT})", source_text)
            if behind:
                distance = _to_m(behind.group(1), behind.group(2))
                facts.append(
                    "后方贯穿线：与阵列后边界净距="
                    f"{_format_number(distance)}米，长度={_format_number(total_width)}米。"
                )

    u_shape = _normalize_u_shape(source_text)
    facts.extend(u_shape)
    if not facts:
        return source_text, []
    return source_text + _NORMALIZATION_MARKER + "\n".join(f"- {fact}" for fact in facts), facts


def _requested_area_square_metres(source_text: str) -> float | None:
    match = re.search(
        rf"({_NUMBER})\s*(平方米|平米|m\s*[²2]|square\s*met(?:er|re)s?)",
        source_text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    value = float(match.group(1))
    return value if value > 0 else None


def normalize_explicit_area_once(
    payload: dict[str, Any], source_text: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Scale one unambiguously closed model output to the user's stated area.

    This is a generic path-3 constraint repair: it does not recognize object
    names or add geometry. It only applies when the request states an area and
    the model plan proves exactly one closed output boundary.
    """
    target_area = _requested_area_square_metres(source_text)
    if target_area is None or not isinstance(payload, dict):
        return payload, []
    repaired = deepcopy(payload)
    plan = repaired.get("plan")
    if not isinstance(plan, dict):
        return repaired, []
    trial = _trial_plan_without_assertions(plan)
    if not isinstance(trial, dict):
        return repaired, []
    symbol_table = trial.get("symbol_table")
    geometries = trial.get("geometries")
    steps = plan.get("steps")
    if not isinstance(symbol_table, dict) or not isinstance(geometries, list) or not isinstance(steps, list):
        return repaired, []
    by_id = {int(item["id"]): item for item in geometries if isinstance(item, dict) and "id" in item}
    closed_refs: list[tuple[str, list[dict[str, Any]]]] = []
    for output_ref, ids in symbol_table.items():
        if not isinstance(ids, list):
            continue
        selected = [by_id[value] for value in ids if value in by_id]
        if len(selected) != 1:
            continue
        item = selected[0]
        if item.get("type") in {"circle", "ellipse"} or (
            item.get("type") in {"polyline", "spline"} and item.get("closed") is True
        ):
            closed_refs.append((str(output_ref), selected))
    if len(closed_refs) != 1:
        return repaired, []
    target_ref, selected = closed_refs[0]
    scale = 1000.0 if plan.get("units", "m") == "m" else 1.0
    target_area_in_plan_units = (
        target_area if plan.get("units", "m") == "m" else target_area * 1_000_000.0
    )
    current_area = construction_geometry_area(selected) / (scale * scale)
    if current_area <= 0:
        return repaired, []
    factor = math.sqrt(target_area_in_plan_units / current_area)
    step = next(
        (item for item in steps if isinstance(item, dict) and item.get("output_ref") == target_ref),
        None,
    )
    if not isinstance(step, dict) or not _scale_area_step(step, factor):
        return repaired, []
    assertions = plan.setdefault("assertions", [])
    if not isinstance(assertions, list):
        return repaired, []
    assertions[:] = [
        item for item in assertions
        if not (isinstance(item, dict) and item.get("kind") == "area" and item.get("target_ref") == target_ref)
    ]
    assertions.append({
        "kind": "area",
        "assertion_id": "explicit-area",
        "target_ref": target_ref,
        "area": target_area_in_plan_units,
        "tolerance": max(0.001, target_area_in_plan_units * 0.0001),
    })
    return repaired, [{
        "kind": "normalize_explicit_area",
        "target_ref": target_ref,
        "from": current_area,
        "to_square_metres": target_area,
        "scale_factor": factor,
    }]


def _request_construction_schema(text: str, *, source_index=None) -> dict[str, Any]:
    """Limit free outlines to one existing boundary primitive.

    This changes the model's output contract, not geometry generation. Complex
    CAD requests retain the complete construction schema.
    """
    text=text.split('\n后端试算反馈：',1)[0]
    schema = construction_interpretation_json_schema()
    from .cad_requirement_contract import build_requirement_source_index, requirement_contract, junction_intent_guidance
    from .cad_source_acceptance import source_texts
    if source_index is None:
        source_index = build_requirement_source_index(requirement_contract([
            {'source_id': f'user:{i}', 'text': s} for i, s in enumerate(source_texts(text))]))
    permissions = junction_intent_guidance(source_index)['allowed_source_refs_by_intent']
    junction = schema['$defs']['JunctionConstraint']
    choices = []
    for intent, refs in permissions.items():
        if not refs:
            continue
        branch = deepcopy(junction)
        properties = branch['properties']
        properties['intent'] = {'type': 'string', 'enum': [intent]}
        properties['required_continuity'] = {'type': 'string', 'enum': ['G1', 'C1'] if intent == 'smooth' else ['C0']}
        properties['source_requirement_refs'] = {'type': 'array', 'minItems': 1, 'maxItems': 20,
            'items': {'type': 'string', 'enum': refs}}
        if 'source_requirement_refs' not in branch['required']:
            branch['required'].append('source_requirement_refs')
        choices.append(branch)
    # An empty optional junction list remains valid. With no authorized
    # intent, no junction item may claim invented source authority.
    schema['$defs']['JunctionConstraint'] = {'oneOf': choices} if choices else {'not': {}}
    inventory_count=_explicit_line_inventory(text)
    if inventory_count is not None:
        count=inventory_count;defs=schema['$defs'];props=defs['CadConstructionPlan']['properties']
        props['steps']={'type':'array','minItems':count,'maxItems':count,'items':{'$ref':'#/$defs/AddLineStep'}}
        props['shared_points']['minProperties']=2
        defs['CadConstructionPlan'].setdefault('required',[]).append('shared_points')
        defs['SharedEndpointReference']={'type':'object','properties':{
            axis:{'type':'string','pattern':r'^@[A-Za-z][A-Za-z0-9_]{0,63}\.'+axis+'$'} for axis in ('x','y')},
            'required':['x','y'],'additionalProperties':False}
        for field in ('start','end'):defs['AddLineStep']['properties'][field]={'$ref':'#/$defs/SharedEndpointReference'}
        if not re.search(r'宽|高',text):
            props['assertions']={'type':'array','items':{'$ref':'#/$defs/EntityCountAssertion'}}
        return schema
    from .cad_repetition_acceptance import branch_structure_requirements
    network=branch_structure_requirements(text)
    if network:
        props=schema['$defs']['CadConstructionPlan']['properties']
        props['steps']={'type':'array','minItems':network['entity_count'],'maxItems':network['entity_count'],
            'items':{'$ref':'#/$defs/AddLineStep'}}
        props['assertions']={'type':'array','items':{'$ref':'#/$defs/EntityCountAssertion'}}
        return schema
    from .cad_semantic_acceptance import semantic_requirements
    semantics = semantic_requirements(text)
    if semantics:
        # Canonical profiles can contain counters, doors or separate strokes.
        # A single-boundary restriction would make valid plans impossible.
        minimum = max((r.get('representation_contract',{}).get('minimum_path_count',1) for r in semantics),default=1)
        schema['$defs']['CadConstructionPlan']['properties']['steps']['minItems'] = minimum
        return schema
    if not ("轮廓" in text and "闭合" in text) or re.search(
        r"坐标|控制点|顶点|半径|直径|相切|平行|垂直|阵列|多个轮廓|两个轮廓", text
    ):
        return schema
    definitions = schema["$defs"]
    properties = definitions["CadConstructionPlan"]["properties"]
    properties["steps"] = {"type": "array", "minItems": 1, "maxItems": 1,
                           "items": {"oneOf": [
                               {"$ref": "#/$defs/AddPolylineStep"},
                               {"$ref": "#/$defs/AddCompositePathStep"},
                               {"$ref": "#/$defs/AddRotationalPathStep"},
                               {"$ref": "#/$defs/AddParametricCurveStep"},
                           ]}}
    properties["constraints"] = {"type": "array", "maxItems": 0, "items": {}}
    definitions["AddPolylineStep"]["properties"]["closed"] = {"type": "boolean", "const": True}
    required = definitions["AddPolylineStep"].setdefault("required", [])
    if "closed" not in required:
        required.append("closed")
    definitions["AddPolylineStep"]["properties"]["vertices"]["minItems"] = 64
    definitions["AddPolylineStep"]["properties"]["vertices"]["maxItems"] = 240
    definitions["AddCompositePathStep"]["properties"]["closed"] = {"type": "boolean", "const": True}
    definitions["AddParametricCurveStep"]["properties"]["closed"] = {"type": "boolean", "const": True}
    definitions["AddParametricCurveStep"].setdefault("required", []).append("closed")
    # Keep the model's requested sampling within the executor's 500-point
    # limit; smoothness comes from curves rather than excessive JSON points.
    definitions["AddCompositePathStep"]["properties"]["samples_per_curve"]["maximum"] = 32
    composite_required = definitions["AddCompositePathStep"].setdefault("required", [])
    if "closed" not in composite_required:
        composite_required.append("closed")
    requirement = outline_requirements(text)
    if requirement:
        if requirement.get('profile')=='smooth':
            # Periodic smooth boundaries use the existing global curve IR;
            # polygonal outlines and non-periodic boundaries retain their
            # other primitives. Avoid inconsistent hand-built sector seams.
            properties['steps']['items']={'oneOf':[{'$ref':'#/$defs/AddParametricCurveStep'}]}
        rotational = definitions["AddRotationalPathStep"]
        rotational["properties"]["count"]["const"] = requirement["radial_lobes"]
        rotational["properties"]["constrain_sector_end"] = {
            "type": "boolean", "const": True, "default": True,
        }
        rotational.setdefault("required", []).append("constrain_sector_end")
    needed = set()
    def visit(value):
        if isinstance(value, dict):
            ref = value.get("$ref", "")
            if ref.startswith("#/$defs/"):
                name = ref.rsplit("/", 1)[1]
                if name not in needed:
                    needed.add(name)
                    visit(definitions[name])
            for key, child in value.items():
                if key != "$defs":
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(schema)
    schema["$defs"] = {key: value for key, value in definitions.items() if key in needed}
    return schema


def bind_explicit_outline_center(payload, text):
    if re.search(r'控制点|顶点|端点', text):
        return payload, []
    match = re.search(r'(?:几何中心|中心点|中心)(?:位于|在|为|是)?\s*'+_POINT, text)
    plan = payload.get('plan') or {}
    steps = plan.get('steps') or []
    if not match or len(steps) != 1:
        return payload, []
    step = steps[0]
    if step.get('op') not in {'add_parametric_curve','add_composite_path','add_rotational_path','add_polyline'} or not step.get('closed'):
        return payload, []
    units = re.findall(r'坐标单位(?:为|是)?\s*(毫米|厘米|米|mm|cm|m)', text, re.I)
    if not units:
        supplied_units = re.findall(_NUMBER+r'\s*('+_UNIT+r')(?![a-zA-Z])', text, re.I)
        if len(set(supplied_units)) == 1:
            units = supplied_units
    if not units:
        return payload, []
    factor = length_factors('mm')[units[-1].lower()]
    scale = 1000 if plan.get('units','m') == 'm' else 1
    center={'x':float(match[1])*factor/scale,'y':float(match[2])*factor/scale}
    from .cad_requirement_contract import requirement_contract
    contract = requirement_contract([{'source_id':'center-source','text':text}])
    declared_size=any(f['status']=='effective' and f['field'] in {'width','height'} for f in contract['facts'])
    trial_plan=deepcopy(plan)
    if not declared_size:
        for layout in trial_plan.get('free_outline_layout',[]):
            if layout.get('target_ref')==step['output_ref'] and not layout.get('right_of_ref'):
                layout.pop('width',None);layout.pop('height',None);layout['center']=center
    trial = _trial_plan_without_assertions(trial_plan)
    if not trial or len(trial['geometries']) != 1:
        return payload, []
    bounds = construction_geometry_bounds(trial['geometries'])
    layouts = plan.setdefault('free_outline_layout', [])
    item = next((v for v in layouts if v.get('target_ref') == step['output_ref']), None)
    if item is None:
        item = {'target_ref':step['output_ref']}
        if declared_size:
            item.update(width=(bounds['max_x']-bounds['min_x'])/scale,height=(bounds['max_y']-bounds['min_y'])/scale)
        layouts.append(item)
    if item.get('right_of_ref'):
        return payload, []
    item['center'] = center
    if not declared_size:
        item.pop('width',None);item.pop('height',None)
    if len(contract['subjects']) == 1:
        for fact in contract['facts']:
            if (fact['status']=='effective' and fact['operator']=='eq'
                    and fact['subject']==contract['subjects'][0] and fact['field'] in {'width','height'}):
                item[fact['field']] = fact['value_mm']/scale
    return payload, [{'kind':'bind_explicit_outline_center','target_ref':step['output_ref'],'center':item['center']}]


def normalize_explicit_outline_size_once(
    payload: dict[str, Any], source_text: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fit one free outline to explicit width/height without changing topology.

    Fixed coordinates, radii, lengths, area and geometric constraints are not
    eligible. This only handles free control points, never template geometry.
    """
    from .cad_capsule_acceptance import has_local_axis_dimensions
    if has_local_axis_dimensions(source_text):
        # Only an independent, fully consumed source proof can establish that
        # model-authored bounds used local dimensions in a world-bounds tool.
        raw=payload.get('plan') if isinstance(payload,dict) else None
        trial=_trial_plan_without_assertions(raw) if isinstance(raw,dict) else None
        if not trial:return payload, []
        from .cad_source_acceptance import verify_final_source_contract
        try:proof=verify_final_source_contract(source_text,trial['geometries'],trial.get('logical_objects'))
        except StructureContractError:return payload, []
        if proof.get('coverage')!='complete':return payload, []
        values={c.get('field'):c.get('expected') for c in proof.get('checks',[]) if c.get('status')=='passed'}
        if not all(isinstance(values.get(k),(int,float)) for k in ('length_mm','height_mm')):return payload, []
        scale=1000 if raw.get('units','m')=='m' else 1
        ids={g['id'] for g in trial['geometries']};kept=[];changes=[]
        from .cad_construction import BoundsSizeAssertion,construction_geometry_bounds as measured_world_bounds
        world=measured_world_bounds(trial['geometries'])
        world_size=[world['max_x']-world['min_x'],world['max_y']-world['min_y']]
        for assertion in raw.get('assertions',[]):
            if assertion.get('kind')!='bounds_size':kept.append(assertion);continue
            a=BoundsSizeAssertion.model_validate(assertion)
            selected=ids if a.target_ref is None else set(trial.get('reference_table',trial['symbol_table']).get(a.target_ref,[]))
            failed_world=max(abs(world_size[0]-a.width*scale),abs(world_size[1]-a.height*scale))>a.tolerance*scale
            if failed_world and selected==ids and abs(a.width*scale-values['length_mm'])<=.5 and abs(a.height*scale-values['height_mm'])<=.5:
                changes.append({'kind':'source_local_axis_proof_replaces_world_bounds',
                    'assertion':deepcopy(assertion),'source_proof':proof,'geometry_unchanged':True})
            else:kept.append(assertion)
        if not changes:return payload, []
        result=deepcopy(payload);result['plan']['assertions']=kept
        return result,changes
    # Validation feedback is execution evidence, not a new user constraint.
    # An error mentioning a vertex/angle must not disable size fitting on retry.
    source_text = source_text.split("\n后端试算反馈：", 1)[0]
    coordinate_source = re.sub(r'坐标单位(?:为|是)?\s*(?:毫米|厘米|米|mm|cm|m)', '', source_text, flags=re.I)
    if '坐标' in coordinate_source:
        return payload, []
    if re.search(r'每(?:级|个|条|段|层|格|块|片|根)[^。；;\n]{0,40}(?:宽|高|长)',source_text):
        return payload, []
    if re.search(r"控制点|顶点|半径|直径|边长|等比|相切|等长|平行|垂直|角度|间距|平方米|平米|m²|m2|\b[xy]\s*=|参数式|函数表达式", source_text, re.I):
        return payload, []
    from .cad_requirement_contract import requirement_contract
    contract = requirement_contract([{'source_id':'outline-source','text':source_text}])
    sizes = {}
    upper_bounds = set()
    if len(contract['subjects']) == 1:
        for fact in contract['facts']:
            if (fact['status']=='effective' and fact['operator'] in {'eq','lte'}
                    and fact['subject']==contract['subjects'][0] and fact['field'] in {'width','height'}):
                sizes[fact['field']] = fact['value_mm']/1000
                if fact['operator']=='lte': upper_bounds.add(fact['field'])
    if not sizes or min(sizes.values()) <= 0:
        return payload, []
    repaired = deepcopy(payload)
    plan = repaired.get("plan")
    if not isinstance(plan, dict) or plan.get("constraints"):
        return payload, []
    steps = plan.get("steps") or []
    if len(steps) != 1 or not steps[0].get("closed"):
        return payload, []
    step = steps[0]
    if step.get("op") not in {"add_polyline", "add_spline", "add_composite_path", "add_rotational_path", "add_parametric_curve"}:
        return payload, []
    points = []
    if step["op"] in {"add_composite_path", "add_rotational_path"}:
        if step.get("op") == "add_rotational_path":
            step.setdefault("center", {"x": 0, "y": 0})
            points.append(step["center"])
        for segment in step.get("segments") or []:
            if segment.get("kind") == "line":
                points.extend([segment.get("start"), segment.get("end")])
            elif segment.get("kind") in {"bezier", "spline"}:
                points.extend(segment.get("control_points") or [])
            else:
                return payload, []
    else:
        points = step.get("vertices") or step.get("control_points") or []
    if step['op']!='add_parametric_curve' and (not points or not all(isinstance(p, dict) and "x" in p and "y" in p for p in points)):
        return payload, []
    sizing_trial_plan=deepcopy(plan)
    sizing_trial_plan['free_outline_layout']=[]
    trial = _trial_plan_without_assertions(sizing_trial_plan)
    if not trial or len(trial.get("geometries") or []) != 1:
        return payload, []
    bounds = construction_geometry_bounds(trial["geometries"])
    unit = 1000.0 if plan.get("units", "m") == "m" else 1.0
    width = (bounds["max_x"] - bounds["min_x"]) / unit
    height = (bounds["max_y"] - bounds["min_y"]) / unit
    if min(width, height) <= 1e-9:
        return payload, []
    measured = {'width':width*unit/1000,'height':height*unit/1000}
    for axis in upper_bounds:
        sizes[axis] = min(sizes[axis], measured[axis])
    if len(sizes)==1:
        axis=next(iter(sizes));other='height' if axis=='width' else 'width'
        sizes[other]=measured[other]*sizes[axis]/measured[axis]
    factors = (sizes["width"] * 1000 / unit / width, sizes["height"] * 1000 / unit / height)
    center = ((bounds["min_x"] + bounds["max_x"]) / (2 * unit),
              (bounds["min_y"] + bounds["max_y"]) / (2 * unit))
    seen = set()
    if step['op']=='add_parametric_curve':
        # Fit the final sampled geometry. Rewriting the formula using a
        # previous sample's extrema changes adaptive sample locations and
        # can miss the requested bounds on the next execution.
        layout = plan.setdefault('free_outline_layout', [])
        layout[:] = [item for item in layout if item.get('target_ref') != step['output_ref']]
        layout.append({'target_ref': step['output_ref'],
                       'width': sizes['width'] * 1000 / unit,
                       'height': sizes['height'] * 1000 / unit})
    if step["op"] == "add_rotational_path":
        step["fit_width"] = sizes["width"] * 1000 / unit
        step["fit_height"] = sizes["height"] * 1000 / unit
        points = []  # Fit the completed boundary, not its seed before rotation.
    for point in points:
        if id(point) in seen:
            continue
        seen.add(id(point))
        evaluated=ConstructionPoint.model_validate(point)
        for axis, factor, origin in zip(("x", "y"), factors, center):
            point[axis] = origin + (getattr(evaluated,axis) - origin) * factor
    assertions = plan.setdefault("assertions", [])
    target = step["output_ref"]
    assertions[:] = [a for a in assertions if not (a.get("kind") == "bounds_size" and a.get("target_ref") in {None, target})]
    assertions.append({"kind": "bounds_size", "assertion_id": "explicit-outline-size", "target_ref": target,
                       "width": sizes["width"] * 1000 / unit, "height": sizes["height"] * 1000 / unit,
                       "tolerance": max(1e-6, 0.001 * 1000 / unit)})
    return repaired, [{"kind": "normalize_explicit_outline_size", "target_ref": target,
                       "from": {"width": width, "height": height}, "to_metres": sizes,
                       "scale_factors": list(factors)}]


def normalize_composite_path_connections_once(
    payload: dict[str, Any], source_text: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Complete source-required composite continuity without inventing parts.

    Models commonly omit the shared start point of a cubic Bezier after the
    first segment.  A three-point Bezier is otherwise a valid quadratic, so
    schema validation cannot distinguish that omission.  We only prepend the
    preceding explicit endpoint when the enclosing path requires continuity.
    The same pass binds an explicitly top/bottom semicircle to the matching arc
    direction and aligns free cubic handles at measured non-smooth joints.
    It never creates a new segment or a shape-specific generator. Every
    proposed change remains subject to full execution and source acceptance.
    """
    plan = payload.get('plan') if isinstance(payload, dict) else None
    if not isinstance(plan, dict):
        return payload, []
    repaired = deepcopy(payload)
    changes: list[dict[str, Any]] = []

    if plan.get('shared_points') and any(step.get('op') in {'add_composite_path','add_rotational_path'}
                                        for step in plan.get('steps',[]) if isinstance(step,dict)):
        from .cad_shared_points import resolve_shared_points
        repaired['plan']=resolve_shared_points(repaired['plan'])
        changes.append({'kind':'resolve_shared_points_before_connection_checks',
                        'point_names':list(plan['shared_points']),'geometry_generated':False})

    def arc_point(segment: dict[str, Any], *, end: bool) -> dict[str, float] | None:
        center = segment.get('center')
        if not isinstance(center, dict):
            return None
        from .cad_construction import CompositeArcSegment
        arc=CompositeArcSegment.model_validate(segment)
        angle = arc.end_angle if end else arc.start_angle
        return {'x':arc.center.x+arc.radius*math.cos(math.radians(angle)),
                'y':arc.center.y+arc.radius*math.sin(math.radians(angle))}

    def endpoint(segment: dict[str, Any], *, end: bool) -> dict[str, Any] | None:
        kind = segment.get('kind')
        if kind == 'line':
            value = segment.get('end' if end else 'start')
        elif kind == 'arc':
            value = arc_point(segment, end=end)
        else:
            points = segment.get('control_points')
            value = points[-1 if end else 0] if isinstance(points, list) and points else None
        return ConstructionPoint.model_validate(value).model_dump() if isinstance(value,dict) else None

    for step in (repaired.get('plan') or {}).get('steps') or []:
        if not isinstance(step, dict) or step.get('op') not in {'add_composite_path', 'add_rotational_path'}:
            continue
        segments = step.get('segments')
        if not isinstance(segments, list):
            continue
        from .cad_connection_direction import resolve_tangent_arc_directions
        changes.extend(resolve_tangent_arc_directions(step,source_text))
        source_points = list(re.finditer(_POINT, source_text))
        repeated_center = (len(source_points) >= 2
            and len({tuple(float(v) for v in p.groups()) for p in source_points}) == 1
            and all(re.search(r'中心(?:在|为|是)?\s*$', source_text[max(0,p.start()-12):p.start()])
                for p in source_points))
        fixed_source=bool(re.search(r'控制点|顶点|端点|起点|终点|边长|(?:线段|直线|直墙)[^，。；;\n]{0,16}(?:长|长度)',source_text)
            or (len(source_points)>=2 and not repeated_center))
        if not fixed_source:
            # In a declared continuous path, an arc endpoint is determined
            # analytically; the adjoining free line endpoint is a variable.
            # Never add a connector, change an arc or override user points.
            tolerance=ConstructionPoint.model_validate({'x':step.get('connection_tolerance',1e-6),'y':0}).x
            pairs=[(i-1,i) for i in range(1,len(segments))]
            if step.get('op')=='add_composite_path' and step.get('closed') and len(segments)>1:
                pairs.append((len(segments)-1,0))
            for previous,current in pairs:
                left,right=segments[previous],segments[current]
                if left.get('kind')=='line' and right.get('kind')=='arc':
                    line,key,arc_segment,index=left,'end',right,previous
                elif left.get('kind')=='arc' and right.get('kind')=='line':
                    line,key,arc_segment,index=right,'start',left,current
                else:continue
                from .cad_construction import CompositeArcSegment
                arc=CompositeArcSegment.model_validate(arc_segment)
                if math.isclose(arc.start_angle,arc.end_angle,rel_tol=0,abs_tol=1e-12):continue
                anchor=endpoint(arc_segment,end=key=='start')
                old=endpoint(line,end=key=='end')
                if old is None or anchor is None:continue
                gap=math.dist((old['x'],old['y']),(anchor['x'],anchor['y']))
                if gap>tolerance:
                    line[key]=deepcopy(anchor)
                    changes.append({'kind':'bind_free_line_to_arc_endpoint','step_id':step.get('step_id'),
                        'segment_index':index,'endpoint':key,'from':old,'to':deepcopy(anchor),
                        'gap_in_plan_units':gap,'arc_parameters_preserved':True})
        if len(segments)>1:
            from .cad_construction import CompositeArcSegment
            tolerance=ConstructionPoint.model_validate({'x':step.get('connection_tolerance',1e-6),'y':0}).x
            kept=[];removed=[]
            for index,segment in enumerate(segments):
                if segment.get('kind')!='arc':kept.append(segment);continue
                arc=CompositeArcSegment.model_validate(segment)
                if not math.isclose(arc.start_angle,arc.end_angle,rel_tol=0,abs_tol=1e-12):
                    kept.append(segment);continue
                point=endpoint(segment,end=False);neighbors=[]
                if index>0 or step.get('closed'):neighbors.append(endpoint(segments[index-1],end=True))
                if index+1<len(segments) or step.get('closed'):neighbors.append(endpoint(segments[(index+1)%len(segments)],end=False))
                if neighbors and all(p is not None and math.dist((point['x'],point['y']),(p['x'],p['y']))<=tolerance for p in neighbors):
                    removed.append(index)
                else:kept.append(segment)
            if kept and removed:
                step['segments']=segments=kept
                changes.append({'kind':'remove_connected_zero_sweep_arc','step_id':step.get('step_id'),
                    'segment_indices':removed,'geometry_preserved':True})
        if (len(segments)>1 and all(s.get('kind')=='arc' for s in segments)
                and not re.search(r'顺时针|逆时针',source_text)):
            # Traversal direction is not geometry. Resolve an existing arc
            # chain by endpoint equality; never move a centre or infer angles.
            tolerance=ConstructionPoint.model_validate({'x':step.get('connection_tolerance',1e-6),'y':0}).x
            def reversed_arc(segment):
                result=deepcopy(segment)
                result['start_angle'],result['end_angle']=segment['end_angle'],segment['start_angle']
                result['clockwise']=not segment.get('clockwise',False)
                return result
            for reverse_first in (False,True):
                chain=[reversed_arc(segments[0]) if reverse_first else deepcopy(segments[0])]
                for segment in segments[1:]:
                    end=endpoint(chain[-1],end=True)
                    options=[s for s in (deepcopy(segment),reversed_arc(segment))
                        if end is not None and endpoint(s,end=False) is not None
                        and math.dist((end['x'],end['y']),tuple(endpoint(s,end=False)[k] for k in ('x','y')))<=tolerance]
                    if len(options)!=1:break
                    chain.append(options[0])
                if len(chain)!=len(segments):continue
                if step.get('closed'):
                    first,last=endpoint(chain[0],end=False),endpoint(chain[-1],end=True)
                    if math.dist((first['x'],first['y']),(last['x'],last['y']))>tolerance:continue
                if chain!=segments:
                    changes.append({'kind':'orient_existing_arc_chain','step_id':step.get('step_id'),
                        'geometry_preserved':True})
                    step['segments']=segments=chain
                break
        if (step.get('continuity') == 'C1'
                and not re.search(r'(?:平滑|切向连续|\bC1\b)', source_text, re.I)):
            step['continuity'] = 'C0'
            changes.append({'kind': 'remove_unrequested_c1_assumption',
                            'step_id': step.get('step_id')})
        for index in range(1, len(segments)):
            previous = endpoint(segments[index - 1], end=True)
            current = endpoint(segments[index], end=False)
            points = segments[index].get('control_points') if isinstance(segments[index], dict) else None
            if not previous or not current or not isinstance(points, list) or len(points) != 3:
                continue
            if math.hypot(float(previous['x']) - float(current['x']),
                          float(previous['y']) - float(current['y'])) > float(step.get('connection_tolerance', 0.000001)):
                points.insert(0, deepcopy(previous))
                changes.append({'kind': 'complete_composite_bezier_start',
                                'step_id': step.get('step_id'), 'segment_index': index})

        vertical = None
        if re.search(r'(?:上半圆|顶部半圆|向上半圆)', source_text):
            vertical = 'upper'
        elif re.search(r'(?:下半圆|底部半圆|向下半圆)', source_text):
            vertical = 'lower'
        if vertical:
            for index, segment in enumerate(segments):
                if not isinstance(segment, dict) or segment.get('kind') != 'arc':
                    continue
                from .cad_construction import CompositeArcSegment
                arc=CompositeArcSegment.model_validate(segment)
                start,end=arc.start_angle,arc.end_angle
                ccw = (end - start) % 360.0
                cw = (start - end) % 360.0
                if not (math.isclose(ccw, 180.0, abs_tol=1e-6) and math.isclose(cw, 180.0, abs_tol=1e-6)):
                    continue
                ccw_mid_y = math.sin(math.radians(start + ccw / 2))
                want_clockwise = (vertical == 'upper' and ccw_mid_y < 0) or (vertical == 'lower' and ccw_mid_y > 0)
                if bool(segment.get('clockwise')) != want_clockwise:
                    segment['clockwise'] = want_clockwise
                    changes.append({'kind': 'bind_semicircle_orientation',
                                    'step_id': step.get('step_id'), 'segment_index': index,
                                    'orientation': vertical})
        if (step.get('op') == 'add_composite_path' and not fixed_source
                and not plan.get('constraints')
                and re.search(r'平滑|切向连续|\bC1\b', source_text, re.I)
                and not re.search(r'参数式|函数|\b[xy]\s*=|尖点|保留.{0,8}尖角|cusp', source_text, re.I)
                and not any(j.get('intent') not in {None, 'smooth'} for j in step.get('junction_constraints', []))):
            changes.extend(_align_free_cubic_joints(step))
    return (repaired, changes) if changes else (payload, [])


def _align_free_cubic_joints(step: dict[str, Any]) -> list[dict[str, Any]]:
    """Project free handles onto a shared derivative; preserve all endpoints.

    This is only a proposed coordinate correction. The caller still executes
    the full plan and all independent source, shape and topology acceptance.
    Opposite or degenerate tangents have no uniquely defined direction here.
    """
    from .cad_construction import AddCompositePathStep, _composite_continuity
    try:
        measured = _composite_continuity(AddCompositePathStep.model_validate(step))
    except ValueError:
        return []
    changes = []
    for joint in measured['failed_joints']:
        left = step['segments'][joint['left_segment_index']]
        right = step['segments'][joint['right_segment_index']]
        if not all(s.get('kind') == 'bezier' and len(s.get('control_points', [])) == 4 for s in (left, right)):
            continue
        lp, rp = left['control_points'], right['control_points']
        points = [ConstructionPoint.model_validate(p) for p in (lp[-2], lp[-1], rp[0], rp[1])]
        a, end, start, b = points
        if math.dist((end.x, end.y), (start.x, start.y)) > 1e-12:
            continue
        u, v = (end.x-a.x, end.y-a.y), (b.x-start.x, b.y-start.y)
        if min(math.hypot(*u), math.hypot(*v)) <= 1e-12:
            continue
        mean = tuple((x+y)/2 for x, y in zip(u, v))
        if math.hypot(*mean) <= 1e-12 or any(sum(x*y for x, y in zip(mean, t)) <= 0 for t in (u, v)):
            continue
        before = [deepcopy(lp[-2]), deepcopy(rp[1])]
        lp[-2] = {'x': end.x-mean[0], 'y': end.y-mean[1]}
        rp[1] = {'x': start.x+mean[0], 'y': start.y+mean[1]}
        changes.append({'kind': 'align_free_cubic_joint', 'step_id': step['step_id'],
            'junction_index': joint['junction_index'], 'measurement_before': joint,
            'handles_before': before, 'handles_after': [deepcopy(lp[-2]), deepcopy(rp[1])],
            'endpoints_preserved': True, 'segments_preserved': True})
    return changes


def _scale_area_step(step: dict[str, Any], factor: float) -> bool:
    op = step.get("op")
    if op in {"add_polyline", "add_spline"}:
        return _scale_points_about_centroid(step.get("vertices") or step.get("control_points"), factor)
    if op == "add_composite_path":
        points: list[dict[str, Any]] = []
        for segment in step.get("segments") or []:
            if not isinstance(segment, dict):
                return False
            if segment.get("kind") == "line":
                points.extend([segment.get("start"), segment.get("end")])
            else:
                points.extend(segment.get("control_points") or [])
        return _scale_points_about_centroid(points, factor)
    if op in {"add_circle", "add_arc"} and isinstance(step.get("radius"), (int, float)):
        step["radius"] *= factor
        return True
    if op == "add_ellipse" and all(isinstance(step.get(key), (int, float)) for key in ("major_radius", "minor_radius")):
        step["major_radius"] *= factor
        step["minor_radius"] *= factor
        return True
    if op in {"add_rectangle", "add_centered_rectangle"} and all(isinstance(step.get(key), (int, float)) for key in ("width", "height")):
        step["width"] *= factor
        step["height"] *= factor
        return True
    return False


def _scale_points_about_centroid(points: Any, factor: float) -> bool:
    if not isinstance(points, list) or not points or not all(
        isinstance(point, dict) and isinstance(point.get("x"), (int, float)) and isinstance(point.get("y"), (int, float))
        for point in points
    ):
        return False
    center_x = sum(float(point["x"]) for point in points) / len(points)
    center_y = sum(float(point["y"]) for point in points) / len(points)
    for point in points:
        point["x"] = center_x + (float(point["x"]) - center_x) * factor
        point["y"] = center_y + (float(point["y"]) - center_y) * factor
    return True


def _normalize_u_shape(source_text: str) -> list[str]:
    if not re.search(r"U\s*形", source_text, re.IGNORECASE):
        return []
    left_bottom = _named_point(source_text, "左下角")
    right_bottom = _named_point(source_text, "右下角")
    top_match = re.search(
        rf"两侧墙顶端分别为\s*{_POINT}\s*和\s*{_POINT}", source_text,
    )
    if left_bottom is None or right_bottom is None or top_match is None:
        return []
    left_top = _point(top_match.group(1), top_match.group(2))
    right_top = _point(top_match.group(3), top_match.group(4))
    facts = [
        "U形开放边界：使用一条不闭合多段线，顶点顺序为"
        f"({_format_number(left_top['x'])},{_format_number(left_top['y'])}) -> "
        f"({_format_number(left_bottom['x'])},{_format_number(left_bottom['y'])}) -> "
        f"({_format_number(right_bottom['x'])},{_format_number(right_bottom['y'])}) -> "
        f"({_format_number(right_top['x'])},{_format_number(right_top['y'])})，closed=false。"
    ]
    columns = re.search(
        rf"沿左右两侧各布置\s*(\d+)\s*根半径\s*({_NUMBER})\s*({_UNIT})",
        source_text,
    )
    if not columns:
        return facts
    count = int(columns.group(1))
    radius = _to_m(columns.group(2), columns.group(3))
    if count < 1:
        return facts
    low_y = max(left_bottom["y"], right_bottom["y"]) + radius
    high_y = min(left_top["y"], right_top["y"]) - radius
    if high_y < low_y:
        return facts
    ys = [
        (low_y + (high_y - low_y) * index / (count - 1)) if count > 1 else (low_y + high_y) / 2
        for index in range(count)
    ]
    left_x = min(left_bottom["x"], left_top["x"]) + radius
    right_x = max(right_bottom["x"], right_top["x"]) - radius
    y_text = ", ".join(_format_number(value) for value in ys)
    facts.append(
        "对称柱列规范化约定：柱心向厂房内部离墙一个半径，"
        f"左列x={_format_number(left_x)}米，右列x={_format_number(right_x)}米，"
        f"两列共同y坐标=[{y_text}]米；共{count * 2}个独立具名圆。"
    )
    return facts


def _named_point(text: str, label: str) -> dict[str, float] | None:
    match = re.search(rf"{label}\s*{_POINT}", text)
    return _point(match.group(1), match.group(2)) if match else None


def _format_number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def repair_construction_references_once(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Repair only references that resolve unambiguously inside one plan.

    The repair never creates geometry, changes dimensions or guesses a target.
    A multi-target alias is accepted only for an ``entity_count`` assertion
    whose requested total exactly equals the statically predicted entity count;
    that aggregate assertion is then expanded into one assertion per output.
    """
    if not isinstance(payload, dict):
        return payload, []
    repaired = deepcopy(payload)
    plan = repaired.get("plan")
    if not isinstance(plan, dict):
        return repaired, []
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        return repaired, []

    records = _construction_reference_records(steps)
    known_refs = {record["output_ref"] for record in records}
    from .cad_plan_references import plan_reference_catalog
    explicit_refs, _ = plan_reference_catalog(steps)
    known_refs.update(explicit_refs)
    repairs: list[dict[str, Any]] = []
    # Preserve misplaced assertions verbatim only when no plan value competes.
    if isinstance(repaired.get("assertions"), list) and not plan.get("assertions"):
        plan["assertions"] = repaired.pop("assertions")
        repairs.append({"kind": "move_assertions_to_plan", "count": len(plan["assertions"])})

    # Array sources can only be repaired when exactly one existing output is
    # named by the alias. Group aliases are not valid array sources.
    for step in steps:
        if not isinstance(step, dict) or step.get("op") != "rectangular_array":
            continue
        source_ref = step.get("source_ref")
        if not isinstance(source_ref, str) or source_ref in known_refs:
            continue
        matches = _matching_output_refs(source_ref, records)
        if len(matches) == 1:
            step["source_ref"] = matches[0]
            repairs.append({
                "kind": "source_ref_alias",
                "from": source_ref,
                "to": matches[0],
                "step_id": step.get("step_id"),
            })

    # Binary constraints describe a relation between two different outputs.
    # Normalize unambiguous aliases exactly as assertions are normalized.  A
    # constraint that resolves both ends to the same output is a no-op (and is
    # rejected by the strict IR), so remove only that constraint while keeping
    # every geometry step and assertion intact.  This is schema repair, not a
    # geometric fallback.
    constraints = plan.get("constraints")
    if isinstance(constraints, list):
        repaired_constraints: list[Any] = []
        for constraint in constraints:
            if not isinstance(constraint, dict):
                repaired_constraints.append(constraint)
                continue
            updated = deepcopy(constraint)
            for field in ("target_ref", "reference_ref"):
                value = updated.get(field)
                if not isinstance(value, str) or value in known_refs:
                    continue
                matches = _matching_output_refs(value, records)
                if len(matches) == 1:
                    updated[field] = matches[0]
                    repairs.append({
                        "kind": "constraint_ref_alias",
                        "field": field,
                        "from": value,
                        "to": matches[0],
                        "constraint_id": constraint.get("constraint_id"),
                    })
            target = updated.get("target_ref")
            reference = updated.get("reference_ref")
            if (isinstance(target, str) and isinstance(reference, str)
                    and target == reference and target in known_refs):
                repairs.append({
                    "kind": "remove_self_referential_constraint",
                    "constraint_id": constraint.get("constraint_id"),
                    "constraint_kind": constraint.get("kind"),
                    "target_ref": target,
                })
                continue
            repaired_constraints.append(updated)
        plan["constraints"] = repaired_constraints

    # Binary assertion and layout references use the same symbol table as
    # unary assertion targets. Resolve only an exact, unambiguous alias;
    # unknown or ambiguous names remain invalid for the common compiler.
    for group, fields in (("assertions", ("reference_ref",)),
                          ("free_outline_layout", ("target_ref", "right_of_ref"))):
        for relation in plan.get(group) or []:
            if not isinstance(relation, dict):
                continue
            for field in fields:
                value = relation.get(field)
                if not isinstance(value, str) or value in known_refs:
                    continue
                matches = _matching_output_refs(value, records)
                if len(matches) == 1:
                    relation[field] = matches[0]
                    repairs.append({"kind": "relation_ref_alias", "group": group,
                                    "field": field, "from": value, "to": matches[0]})

    predicted_counts = _predicted_output_counts(steps)
    steps_by_ref = {
        str(step.get("output_ref")): step
        for step in steps
        if isinstance(step, dict) and step.get("output_ref")
    }
    diagnostic_trial = _trial_plan_without_assertions(plan)
    assertions = plan.get("assertions")
    if not isinstance(assertions, list):
        return repaired, repairs
    repaired_assertions: list[Any] = []
    for assertion in assertions:
        if not isinstance(assertion, dict):
            repaired_assertions.append(assertion)
            continue
        target_ref = assertion.get("target_ref")
        kind = assertion.get("kind")
        if (
            kind == "closed"
            and isinstance(target_ref, str)
            and _target_is_provably_open(target_ref, steps)
        ):
            repairs.append({
                "kind": "remove_inapplicable_closed_assertion",
                "from": target_ref,
                "to": None,
                "assertion_id": assertion.get("assertion_id"),
            })
            continue
        expected = assertion.get("equals")
        target_step = steps_by_ref.get(str(target_ref))
        vertices = (
            target_step.get("vertices")
            if isinstance(target_step, dict)
            and target_step.get("op") == "add_polyline"
            else None
        )
        if (
            kind == "entity_count"
            and isinstance(target_ref, str)
            and target_ref in known_refs
            and isinstance(expected, int)
            and isinstance(vertices, list)
            and expected == len(vertices)
            and predicted_counts.get(target_ref) == 1
            and expected != 1
        ):
            # Models sometimes use entity_count as a vertex-count assertion.
            # The polyline step already contains and validates every vertex;
            # remove only the semantically invalid assertion instead of
            # changing geometry or inventing a new primitive-specific rule.
            repairs.append({
                "kind": "remove_polyline_vertex_count_misuse",
                "from": expected,
                "to": None,
                "target_ref": target_ref,
                "assertion_id": assertion.get("assertion_id"),
            })
            continue
        if (
            kind == "entity_count"
            and target_ref is None
            and isinstance(expected, int)
            and sum(predicted_counts.values()) != expected
        ):
            named_matches = _matching_assertion_output_refs(
                str(assertion.get("assertion_id") or ""), records,
            )
            named_counts = [predicted_counts.get(value) for value in named_matches]
            if (
                named_matches
                and all(isinstance(value, int) for value in named_counts)
                and sum(named_counts) == expected
            ):
                base_id = str(assertion.get("assertion_id") or "entity-count")
                for index, (match, count) in enumerate(
                    zip(named_matches, named_counts), start=1,
                ):
                    repaired_assertions.append({
                        **deepcopy(assertion),
                        "assertion_id": f"{base_id[:54]}-{index}",
                        "target_ref": match,
                        "equals": count,
                    })
                repairs.append({
                    "kind": "named_assertion_group_binding",
                    "from": None,
                    "to": named_matches,
                    "assertion_id": assertion.get("assertion_id"),
                })
                continue
        if not isinstance(target_ref, str) or target_ref in known_refs:
            updated = _repair_assertion_scope_or_rotated_bounds(
                assertion, plan, steps, diagnostic_trial,
            )
            repaired_assertions.append(updated)
            if updated != assertion:
                repairs.append({
                    "kind": (
                        "rotated_bounds_normalization"
                        if updated.get("target_ref") == assertion.get("target_ref")
                        else "aggregate_assertion_scope"
                    ),
                    "from": assertion.get("target_ref"),
                    "to": updated.get("target_ref"),
                    "assertion_id": assertion.get("assertion_id"),
                })
            continue
        global_alias = _reference_key(target_ref) in {
            "all", "allentities", "allobjects", "全部", "所有", "全部图元", "所有图元",
        }
        total_predicted = sum(predicted_counts.values())
        if (
            assertion.get("kind") == "entity_count"
            and global_alias
            and isinstance(expected, int)
            and len(predicted_counts) == len(records)
            and total_predicted == expected
        ):
            updated = deepcopy(assertion)
            updated["target_ref"] = None
            repaired_assertions.append(updated)
            repairs.append({
                "kind": "global_target_alias",
                "from": target_ref,
                "to": None,
                "assertion_id": assertion.get("assertion_id"),
            })
            continue
        matches = _matching_output_refs(target_ref, records)
        if len(matches) == 1:
            updated = deepcopy(assertion)
            updated["target_ref"] = matches[0]
            repaired_assertions.append(updated)
            repairs.append({
                "kind": "target_ref_alias",
                "from": target_ref,
                "to": matches[0],
                "assertion_id": assertion.get("assertion_id"),
            })
            continue
        counts = [predicted_counts.get(value) for value in matches]
        if (
            assertion.get("kind") == "entity_count"
            and matches
            and isinstance(expected, int)
            and all(isinstance(value, int) for value in counts)
            and sum(counts) == expected
        ):
            base_id = str(assertion.get("assertion_id") or "entity-count")
            for index, (match, count) in enumerate(zip(matches, counts), start=1):
                repaired_assertions.append({
                    **deepcopy(assertion),
                    "assertion_id": f"{base_id[:54]}-{index}",
                    "target_ref": match,
                    "equals": count,
                })
            repairs.append({
                "kind": "target_ref_group_expansion",
                "from": target_ref,
                "to": matches,
                "assertion_id": assertion.get("assertion_id"),
            })
            continue
        repaired_assertions.append(assertion)
    plan["assertions"] = repaired_assertions
    return repaired, repairs


def _trial_plan_without_assertions(
    plan: dict[str, Any],
) -> dict[str, Any] | None:
    candidate = deepcopy(plan)
    candidate["assertions"] = []
    try:
        return execute_construction_plan(CadConstructionPlan.model_validate(candidate))
    except Exception:
        return None


def _target_is_provably_open(target_ref: str, steps: list[Any]) -> bool:
    for step in steps:
        if not isinstance(step, dict) or step.get("output_ref") != target_ref:
            continue
        if step.get("op") == "add_line":
            return True
        if step.get("op") == "add_polyline" and step.get("closed") is not True:
            return True
    return False


def _repair_assertion_scope_or_rotated_bounds(
    assertion: dict[str, Any],
    plan: dict[str, Any],
    steps: list[Any],
    trial: dict[str, Any] | None,
) -> dict[str, Any]:
    if trial is None:
        return assertion
    kind = assertion.get("kind")
    target_ref = assertion.get("target_ref")
    if kind == "bounds_size" and target_ref is None:
        return _repair_global_centered_rectangle_bounds(
            assertion, plan, steps, trial,
        )
    if not isinstance(target_ref, str):
        return assertion
    symbol_table = trial.get("symbol_table")
    geometries = trial.get("geometries")
    if not isinstance(symbol_table, dict) or not isinstance(geometries, list):
        return assertion
    target_ids = symbol_table.get(target_ref)
    if not isinstance(target_ids, list):
        return assertion
    selected = [item for item in geometries if item.get("id") in target_ids]
    if kind == "entity_count":
        expected = assertion.get("equals")
        if (
            isinstance(expected, int)
            and len(selected) != expected
            and len(geometries) == expected
        ):
            return {**deepcopy(assertion), "target_ref": None}
        return assertion
    if kind != "bounds_size":
        return assertion
    expected_width = assertion.get("width")
    expected_height = assertion.get("height")
    tolerance = float(assertion.get("tolerance", 0.001))
    if not isinstance(expected_width, (int, float)) or not isinstance(
        expected_height, (int, float)
    ):
        return assertion
    scale = 1000.0 if plan.get("units", "m") == "m" else 1.0
    target_size = _construction_size(selected, scale)
    if _size_matches(target_size, expected_width, expected_height, tolerance):
        return assertion
    global_size = _construction_size(geometries, scale)
    if _size_matches(global_size, expected_width, expected_height, tolerance):
        return {**deepcopy(assertion), "target_ref": None}
    step = next(
        (
            value for value in steps
            if isinstance(value, dict) and value.get("output_ref") == target_ref
        ),
        None,
    )
    if (
        isinstance(step, dict)
        and step.get("op") in {"add_rectangle", "add_centered_rectangle"}
        and not _near(float(step.get("rotation_deg", 0.0)) % 180.0, 0.0, tolerance)
        and _near(float(step.get("width", -1.0)), float(expected_width), tolerance)
        and _near(float(step.get("height", -1.0)), float(expected_height), tolerance)
        and target_size is not None
    ):
        return {
            **deepcopy(assertion),
            "width": target_size[0],
            "height": target_size[1],
        }
    return assertion


def _repair_global_centered_rectangle_bounds(
    assertion: dict[str, Any],
    plan: dict[str, Any],
    steps: list[Any],
    trial: dict[str, Any],
) -> dict[str, Any]:
    """Repair a global bound only when one centered frame proves that bound.

    This is intentionally narrower than replacing an arbitrary assertion with
    trial output: every other generated entity must remain inside the single
    centered rectangle, so the frame alone determines the global extent.
    """
    centered_steps = [
        step for step in steps
        if isinstance(step, dict) and step.get("op") == "add_centered_rectangle"
    ]
    if len(centered_steps) != 1:
        return assertion
    symbol_table = trial.get("symbol_table")
    geometries = trial.get("geometries")
    if not isinstance(symbol_table, dict) or not isinstance(geometries, list):
        return assertion
    output_ref = centered_steps[0].get("output_ref")
    frame_ids = symbol_table.get(output_ref)
    if not isinstance(frame_ids, list):
        return assertion
    frame = [item for item in geometries if item.get("id") in frame_ids]
    scale = 1000.0 if plan.get("units", "m") == "m" else 1.0
    frame_size = _construction_size(frame, scale)
    global_size = _construction_size(geometries, scale)
    if frame_size is None or global_size is None:
        return assertion
    proof_tolerance = 1e-6
    if not _size_matches(
        global_size, frame_size[0], frame_size[1], proof_tolerance,
    ):
        return assertion
    expected_width = assertion.get("width")
    expected_height = assertion.get("height")
    tolerance = float(assertion.get("tolerance", 0.001))
    if not isinstance(expected_width, (int, float)) or not isinstance(
        expected_height, (int, float)
    ):
        return assertion
    if _size_matches(global_size, expected_width, expected_height, tolerance):
        return assertion
    return {
        **deepcopy(assertion),
        "width": global_size[0],
        "height": global_size[1],
    }


def _construction_size(
    geometries: list[dict[str, Any]], scale: float,
) -> tuple[float, float] | None:
    if not geometries:
        return None
    try:
        bounds = construction_geometry_bounds(geometries)
    except ConstructionPlanError:
        return None
    return (
        (bounds["max_x"] - bounds["min_x"]) / scale,
        (bounds["max_y"] - bounds["min_y"]) / scale,
    )


def _size_matches(
    actual: tuple[float, float] | None,
    width: float,
    height: float,
    tolerance: float,
) -> bool:
    return actual is not None and _near(actual[0], width, tolerance) and _near(
        actual[1], height, tolerance,
    )


def _near(left: float, right: float, tolerance: float) -> bool:
    return abs(left - right) <= max(tolerance, 1e-9)


def _construction_reference_records(
    steps: list[Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        output_ref = step.get("output_ref")
        if not isinstance(output_ref, str) or not output_ref:
            continue
        semantic = step.get("semantic") if isinstance(step.get("semantic"), dict) else {}
        aliases = [output_ref]
        for key in ("object_id", "object_type", "label", "role"):
            value = semantic.get(key)
            if isinstance(value, str) and value:
                aliases.append(value)
        records.append({"output_ref": output_ref, "aliases": aliases})
    return records


def _reference_key(value: str, *, remove_index: bool = False) -> str:
    normalized = "".join(char for char in value.casefold() if char.isalnum())
    return re.sub(r"\d+$", "", normalized) if remove_index else normalized


def _matching_output_refs(
    target_ref: str, records: list[dict[str, Any]],
) -> list[str]:
    target = _reference_key(target_ref)
    target_stem = _reference_key(target_ref, remove_index=True)
    if not target:
        return []
    exact = [
        record["output_ref"] for record in records
        if any(_reference_key(alias) == target for alias in record["aliases"])
    ]
    if exact:
        return list(dict.fromkeys(exact))
    if len(target_stem) < 3:
        return []
    grouped = [
        record["output_ref"] for record in records
        if any(
            _reference_key(alias, remove_index=True) == target_stem
            or _reference_key(alias, remove_index=True).startswith(target_stem)
            for alias in record["aliases"]
        )
    ]
    return list(dict.fromkeys(grouped))


def _matching_assertion_output_refs(
    assertion_id: str, records: list[dict[str, Any]],
) -> list[str]:
    tokens = [
        _reference_key(value)
        for value in re.split(r"[^A-Za-z0-9\u4e00-\u9fff]+", assertion_id)
        if value
    ]
    ignored = {
        "assert", "assertion", "entity", "entities", "count", "number",
        "total", "check", "数量", "计数", "断言", "检查", "总数",
    }
    tokens = [value for value in tokens if value not in ignored and len(value) >= 2]
    if not tokens:
        return []
    matches = [
        record["output_ref"] for record in records
        if any(
            all(token in _reference_key(alias) for token in tokens)
            for alias in record["aliases"]
        )
    ]
    return list(dict.fromkeys(matches))


def _predicted_output_counts(steps: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for step in steps:
        if not isinstance(step, dict):
            continue
        output_ref = step.get("output_ref")
        if not isinstance(output_ref, str) or not output_ref:
            continue
        if step.get("op") != "rectangular_array":
            counts[output_ref] = 1
            continue
        source_count = counts.get(str(step.get("source_ref") or ""))
        rows, columns = step.get("rows"), step.get("columns")
        if not all(isinstance(value, int) for value in (source_count, rows, columns)):
            continue
        placements = rows * columns
        if not bool(step.get("include_source", False)):
            placements -= 1
        counts[output_ref] = source_count * max(placements, 0)
    return counts


def parse_rule_construction_plan(source_text: str) -> CadConstructionPlan | None:
    """Parse explicit primitive construction sentences without guessing.

    Supported primitives are line, rectangle, circle, arc, ellipse and
    polyline. Multiple clauses may be combined with Chinese punctuation.
    """
    if not any(marker in source_text for marker in _CONSTRUCTION_MARKERS):
        return None
    from .cad_axis_requirements import ellipse_axes
    axes = ellipse_axes(source_text)
    if axes['status']=='complete' and axes['full_source']:
        values=axes['dimensions'];center=axes['center_m'] or [0,0]
        return CadConstructionPlan.model_validate({'units':'m','steps':[{
            'op':'add_ellipse','step_id':'step-1','output_ref':'ellipse',
            'semantic':{'label':'椭圆'},'center':{'x':center[0],'y':center[1]},
            'major_radius':values['major_radius_m'],'minor_radius':values['minor_radius_m'],
            'rotation_deg':axes['rotation_deg'] or 0}]})
    clauses = [
        value.strip() for value in re.split(r"[；;。\n]+", source_text)
        if value.strip()
    ]
    steps: list[dict[str, Any]] = []
    assertions: list[dict[str, Any]] = []
    for clause in clauses:
        parsed = _parse_clause(clause, len(steps) + 1)
        if parsed is None:
            return None
        step, clause_assertions = parsed
        steps.append(step)
        assertions.extend(clause_assertions)
    if not steps:
        return None
    return CadConstructionPlan.model_validate({
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": steps,
        "assertions": assertions,
        "budgets": {"max_steps": 100, "max_entities": 500},
    })


def _parse_clause(
    clause: str, index: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    if not any(marker in clause for marker in _CONSTRUCTION_MARKERS):
        return None
    base = {
        "step_id": f"step-{index}",
        "output_ref": f"shape-{index}",
        "layer_id": 1,
    }
    label = _label_for_clause(clause, index)
    semantic = {"object_type": _object_type(clause), "label": label}
    assertions: list[dict[str, Any]] = []

    line = re.search(rf"(?:线段|直线).*?(?:从|起点)\s*{_POINT}.*?(?:到|至|终点)\s*{_POINT}", clause)
    if line:
        return ({
            **base, "op": "add_line", "semantic": semantic,
            "start": _point(line.group(1), line.group(2)),
            "end": _point(line.group(3), line.group(4)),
        }, assertions)

    rectangle = (
        re.search(
            rf"(?:矩形|长方形).*?(?:宽|宽度)\s*({_NUMBER})\s*({_UNIT}).*?"
            rf"(?:高|高度|长)\s*({_NUMBER})\s*({_UNIT})",
            clause, re.IGNORECASE,
        )
        or re.search(
            rf"(?:宽|宽度)\s*({_NUMBER})\s*({_UNIT}).*?"
            rf"(?:高|高度|长)\s*({_NUMBER})\s*({_UNIT}).*?(?:矩形|长方形)",
            clause, re.IGNORECASE,
        )
    )
    if rectangle and any(value in clause for value in ("矩形", "长方形")):
        width = _to_m(rectangle.group(1), rectangle.group(2))
        height = _to_m(rectangle.group(3), rectangle.group(4))
        rotation = _angle(clause, "旋转") or 0.0
        center = _first_point_after(clause, ("几何中心", "中心点", "中心"))
        if center is not None:
            step = {
                **base, "op": "add_centered_rectangle", "semantic": semantic,
                "center": center, "width": width, "height": height,
                "rotation_deg": rotation,
            }
        else:
            origin = _first_point_after(
                clause, ("左下角", "原点", "起点")
            ) or {"x": 0.0, "y": 0.0}
            step = {
                **base, "op": "add_rectangle", "semantic": semantic,
                "origin": origin, "width": width, "height": height,
                "rotation_deg": rotation,
            }
        bounds_width, bounds_height = _rotated_rectangle_bounds(
            width, height, rotation,
        )
        assertions.extend([
            {"kind": "bounds_size", "assertion_id": f"size-{index}",
             "target_ref": base["output_ref"], "width": bounds_width,
             "height": bounds_height},
            {"kind": "closed", "assertion_id": f"closed-{index}",
             "target_ref": base["output_ref"]},
        ])
        return step, assertions

    arc = re.search(
        rf"(?:圆弧|弧线).*?(?:圆心|中心)\s*{_POINT}.*?半径\s*({_NUMBER})\s*({_UNIT})"
        rf".*?起始角\s*({_NUMBER})\s*度.*?终止角\s*({_NUMBER})\s*度",
        clause, re.IGNORECASE,
    )
    if arc:
        return ({
            **base, "op": "add_arc", "semantic": semantic,
            "center": _point(arc.group(1), arc.group(2)),
            "radius": _to_m(arc.group(3), arc.group(4)),
            "start_angle": float(arc.group(5)), "end_angle": float(arc.group(6)),
        }, assertions)

    circle = re.search(
        rf"(?:圆形|圆)(?!弧).*?(?:圆心|中心)\s*{_POINT}.*?半径\s*({_NUMBER})\s*({_UNIT})",
        clause, re.IGNORECASE,
    )
    circle_reversed = re.search(
        rf"(?:圆形|圆)(?!弧).*?半径\s*({_NUMBER})\s*({_UNIT}).*?(?:圆心|中心)\s*{_POINT}",
        clause, re.IGNORECASE,
    )
    if circle:
        return ({
            **base, "op": "add_circle", "semantic": semantic,
            "center": _point(circle.group(1), circle.group(2)),
            "radius": _to_m(circle.group(3), circle.group(4)),
        }, [{"kind": "closed", "assertion_id": f"closed-{index}",
             "target_ref": base["output_ref"]}])
    if circle_reversed:
        return ({
            **base, "op": "add_circle", "semantic": semantic,
            "center": _point(circle_reversed.group(3), circle_reversed.group(4)),
            "radius": _to_m(circle_reversed.group(1), circle_reversed.group(2)),
        }, [{"kind": "closed", "assertion_id": f"closed-{index}",
             "target_ref": base["output_ref"]}])

    ellipse = re.search(
        rf"(?:椭圆).*?(?:中心|圆心)\s*{_POINT}.*?长半轴\s*({_NUMBER})\s*({_UNIT})"
        rf".*?短半轴\s*({_NUMBER})\s*({_UNIT})",
        clause, re.IGNORECASE,
    )
    if ellipse:
        return ({
            **base, "op": "add_ellipse", "semantic": semantic,
            "center": _point(ellipse.group(1), ellipse.group(2)),
            "major_radius": _to_m(ellipse.group(3), ellipse.group(4)),
            "minor_radius": _to_m(ellipse.group(5), ellipse.group(6)),
            "rotation_deg": _angle(clause, "旋转") or 0.0,
        }, [{"kind": "closed", "assertion_id": f"closed-{index}",
             "target_ref": base["output_ref"]}])

    if any(value in clause for value in ("多段线", "折线", "轮廓")):
        points = [
            _point(x, y) for x, y in re.findall(_POINT, clause)
        ]
        if len(points) < 2:
            return None
        closed = any(value in clause for value in ("闭合", "封闭", "轮廓"))
        step = {
            **base, "op": "add_polyline", "semantic": semantic,
            "vertices": points, "closed": closed,
        }
        if closed:
            assertions.append({"kind": "closed", "assertion_id": f"closed-{index}",
                               "target_ref": base["output_ref"]})
        return step, assertions
    return None


def _to_m(number: str, unit: str) -> float:
    scale = length_factors('m', float_values=True)
    return float(number) * scale[unit.lower()]


def _rotated_rectangle_bounds(
    width: float, height: float, rotation_deg: float,
) -> tuple[float, float]:
    angle = math.radians(rotation_deg)
    cos_a = abs(math.cos(angle))
    sin_a = abs(math.sin(angle))
    return (
        width * cos_a + height * sin_a,
        width * sin_a + height * cos_a,
    )


def _point(x: str, y: str) -> dict[str, float]:
    return {"x": float(x), "y": float(y)}


def _first_point_after(text: str, markers: tuple[str, ...]) -> dict[str, float] | None:
    for marker in markers:
        match = re.search(rf"{marker}\s*(?:在|为|是)?\s*{_POINT}", text)
        if match:
            return _point(match.group(1), match.group(2))
    return None


def _angle(text: str, marker: str) -> float | None:
    match = re.search(rf"{marker}\s*({_NUMBER})\s*度", text)
    return float(match.group(1)) if match else None


def _label_for_clause(clause: str, index: int) -> str:
    for value in ("矩形", "长方形", "圆弧", "椭圆", "圆", "多段线", "折线", "线段", "直线"):
        if value in clause:
            return f"{value}{index}"
    return f"图形{index}"


def _object_type(clause: str) -> str:
    mapping = {
        "矩形": "rectangle", "长方形": "rectangle", "圆弧": "arc",
        "椭圆": "ellipse", "圆": "circle", "多段线": "polyline",
        "折线": "polyline", "线段": "line", "直线": "line",
    }
    return next((value for key, value in mapping.items() if key in clause), "drawing_part")


def _evidence_is_grounded(source_text: str, evidence: list[str]) -> bool:
    if not evidence:
        return False
    compact = "".join(source_text.lower().split())
    return all(
        bool(value.strip()) and "".join(value.lower().split()) in compact
        for value in evidence
    )


def _failure(
    code: str, message: str, parser: str, *, clarification_required: bool = False,
) -> dict[str, Any]:
    return {
        "schema": "cad.construction-interpretation-result.v1",
        "status": "clarification_required" if clarification_required else "invalid",
        "parser": parser,
        "error": {"code": code, "message": message},
    }
