"""Pure reference compilation shared by every construction-plan consumer."""
from collections import Counter


def plan_reference_errors(plan):
    errors = []
    outputs = {step.output_ref for step in plan.steps}

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
                if ref is not None and ref not in outputs:
                    reject(f'{group}[{index}].{field}',
                           f'{group[:-1]} references unavailable {field} {ref}',
                           reference=ref, available_refs=sorted(outputs))

    placed = set()
    layout_targets = {item.target_ref for item in plan.free_outline_layout}
    for index, item in enumerate(plan.free_outline_layout):
        if item.target_ref not in outputs or item.target_ref in placed:
            reject(f'free_outline_layout[{index}].target_ref', 'layout target must exist and be unique', reference=item.target_ref)
        ref = item.right_of_ref
        if ref is not None and (ref not in outputs or ref == item.target_ref
                                or (ref in layout_targets and ref not in placed)):
            reject(f'free_outline_layout[{index}].right_of_ref',
                   'layout reference must exist and precede its dependent target', reference=ref)
        placed.add(item.target_ref)
    return errors
