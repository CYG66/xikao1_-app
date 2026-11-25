import json
from unittest.mock import patch, PropertyMock
import pytest

from app.agent_service import RobotAgentService
from app.schemas import AgentConfigCommand
from app.user_model_config import UserModelConfigStore
from app.request_context import agent_user_scope


def test_new_and_legacy_user_profiles_default_to_chat_in_both_modes(tmp_path):
    path = tmp_path/'profiles.json'
    path.write_text(json.dumps({'profiles':{'legacy':{'mode':'deepseek','model':'deepseek-chat',
        'advanced_model':'deepseek-reasoner','api_keys':{}}}}),encoding='utf-8')
    store = UserModelConfigStore(path)
    assert store.get('legacy')['advanced_model'] == 'deepseek-chat'
    assert store.get('legacy')['cad_planning_model'] == 'deepseek-chat'
    profile=store.update('new',mode='deepseek',model='deepseek-chat',cad_planning_model='deepseek-reasoner')
    assert profile['advanced_model']=='deepseek-chat'
    assert UserModelConfigStore(path).get('new')['cad_planning_model']=='deepseek-reasoner'
    store.update('new',mode='deepseek',model='deepseek-chat')
    assert store.get('new')['cad_planning_model']=='deepseek-reasoner'


def test_backend_defaults_and_optional_planning_override_are_separate(tmp_path):
    with patch.dict('os.environ',{'XLINE_AGENT_PROVIDER':'deepseek','DEEPSEEK_MODEL':'deepseek-chat',
        'DEEPSEEK_BASE_MODEL':'','DEEPSEEK_ADVANCED_MODEL':'','DEEPSEEK_CAD_PLANNING_MODEL':''}), patch.object(RobotAgentService,'_load_config'):
        service=RobotAgentService(restore_pending_actions=False)
    assert service._model_for_agent_mode('advanced')=='deepseek-chat'
    assert service.cad_planning_model=='deepseek-chat'
    store=UserModelConfigStore(tmp_path/'users.json')
    with patch('app.agent_service.user_model_config',store), agent_user_scope('owner'):
        service.update_config('deepseek','deepseek-chat',cad_planning_model='deepseek-reasoner')
        assert service._model_for_agent_mode('advanced')=='deepseek-chat'
        assert service.cad_planning_model=='deepseek-reasoner'
        with patch.object(RobotAgentService,'configured',new_callable=PropertyMock,return_value=True), patch.object(service,'_structured_review_text',return_value='{}') as review:
            callback,_=service._cad_construction_model_callback(mode='advanced')
            callback('生成图形',{})
        assert review.call_args.kwargs['model_override']=='deepseek-reasoner'
    with patch('app.agent_service.user_model_config',store), agent_user_scope('other'):
        assert service.cad_planning_model=='deepseek-chat'


def test_local_settings_roundtrip_keeps_planning_choice(tmp_path):
    service=RobotAgentService(restore_pending_actions=False)
    service.config_path=tmp_path/'config.json';service.api_keys={}
    with agent_user_scope(None):
        service.update_config('deepseek','deepseek-chat',cad_planning_model='deepseek-reasoner')
        assert service.advanced_model=='deepseek-chat'
        assert json.loads(service.config_path.read_text(encoding='utf-8'))['cad_planning_model']=='deepseek-reasoner'
        service._cad_planning_model='deepseek-chat'
        with patch.dict('os.environ',{'DEEPSEEK_CAD_PLANNING_MODEL':''}):service._load_config()
        assert service.cad_planning_model=='deepseek-reasoner'


def test_invalid_planning_model_rejected_by_http_contract():
    with pytest.raises(ValueError):AgentConfigCommand(mode='deepseek',model='deepseek-chat',cad_planning_model='unknown')


def test_config_endpoint_roundtrip_scopes_optional_reasoner_to_owner(tmp_path):
    from app.routers.agent import update_agent_config, agent_config
    service=RobotAgentService(restore_pending_actions=False)
    store=UserModelConfigStore(tmp_path/'users.json')
    with patch('app.routers.agent.robot_agent',service), patch('app.agent_service.user_model_config',store):
        saved=update_agent_config(AgentConfigCommand(mode='deepseek',model='deepseek-chat',
            cad_planning_model='deepseek-reasoner',client_id='planning-owner'))
        assert saved['advanced_model']=='deepseek-chat' and saved['cad_planning_model']=='deepseek-reasoner'
        assert agent_config('planning-owner')['cad_planning_model']=='deepseek-reasoner'
        assert agent_config('other-owner')['cad_planning_model']=='deepseek-chat'


def test_explicit_planning_reasoner_does_not_change_normal_structured_requests():
    service=RobotAgentService(restore_pending_actions=False);service.mode='deepseek'
    response={'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}
    with patch.object(RobotAgentService,'configured',new_callable=PropertyMock,return_value=True), patch.object(service,'_model_for_agent_mode',return_value='deepseek-chat'), patch.object(service,'_deepseek_request',return_value=response) as provider:
        service._structured_review_text([],mode='advanced',model_override='deepseek-reasoner')
        assert provider.call_args.kwargs['model_override']=='deepseek-reasoner'
        assert provider.call_args.kwargs['stream_structured'] is True
        service._structured_review_text([],mode='advanced')
        assert 'model_override' not in provider.call_args.kwargs
        assert provider.call_args.kwargs['stream_structured'] is False
