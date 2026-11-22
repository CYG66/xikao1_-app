"""Merge only measured failing components; preserve every other plan relation."""
import json
from copy import deepcopy


class ComponentRepairError(ValueError):
    """A component repair that cannot be merged without losing plan semantics."""

    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        # Previous plan attached by the merger so the interpreter can surface
        # it to the next repair round; kept out of the serializable details.
        self.previous_plan = None


_POLICY_FIELDS = (
    'closed',
    'samples_per_curve',
    'connection_tolerance',
    'continuity',
    'tangent_tolerance_deg',
    'allow_self_intersection',
    'allow_duplicate_segments',
    'max_curvature',
    'max_sampling_error',
)
_NULLABLE_POLICY_FIELDS = {'max_curvature', 'max_sampling_error'}
_MAX_POLICY_FIELDS = {'connection_tolerance', 'tangent_tolerance_deg',
                      'max_curvature', 'max_sampling_error'}
_BOOL_POLICY_FIELDS = {'allow_self_intersection', 'allow_duplicate_segments'}


def _segment_identity(segment):
    return json.dumps(segment, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _structure_change_reason(original, replacement):
    """Return why segment indices cannot be assumed stable, or None.

    A same-count geometry edit keeps indices meaningful: the model is still
    repairing segment 0, 1, ... in place.  A changed count, changed segment
    kind sequence, or a pure reorder does not.
    """
    original_segments = original.get('segments')
    replacement_segments = replacement.get('segments')
    if replacement_segments is None:
        return None
    if not isinstance(original_segments, list) or not isinstance(replacement_segments, list):
        return 'segments_not_a_list'
    if len(original_segments) != len(replacement_segments):
        return 'segment_count_changed'
    original_hashes = [_segment_identity(item) for item in original_segments]
    replacement_hashes = [_segment_identity(item) for item in replacement_segments]
    if sorted(original_hashes) == sorted(replacement_hashes) and original_hashes != replacement_hashes:
        return 'segment_identity_order_changed'
    original_kinds = [item.get('kind') for item in original_segments]
    replacement_kinds = [item.get('kind') for item in replacement_segments]
    if original_kinds != replacement_kinds:
        return 'segment_kind_order_changed'
    return None


def _constraint_key(item):
    return (
        item.get('junction_index'),
        item.get('left_segment_index'),
        item.get('right_segment_index'),
    )


def _constraint_mapping_error(output_ref, reason, **details):
    return ComponentRepairError(
        'junction_constraint_mapping_unsafe',
        '部件修复改变了段结构，不能沿用原连接点索引；请提供与新段结构匹配的完整连接约束',
        output_ref=output_ref,
        reason=reason,
        **details,
    )


def _validate_junction_constraints(step, constraints, *, output_ref):
    """Validate indices against the step that will actually be executed.

    Source authorization is intentionally not checked here; H3 remains the
    only authority for ``source_requirement_refs``.  This function only proves
    that every index points at the same adjacent segment pair the model named.
    """
    segments = step.get('segments')
    if not isinstance(segments, list) or not segments:
        raise ComponentRepairError(
            'junction_constraints_invalid',
            '连接约束必须绑定到非空的复合路径段',
            output_ref=output_ref,
        )
    count = len(segments)
    closed = bool(step.get('closed', False))
    seen = set()
    for item in constraints:
        if not isinstance(item, dict):
            raise ComponentRepairError(
                'junction_constraints_invalid',
                '连接约束条目必须是对象',
                output_ref=output_ref,
            )
        junction_index = item.get('junction_index')
        left = item.get('left_segment_index')
        right = item.get('right_segment_index')
        for name, value in (
            ('junction_index', junction_index),
            ('left_segment_index', left),
            ('right_segment_index', right),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ComponentRepairError(
                    'junction_constraints_invalid',
                    f'{name} 必须是整数索引',
                    output_ref=output_ref,
                    field=name,
                )
        if left < 0 or left >= count or right < 0 or right >= count:
            raise ComponentRepairError(
                'junction_constraint_mapping_unsafe',
                '连接约束索引超出复合路径段范围',
                output_ref=output_ref,
                left_segment_index=left,
                right_segment_index=right,
                segment_count=count,
            )
        expected_right = (left + 1) % count
        if right != expected_right:
            raise ComponentRepairError(
                'junction_constraint_mapping_unsafe',
                '连接约束必须指向相邻段',
                output_ref=output_ref,
                left_segment_index=left,
                right_segment_index=right,
            )
        if right == 0 and not closed:
            raise ComponentRepairError(
                'junction_constraint_mapping_unsafe',
                '开放路径不能声明首尾连接约束',
                output_ref=output_ref,
                left_segment_index=left,
            )
        if junction_index != left:
            raise ComponentRepairError(
                'junction_constraint_mapping_unsafe',
                'junction_index 必须等于左段索引',
                output_ref=output_ref,
                junction_index=junction_index,
                left_segment_index=left,
            )
        key = (left, right)
        if key in seen:
            raise ComponentRepairError(
                'junction_constraints_invalid',
                '同一连接点不能重复声明约束',
                output_ref=output_ref,
                left_segment_index=left,
                right_segment_index=right,
            )
        seen.add(key)
        intent = item.get('intent')
        if intent not in {'smooth', 'intentional_cusp', 'intentional_corner', 'unknown'}:
            raise ComponentRepairError(
                'junction_constraints_invalid',
                '连接意图不在允许范围内',
                output_ref=output_ref,
                intent=intent,
            )
        required = item.get('required_continuity')
        if required not in {'C0', 'G1', 'C1'}:
            raise ComponentRepairError(
                'junction_constraints_invalid',
                '连接连续性必须为 C0、G1 或 C1',
                output_ref=output_ref,
                required_continuity=required,
            )
        tolerance = item.get('tangent_tolerance_deg')
        if tolerance is not None:
            if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)):
                raise ComponentRepairError(
                    'junction_constraints_invalid',
                    '连接切向容差必须是数值或 null',
                    output_ref=output_ref,
                )
            if tolerance <= 0:
                raise ComponentRepairError(
                    'junction_constraints_invalid',
                    '连接切向容差必须大于 0',
                    output_ref=output_ref,
                    tangent_tolerance_deg=tolerance,
                )


