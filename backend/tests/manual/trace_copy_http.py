"""Offline HTTP copy/confirm regression. No provider or hardware access."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--diagnose', action='store_true')
    parser.add_argument('--require-confirmation', action='store_true',
                        help='Test-only extra confirmation via existing production confirmation API')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    os.environ.update({
        'DEEPSEEK_API_KEY': 'offline-no-network', 'XLINE_RUNTIME_PROFILE': 'virtual_sim',
        'XLINE_DATABASE_PATH': str(out/'test.db'),
        'XLINE_CREATIVE_PROJECT_STORE': str(out/'projects.json'),
        'XLINE_AGENT_MEMORY_STORE': str(out/'memory.json'),
        'XLINE_AGENT_TASK_STORE': str(out/'tasks.json'),
        'XLINE_AGENT_RUN_STORE': str(out/'runs.json'),
        'XLINE_AGENT_AUDIT_STORE': str(out/'audit.jsonl'),
        'XLINE_AGENT_PLAN_STORE': str(out/'plans.sqlite'), 'XLINE_CAD_DIR': str(out/'cad'),
    })
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import app.agent_service as service
    import app.creative_projects as cp
    from app.routers.agent import router
    from app.task_store import agent_tasks
    from app.cad_construction import execute_construction_plan
    from app.cad_candidate_state import candidate_is_accepted
    from app.cad_target_resolver import resolve_created_target, recent_creation_selector
    import app.cad_target_resolver as target_resolver
    store = cp.CreativeProjectStore(out/'projects.json')
    cp._project_store = store
    project = store.create('HTTP identity fixture', '一个圆，半径1米，圆心(0,0)',
                           {'shape': 'circle', 'quantity': 1}, {}, [])
    trial = execute_construction_plan({'units':'mm','steps':[{'op':'add_circle',
        'step_id':'circle','output_ref':'circle','semantic':{'label':'圆','object_type':'circle'},
        'center':{'x':0,'y':0},'radius':1000}]})
    circle = trial['geometries'][0]
    circle['template_instance'] = 1
    assert circle['radius'] == 1000 and circle['center']['x'] == circle['center']['y'] == 0
    # Acceptance is independent measurement of this initial fixture only.
    initial = store.add_variant(project['id'], 'initial', trial['geometries'], 'fixture', {}, [],
        logical_objects=trial['logical_objects'], topology=trial['topology'],
        acceptance_summary={'status':'passed','review_required':False,
                            'authority':'independently_measured_initial_fixture'})
    original = deepcopy(initial['geometries'][0])
    trace = []
    current = {'variant': initial['id']}
    confirmation_requested = []
    def record(boundary, contract=None, variant=None, **extra):
        contract = contract or {}
        proof = contract.get('execution_identity') or {}
        mapping = (variant or {}).get('reference_mapping') or {}
        trace.append({'boundary':boundary,'project_id':project['id'],
            'source_variant_id':current['variant'], 'target_variant_id':(variant or {}).get('id'),
            'operation_ids':sorted({m.get('operation_id','') for m in proof.get('members',[])}),
            'execution_identity':deepcopy(proof),'creation_events':deepcopy(mapping.get('creation_events',[])),
            **extra})
    execute = service.edit_candidate_geometries
    build = service.build_cad_edit_contract
    persist = service.robot_agent._persist_candidate_edit
    def traced_execute(source, edit):
        result, error = execute(source, edit)
        record('executor_return:edit.execution_identity', edit,
               source_geometry_ids=[g['id'] for g in source],
               result_geometry_ids=[g['id'] for g in result or []])
        return result, error
    def traced_build(edit, **kwargs):
        record('contract_input:edit.execution_identity', edit)
        contract = build(edit, **kwargs)
        from app.cad_edit_contract import CadEditCommand
        roundtrip = CadEditCommand.model_validate_json(json.dumps(contract)).model_dump(mode='json',by_alias=True)
        record('cad.edit.v2_serialized:execution_identity', roundtrip)
        return contract
    def traced_persist(*pos, **kwargs):
        record('persist_input:cad_edit_contract.execution_identity', kwargs.get('cad_edit_contract'))
        if args.require_confirmation and not confirmation_requested:
            # Selected-circle duplicate is normally low-risk and saves directly.
            # Add a confirmation in this test only, using the actual executor's
            # contract and preview, then exercise unmodified confirm/replay/save.
            from app.cad_edit_gate import build_cad_edit_preflight
            contract = kwargs['cad_edit_contract']
            parent = pos[1]
            preflight = build_cad_edit_preflight(parent['geometries'], pos[2], contract)
            confirmation_requested.append(True)
            return service.robot_agent.request_confirmation('apply_cad_candidate_edit', {
                'project_id':project['id'],'parent_variant_id':parent['id'],
                'parent_geometry_sha256':preflight['source_fingerprint'],
                'edit_contract':contract,'edit_preview':kwargs['edit_preview']},mode='advanced')
        result = persist(*pos, **kwargs)
        record('persist_output:variant.reference_mapping', variant=result.get('variant'))
        return result
    def traced_resolve(variant, project_id, selector):
        result = resolve_created_target(variant, project_id, selector)
        record('target_resolver:reference_mapping.creation_events', variant=variant,
               resolved_geometry_ids=result.get('geometry_ids'), resolution_status=result.get('status'))
        return result
    app = FastAPI(); app.include_router(router)
    def run(client, variant, message, selection=None):
        current['variant'] = variant['id']
        assert store.begin_design_iteration(project['id'], variant['id'])
        body = {'message':message,'mode':'advanced','project_id':project['id'],
                'variant_id':variant['id'],'conversation_id':'copy-http','client_id':'copy-http'}
        if selection: body['drawing_selection'] = selection
        response = client.post('/api/agent/chat', json=body)
        assert response.status_code == 200
        result = response.json()
        pending = result.get('pending_action')
        if pending:
            task = agent_tasks.get(pending['id'])
            record('pending_store_read:arguments.edit_contract', task['arguments'].get('edit_contract'))
            # Verify the persisted confirmation payload, not only the memory copy.
            disk = json.loads((out/'tasks.json').read_text(encoding='utf-8'))
            (out/'pending-task-snapshot.json').write_text(json.dumps(disk,ensure_ascii=False),encoding='utf-8')
            from app.task_store import AgentTaskStore
            disk_task = AgentTaskStore(out/'tasks.json').get(pending['id'])
            assert disk_task['arguments']['edit_contract'] == task['arguments']['edit_contract']
            record('pending_file_reload:arguments.edit_contract', disk_task['arguments']['edit_contract'])
            record('confirm_request:arguments.edit_contract', task['arguments'].get('edit_contract'))
            confirmed = client.post('/api/agent/confirm', json={
                'action_id':pending['id'],'approved':True,'client_id':'copy-http'})
            assert confirmed.status_code == 200
            result = confirmed.json()
        trace.append({'boundary':'http_response','message':message,'ok':result.get('ok'),
                      'edit_outcome':result.get('edit_outcome'),'response_message':result.get('message')})
        return result
    provider_calls = []
    def block_provider(*a, **kw):
        provider_calls.append(True)
        raise AssertionError('No paid model calls allowed')
    completed = False
    try:
        with patch.object(service.robot_agent,'_deepseek_response',side_effect=block_provider), \
             patch.object(service,'edit_candidate_geometries',side_effect=traced_execute), \
             patch.object(service,'build_cad_edit_contract',side_effect=traced_build), \
             patch.object(service.robot_agent,'_persist_candidate_edit',side_effect=traced_persist), \
             patch.object(target_resolver,'resolve_created_target',side_effect=traced_resolve), \
             TestClient(app) as client:
            selection = {'project_id':project['id'],'variant_id':initial['id'],
                         'scope':'group','instance_id':1,'geometry_ids':[original['id']]}
            copied = run(client, initial, '复制这个圆到右侧 3 米。', selection)
            assert copied['ok'], copied.get('message')
            second = copied['variant']
            reloaded = cp.CreativeProjectStore(out/'projects.json').get(project['id'])['variants'][-1]
            record('file_reload:variant.reference_mapping', variant=reloaded)
            if args.diagnose:
                return
            assert bool(confirmation_requested) == args.require_confirmation
            assert reloaded['reference_mapping'] == second['reference_mapping']
            new = [g for g in second['geometries'] if g['id'] != original['id']]
            assert len(new) == 1 and second['geometries'][0] == original
            members = second['reference_mapping']['creation_events'][-1]['members']
            assert [(m['source_geometry_id'],m['geometry_id']) for m in members] == [(original['id'],new[0]['id'])]
            assert second['parent_variant_id'] == initial['id']
            resized = run(client, second, '把刚才复制的圆半径改成 0.5 米。')
            assert resized['ok'], resized.get('message')
            third = resized['variant']; byid = {g['id']:g for g in third['geometries']}
            assert byid[original['id']] == original and byid[new[0]['id']]['radius'] == 500
            assert third['parent_variant_id'] == second['id'] and third['id'] != second['id']
            assert candidate_is_accepted(third)
            reloaded_third = cp.CreativeProjectStore(out/'projects.json').get(project['id'])['variants'][-1]
            assert reloaded_third['geometries'] == third['geometries']
            assert reloaded_third['reference_mapping'] == third['reference_mapping']
            count = len(store.get(project['id'])['variants'])
            unchanged = run(client, third, '把刚才复制的圆半径改成 0.5 米。')
            assert unchanged['cad_edit_result']['status'] == 'no_change'
            assert len(store.get(project['id'])['variants']) == count
            selector = recent_creation_selector('把刚才复制的圆半径改成 0.5 米。')
            assert resolve_created_target(third,'other-project',selector)['status'] == 'needs_clarification'
            stale = deepcopy(third); stale['id'] = 'incompatible'
            assert resolve_created_target(stale,project['id'],selector)['status'] == 'needs_clarification'
            deleted = run(client, third, '删除刚才复制的圆')
            assert deleted['ok'], deleted.get('message')
            assert deleted['variant']['geometries'] == [original]
            failed = run(client, deleted['variant'], '把刚才复制的圆半径改成 0.5 米。')
            assert failed.get('ok') is False and failed.get('edit_outcome') == 'target_resolution_failed'
            assert store.get(project['id'])['variants'][-1]['geometries'] == [original]
            # Isolate deliberate conflicting-selection rejection from the
            # successful conversation; do not reuse its rejected binding.
            from app.conversation_memory import conversation_memory
            conversation_memory.delete('copy-http')
            multi = run(client, second, '复制选中的圆到右侧10米',
                {'project_id':project['id'],'variant_id':second['id'],'scope':'group',
                 'geometry_ids':[original['id'],new[0]['id']]})
            assert multi['ok'], multi.get('message')
            multi_variant = multi['variant']
            assert len(multi_variant['reference_mapping']['creation_events'][-1]['members']) == 2
            count = len(store.get(project['id'])['variants'])
            ambiguous = run(client, multi_variant, '把刚才复制的圆半径改成0.5米')
            assert ambiguous.get('ok') is False and ambiguous.get('edit_outcome') == 'target_resolution_failed'
            assert len(store.get(project['id'])['variants']) == count
            conversation_memory.delete('copy-http')
            conflict = run(client, second, '把刚才复制的圆半径改成 0.5 米。',
                {**selection,'variant_id':second['id'],'scope':'entity'})
            assert conflict.get('ok') is False and conflict.get('edit_outcome') == 'target_resolution_failed'
            assert not provider_calls
            completed = True
    finally:
        (out/'trace.json').write_text(json.dumps({'trace':trace,'provider_calls':len(provider_calls),
            'completed':completed,'confirmation_adapter':args.require_confirmation},
            ensure_ascii=False,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
