"""Offline fault injection into existing service adapters; no network or devices."""
from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.agent_service import RobotAgentService

network_guard = patch('urllib.request.urlopen', side_effect=AssertionError('Network forbidden'))
https_guard = patch('http.client.HTTPSConnection', side_effect=AssertionError('Network forbidden'))
urlopen_calls = network_guard.start()
https_calls = https_guard.start()


class Response:
    status = 200

    def __init__(self, events):
        self.lines = iter(('data: ' + json.dumps(event) + '\n').encode() for event in events)

    def readline(self):
        return next(self.lines, b'')

    def close(self):
        pass


service = RobotAgentService(restore_pending_actions=False)
service.mode = 'deepseek'
service.api_keys = {'deepseek': 'offline-test-placeholder'}
service.model = service.base_model = service.advanced_model = 'deepseek-flash'
route = {'name': 'drawing_design', 'operation': 'create', 'tool_family': 'cad'}
tool_delta = {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'review-call',
    'function': {'name': 'parameterize_design', 'arguments': '{"request":"rectangle"}'}}]}}]}
out = {'scope': 'Injected transport events and bypassed unrelated routing only; '
                'real stream loop/request adapter, file preview and config loader. '
                'No live API, actual tool dispatch, candidate save or hardware execution.'}
out['stream_termination'] = []
for kind, events in (('unexpected_eof', [tool_delta]),
                     ('provider_error_then_eof', [tool_delta, {'error': {'message': 'offline upstream aborted'}}])):
    payloads = []

    def transport(payload):
        payloads.append(deepcopy(payload))
        return None, Response(events)

    with patch.object(service, '_deepseek_response', side_effect=transport), \
         patch.object(service, '_system_context', return_value='offline prompt'), \
         patch.object(service, '_stale_project_guard', return_value=None), \
         patch.object(service, '_pending_design_followup', return_value=None), \
         patch.object(service, '_apply_design_requirement_followup', return_value=None), \
         patch.object(service, '_run_advanced_cad_pipeline', return_value=(route, None)), \
         patch.object(service, '_streamed_tool_result', return_value={'ok': True, 'message': 'dispatcher reached'}) as dispatch:
        result_events = list(service._chat_stream_impl('整理参数', [], mode='advanced', route=route))
    with patch.object(service, '_deepseek_response', side_effect=transport):
        try:
            service._deepseek_request([{'role': 'user', 'content': 'offline'}],
                                     tools=[], mode='advanced', stream_structured=True)
        except RuntimeError as exc:
            structured = {'rejected': True, 'message': str(exc)}
        else:
            structured = {'rejected': False}
    out['stream_termination'].append({'case': kind, 'input_has_finish_reason': False,
        'tool_dispatch_boundary_reached': dispatch.call_count,
        'stream_result_events': result_events, 'structured_adapter': structured,
        'stream_thinking_field': payloads[0].get('thinking'),
        'structured_thinking_field': payloads[1].get('thinking')})

socket = Mock()
response = SimpleNamespace(fp=SimpleNamespace(raw=SimpleNamespace(_sock=socket)))
connection = SimpleNamespace(sock=None)
service._set_deepseek_socket_timeout(connection, time.monotonic() + 10)
wrapper_calls = socket.settimeout.call_count
service._deepseek_transport().set_socket_timeout(connection, time.monotonic() + 10, response=response)
out['stream_socket_timeout_adapter'] = {'wrapper_settimeout_calls': wrapper_calls,
                                       'direct_transport_settimeout_calls': socket.settimeout.call_count - wrapper_calls}

with TemporaryDirectory() as temp:
    source = Path(temp) / 'source.json'
    geometries = [{'id': i, 'type': 'line', 'layer_id': 1,
        'start': {'x': x, 'y': 0}, 'end': {'x': x + 1000, 'y': 0}}
        for i, x in ((1, 0), (2, 5000))]
    objects = [{'object_id': f'part-{i}', 'geometry_refs': [i], 'label': f'part-{i}'} for i in (1,2)]
    topology = {'shared_geometries': [], 'relations': [{
        'source_object_id': 'part-1', 'target_object_id': 'part-2', 'relation': 'left_of'}]}
    source.write_text(json.dumps({'unit': 'mm', 'lines': geometries,
                                 'logical_objects': objects, 'topology': topology}), encoding='utf-8')
    before = source.read_bytes()
    with patch.dict(os.environ, {'XLINE_CAD_DIR': temp}):
        prepared = service._prepare_drawing_modification({'source_file_name': source.name,
            'target': {'scope': 'geometry', 'geometry_ids': [1]},
            'operations': [{'op': 'update', 'geometry_id': 1, 'patch': {'end': {'x': 2000, 'y': 0}}}]})
    out['standalone_graph_preservation'] = {'preparation_ok': prepared.get('ok'),
        'message': prepared.get('message'), 'source_object_count': len(objects),
        'source_relation_count': len(topology['relations']),
        'prepared_objects': prepared.get('payload', {}).get('logical_objects'),
        'prepared_topology': prepared.get('payload', {}).get('topology'),
        'source_unchanged': source.read_bytes() == before}

    config_service = RobotAgentService(restore_pending_actions=False)
    config_service.config_path = Path(temp) / 'isolated-config.json'
    config_service.api_keys = {}
    with patch.dict(os.environ):
        os.environ.pop('DEEPSEEK_CAD_PLANNING_MODEL', None)
        saved = config_service.update_config('local', 'offline-model', cad_planning_model='deepseek-flash')
        config_service._cad_planning_model = 'deepseek-chat'
        config_service._load_config()
        out['planning_model_config_roundtrip'] = {
            'saved_model': saved['cad_planning_model'],
            'file_model': json.loads(config_service.config_path.read_text(encoding='utf-8'))['cad_planning_model'],
            'reloaded_model': config_service.cad_planning_model}

destination = Path('.local-dev/code-capability-audit-20261125/phase6-probes.json')
out['network_guard_calls'] = {'urlopen': urlopen_calls.call_count, 'https_connection': https_calls.call_count}
network_guard.stop()
https_guard.stop()
destination.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(out, ensure_ascii=True, indent=2))
