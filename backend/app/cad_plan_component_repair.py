"""Merge only measured failing components; preserve every other plan relation."""
from copy import deepcopy


def normalize_component_repair_context(context):
    """Use the same explicit identity catalog as construction consumers."""
    from .cad_plan_references import plan_reference_catalog
    result=deepcopy(context)
    plan=result.get('plan') or result.get('rejected_plan') or {}
    details=(result.get('construction_error') or {}).get('details') or {}
    graph=details.get('logical_graph_validation') or {}
    if (graph.get('identity_only_repair') is True and graph.get('affected_output_refs')
            and any(e.get('code')=='invalid_object_ids' for e in graph.get('validation_errors',[]))):
        # Assertion failure may be reported before logical identity validation.
        # Repair its recorded conflicts first; geometry remains protected.
        details['identity_only_repair']=True
        details['affected_output_refs']=list(graph['affected_output_refs'])
    refs=details.get('affected_output_refs') or []
    if not refs:return result
    catalog,conflicts=plan_reference_catalog(plan.get('steps',[]))
    bindings={}
    for ref in refs:
        if ref in conflicts or ref not in catalog:
            raise ValueError('部件修复引用未知或有歧义：'+str(ref))
        bindings[ref]=catalog[ref]
    details.setdefault('affected_reference_bindings',bindings)
    details['affected_output_refs']=list(dict.fromkeys(r for values in bindings.values() for r in values))
    error=result.get('construction_error') or {}
    # A replacement primitive inventory is not a rename. Only the existing
    # whole-plan recompilation path may accept it. Promote a measured conflict
    # that covers every segment of the only failed step, never a local patch.
    if (error.get('code')=='self_intersecting_composite_path'
            and not details.get('local_repair_scope') and not details.get('identity_only_repair')):
        steps=plan.get('steps',[])
        failed=[s for s in steps if s.get('step_id')==error.get('step_id')]
        if len(failed)==1 and failed[0].get('op')=='add_composite_path':
            segments=failed[0].get('segments',[])
            implicated=details.get('affected_segment_indices',[])
            outputs={s.get('output_ref') for s in steps}
            if (segments and implicated and all(type(i) is int for i in implicated)
                    and set(implicated)==set(range(len(segments)))
                    and outputs and outputs<=set(details['affected_output_refs'])):
                details['requires_structural_replan']=True
                details['structural_replan_evidence']={
                    'reason':'all_segments_and_all_plan_outputs_measured_in_conflict',
                    'step_id':failed[0]['step_id'],'segment_indices':sorted(set(implicated)),
                    'output_refs':sorted(outputs),'source_requirements_unchanged':True}
    result['construction_error']['details']=details
    return result


def merge_component_repair(context, payload, *, source_text=None, resolutions=None):
    context=normalize_component_repair_context(context)
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
    if not details.get('identity_only_repair'):
        from .cad_shared_points import resolve_shared_points
        proposed=resolve_shared_points({**proposed,'shared_points':{
            **(plan.get('shared_points') or {}),**(proposed.get('shared_points') or {})}})
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
        from .cad_plan_references import plan_reference_catalog
        catalog,_=plan_reference_catalog(plan.get('steps',[]))
        # A model-authored assertion that failed is not a user requirement.
        # Allow its correction while retaining every unrelated assertion;
        # source-based geometry acceptance still runs after the merge.
        updates = [a for a in proposed.get('assertions', [])
                   if a.get('assertion_id') == failed_assertion
                   and catalog.get(a.get('target_ref'))
                   and set(catalog[a['target_ref']])<=affected]
        if len(updates) > 1:
            raise ValueError('失败断言重复')
        if updates:
            merged['assertions'] = [deepcopy(updates[0]) if a.get('assertion_id') == failed_assertion
                and a.get('target_ref') == updates[0].get('target_ref') else a
                for a in merged.get('assertions', [])]
    result = deepcopy(payload)
    result['plan'] = merged
    return result
