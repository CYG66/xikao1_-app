from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.incremental_cad import parse_incremental_edit
from app.cad_edit_session import fresh_creation


@pytest.mark.parametrize('text',[
    '把圆的半径改为460毫米，其他图形保持不变。',
    '将左圆的半径改为510毫米，圆心不动，其他图形保持不变。',
    '将下矩形整体向右移动230毫米，尺寸不变，其他图形保持不变。',
])
def test_delivery_intent_does_not_turn_an_edit_into_creation_or_drive(text):
    full=text+'只生成预览，不执行小车。'
    assert parse_incremental_edit(full)==parse_incremental_edit(text)
    assert parse_incremental_edit(full) is not None
    assert not fresh_creation(full)
    assert parse_incremental_edit(full+'执行小车。') is None


@pytest.mark.parametrize('with_variant',[True,False])
def test_bound_version_edit_cannot_be_downgraded_by_create_classifier(with_variant,monkeypatch,tmp_path):
    from app import agent_http_service as http
    from app.agent_service import RobotAgentService
    from app.schemas import AgentChatRequest
    from app.creative_projects import CreativeProjectStore
    from app.conversation_memory import ConversationMemoryStore
    fixture=Path(__file__).parent/'fixtures/edit_transport_parent.json'
    target=tmp_path/'projects.json';target.write_bytes(fixture.read_bytes())
    store=CreativeProjectStore(target);project=store.list()[0]
    monkeypatch.setattr(http,'get_creative_project_store',lambda:store)
    monkeypatch.setattr('app.agent_service.get_creative_project_store',lambda:store)
    monkeypatch.setattr(http,'conversation_memory',ConversationMemoryStore(tmp_path/'memory.json'))
    service=RobotAgentService(restore_pending_actions=False)
    monkeypatch.setattr(service,'resolve_intent',lambda *a,**k:{'name':'drawing_design','operation':'create','tool_family':'cad'})
    monkeypatch.setattr(service,'knowledge_context',lambda *a,**k:{})
    monkeypatch.setattr(http,'robot_agent',service)
    before=deepcopy(store.get(project['id']))
    body={'message':'将左圆的半径改为510毫米，圆心不动。只生成预览，不执行小车。',
          'mode':'advanced','conversation_id':'bound-test','project_id':project['id']}
    if with_variant:body['variant_id']=project['variants'][0]['id']
    prepared=http._prepare_agent_chat_context(AgentChatRequest(**body))
    assert prepared['route']['operation']==('modify' if with_variant else 'create')
    if with_variant:
        assert prepared['route']['decision_source']=='incremental_cad_edit'
        assert prepared['route']['resolved_edit']['value_mm']==510
    assert store.get(project['id'])==before
