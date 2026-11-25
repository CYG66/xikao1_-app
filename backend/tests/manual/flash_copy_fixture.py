"""Load archived accepted baseline without manufacturing acceptance or target answers."""
from copy import deepcopy
import json
from pathlib import Path


def load_circle_fixture(source: Path,destination: Path):
    from app.cad_candidate_state import candidate_is_accepted,geometry_evidence_hash
    from app.cad_construction import execute_construction_plan
    from app.creative_projects import CreativeProjectStore
    data=json.loads((source/'projects.json').read_text(encoding='utf-8'))
    if len(data.get('projects',[]))!=1:raise ValueError('fixture_project_not_unique')
    project=data['projects'][0]
    if len(project.get('variants',[]))!=1:raise ValueError('fixture_variant_not_unique')
    variant=project['variants'][0];before=deepcopy(variant)
    if not candidate_is_accepted(variant):raise ValueError('fixture_not_accepted')
    gs=variant.get('geometries') or []
    if len(gs)!=1 or gs[0].get('type')!='circle' or gs[0].get('radius')!=1000:
        raise ValueError('fixture_circle_not_plan_baseline')
    circle=gs[0]
    if circle['center']['x']!=0 or circle['center']['y']!=0:raise ValueError('fixture_center_mismatch')
    repaired=[]
    if not variant.get('logical_objects'):
        # Restore the omitted output of the same backend circle execution.
        # This establishes the initial canvas object, not the later copy ID.
        trial=execute_construction_plan({'units':'mm','steps':[{'op':'add_circle','step_id':'circle','output_ref':'circle',
            'semantic':{'label':'圆','object_type':'circle'},'center':{'x':0,'y':0},'radius':1000}]})
        measured=trial['geometries'][0]
        if any(measured[k]!=circle[k] for k in ('id','type','center','radius')):
            raise ValueError('backend_baseline_identity_mismatch')
        variant['logical_objects']=trial['logical_objects']
        repaired=['logical_objects']
        if not variant.get('topology'):
            variant['topology']=trial['topology'];repaired.append('topology')
    ids={g['id'] for g in gs}
    if not variant.get('logical_objects') or any(
        any(i not in ids for i in obj.get('geometry_refs',[])) for obj in variant['logical_objects']):
        raise ValueError('fixture_logical_reference_invalid')
    destination.mkdir(parents=True,exist_ok=False)
    target=destination/'projects.json'
    target.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    store=CreativeProjectStore(target);loaded=store.get(project['id'])
    restored=next(v for v in loaded['variants'] if v['id']==variant['id'])
    for field in ('geometries','identity_contract','acceptance_summary','created_at','selected'):
        if restored.get(field)!=before.get(field):raise ValueError('fixture_reload_changed_'+field)
    if restored['logical_objects']!=variant['logical_objects']:raise ValueError('logical_graph_reload_mismatch')
    selection={'project_id':project['id'],'variant_id':variant['id'],'scope':'group',
               'instance_id':circle.get('template_instance',1),'geometry_ids':[circle['id']]}
    evidence={'source':str(source),'project_id':project['id'],'variant_id':variant['id'],
        'source_geometry_hash':geometry_evidence_hash(before['geometries']),
        'loaded_geometry_hash':geometry_evidence_hash(restored['geometries']),
        'restored_omitted_fields':repaired,'acceptance_unchanged':restored['acceptance_summary']==before['acceptance_summary'],
        'baseline_provenance':'previous independently verified accepted test baseline; not a newly model-generated circle',
        'initial_canvas_selection':selection,'copied_target_id_injected':False}
    (destination/'fixture-check.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    return store,loaded,restored,selection
