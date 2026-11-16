import io
import json
from types import SimpleNamespace
from unittest.mock import patch
from app.agent_service import RobotAgentService


def test_flash_override_disables_thinking_without_changing_default():
    service=RobotAgentService(restore_pending_actions=False)
    original=service.model
    seen=[]
    def transport(payload):
        seen.append(payload)
        response={'model':'deepseek-flash','choices':[{'message':{'content':'{}'},'finish_reason':'stop'}]}
        return None,SimpleNamespace(status=200,read=io.BytesIO(json.dumps(response).encode()).read,close=lambda:None)
    with patch.object(service,'_deepseek_response',side_effect=transport):
        result=service._deepseek_request([],tools=[],model_override='deepseek-flash',max_tokens_override=128)
    assert result['model']=='deepseek-flash'
    assert seen[0]['thinking']=={'type':'disabled'}
    assert service.model==original
