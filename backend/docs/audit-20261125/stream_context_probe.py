"""Offline adapter/fault-injection probe; no model or hardware calls."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, Mock

import app.agent_http_service as service
from app.agent_run_store import AgentRunStore
from app.schemas import AgentChatRequest

context = {'project_id': None, 'operation': 'create', 'drawing_selection': None,
           'request_id': 'offline-review-probe'}
context['sha256'] = hashlib.sha256(json.dumps(context, ensure_ascii=False,
    sort_keys=True, separators=(',', ':')).encode()).hexdigest()
prepared = {'history': [], 'memory_before': {}, 'navigation_result': None,
            'resolution': {}, 'model_message': 'probe', 'knowledge': {}, 'stale_guide': None,
            'route': {'name': 'drawing_design', 'tool_family': 'cad', 'operation': 'create',
                      'drawing_selection': None, 'execution_context': context}}

class UpstreamResult:
    configured = False
    mode = 'local'
    def _project_id_from_route(self, route): return None
    def knowledge_context(self, *a): return {}
    def enrich_result(self, result, *a): return result
    def chat(self, *a, **k): return {'ok': True, 'message': 'offline upstream result'}
    def chat_stream(self, *a, **k):
        yield {'type': 'result', 'ok': True, 'message': 'offline upstream result'}

command = AgentChatRequest(message='probe', mode='advanced', client_id='review-user')
memory = Mock()
memory.context.return_value = {}
memory.remember.return_value = {}
out = {'scope': 'Real sync/stream adapters and resume guard; prepared context and upstream response injected. No real CAD/model generation.'}

with TemporaryDirectory() as temporary:
    store = AgentRunStore(Path(temporary)/'runs.json')
    with patch.object(service, 'robot_agent', UpstreamResult()), \
         patch.object(service, 'conversation_memory', memory), \
         patch.object(service, 'agent_runs', store), \
         patch.object(service, '_prepare_agent_chat_context', side_effect=lambda c: deepcopy(prepared)):
        out['context_validation_error'] = service._execution_context_error(prepared['route'])
        sync_result = service._agent_chat(command, prepared=deepcopy(prepared))
        out['sync_result_has_execution_context'] = sync_result.get('execution_context') == context
        events = [json.loads(value) for value in service._agent_chat_stream_events(command, prepared=deepcopy(prepared))]
        terminal = next(value for value in events if value.get('type') == 'result')
        out['stream_result_has_execution_context'] = terminal.get('execution_context') == context
        with patch.object(service, '_finalize_run_result', side_effect=RuntimeError('injected interruption after result checkpoint')):
            response = service.agent_chat_stream(command)
            async def consume():
                async for _ in response.body_iterator: pass
            try: asyncio.run(consume())
            except RuntimeError as exc: out['injected_interruption'] = str(exc)
        run = store.list()[0]
        checkpoint = run['checkpoint']
        out['actual_checkpoint_step'] = checkpoint.get('step_id')
        out['actual_checkpoint_has_execution_context'] = isinstance(checkpoint.get('execution_context'), dict)
        out['actual_checkpoint_has_prepared_context'] = isinstance(checkpoint.get('prepared_context'), dict)
        with store._lock:
            store._runs[run['id']]['timeout_at'] = '2000-01-01T00:00:00+00:00'
        paused = store.get(run['id'])
        resumed = service.resume_agent_run(run['id'], client_id='review-user')
        out['paused_state'] = paused['state']
        out['resume_ok'] = resumed['ok']
        out['resume_message'] = resumed['message']

Path('.local-dev/code-capability-audit-20261125/stream-context-probe.json').write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(out, ensure_ascii=False, indent=2))
