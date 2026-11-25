from copy import deepcopy
from pathlib import Path
import json
from unittest.mock import patch

import pytest

from app.cad_requirement_contract import requirement_contract
from app.cad_structure_contract import explicit_dimensions, StructureContractError
from app.cad_source_acceptance import verify_final_source_contract
from app.cad_construction import execute_construction_plan

FIXTURES=json.loads((Path(__file__).parent/'fixtures/recorded_component_scope.json').read_text(encoding='utf-8'))


def contract(fixture):
    return requirement_contract([{'source_id':str(i),'text':s}
        for i,s in enumerate([fixture['original'],fixture['followup']])])


def test_component_dimensions_are_separate_from_root_and_have_exact_evidence():
    f=FIXTURES[1];c=contract(f)
    active={(v['subject'],v['field']):v['value_mm'] for v in c['facts'] if v['status']=='effective'}
    assert active[('房子轮廓','width')]==4000
    assert active[('房子轮廓','height')]==3000
    assert active[('墙体','height')]==2000
    assert active[('门','width')]==1000
    assert active[('门','height')]==1500
    assert explicit_dimensions(f['source'])==(4,3)
    for v in c['facts']:
        source=[f['original'],f['followup']][int(v['source_id'])]
        e=v['evidence'];assert source[e['start']:e['end']]==e['text']


def test_inline_dimensions_do_not_become_object_identity_or_entire_drawing_bounds():
    f=FIXTURES[0];c=contract(f)
    assert c['subjects']==['矩形']
    facts=[v for v in c['facts'] if v['status']=='effective']
    assert all(v['binding']=='explicit_subject' for v in facts)
    gs=execute_construction_plan(f['plan'])['geometries']
    report=verify_final_source_contract(f['source'],gs)
    assert {v['actual_mm'] for v in report['checks']}=={4000,2000}
    # The circles extend beyond the base rectangle: measuring all geometry is wrong.
    assert all(v['geometry_ids']==[1] for v in report['checks'])
    wrong=deepcopy(gs)
    for p in wrong[0]['vertices']:p['x']*=.9
    with pytest.raises(StructureContractError):verify_final_source_contract(f['source'],wrong)


def test_repeated_primitive_type_stays_unresolved_instead_of_selecting_by_size():
    f=FIXTURES[0];gs=execute_construction_plan(f['plan'])['geometries']
    gs.append({**deepcopy(gs[0]),'id':99})
    report=verify_final_source_contract(f['source'],gs)
    assert report['review_required'] and report['unknown_requirements']


def test_wrong_door_is_still_rejected_at_its_actual_scope():
    f=FIXTURES[1];trial=execute_construction_plan(f['plan']);gs=trial['geometries']
    with pytest.raises(StructureContractError) as caught:
        verify_final_source_contract(f['source'],gs,trial['logical_objects'])
    failures=caught.value.details['failures']
    assert any(v['expected_mm']==1000 and v['geometry_ids']==[2] for v in failures)
    assert not any(v['geometry_ids']==[1,2] for v in failures)


def test_local_followup_does_not_overwrite_persisted_overall_index(tmp_path):
    from app.agent_service import robot_agent
    from app.creative_projects import CreativeProjectStore
    f=FIXTURES[1];store=CreativeProjectStore(tmp_path/'projects.json')
    project=store.create('组合',f['original'],requirements={'shape':'generic_2d_cad',
        'dimensions':{'width_m':4,'height_m':3}},constraints={},missing_parameters=[])
    with patch('app.agent_service.get_creative_project_store',return_value=store):
        result=robot_agent._apply_design_requirement_followup(f['followup'],
            {'selected_project_id':project['id'],'mode':'advanced'})
    assert result is not None
    p=store.get(project['id'])
    assert p['requirements']['dimensions']=={'width_m':4,'height_m':3}
    assert p['requirements']['source_followups']==[f['followup']]


def test_stale_numeric_snapshot_cannot_replace_source_dimensions():
    from app.cad_construction_interpreter import interpret_construction_request
    f=FIXTURES[1]
    snapshot={'original_prompt':f['original'],'requirements':{
        'source_followups':[f['followup']],'dimensions':{'width_m':1,'height_m':1.5}}}
    source='[CAD_REQUIREMENT_CONTRACT_SNAPSHOT.v1]\n'+json.dumps(snapshot,ensure_ascii=False)
    result=interpret_construction_request(source,lambda *_:{
        'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
        'confidence':.99,'evidence_text':[f['original']],'plan':f['plan']},force_structured_model=True)
    assert result['status']=='invalid'
    assert result['construction_error']['code']=='structure_requirement_failed'
    assert result['construction_error']['details']['failures']


def test_component_scope_ends_at_semicolon_instead_of_leaking_to_next_part():
    c=requirement_contract([{'source_id':'s','text':'孔甲：圆，圆心(0,0)，半径1米；孔乙：圆，圆心(3,0)，半径2米'}])
    assert [(v['subject'],v['value_mm']) for v in c['facts']]==[('孔甲',1000),('孔乙',2000)]
