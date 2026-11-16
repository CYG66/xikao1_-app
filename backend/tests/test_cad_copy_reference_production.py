"""Offline production editing; initial accepted geometry is an explicit fixture."""
from copy import deepcopy
from unittest.mock import patch
from app.agent_service import robot_agent
from app.creative_projects import CreativeProjectStore
from app.cad_construction import execute_construction_plan


def run_edit(store,project_id,variant_id,message,selection=None):
    assert store.begin_design_iteration(project_id,variant_id) is not None
    route=robot_agent.resolve_intent(message,'advanced',[])
    route['selected_project_id']=project_id
    route['selected_variant_id']=variant_id
    route['object_memory']={'objects':{'project':[{'id':project_id}]}}
    if selection is not None:route['drawing_selection']=selection
    result=robot_agent.chat(message,[],mode='advanced',route=route)
    if result.get('pending_action'):
        result=robot_agent.confirm(result['pending_action']['id'],True)
    return result


def test_copy_then_recent_reference_changes_only_copy_via_agent(tmp_path):
    store=CreativeProjectStore(tmp_path/'projects.json')
    project=store.create('circle identity fixture','一个圆，半径1米，圆心(0,0)',
        {'shape':'circle','quantity':1}, {}, [])
    trial=execute_construction_plan({'units':'m','steps':[{'op':'add_circle','step_id':'circle','output_ref':'circle',
        'semantic':{'label':'圆'},'center':{'x':0,'y':0},'radius':1}],
        'assertions':[{'kind':'entity_count','assertion_id':'one','equals':1},
            {'kind':'bounds_size','assertion_id':'size','target_ref':'circle','width':2,'height':2}]})
    geometry=trial['geometries'];geometry[0]['template_instance']=1
    # Independently verify every requirement in this deliberately small fixture.
    assert len(geometry)==1 and geometry[0]['radius']==1000 and geometry[0]['center']['x']==0 and geometry[0]['center']['y']==0
    summary={'status':'passed','review_required':False,'authority':'independently_measured_initial_fixture'}
    original=store.add_variant(project['id'],'initial',geometry,'fixture',{},[],acceptance_summary=summary)
    before=deepcopy(original['geometries'][0])
    with patch('app.agent_service.get_creative_project_store',side_effect=lambda:store):
        copied=run_edit(store,project['id'],original['id'],'复制第一个图形到上方3米')
        assert copied['ok'],copied
        second=copied['variant'];new=[g for g in second['geometries'] if g['id']!=before['id']]
        assert len(new)==1 and second['geometries'][0]==before
        events=second['reference_mapping']['creation_events']
        assert events[-1]['members'][0]['source_geometry_id']==before['id']
        assert events[-1]['members'][0]['geometry_id']==new[0]['id']
        restored=CreativeProjectStore(tmp_path/'projects.json').get(project['id'])
        assert restored['variants'][-1]['reference_mapping']==second['reference_mapping']
        conflict=run_edit(store,project['id'],second['id'],'把刚才复制的圆半径改为0.5米',
            {'project_id':project['id'],'variant_id':second['id'],'scope':'entity','geometry_ids':[before['id']]})
        assert not conflict['ok'] and conflict['edit_outcome']=='target_resolution_failed'
        store=CreativeProjectStore(tmp_path/'projects.json')
        resized=run_edit(store,project['id'],second['id'],'把刚才复制的圆半径改为0.5米')
        assert resized['ok'],resized
        third=resized['variant'];byid={g['id']:g for g in third['geometries']}
        assert third['id']!=second['id'] and third['parent_variant_id']==second['id']
        assert byid[new[0]['id']]['radius']==500
        assert byid[before['id']]==before
        assert resized['cad_edit_result']['status']=='changed'
        count=len(store.get(project['id'])['variants'])
        no_change=run_edit(store,project['id'],third['id'],'把刚才复制的圆半径改为0.5米')
        assert 'cad_edit_result' in no_change,no_change
        assert no_change['cad_edit_result']['status']=='no_change'
        assert len(store.get(project['id'])['variants'])==count
        from app.cad_target_resolver import resolve_created_target,recent_creation_selector
        selector=recent_creation_selector('把刚才复制的圆半径改为0.5米')
        assert resolve_created_target(third,project['id'],selector)['geometry_ids']==[new[0]['id']]
        assert resolve_created_target(third,'other-project',selector)['status']=='needs_clarification'
        assert resolve_created_target(original,project['id'],selector)['status']=='needs_clarification'
        stale=deepcopy(third);stale['id']='incompatible-version'
        assert resolve_created_target(stale,project['id'],selector)['status']=='needs_clarification'
        deleted=run_edit(store,project['id'],third['id'],'删除刚才复制的圆')
        assert deleted['ok'],deleted
        assert deleted['variant']['geometries']==[before]
        assert resolve_created_target(deleted['variant'],project['id'],selector)['status']=='needs_clarification'
        failed=run_edit(store,project['id'],deleted['variant']['id'],'把刚才复制的圆半径改为0.5米')
        assert failed['ok'] is False and failed['edit_outcome']=='target_resolution_failed'
        assert store.get(project['id'])['variants'][-1]['geometries']==[before]
