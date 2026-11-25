"""Pure reference compilation shared by every construction-plan consumer."""
from collections import Counter


REFERENCE_DESCRIPTION = (
    '引用精确的output_ref，或object:<semantic.object_id>、assembly:<semantic.assembly_id>。'
    '类型别名仅来自保留该身份的原语步骤；阵列和模板使用output_ref。'
    '整体引用包含该整体全部部件，不按label猜测；单图元工具仍拒绝多图元整体。'
)


def plan_reference_catalog(steps):
    """Compile explicit identities, never fuzzy labels or geometric proximity.

    A typed alias must have one meaning even if an output uses the same name.
    Conflicts are returned separately so callers cannot silently prefer one.
    """
    candidates = {}
    assemblies = {}
    for step in steps:
        get = step.get if isinstance(step, dict) else lambda k, default=None: getattr(step, k, default)
        output = get('output_ref')
        if not output:
            continue
        candidates.setdefault(output, []).append([output])
        if get('op') in {'rectangular_array', 'add_template'}:
            # These operations assign instance identities during expansion;
            # their step-level semantic seed is not an actual logical object.
            continue
        semantic = get('semantic') or {}
        sem = semantic.get if isinstance(semantic, dict) else lambda k: getattr(semantic, k, None)
        if isinstance(sem('object_id'), str) and sem('object_id'):
            candidates.setdefault('object:' + sem('object_id'), []).append([output])
        if isinstance(sem('assembly_id'), str) and sem('assembly_id'):
            assemblies.setdefault('assembly:' + sem('assembly_id'), []).append(output)
    for key, members in assemblies.items():
        candidates.setdefault(key, []).append(members)
    conflicts = {key for key, meanings in candidates.items()
                 if len({tuple(sorted(set(m))) for m in meanings}) != 1}
    return ({key: list(dict.fromkeys(meanings[0])) for key, meanings in candidates.items()
             if key not in conflicts}, conflicts)


def bind_plan_references(steps, output_refs):
    """Resolve the same checked catalog to physical IDs for every consumer."""
    catalog, _ = plan_reference_catalog(steps)
    return {**output_refs, **{name: list(dict.fromkeys(gid for member in members for gid in output_refs[member]))
                             for name, members in catalog.items()}}


def plan_reference_errors(plan):
    errors = []
    outputs = {step.output_ref for step in plan.steps}
    catalog, conflicts = plan_reference_catalog(plan.steps)

    def reject(path, message, **details):
        errors.append({'path': path, 'message': message, **details})

    for field, values in (
        ('step_id', [s.step_id for s in plan.steps]),
        ('output_ref', [s.output_ref for s in plan.steps]),
        ('assertion_id', [a.assertion_id for a in plan.assertions]),
        ('constraint_id', [c.constraint_id for c in plan.constraints]),
    ):
        for value, count in Counter(values).items():
            if count > 1:
                reject(field, f'{field} values must be unique', value=value)

    known = set()
    for index, step in enumerate(plan.steps):
        source = getattr(step, 'source_ref', None)
        if source is not None and source not in known:
            reject(f'steps[{index}].source_ref',
                   f'step {step.step_id} references unavailable source_ref {source}',
                   reference=source, reason='forward_reference' if source in outputs else 'unknown_reference')
        known.add(step.output_ref)

    for group in ('assertions', 'constraints'):
        for index, relation in enumerate(getattr(plan, group)):
            for field in ('target_ref', 'reference_ref'):
                ref = getattr(relation, field, None)
                if ref is not None and ref not in catalog:
                    reject(f'{group}[{index}].{field}',
                           f'{group[:-1]} references unavailable {field} {ref}',
                           reference=ref, reason='ambiguous_reference' if ref in conflicts else 'unknown_reference',
                           available_refs=sorted(catalog))

    placed = set()
    layout_targets = {item.target_ref for item in plan.free_outline_layout}
    for index, item in enumerate(plan.free_outline_layout):
        members = catalog.get(item.target_ref, [])
        if len(members) != 1 or members[0] in placed:
            reject(f'free_outline_layout[{index}].target_ref', 'layout target must exist and be unique', reference=item.target_ref)
        ref = item.right_of_ref
        reference_members = catalog.get(ref, []) if ref is not None else []
        pending_targets = {m for name in layout_targets for m in catalog.get(name, [])}
        if ref is not None and (not reference_members or set(reference_members) & set(members)
                                or (set(reference_members) & pending_targets) - placed):
            reject(f'free_outline_layout[{index}].right_of_ref',
                   'layout reference must exist and precede its dependent target', reference=ref)
        placed.update(members)
    return errors
