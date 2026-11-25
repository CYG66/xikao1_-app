from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_semantic_source_coverage import verify_semicircular_outline_source
from app.cad_structure_contract import StructureContractError

ROW=json.loads((Path(__file__).parent/'fixtures/arch_failed_boundary.json').read_text(encoding='utf-8'))


def test_proven_bad_boundary_is_a_repairable_error_not_a_draft():
    plan=deepcopy(ROW['plans'][0]);gs=execute_construction_plan(plan)['geometries']
    with pytest.raises(StructureContractError) as caught:
        verify_semicircular_outline_source(ROW['source'],gs)
    assert caught.value.details['reason']=='non_semicircular_boundary_edge'
    assert caught.value.details['geometry_ids']==[gs[0]['id']]
    result=interpret_construction_request(ROW['source'],lambda *_:{'schema_version':'cad.construction-interpretation.v1',
        'is_construction_request':True,'confidence':.99,'evidence_text':[ROW['source']],'plan':deepcopy(plan)},force_structured_model=True)
    assert result['status']=='invalid'
    assert result['construction_error']['code']=='structure_requirement_failed'
    assert result['construction_error']['details']['reason']=='non_semicircular_boundary_edge'
    assert plan==ROW['plans'][0]


def test_correct_replan_and_unknown_clause_keep_existing_boundaries():
    gs=execute_construction_plan(ROW['plans'][1])['geometries']
    assert verify_semicircular_outline_source(ROW['source'],gs)['coverage']=='complete'
    assert verify_semicircular_outline_source(ROW['source']+'整体旋转12度。',gs)['coverage']=='partial'


@pytest.mark.parametrize('correct_geometry',[True,False])
def test_single_production_request_repairs_and_persists_only_correct_geometry(correct_geometry,monkeypatch,tmp_path):
    from app.agent_service import RobotAgentService
    from app.creative_projects import CreativeProjectStore
    from app.cad_candidate_state import candidate_is_accepted
    bad=deepcopy(ROW['plans'][0]);fixed=deepcopy(bad)
    fixed['steps'][0]['segments']=deepcopy(ROW['plans'][1]['steps'][0]['segments'])
    calls=[]
    def callback(text,schema):
        calls.append(text)
        return {'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
                'confidence':.99,'evidence_text':[ROW['source']],
                'plan':deepcopy(fixed if correct_geometry and len(calls)>1 else bad)}
    service=RobotAgentService(restore_pending_actions=False);service.mode='deepseek'
    monkeypatch.setattr(service,'_cad_construction_model_callback',lambda **kw:(callback,{'provider_attempted':True,'request_attempts':1}))
    store=CreativeProjectStore(tmp_path/'projects.json')
    monkeypatch.setattr('app.agent_service.get_creative_project_store',lambda:store)
    result=service._formal_cad_construction(ROW['source'],{'name':'drawing_design','operation':'create'},mode='advanced')
    assert 2<=len(calls)<=3
    assert 'non_semicircular_boundary_edge' in calls[1]
    assert ROW['source'] in calls[1]
    assert bool(result['ok'])==correct_geometry,result
    if correct_geometry:
        assert candidate_is_accepted(result['variant'])
        p=store.get(result['project_id'])
        assert len(p['variants'])==1 and candidate_is_accepted(p['variants'][0])
        assert p['variants'][0]['construction_record']['recovery']['repair_count']==1
    else:
        assert not result.get('variant')
        assert not store.get(result['project_id'])['variants']
