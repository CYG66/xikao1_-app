from unittest.mock import patch
from app.rosbridge_protocol import handle_rosbridge_payload

def test_mission_rejection_echoes_request_id_for_current_command():
    with patch('app.rosbridge_protocol.ros_adapter.owns_control',return_value=False):
        result=handle_rosbridge_payload({'op':'mission_control','action':'start','file_name':'a.json','client_id':'owner','request_id':'mission-123'})
    assert result['ok'] is False
    assert result['request_id']=='mission-123'

def test_legacy_mission_payload_does_not_change_response_shape():
    with patch('app.rosbridge_protocol.ros_adapter.owns_control',return_value=False):
        result=handle_rosbridge_payload({'op':'mission_control','action':'start','file_name':'a.json','client_id':'owner'})
    assert result=={'op':'mission_response','ok':False,'message':'control lease required'}
