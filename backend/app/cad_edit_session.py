"""Source-preserving continuation of an unfinished edit, never a geometry writer."""
from copy import deepcopy
import re


def fresh_creation(text):
    return bool(re.search(r'(?:新建|重新生成|另画|另建|生成|画一|绘制)',text)) and not bool(re.search(r'同样|复制|副本|新增|添加',text))


def edit_text(text):
    # A contextual duplicate is an edit of an existing object, not a new shape.
    if re.search(r'同样的|相同的',text) and re.search(r'[左右上下](?:侧|方).*?\d',text):
        text=re.sub(r'规划(?:一个)?同样的','复制一个同样的',text)
    return text


def selection_binding(selection):
    """Canonical immutable binding for an edit continuation."""
    if not isinstance(selection,dict):return None
    pid=str(selection.get('project_id') or '')
    vid=str(selection.get('variant_id') or '')
    try:
        gids=tuple(sorted(int(value) for value in selection.get('geometry_ids') or []))
    except (TypeError, ValueError):
        return None
    object_ids=tuple(sorted(str(value) for value in selection.get('object_ids') or []))
    object_id=str(selection.get('object_id') or '')
    if not pid or not vid or not gids:return None
    return {'project_id':pid,'variant_id':vid,'geometry_ids':gids,
        'scope':str(selection.get('scope') or ''),'object_id':object_id,
        'object_ids':object_ids,'instance_id':selection.get('instance_id')}


def binding_key(binding):
    """Return the immutable four-part edit context key.

    The project/version/selection tuple is deliberately kept separate from
    the mutable command body.  Every continuation and confirmation must use
    this key, otherwise a stale command can be applied to a newly selected
    drawing that happens to have similar geometry ids.
    """
    if not isinstance(binding, dict):
        return None
    project_id = str(binding.get('project_id') or '')
    variant_id = str(binding.get('variant_id') or '')
    try:
        geometry_ids = tuple(sorted(int(value) for value in binding.get('geometry_ids') or []))
    except (TypeError, ValueError):
        return None
    if not project_id or not variant_id or not geometry_ids:
        return None
    return (
        project_id,
        variant_id,
        geometry_ids,
        str(binding.get('scope') or ''),
        str(binding.get('object_id') or ''),
        tuple(sorted(str(value) for value in binding.get('object_ids') or [])),
        binding.get('instance_id'),
    )


def pending_binding(pending):
    """Canonical binding for a persisted pending command."""
    if not isinstance(pending, dict):
        return None
    return pending.get('binding') or selection_binding(pending.get('drawing_selection') or {})


def binding_matches(pending, selection):
    """Whether a pending command and the current selection are identical."""
    return binding_key(pending_binding(pending)) == binding_key(selection_binding(selection))


