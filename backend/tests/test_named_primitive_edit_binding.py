from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.incremental_cad import parse_incremental_edit
from app.cad_target_resolver import resolve_logical_object_target

DATA=json.loads((Path(__file__).parent/'fixtures/edit_transport_parent.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('label,text',[('左圆','将左圆的半径改为510毫米。'),('下矩形','将下矩形整体向右移动230毫米。')])
def test_original_named_edits_bind_to_confirmed_objects_and_commit(label,text,monkeypatch,tmp_path):
    from app.creative_projects import CreativeProjectStore
    from app.agent_service import RobotAgentService
    from app.cad_candidate_state import candidate_is_accepted
    target=tmp_path/'projects.json';target.write_text(json.dumps(DATA,ensure_ascii=False),encoding='utf-8')
    store=CreativeProjectStore(target);p=store.list()[0];parent=deepcopy(p['variants'][0])
    monkeypatch.setattr('app.agent_service.get_creative_project_store',lambda:store)
    service=RobotAgentService(restore_pending_actions=False)
    edit=parse_incremental_edit(text+'只生成预览，不执行小车。')
    assert edit['logical_object_selector']['label']==label
    resolution=resolve_logical_object_target(edit['logical_object_selector'],parent['logical_objects'])
    assert resolution['status']=='resolved'
    result=service._apply_incremental_candidate_edit(text,{'name':'drawing_design','operation':'modify',
        'decision_source':'incremental_cad_edit','selected_project_id':p['id'],'selected_variant_id':parent['id'],'resolved_edit':edit})
    assert result.get('ok') and result.get('variant'),result
    assert candidate_is_accepted(result['variant'])
    wanted=resolution['geometry_ids'];after=result['variant']['geometries']
    changed=next(g for g in after if g['id'] in wanted)
    original=next(g for g in parent['geometries'] if g['id']==changed['id'])
    if label=='左圆':
        assert changed['radius']==510 and changed['center']==original['center']
    else:
        assert [v['x'] for v in changed['vertices']]==[v['x']+230 for v in original['vertices']]
        assert [v['y'] for v in changed['vertices']]==[v['y'] for v in original['vertices']]
    assert all(g==next(a for a in after if a['id']==g['id']) for g in parent['geometries'] if g['id'] not in wanted)
    assert len(store.list())==1
    assert next(v for v in store.get(p['id'])['variants'] if v['id']==parent['id'])==parent


def test_duplicate_or_missing_named_geometry_does_not_guess():
    objs=deepcopy(DATA['projects'][0]['variants'][0]['logical_objects'])
    named=next(o for o in objs if o['label']=='左圆')
    selector={'label':'左圆','position':'left','object_type':'circle'}
    assert resolve_logical_object_target(selector,objs+[deepcopy(named)])['status']=='needs_clarification'
    named['geometry_refs']=[]
    assert resolve_logical_object_target(selector,objs)['status']=='needs_clarification'


def test_generic_circle_does_not_acquire_a_named_target():
    assert 'logical_object_selector' not in parse_incremental_edit('把圆的半径改为460毫米。')
    assert 'logical_object_selector' not in parse_incremental_edit('将左圆和右圆的半径改为460毫米。')
