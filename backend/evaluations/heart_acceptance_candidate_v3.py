"""Offline three-way candidate; unresolved source extrema never imply passing."""
from copy import deepcopy
import hashlib
import json
from app.cad_construction import execute_construction_plan, construction_geometry_bounds
from app.cad_construction_interpreter import interpret_construction_request
from evaluations.heart_acceptance_candidate_v2 import compare as compare_v2
from evaluations.bezier_layout_minimum_v1 import measure

VERSION='cad.heart-acceptance-candidate.v3'


def compare(source,payload,*,_minimum_measure=None):
    previous=compare_v2(source,payload)
    base={'version':VERSION,'scope':'offline_three_way_comparison_only','v2_result':previous,
        'legacy_passed':previous['legacy_passed'],'formal_candidate_accepted':False}
    def verdict(decision,reason,**details):
        return {**base,'decision':decision,'candidate_passed':decision=='passed',
            'reason':reason,**details}
    if not previous.get('v1_candidate_passed'):
        status=previous.get('candidate_status')
        return verdict('rejected' if status=='invalid' else 'undetermined','inherited_checks_not_passed')
    baseline=interpret_construction_request(source,lambda *_:deepcopy(payload),force_structured_model=True)
    plan=baseline['plan'];trial=execute_construction_plan(plan)
    digest=hashlib.sha256(json.dumps(trial['geometries'],sort_keys=True).encode()).hexdigest()
    if digest!=previous['geometry_sha256']:raise RuntimeError('Rule comparison changed geometry')
    details={'geometry_unchanged':True,'geometry_sha256':digest}
    steps=plan['steps']
    if len(steps)!=1 or plan.get('constraints'):
        return verdict('undetermined','source_transform_not_audited',**details)
    if steps[0]['op']=='add_polyline':
        return verdict('passed' if previous['candidate_passed'] else 'rejected',
            'literal_polyline_uses_existing_taper_rule',**details)
    minimum=(_minimum_measure or measure)(plan);details['source_minimum']=minimum
    if minimum['status']!='mapped_analytic_candidates':
        return verdict('undetermined','source_extremum_not_resolved',**details)
    if minimum['minimum_kind']=='flat_interval':
        widths=[p['x_interval_mm'][1]-p['x_interval_mm'][0] for p in minimum['minimum_intervals_mm']]
        return verdict('rejected' if max(widths)>.5 else 'undetermined','source_has_lowest_flat_interval',**details)
    if minimum['minimum_kind']!='isolated_point':
        return verdict('undetermined','multiple_source_minima_need_relation_measurement',**details)
    bounds=construction_geometry_bounds(trial['geometries'])
    cx=(bounds['min_x']+bounds['max_x'])/2
    if abs(minimum['minimum_points_mm'][0][0]-cx)>.5:
        return verdict('rejected','source_minimum_not_central',**details)
    if not previous['candidate_passed']:
        return verdict('undetermined','isolated_source_minimum_does_not_resolve_failed_sample_sections',**details)
    return verdict('passed','existing_checks_and_mapped_source_minimum_agree',**details)
