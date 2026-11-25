"""Post-hoc diagnostics only. Never updates pilot scores or model budgets."""
from copy import deepcopy
import json
from pathlib import Path


def diagnose(root):
    from app.cad_construction_interpreter import _coerce_model_payload,StructuredConstructionInterpretation,repair_construction_references_once
    from app.cad_construction import execute_construction_plan
    from evaluations.relation_pilot.compiler import compile_relations
    from evaluations.relation_pilot.oracle import evaluate
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    manifest=read(root/'manifest.json');specs={row['id']:row for row in manifest['cases']};rows=[]
    for trial in read(root/'results.json'):
        if trial['passed']:continue
        folder=root/trial['trial'];responses=sorted(folder.glob('response-*.json'))
        record={'trial':trial['trial'],'arm':trial['arm'],'original_passed':False,'scope':'Last-output post-hoc diagnostic, not a score or extra model attempt'}
        try:
            raw=(read(responses[-1]).get('choices') or [{}])[0].get('message',{}).get('content','')
            payload=_coerce_model_payload(raw)
            if trial['arm']=='B':payload,_=compile_relations(payload,specs[trial['case']]['text'])
            payload,repairs=repair_construction_references_once(deepcopy(payload))
            record['reference_repairs']=repairs
            interpreted=StructuredConstructionInterpretation.model_validate(payload)
            if interpreted.plan is None:raise ValueError('no_plan')
            plan=interpreted.plan.model_dump(mode='json')
            try:
                execution=execute_construction_plan(plan)
                record['passes_after_reference_normalization']=evaluate(specs[trial['case']],execution['geometries'])['passed']
            except Exception as error:
                record['after_normalization_error']=str(error)
                if getattr(error,'code',None)=='assertion_failed':
                    diagnostic=deepcopy(plan);diagnostic['assertions']=[]
                    try:
                        execution=execute_construction_plan(diagnostic)
                        record['geometry_passes_without_model_assertions']=evaluate(specs[trial['case']],execution['geometries'])['passed']
                    except Exception as second:record['without_assertions_error']=str(second)
                # A deliberately separate geometry-only probe: remove model
                # assertions and assign temporary unique semantic identities.
                # Coordinates, operations, layout and constraints stay intact.
                # This is never a formal candidate or a replacement score.
                if getattr(error,'code',None) in {'logical_graph_invalid','assertion_failed'}:
                    diagnostic=deepcopy(plan);diagnostic['assertions']=[]
                    for index,step in enumerate(diagnostic['steps']):
                        step.setdefault('semantic',{})['object_id']='diagnostic:'+str(index)
                    try:
                        execution=execute_construction_plan(diagnostic)
                        record['geometry_passes_with_diagnostic_ids_and_no_model_assertions']=evaluate(specs[trial['case']],execution['geometries'])['passed']
                    except Exception as second:record['geometry_only_probe_error']=str(second)
        except Exception as error:record['diagnostic_unavailable']=str(error)
        rows.append(record)
    result={'scope':'Exploratory only; original failures, pass rates and ledger unchanged','rows':rows,
        'summary':{arm:{'failed_trials':sum(r['arm']==arm for r in rows),
            'last_output_passes_after_existing_reference_normalization':sum(r['arm']==arm and r.get('passes_after_reference_normalization',False) for r in rows),
            'last_output_geometry_passes_without_model_assertions':sum(r['arm']==arm and r.get('geometry_passes_without_model_assertions',False) for r in rows)} for arm in ('A','B')}}
    for arm in ('A','B'):
        result['summary'][arm]['last_output_geometry_passes_after_diagnostic_ids_and_assertion_removal']=sum(r['arm']==arm and r.get('geometry_passes_with_diagnostic_ids_and_no_model_assertions',False) for r in rows)
    (root/'failure-diagnostics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result['summary'],ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,required=True)
    diagnose(parser.parse_args().run)
