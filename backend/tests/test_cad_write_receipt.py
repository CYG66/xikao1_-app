from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import pytest

from app.creative_projects import CreativeProjectStore
from app.cad_candidate_orchestrator import persist_candidate_variant


def setup_store(tmp_path):
    store=CreativeProjectStore(tmp_path/'projects.json')
    project=store.create('图形','生成图形',requirements={'shape':'rectangle'},missing_parameters=[])
    return store,project['id']


def write(store,pid,**metadata):
    return persist_candidate_variant(project_id=pid,name='候选',
        geometries=[{'id':1,'type':'line','start':{'x':0,'y':0},'end':{'x':1000,'y':0}}],
        rationale='',assessment={},add_variant=store.add_variant,get_project=store.get,**metadata)


def test_write_receipt_does_not_depend_on_subsequent_project_read(tmp_path,monkeypatch):
    store,pid=setup_store(tmp_path)
    monkeypatch.setattr(store,'get',lambda _:None)
    result=write(store,pid)
    assert result['ok'] and result['persisted'] and not result['refresh_required']
    assert result['project']['status']=='designing'
    assert result['project']['variants'][0]['id']==result['variant']['id']


def test_concurrent_retries_and_restart_return_same_durable_variant(tmp_path):
    store,pid=setup_store(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:write(store,pid),range(8)))
    assert all(r['ok'] for r in results)
    ids={r['variant']['id'] for r in results}
    assert len(ids)==1
    restored=CreativeProjectStore(tmp_path/'projects.json')
    assert write(restored,pid)['variant']['id'] in ids
    assert len(restored.get(pid)['variants'])==1


def test_new_parent_is_a_new_edit_not_a_retry(tmp_path):
    store,pid=setup_store(tmp_path)
    first=write(store,pid)
    second=write(store,pid,parent_variant_id=first['variant']['id'])
    assert second['ok'] and second['variant']['id']!=first['variant']['id']


def test_failed_save_does_not_leave_an_in_memory_candidate(tmp_path,monkeypatch):
    store,pid=setup_store(tmp_path)
    before=deepcopy(store.get(pid))
    def fail():raise OSError('disk unavailable')
    with monkeypatch.context() as m:
        m.setattr(store,'_save',fail)
        with pytest.raises(OSError):write(store,pid)
    assert store.get(pid)==before
    assert write(store,pid)['ok']


def test_external_writer_read_failure_is_reported_as_committed():
    result=persist_candidate_variant(project_id='p',name='n',geometries=[
        {'id':1,'type':'line','start':{'x':0,'y':0},'end':{'x':1,'y':0}}],rationale='',assessment={},
        add_variant=lambda *a,**kw:{'id':'v'},get_project=lambda _:None)
    assert result['ok'] and result['persisted'] and result['refresh_required']
    assert result['variant']['id']=='v'
