"""Read-only code review probes with isolated stores and mocked device calls."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.conversation_memory import ConversationMemoryStore
from app.agent_skills import _template_layout_requirements, parameterize_design
import app.agent_service as service_module
from app.agent_service import RobotAgentService, set_request_execution_context, reset_request_execution_context
from app.task_store import AgentTaskStore
from app.tooling import validate_tool_arguments

out = {'scope': 'Offline source functions and pending-action lifecycle; no live model or hardware execution.'}
out['unit_equivalence'] = []
for unit in ('毫米', 'mm', '厘米', 'cm', '米', 'm'):
    source = f'矩形宽度20{unit}，高度30{unit}'
    layout = f'两个矩形间距20{unit}'
    out['unit_equivalence'].append({'unit': unit, 'source': source,
        'memory_profile': ConversationMemoryStore._extract_requirements(source),
        'parameterized': parameterize_design(source),
        'layout_source': layout, 'layout_requirements': _template_layout_requirements(layout)})

service = RobotAgentService(restore_pending_actions=False)
try:
    service._recover_candidate_after_empty_response({}, 'advanced')
except Exception as exc:
    out['empty_response_recovery'] = {'exception': type(exc).__name__, 'message': str(exc)}
else:
    out['empty_response_recovery'] = {'exception': None}

context = {'request_id': 'phase2-review', 'operation': 'device_demo'}
context['sha256'] = hashlib.sha256(json.dumps(context, ensure_ascii=False,
    sort_keys=True, separators=(',', ':')).encode()).hexdigest()
not_ready = {'ready': False, 'checks': [{'code': 'control_owner', 'ok': False,
    'detail': 'offline simulated unavailable control lease'}]}
with TemporaryDirectory() as temp:
    store = AgentTaskStore(Path(temp)/'tasks.json')
    with patch.object(service_module, 'agent_tasks', store), \
         patch.object(service_module, 'build_action_preflight', return_value=deepcopy(not_ready)), \
         patch.object(service, '_execute_confirmed', side_effect=AssertionError('Hardware execution forbidden')) as executor:
        token = set_request_execution_context(context)
        try:
            original = service._register_pending('drive_robot',
                {'linear': 0.1, 'angular': 0.0, 'duration_seconds': 1.0}, mode='base')
        finally:
            reset_request_execution_context(token)
        first = service._confirm_impl(original['id'], True)
        retry = first.get('pending_action') or {}
        retry_record = store.get(retry.get('id', '')) or {}
        second = service._confirm_impl(retry['id'], True) if retry.get('id') else {}
        out['confirmation_retry_context'] = {
            'original_has_context': isinstance(store.get(original['id']).get('execution_context'), dict),
            'first_retryable': first.get('retryable'), 'retry_created': bool(retry.get('id')),
            'retry_has_context': isinstance(retry_record.get('execution_context'), dict),
            'second_ok': second.get('ok'), 'second_message': second.get('message'),
            'hardware_execution_count': executor.call_count}

with TemporaryDirectory() as temp:
    source = Path(temp)/'source.json'
    source.write_text(json.dumps({'unit': 'mm', 'lines': [{'id': 1, 'type': 'line',
        'start': {'x': 0, 'y': 0}, 'end': {'x': 1000, 'y': 0}}]}), encoding='utf-8')
    before = source.read_bytes()
    arguments = {'source_file_name': source.name, 'target': {'scope': 'geometry', 'geometry_ids': [1]},
        'operations': [{'op': 'update', 'geometry_id': 1, 'patch': {'end': {'x': 2000, 'y': 0}}}]}
    checked, error = validate_tool_arguments('modify_drawing', arguments)
    with patch.dict(os.environ, {'XLINE_CAD_DIR': temp}):
        direct = service._prepare_drawing_modification(service._drop_none_values(checked))
        outputs = []
        early, summaries = service._dispatch_tool_calls([{'id': 'review-call', 'name': 'modify_drawing',
            'arguments': arguments}], service._empty_usage(),
            {'operation': 'modify', 'edit_domain': 'standalone_drawing'}, 'advanced',
            append_result=lambda call, result: outputs.append(result))
    out['standalone_modify_dispatch'] = {'schema_valid': checked is not None, 'schema_error': error,
        'existing_preparation_ok': direct.get('ok'), 'existing_preparation_message': direct.get('message'),
        'dispatcher_early_result': early, 'dispatcher_outputs': outputs,
        'source_unchanged': source.read_bytes() == before}

destination = Path('.local-dev/code-capability-audit-20261125/phase2-probes.json')
destination.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(out, ensure_ascii=False, indent=2))
