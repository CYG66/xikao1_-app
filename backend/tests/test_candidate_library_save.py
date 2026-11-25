from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import pytest
from pydantic import ValidationError
from app.creative_projects import CreativeProjectStore
from app.drawing_versions import DrawingVersionStore
from app.routers.projects import save_candidate_drawing
from app.schemas import CreativeProjectSaveDrawingRequest


def variant(store, project, end=1000):
    return store.add_variant(project['id'], '同名方案', [{'id':1, 'type':'line', 'layer_id':1,
        'start':{'x':0,'y':0,'z':0},'end':{'x':end,'y':0,'z':0}}], '', {}, [],
        acceptance_summary={'status':'passed','review_required':False})

@pytest.fixture
def env(tmp_path):
    store=CreativeProjectStore(tmp_path/'projects.json')
    versions=DrawingVersionStore(tmp_path/'versions.json')
    with ExitStack() as stack:
        stack.enter_context(patch('app.routers.projects.get_creative_project_store',return_value=store))
        stack.enter_context(patch('app.routers.projects.drawing_versions',versions))
        stack.enter_context(patch('app.routers.projects._cad_directory',return_value=tmp_path/'cad'))
        yield store,versions,tmp_path/'cad'

def save(p,v,**kwargs):
    return save_candidate_drawing(p['id'],v['id'],CreativeProjectSaveDrawingRequest(name='同名图纸',**kwargs))

def test_different_projects_with_same_name_have_independent_history(env):
    store,versions,_=env
    p1=store.create('同名项目','draw',{}, {}, [])
    p2=store.create('同名项目','draw',{}, {}, [])
    a=save(p1,variant(store,p1)); b=save(p2,variant(store,p2))
    assert a['ok'] and b['ok']
    assert a['version']['drawing_id']!=b['version']['drawing_id']
    assert a['file_name']!=b['file_name']
    assert a['version']['version']==b['version']['version']==1
    assert len(versions.list(a['version']['drawing_id']))==1

def test_new_candidate_is_next_version_in_same_project(env):
    store,versions,_=env;p=store.create('项目','draw',{}, {}, [])
    a=save(p,variant(store,p));b=save(p,variant(store,p,2000))
    assert a['version']['drawing_id']==b['version']['drawing_id']
    assert b['version']['version']==2
    assert b['version']['parent_file_name']==a['file_name']
    assert len(versions.list(a['version']['drawing_id']))==2

def test_copy_is_independent_and_retry_does_not_duplicate(env):
    store,versions,directory=env;p=store.create('项目','draw',{}, {}, []);v=variant(store,p)
    a=save(p,v);b=save(p,v,save_as=True,request_id='copy-one')
    retry=save(p,v,save_as=True,request_id='copy-one')
    c=save(p,v,save_as=True,request_id='copy-two')
    assert len({a['version']['drawing_id'],b['version']['drawing_id'],c['version']['drawing_id']})==3
    assert retry['file_name']==b['file_name']
    assert len(versions.list())==3
    assert all((directory/r['file_name']).is_file() for r in [a,b,c])
    # A normal repeat save still refers to its original document.
    assert save(p,v)['file_name']==a['file_name']

def test_concurrent_copy_retry_commits_once(env):
    store,versions,_=env;p=store.create('项目','draw',{}, {}, []);v=variant(store,p)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:save(p,v,save_as=True,request_id='same-request'),range(8)))
    assert all(r['ok'] for r in results)
    assert len({r['file_name'] for r in results})==1
    assert len(versions.list())==1

def test_copy_requires_idempotency_key():
    with pytest.raises(ValidationError):
        CreativeProjectSaveDrawingRequest(save_as=True)

def test_planning_artifacts_of_same_name_do_not_share_identity(env):
    store,versions,directory=env
    projects=[store.create('同名','draw',{}, {}, []) for _ in range(2)]
    saved=[]
    for p in projects:
        v=variant(store,p)
        assert store.select_variant(p['id'],v['id'])
        result=versions.save_project_planning(directory,'same.json',{'lines':[]},'creative_project','plan',
            project_store=store,project_id=p['id'],planning_factory=lambda v:{'file_name':v['file_name']})
        saved.append(result['drawing_version'])
    assert saved[0]['drawing_id']!=saved[1]['drawing_id']
    assert saved[0]['file_name']!=saved[1]['file_name']


def test_long_display_name_stays_editable_in_legacy_editor(env):
    import re
    from app.schemas import DrawingSaveRequest
    store,versions,_=env;p=store.create("project","draw",{}, {}, []);v=variant(store,p)
    result=save_candidate_drawing(p['id'],v['id'],CreativeProjectSaveDrawingRequest(name="很长的图纸名称"*20))
    assert result['ok']
    stem=re.sub(r"_v\d+\.json$", "", result['file_name'])
    validated=DrawingSaveRequest(name=stem,overwrite=True,file_name=result['file_name'],
        segments=[{'start_x':0,'start_y':0,'end_x':1,'end_y':0}])
    assert validated.name==stem