def _guard_numeric_policy(original, replacement, key, *, output_ref):
    if key not in replacement or key not in original:
        return
    old = original[key]
    new = replacement[key]
    if isinstance(old, (int, float)) and not isinstance(old, bool) \
            and isinstance(new, (int, float)) and not isinstance(new, bool) \
            and new > old:
        code = 'tangent_tolerance_weakened' if key == 'tangent_tolerance_deg' \
            else f'{key}_weakened'
        raise ComponentRepairError(
            code,
            f'部件修复不能放宽原计划的 {key} 验收阈值',
            output_ref=output_ref,
            original=old,
            replacement=new,
        )


def _merge_step_policy(original, replacement, *, output_ref):
    """Carry forward omitted execution policy and reject explicit relaxation."""
    for key in _POLICY_FIELDS:
        if key not in replacement:
            if key in original:
                replacement[key] = deepcopy(original[key])
            continue
        value = replacement[key]
        if value is None and key not in _NULLABLE_POLICY_FIELDS:
            raise ComponentRepairError(
                'component_repair_null_field',
                f'部件修复不能把 {key} 显式设为 null',
                output_ref=output_ref,
                field=key,
            )
        if key in _BOOL_POLICY_FIELDS and original.get(key) is False and value is True:
            raise ComponentRepairError(
                f'{key}_weakened',
                f'部件修复不能放宽原计划的 {key} 策略',
                output_ref=output_ref,
                field=key,
                original=False,
                replacement=True,
            )
        if key in _MAX_POLICY_FIELDS:
            _guard_numeric_policy(original, replacement, key, output_ref=output_ref)
        if key == 'continuity' and value is not None and value not in {'C0', 'C1'}:
            raise ComponentRepairError(
                'continuity_invalid',
                '连续性质必须为 C0 或 C1',
                output_ref=output_ref,
                continuity=value,
            )


