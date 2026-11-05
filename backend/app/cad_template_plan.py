"""Compile confirmed template parameters into the common construction IR."""
from copy import deepcopy
import re

from .cad_construction import CadConstructionPlan, TemplateInstanceSpec, execute_construction_plan


def template_covers_request(project, route):
    """One strategy gate for both fresh requests and confirmed projects.

    Decline additions not represented by a registered template. Standard
    component descriptions alone (centre circle, sidelines) are not additions.
    """
    from .agent_skills import recognize_drawing_template, recognize_drawing_template_set
    from .cad_structure_contract import reference_contract, explicit_composition
    from .cad_project_candidates import candidate_generation_context
    context = candidate_generation_context(project, route)
    text = context['prompt'] + '\n' + '\n'.join(context['requirements'].get('source_followups') or [])
    # Scalar template dimensions cannot encode articulated parts and joints.
    # Preserve those requirements for the general construction planner.
    if (re.search(r'(?:两|[二三四五六七八九]|\d+)\s*(?:条|个)?\s*(?:臂|分支|支臂)', text)
            and re.search(r'连接|转角|直角|夹角|分别', text)):
        return False
    legacy_components = not (recognize_drawing_template(text) or recognize_drawing_template_set(text))
    if reference_contract(text) or (explicit_composition(text) and not legacy_components):
        return False
    if not context.get('expected_template') and not context.get('template_set'):
        return False
    # Each explicitly requested additional object must itself be a template.
    additions = re.split(r'(?:再|另|额外|另外|还)(?:添加|增加|加上|画出|画|绘制|生成)|(?:添加|增加)\s*(?=[一两二三四五六七八九十\d])|[和与及]\s*(?=[一两二三四五六七八九十\d]+\s*[个条朵颗张]|画|绘制|生成)|[＋+]', text)
    for addition in additions[1:]:
        if not (recognize_drawing_template(addition) or recognize_drawing_template_set(addition)):
            return False
    # A relative placement can introduce a component without another "draw".
    for clause in re.split(r'[，,；;。\n]', text):
        if re.search(r'(?:旁边|外侧|内部|里面|上方|下方|左侧|右侧).*(?:有|放置|设置|包含)', clause):
            if not (recognize_drawing_template(clause) or recognize_drawing_template_set(clause)):
                return False
    return True


def template_plan_for_project(project, route):
    # Imported drawings are snapshots, never instructions to regenerate a template.
    if project.get("source_drawing"):
        return None
    if not template_covers_request(project, route):
        return None
    from .cad_project_candidates import candidate_generation_context
    context = candidate_generation_context(project, route)
    matches = deepcopy(context.get("template_set") or [])
    if not matches and context.get("expected_template"):
        matches = [deepcopy(context["expected_template"])]
    if not matches:
        return None
    if context.get("layout_conflicts"):
        raise ValueError("排列要求存在冲突：" + "、".join(context["layout_conflicts"]))
    requirements = context["requirements"]
    for key in ("spacing_m", "arrangement", "peer_placement", "layout_override", "spacing_reference"):
        if requirements.get(key) is not None:
            matches[0][key] = requirements[key]
    if len(matches) == 1:
        if requirements.get("quantity") is not None:
            matches[0]["quantity"] = requirements["quantity"]
        for key, value in (requirements.get("dimensions") or {}).items():
            if key in {"width_m", "height_m", "radius_m"}:
                matches[0][key] = value
        for key in ('grid_columns', 'grid_rows'):
            if key in requirements:
                matches[0][key] = requirements[key]
    specs = [{key: value for key, value in match.items()
              if key in TemplateInstanceSpec.model_fields and value is not None} for match in matches]
    prompt = context["prompt"]
    circle = (len(matches) == 1 and matches[0]["template"] == "basketball" and "圆" in prompt
              and any(word in prompt for word in ("内接", "外接圆", "大圆", "顶角都在圆", "四个顶角在圆")))
    placement_text = prompt + '\n' + '\n'.join(requirements.get('source_followups') or [])
    origins = list(re.finditer(r'(?:中心|原点|位置)(?:坐标)?\s*(?:为|在|是|=|：|:)?\s*[（(]\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)\s*[)）]\s*(毫米|mm|米|m)?', placement_text, re.I))
    origin = origins[-1] if origins else None
    if origin and not isinstance(requirements.get('origin'), dict):
        requirements['origin'] = {'x': float(origin[1]), 'y': float(origin[2]),
                                  'units': 'mm' if origin[3] in ('mm', '毫米') else 'm'}
    rotations = list(re.finditer(r'(顺时针|逆时针)?\s*旋转\s*(-?\d+(?:\.\d+)?)\s*(?:度|°)', placement_text))
    rotation = rotations[-1] if rotations else None
    if rotation and 'rotation_deg' not in requirements:
        requirements['rotation_deg'] = float(rotation[2]) * (-1 if rotation[1] == '顺时针' else 1)
    origin = requirements.get('origin')
    position = {'x': 0, 'y': 0}
    if isinstance(origin, dict):
        units = origin.get('units', requirements.get('units', 'm'))
        if units not in {'m', 'mm'}:
            raise ValueError('模板位置单位必须为 m 或 mm')
        factor = 1000 if units == 'm' else 1
        position = {key: float(origin.get(key, 0)) * factor for key in ('x', 'y')}
    rotation = requirements.get('rotation_deg', 0)
    steps=[{"op": "add_template", "step_id": "template-1",
            "output_ref": "template-design", "semantic": {"label": "参数化模板"},
            "matches": specs, "circumscribed_circle": circle,
            "origin": position, "rotation_deg": rotation}]
    return CadConstructionPlan.model_validate({
        "units": "mm", "steps": steps,
        "budgets": {"max_entities": 5000},
    })


def interpret_template_project(project, route):
    plan = template_plan_for_project(project, route)
    if plan is None:
        return None
    trial = execute_construction_plan(plan)
    from .cad_standard_templates import template_profile
    # Template execution is deterministic, but it still participates in the
    # same response visibility contract as model-produced plans.  Persist an
    # explicit backend acceptance result instead of making the HTTP layer
    # infer success from the presence of geometries alone.
    assertions = trial.get("assertions") if isinstance(trial, dict) else None
    accepted = isinstance(assertions, dict) and assertions.get("ok") is True
    acceptance_summary = {
        "status": "passed" if accepted else "review_required",
        "review_required": not accepted,
        "authority": "backend_measured_geometry",
        "source": "deterministic_template_execution",
        "geometry_count": len(list(trial.get("geometries") or [])),
    }
    return {"schema": "cad.construction-interpretation-result.v1", "status": "ready",
            "parser": "parameterized_template", "confidence": 1.0,
            "plan": plan.model_dump(mode="json"), "trial_result": trial,
            "provider_attempted": False, 'template_specifications':template_profile(plan),
            "acceptance_summary": acceptance_summary}


def template_plan_from_text(text):
    from .agent_skills import parameterize_design
    requirements = parameterize_design(text)
    return template_plan_for_project({"name": text, "original_prompt": text,
                                      "requirements": requirements}, {})
