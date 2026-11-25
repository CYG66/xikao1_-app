from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app import cad_geometry_measurements as measurements
from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_path_relation_acceptance import verify_path_relations
from app.cad_symmetric_divider_acceptance import verify_symmetric_divider_source
from app.cad_structure_contract import StructureContractError,_frame
from app.cad_validation_evidence import ConstructionEvidence

FIXTURES=Path(__file__).parent/'fixtures'


def interpret(source,plan):
    return interpret_construction_request(source,lambda *_:{
        'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
        'plan':deepcopy(plan),'confidence':.99,'evidence_text':[source],'assumptions':[]},force_structured_model=True)


@pytest.mark.parametrize('case',['rectangle','layout'])
def test_business_rules_share_one_rectangle_measurement_per_geometry(case):
    if case=='rectangle':row=json.loads((FIXTURES/'recorded_rectangle_handoff.json').read_text(encoding='utf-8'))[0]
    else:row=next(r for r in json.loads((FIXTURES/'recorded_primitive_layout.json').read_text(encoding='utf-8')) if r['case']=='A11')
    before=deepcopy(row['plan'])
    with patch.object(measurements,'rectangle_frame',wraps=measurements.rectangle_frame) as measured:
        result=interpret(row['source'],row['plan'])
    assert result['status']=='ready',result.get('error')
    assert result['acceptance_summary']['status']=='passed'
    counts=Counter(call.args[0]['id'] for call in measured.call_args_list)
    assert counts and all(count==1 for count in counts.values())
    assert row['plan']==before


def test_s_path_sampling_is_shared_without_combining_business_rules():
    row=json.loads((FIXTURES/'recorded_symmetric_divider.json').read_text(encoding='utf-8'))
    source='\n'.join([row['original'],*row['followups']])
    with patch.object(measurements,'path_geometry_facts',wraps=measurements.path_geometry_facts) as measured:
        result=interpret(source,row['plan'])
    assert result['acceptance_summary']['status']=='passed'
    assert measured.call_count==1
    assert 'path_relation_acceptance' in result['source_acceptance']
    assert 'divider_acceptance' in result['source_acceptance']


def test_s_path_and_source_radius_share_native_circle_facts():
    row=json.loads((FIXTURES/'recorded_symmetric_divider.json').read_text(encoding='utf-8'))
    with patch.object(measurements,'circle_facts',wraps=measurements.circle_facts) as measured:
        result=interpret(row['original'],row['plan'])
    assert result['acceptance_summary']['status']=='passed'
    counts=Counter(call.args[0]['id'] for call in measured.call_args_list)
    assert counts and all(count==1 for count in counts.values())


def test_symmetric_dot_shift_still_distinguishes_generic_and_extra_constraints():
    row=json.loads((FIXTURES/'recorded_symmetric_divider.json').read_text(encoding='utf-8'))
    gs=execute_construction_plan(row['plan'])['geometries']
    dots=sorted([g for g in gs if g['type']=='circle'],key=lambda g:g['radius'])[:2]
    dots[0]['center']['y']+=100;dots[1]['center']['y']-=100
    context=ConstructionEvidence()
    generic=verify_path_relations(row['original'],gs,evidence_context=context)
    assert generic['status']=='partial' and all(c['status']=='passed' for c in generic['checks'])
    with pytest.raises(StructureContractError,match='小圆分别位于两瓣中心'):
        verify_symmetric_divider_source(row['original'],gs,evidence_context=context)


def test_generic_sampled_path_support_is_preserved():
    from app.drawing_store import _geometry_points
    row=json.loads((FIXTURES/'recorded_symmetric_divider.json').read_text(encoding='utf-8'))
    gs=execute_construction_plan(row['plan'])['geometries']
    sampled=[g if g['type']!='arc' else {'id':g['id'],'type':'polyline','closed':False,
        'vertices':[{'x':p[0]*1000,'y':p[1]*1000} for p in _geometry_points(g)]} for g in gs]
    assert verify_path_relations(row['original'],sampled)['status']=='partial'
    assert verify_symmetric_divider_source(row['original'],sampled)['coverage']=='partial'


def test_measurement_context_does_not_reuse_rectangle_after_geometry_change():
    gs=[{'id':1,'type':'polyline','closed':True,'vertices':[
        {'x':0,'y':0},{'x':4,'y':0},{'x':4,'y':2},{'x':0,'y':2}]}]
    context=ConstructionEvidence()
    assert _frame(gs[0],evidence_context=context)==(0,0,4,2)
    gs[0]['vertices'][1]['x']=5
    assert _frame(gs[0],evidence_context=context) is None


def test_same_trial_owner_can_be_forwarded_without_disabling_evidence_reuse():
    context=ConstructionEvidence();calls=[]
    def verify(source,*,evidence_context):calls.append(1);return {'source':source}
    assert context.measure(verify,'source',evidence_context=context)==context.measure(verify,'source',evidence_context=context)
    assert len(calls)==1