def _merge_junction_constraints(original, replacement, *, output_ref):
    original_constraints = original.get('junction_constraints') or []
    if not isinstance(original_constraints, list):
        original_constraints = []
    structure_reason = _structure_change_reason(original, replacement)
    if 'junction_constraints' in replacement:
        constraints = replacement['junction_constraints']
        if constraints is None:
            raise ComponentRepairError(
                'junction_constraints_null_rejected',
                '部件修复不能把 junction_constraints 显式设为 null',
                output_ref=output_ref,
            )
        if not isinstance(constraints, list):
            raise ComponentRepairError(
                'junction_constraints_invalid',
                'junction_constraints 必须是数组',
                output_ref=output_ref,
            )
        if not constraints and original_constraints:
            raise ComponentRepairError(
                'junction_constraints_clear_rejected',
                '部件修复不能清空原计划的有效连接约束；请保留原约束或提交经结构校验的新约束集合',
                output_ref=output_ref,
            )
        if constraints and structure_reason is None:
            original_keys = {_constraint_key(item) for item in original_constraints}
            replacement_keys = {_constraint_key(item) for item in constraints}
            missing = original_keys - replacement_keys
            if missing:
                raise ComponentRepairError(
                    'junction_constraints_partial_replacement_rejected',
                    '部件修复不能只提交部分原连接约束；段结构未变时必须保留全部原约束',
                    output_ref=output_ref,
                    missing=list(missing),
                )
        replacement['junction_constraints'] = deepcopy(constraints)
        _validate_junction_constraints(replacement, constraints, output_ref=output_ref)
        return
    if original_constraints:
        if structure_reason is not None:
            raise _constraint_mapping_error(
                output_ref, structure_reason,
                original_constraint_count=len(original_constraints),
            )
        replacement['junction_constraints'] = deepcopy(original_constraints)
        _validate_junction_constraints(
            replacement, original_constraints, output_ref=output_ref
        )


def merge_component_repair(context, payload):
    plan = context.get('plan') or context.get('rejected_plan')
    details = (context.get('construction_error') or {}).get('details') or {}
    affected = set(details.get('affected_output_refs') or [])
    if not isinstance(plan, dict) or not affected:
        raise ValueError('缺少可验证的部件修复范围')
    proposed = payload.get('plan') if isinstance(payload, dict) else None
    if not isinstance(proposed, dict):
        raise ValueError('部件修复未返回构造计划')
    if proposed.get('units', 'm') != plan.get('units', 'm'):
        raise ValueError('部件修复不能改变原计划单位；请按原单位重新输出坐标')
    replacements = {}
    for step in proposed.get('steps') or []:
        ref = step.get('output_ref')
        if ref in affected:
            if ref in replacements:
                raise ValueError('部件修复重复输出同一引用')
            replacements[ref] = step
    if set(replacements) != affected:
        raise ValueError('部件修复必须保留失败部件的原输出引用')
    try:
        merged = deepcopy(plan)
        if details.get('identity_only_repair'):
            for index, original in enumerate(plan['steps']):
                ref=original['output_ref']
                if ref not in affected:continue
                identity=(replacements[ref].get('semantic') or {}).get('object_id')
                if not isinstance(identity,str) or not identity.strip():
                    raise ValueError('身份修复必须返回明确的object_id')
                merged['steps'][index].setdefault('semantic',{})['object_id']=identity
            result=deepcopy(payload);result['plan']=merged
            return result
        for index, original in enumerate(plan['steps']):
            if original['output_ref'] not in affected:
                continue
            replacement = deepcopy(replacements[original['output_ref']])
            for key in ('step_id', 'output_ref', 'semantic', 'layer_id'):
                if key in original:
                    replacement[key] = deepcopy(original[key])
            if original.get('op') != replacement.get('op'):
                has_connection_semantics = bool(original.get('junction_constraints')) \
                    or 'continuity' in original or 'tangent_tolerance_deg' in original
                if has_connection_semantics:
                    raise ComponentRepairError(
                        'component_repair_op_change_requires_replan',
                        '更换构造操作会破坏原连接语义；请重新规划而不是局部修复',
                        output_ref=original['output_ref'],
                        original_op=original.get('op'),
                        replacement_op=replacement.get('op'),
                    )
            _merge_step_policy(original, replacement, output_ref=original['output_ref'])
            _merge_junction_constraints(
                original, replacement, output_ref=original['output_ref']
            )
            merged['steps'][index] = replacement
        failed_assertion = (context.get('construction_error') or {}).get('assertion_id')
        if failed_assertion:
            # A model-authored assertion that failed is not a user requirement.
            # Allow its correction while retaining every unrelated assertion;
            # source-based geometry acceptance still runs after the merge.
            updates = [a for a in proposed.get('assertions', [])
                       if a.get('assertion_id') == failed_assertion
                       and a.get('target_ref') in affected]
            if len(updates) > 1:
                raise ValueError('失败断言重复')
            if updates:
                merged['assertions'] = [deepcopy(updates[0]) if a.get('assertion_id') == failed_assertion
                    and a.get('target_ref') == updates[0].get('target_ref') else a
                    for a in merged.get('assertions', [])]
        result = deepcopy(payload)
        result['plan'] = merged
        return result
    except ComponentRepairError as exc:
        exc.details['affected_output_refs'] = sorted(
            {ref for ref in affected if isinstance(ref, str) and ref}
        )
        exc.previous_plan = deepcopy(plan)
        raise
