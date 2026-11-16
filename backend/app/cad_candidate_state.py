"""Shared candidate eligibility for restore, selection and editing.

Acceptance is evidence, not a default.  Every consumer must use this helper so
that a candidate cannot be visible in one route and rejected in another.
"""

def geometry_evidence_hash(geometries):
    import hashlib
    import json
    return hashlib.sha256(json.dumps(geometries,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def bind_version_symbols(record,variant,project_id):
    from copy import deepcopy
    table=record.get('symbol_table');gs=variant.get('geometries') or []
    ids={g.get('id') for g in gs};actual=geometry_evidence_hash(gs)
    if (not isinstance(table,dict) or not table or record.get('geometry_hash')!=actual
        or any(not isinstance(values,list) or not values or any(i not in ids for i in values) for values in table.values())):
        return {'status':'unknown','reason':'missing_or_incompatible_execution_mapping'}
    return {'status':'bound','project_id':project_id,'variant_id':variant['id'],
        'geometry_hash':actual,'symbol_table':deepcopy(table),
        'cardinality':{ref:'one' if len(values)==1 else 'many' for ref,values in table.items()}}


def resolve_version_symbols(variant,project_id):
    from copy import deepcopy
    mapping=(variant.get('construction_record') or {}).get('version_symbols') or variant.get('reference_mapping') or {}
    if (mapping.get('status')!='bound' or mapping.get('project_id')!=project_id
        or mapping.get('variant_id')!=variant.get('id')
        or mapping.get('geometry_hash')!=geometry_evidence_hash(variant.get('geometries') or [])):
        return None
    return deepcopy(mapping['symbol_table'])


def transformed_version_symbols(parent,variant,project_id,operation):
    """Carry identities only through explicit ID-preserving transformations."""
    table=resolve_version_symbols(parent,project_id)
    old_ids={g['id'] for g in parent.get('geometries',[])}
    new_ids={g['id'] for g in variant.get('geometries',[])}
    if table is None or operation not in {'translate','rotate','scale','resize','align','delete'}:
        return {'status':'unknown','reason':'no_verified_identity_preserving_edit'}
    if operation=='delete':
        if not new_ids.issubset(old_ids):return {'status':'unknown','reason':'unexpected_new_geometry'}
        table={ref:[i for i in ids if i in new_ids] for ref,ids in table.items()}
        table={ref:ids for ref,ids in table.items() if ids}
    elif new_ids!=old_ids:return {'status':'unknown','reason':'geometry_identity_changed'}
    result=bind_version_symbols({'symbol_table':table,'geometry_hash':geometry_evidence_hash(variant['geometries'])},variant,project_id)
    result['parent_variant_id']=parent['id']
    result['operation']=operation
    return result


def candidate_is_reviewable_draft(variant):
    if not isinstance(variant,dict) or not variant.get('geometries'):
        return False
    summary=variant.get('acceptance_summary') or {}
    record=variant.get('construction_record') or {}
    return (summary.get('status')=='review_required' and summary.get('review_required') is True
            and (record.get('feasibility') or {}).get('ok') is True
            and (record.get('constraint_solve') or {}).get('verified') is True
            and (record.get('acceptance_summary') or summary)==summary)


def bind_creation_history(parent,variant,project_id,edit_contract=None):
    """Bind executor-proven creation edges to this immutable version."""
    from copy import deepcopy
    previous=(parent or {}).get('reference_mapping') or {}
    binding=previous.get('creation_binding') or {}
    events=[]
    if parent and binding=={'project_id':project_id,'variant_id':parent['id'],
                           'parent_variant_id':parent.get('parent_variant_id'),
                           'geometry_hash':geometry_evidence_hash(parent.get('geometries') or [])}:
        events=deepcopy(previous.get('creation_events') or [])
    old_ids={g['id'] for g in (parent or {}).get('geometries',[])}
    present={g['id'] for g in variant.get('geometries',[])}
    if len(present)!=len(variant.get('geometries',[])):raise ValueError('重复几何ID')
    for event in events:
        event['members']=[m for m in event['members'] if m['geometry_id'] in present]
    grouped={}
    proof=(edit_contract or {}).get('execution_identity') or {}
    proven={}
    if (parent and proof.get('source_hash')==geometry_evidence_hash(parent.get('geometries') or [])
        and proof.get('result_hash')==geometry_evidence_hash(variant.get('geometries') or [])):
        members=proof.get('members',[])
        if (len({m.get('geometry_id') for m in members})==len(members)
            and {m.get('geometry_id') for m in members}==present-old_ids
            and all(m.get('operation')=='duplicate' and m.get('source_geometry_id') in old_ids for m in members)):
            proven={m['geometry_id']:m for m in members}
    for geometry in variant.get('geometries',[]):
        if geometry['id'] in old_ids:continue
        proof=proven.get(geometry['id']) or {}
        if not proof.get('operation_id') or proof.get('geometry_id')!=geometry['id']:continue
        source_id=proof.get('source_geometry_id')
        if source_id is not None and source_id not in old_ids:continue
        operation_id=proof['operation_id']
        event=grouped.setdefault(operation_id,{'operation_id':operation_id,'operation':proof['operation'],'members':[]})
        objects=[obj.get('object_id') for obj in variant.get('logical_objects',[])
                 if geometry['id'] in (obj.get('geometry_refs') or obj.get('geometry_ids') or [])]
        event['members'].append({'geometry_id':geometry['id'],'source_geometry_id':source_id,
            'instance_id':geometry.get('template_instance'),'logical_object_id':objects[0] if len(objects)==1 else None})
    events.extend(grouped.values())
    return {'creation_binding':{'project_id':project_id,'variant_id':variant['id'],
                'parent_variant_id':variant.get('parent_variant_id'),
                'geometry_hash':geometry_evidence_hash(variant.get('geometries') or [])},'creation_events':events}


def candidate_is_accepted(variant):
    if not isinstance(variant, dict):
        return False
    record = variant.get('construction_record')
    record = record if isinstance(record, dict) else {}
    summaries = [variant.get('acceptance_summary'), record.get('acceptance_summary')]
    evidence = [s for s in summaries if isinstance(s, dict)]
    return isinstance(variant.get('acceptance_summary'), dict) and bool(evidence) and all(
        s.get('status') == 'passed' and s.get('review_required') is not True
        for s in evidence
    )


def authoritative_acceptance_summary(variant):
    if not isinstance(variant, dict):
        return None
    record=variant.get('construction_record')
    values=[variant.get('acceptance_summary'),
            record.get('acceptance_summary') if isinstance(record,dict) else None]
    evidence=[v for v in values if isinstance(v,dict)]
    if not isinstance(variant.get('acceptance_summary'), dict) or not evidence or not all(v.get('status') == 'passed' and v.get('review_required') is not True for v in evidence):
        return None
    return evidence[0]


def accepted_project_view(project):
    """Return the project shape safe for all read-only project endpoints."""
    if not isinstance(project, dict):
        return project
    from copy import deepcopy
    view=deepcopy(project)
    variants=view.get('variants')
    if isinstance(variants,list):
        view['variants']=[v for v in variants if candidate_is_accepted(v)]
        visible_ids={str(v.get('id')) for v in view['variants']}
        if str(view.get('selected_variant_id') or '') not in visible_ids:
            view['selected_variant_id']=None
        if str(view.get('design_base_variant_id') or '') not in visible_ids:
            view['design_base_variant_id']=None
    return view