def continuation(text,memory,project_id,selection,get_project):
    pending=memory.get('pending_cad_edit') if isinstance(memory,dict) else None
    if not isinstance(pending,dict) or fresh_creation(text):return None
    if re.search(r'取消|不用了|停止修改|换个任务',text):return None
    if project_id and project_id!=pending['project_id']:return None
    if not project_id:
        projects=(memory.get('objects') or {}).get('project') or []
        if projects and projects[0].get('id') and projects[0]['id']!=pending['project_id']:return None
    old=pending.get('drawing_selection') or {}
    pending_binding=pending.get('binding') or selection_binding(old)
    if pending_binding is None:return None
    if selection and binding_key(selection_binding(selection)) != binding_key(pending_binding):return None
    # A new standalone edit replaces the pending operation. Parameter answers
    # may repeat the same operation, but must not inherit an unrelated command.
    if re.search(r'把(?:另|其他)|改为.*(?:删除|复制|平移)|改做',text):return None
    if re.search(r'小车|机器人|设备执行|启动任务',text):return None
    # Compare standalone commands before joining turns: a new translation must
    # never accidentally complete an earlier rotation or scale clarification.
    from .incremental_cad import parse_incremental_edit
    current=parse_incremental_edit(edit_text(text)+' 图形')
    original=parse_incremental_edit(edit_text('\n'.join(pending.get('source_turns') or []))+' 图形')
    if current and original and current.get('operation')!=original.get('operation'):
        # A reference/metric answer may describe the resulting translation
        # or resize, but it still completes the pending align/constraint.
        # Binding has already been checked above; unrelated edits still replace it.
        relation_answer = (original.get('operation') in {'align', 'constraint'}
                           and bool(re.search(r'基准|参考|固定|保持|相同|直径', text)))
        if not relation_answer:
            return None
    if not re.search(r'基点|基准|参考|固定|保持|圆心|中心|坐标|单位|尺寸|宽|高|长|半径|面积|周长|顺时针|逆时针|保留|米|mm|cm|倍|对齐|同心|相等|确认|重试|百分|%|度',text):return None
    project=get_project(pending['project_id'])
    if not project:return None
    variants=project.get('variants') or []
    if not any(v.get('id')==pending['variant_id'] for v in variants):return None
    active=project.get('design_base_variant_id') or project.get('selected_variant_id') or (variants[-1].get('id') if variants else None)
    if active!=pending['variant_id']:return None
    turns=list(pending.get('source_turns') or [])+[text]
    combined='\n'.join(turns)
    if original and original.get('operation')=='rotate':
        supplied_angle=re.findall(r'(\d+(?:\.\d+)?)\s*度',text)
        if supplied_angle:
            combined=re.sub(r'(旋转\s*)\d+(?:\.\d+)?\s*度',
                lambda m:m[1]+supplied_angle[-1]+'度',combined)
    # Preserve the specified magnitude when only the direction was missing.
    if re.search(r'顺时针|逆时针',text):
        direction='逆时针' if '逆时针' in text else '顺时针'
        combined=re.sub(r'(?:(?:顺时针|逆时针)(?:方向)?)?旋转\s*(\d+(?:\.\d+)?)\s*度',
            lambda m:direction+'旋转'+m[1]+'度',combined)
    return {**deepcopy(pending),'binding':pending_binding,
        'source_turns':turns,'message':edit_text(combined)}


def remember_edit(previous,message,result,route):
    if not isinstance(route,dict):return previous
    if route.get('operation')=='create' or re.search(r'取消|不用了|停止修改|换个任务',message):return None
    if result.get('ok') is True and result.get('cad_edit_outcome')=='already_satisfied':return None
    selected_project=route.get('selected_project_id')
    if isinstance(previous,dict) and selected_project and selected_project!=previous.get('project_id'):
        previous=None
    selection=route.get('drawing_selection')
    if route.get('operation')!='modify' or not isinstance(selection,dict):return previous
    pid=selection.get('project_id');vid=selection.get('variant_id')
    if not pid or not vid:return previous
    variant=result.get('variant') or {}
    if result.get('ok') is True and variant.get('id') and variant['id']!=vid:return None
    if result.get('pending_action'):return None
    session=route.get('cad_edit_session') or {}
    binding=selection_binding(selection)
    if binding is None:return previous
    command=(route.get('resolved_edit') or result.get('cad_edit_contract')
             or result.get('cad_edit_command'))
    if isinstance(command, dict):
        command = deepcopy(command)
        command.setdefault('project_id', str(pid))
        command.setdefault('variant_id', str(vid))
        command['binding'] = deepcopy(binding)
    return {'schema':'cad.edit-session.v1','project_id':pid,'variant_id':vid,
        'binding':binding,'command':command if isinstance(command,dict) else None,
        'drawing_selection':deepcopy(selection),'source_turns':list(session.get('source_turns') or [message]),
        'question':str(result.get('clarification_question') or result.get('message') or ''),
        'state':'awaiting_parameters_or_retry'}
