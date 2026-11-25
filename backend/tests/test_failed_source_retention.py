from copy import deepcopy
import json
from pathlib import Path
from app.agent_service import RobotAgentService
from app.creative_projects import CreativeProjectStore
from app.cad_construction_commit import retain_failed_construction_source

DATA=json.loads((Path(__file__).parent/'fixtures/frozen_holdout_repair_context_20261124.json').read_text(encoding='utf-8'))


def test_failure_retains_source_and_restart_confirmation_uses_same_project(monkeypatch,tmp_path):
    source=DATA['original']['evidence_text'][0]
    path=tmp_path/'projects.json';store=CreativeProjectStore(path)
    monkeypatch.setattr('app.agent_service.get_creative_project_store',lambda:store)
    first_service=RobotAgentService(restore_pending_actions=False)
    monkeypatch.setattr(first_service,'_interpret_cad_construction_plan',lambda *a,**kw:{
        'status':'invalid','provider_attempted':True,'error':{'code':'invalid_plan','message':'self intersection'}})
    first=first_service._formal_cad_construction(source,{'name':'drawing_design','operation':'create'},mode='advanced')
    assert not first['ok'] and not first.get('variant')
    project=store.get(first['project_id'])
    assert project['original_prompt']==source and not project['variants']
    req=project['requirements']
    assert req['source_validation_at_retention']=='not_completed' and 'dimensions' not in req
    assert req['requirement_ledger']['sources'][0]['text']==source
    # Fresh service/store emulates a new HTTP worker, not in-memory recovery.
    restored=CreativeProjectStore(path)
    monkeypatch.setattr('app.agent_service.get_creative_project_store',lambda:restored)
    second_service=RobotAgentService(restore_pending_actions=False)
    calls=[]
    def callback(text,schema):
        calls.append(text);return deepcopy(DATA['geometry_repair'])
    monkeypatch.setattr(second_service,'_cad_construction_model_callback',lambda **kw:(callback,{'provider_attempted':True,'request_attempts':1}))
    result=second_service._formal_cad_construction('确认需求并生成CAD候选，只预览，不执行小车。',
        {'name':'drawing_design','operation':'create','stage':'candidate_generation','selected_project_id':project['id']},mode='advanced')
    assert result['ok'],result
    assert result['project_id']==project['id']
    assert calls and source in calls[0]
    assert restored.get(project['id'])['variants'][0]['acceptance_summary']['status']=='passed'


def test_retention_does_not_turn_conflicts_into_ready_requirements(tmp_path):
    from app.cad_project_candidates import candidate_requirement_readiness
    store=CreativeProjectStore(tmp_path/'projects.json')
    source='画一个矩形，宽不超过1米，宽至少2米，高1米。'
    project=retain_failed_construction_source(source,store=store)
    assert not project['variants']
    assert not candidate_requirement_readiness(project,{})['ready']


def test_stale_explicit_project_id_does_not_create_another_project(monkeypatch,tmp_path):
    store=CreativeProjectStore(tmp_path/'projects.json')
    monkeypatch.setattr('app.agent_service.get_creative_project_store',lambda:store)
    service=RobotAgentService(restore_pending_actions=False)
    result=service._formal_cad_construction('确认需求并生成CAD候选，只预览，不执行小车。',
        {'name':'drawing_design','operation':'create','selected_project_id':'missing'},mode='advanced')
    assert result['ok'] is False and not result.get('project')
