"""Exercise real offline HTTP business helpers on measured accepted versions."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json

import app.agent_http_service as http
from app.agent_run_store import AgentRunStore
from app.conversation_memory import ConversationMemoryStore
from app.creative_projects import CreativeProjectStore
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_revision import verify_variant_revision_for_planning
from app.schemas import AgentChatRequest

out = {'scope': 'Real agent_chat preparation/navigation/finalization and isolated real stores. No provider/model/hardware call; versions built and measured by existing deterministic interpreter.'}
with TemporaryDirectory() as temp:
    root = Path(temp)
    projects = CreativeProjectStore(root/'projects.json')
    memory = ConversationMemoryStore(root/'memory.json')
    runs = AgentRunStore(root/'runs.json')
    initial = interpret_construction_request('画一个圆，圆心(0,0)，半径1米')
    moved = interpret_construction_request('画一个圆，圆心(2,0)，半径1米')
    project = projects.create('review navigation', '画一个圆，圆心(0,0)，半径1米',
                              requirements={'shape': 'circle'})
    def add(source, **extra):
        trial = source['trial_result']
        return projects.add_variant(project['id'], 'measured version', trial['geometries'], '',
            {'feasibility': trial['feasibility']}, [], logical_objects=trial['logical_objects'],
            topology=trial['topology'], acceptance_summary=source['acceptance_summary'], **extra)
    parent = add(initial)
    child = add(moved, parent_variant_id=parent['id'])
    assert child is not None, 'Probe fixture failed to construct measured child'
    out['initial_acceptance'] = initial['acceptance_summary']['status']
    out['child_acceptance'] = moved['acceptance_summary']['status']
    out['child_revision_gate'] = verify_variant_revision_for_planning(child)
    projects.begin_design_iteration(project['id'], child['id'])
    memory.remember('review-navigation', '移动第1个图形', {
        'ok': True, 'project_id': project['id'], 'variant': child,
        'cad_edit_command': {'schema': 'cad.instance_edit.v1', 'operation': 'translate',
            'target_instance_id': 1, 'parameters': {'dx_mm': 2000, 'dy_mm': 0}}})
    with patch.object(http, 'get_creative_project_store', return_value=projects), \
         patch.object(http, 'conversation_memory', memory), patch.object(http, 'agent_runs', runs), \
         patch.object(http.robot_agent, 'chat', side_effect=AssertionError('Model path forbidden')):
        result = http.agent_chat(AgentChatRequest(message='撤销刚才的修改', mode='advanced',
                                                   conversation_id='review-navigation'))
    out['response_ok'] = result.get('ok')
    out['visibility'] = result.get('candidate_visibility')
    out['rollback_verification'] = result.get('rollback_verification')
    out['returned_variant'] = result.get('variant')
    out['stored_base_is_parent'] = projects.get(project['id']).get('design_base_variant_id') == parent['id']
    out['stored_variant_count'] = len(projects.get(project['id'])['variants'])
    out['run_state'] = runs.list()[0]['state']

Path('.local-dev/code-capability-audit-20261125/phase2-navigation-probe.json').write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(out, ensure_ascii=False, indent=2))
