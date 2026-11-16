"""Exercise actual HTTP endpoints in an isolated process, never live providers."""
from pathlib import Path
import json
import subprocess
import sys
import pytest


@pytest.mark.parametrize('confirm', [False, True])
def test_copy_recent_radius_http_identity(tmp_path, confirm):
    root = Path(__file__).resolve().parents[1]
    out = tmp_path/'http-copy'
    command = [sys.executable, str(root/'tests/manual/trace_copy_http.py'), '--output', str(out)]
    if confirm:
        command.append('--require-confirmation')
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads((out/'trace.json').read_text(encoding='utf-8'))
    assert data['provider_calls'] == 0
    assert data['completed']
    trace = data['trace']
    assert any(t['boundary'] == 'file_reload:variant.reference_mapping' and t['creation_events'] for t in trace)
    if confirm:
        pending = next(t for t in trace if t['boundary'] == 'pending_store_read:arguments.edit_contract')
        assert pending['execution_identity']['members'][0]['source_geometry_id'] == 1


def test_selected_duplicate_complete_provenance():
    from app.incremental_cad import edit_candidate_geometries
    from app.cad_edit_contract import build_cad_edit_contract, CadEditCommand
    source = [{'id':1,'type':'circle','center':{'x':0,'y':0,'z':0},'radius':1000},
              {'id':2,'type':'circle','center':{'x':0,'y':500,'z':0},'radius':200}]
    edit = {'operation':'duplicate','geometry_ids':[1,2],'direction':'右','distance_mm':3000,'placement':'offset'}
    result, error = edit_candidate_geometries(source,edit)
    assert error is None
    assert result[:2] == source
    assert [(m['source_geometry_id'],m['geometry_id']) for m in edit['execution_identity']['members']] == [(1,3),(2,4)]
    assert all('_cad_source_id' not in g for g in result)
    contract = build_cad_edit_contract(edit,source_text='复制选中对象到右侧3米')
    assert CadEditCommand.model_validate_json(json.dumps(contract)).execution_identity == edit['execution_identity']


def test_confirmation_replay_preserves_only_verified_operation_identity():
    from copy import deepcopy
    from app.incremental_cad import edit_candidate_geometries
    from app.cad_edit_contract import build_cad_edit_contract, cad_edit_contract_to_edit
    source = [{'id':1,'type':'circle','center':{'x':0,'y':0,'z':0},'radius':1000}]
    edit = {'operation':'duplicate','geometry_ids':[1],'direction':'右','distance_mm':3000,'placement':'offset'}
    result, error = edit_candidate_geometries(source,edit)
    assert error is None
    contract = build_cad_edit_contract(edit, source_text='复制这个圆到右侧3米')
    replay = cad_edit_contract_to_edit(contract)
    again, error = edit_candidate_geometries(source,replay)
    assert error is None and again == result
    assert replay['execution_identity'] == edit['execution_identity']
    forged = deepcopy(contract)
    forged['execution_identity']['members'][0]['source_geometry_id'] = 99
    forged['execution_identity']['members'][0]['operation_id'] = 'untrusted'
    replay = cad_edit_contract_to_edit(forged)
    again, error = edit_candidate_geometries(source,replay)
    assert error is None and again == result
    member = replay['execution_identity']['members'][0]
    assert member['source_geometry_id'] == 1 and member['operation_id'] != 'untrusted'


def test_recent_copy_is_explicit_target_but_not_permission_to_drift():
    from app.cad_edit_contract import build_cad_edit_contract
    from app.cad_counterfactual_guard import validate_counterfactual_followup
    previous = build_cad_edit_contract({'operation':'translate','instance':1,'dx_mm':1000,'dy_mm':0,'project_id':'p'})
    current = build_cad_edit_contract({'operation':'resize','geometry_ids':[2],
        'dimension':'半径','value_mm':500,'project_id':'p'})
    message = '把刚才复制的圆半径改成0.5米'
    assert validate_counterfactual_followup(previous,current,message)['verified']
    assert not validate_counterfactual_followup(previous,current,'半径改成0.5米')['verified']
    current['project_id'] = 'other'
    assert not validate_counterfactual_followup(previous,current,message)['verified']
