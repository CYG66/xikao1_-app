"""Merge only measured failing components; preserve every other plan relation."""
from copy import deepcopy


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
