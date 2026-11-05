from unittest.mock import patch

from app.creative_projects import CreativeProjectStore
from app.project_ownership import owned_request, owner_conversation
from app.routers.agent import conversation_lifecycle


def test_owner_scope_covers_model_creation_and_resets(tmp_path):
    store = CreativeProjectStore(tmp_path / 'projects.json')
    @owned_request
    def create(*, route):
        return store.create('owned', 'draw')
    @owned_request
    def stream(*, route):
        yield store.create('stream', 'draw')
    route = {'object_memory': {'conversation_id': 'chat-a'}}
    assert create(route=route)['owner_conversation_id'] == 'chat-a'
    iterator = stream(route=route)
    assert next(iterator)['owner_conversation_id'] == 'chat-a'
    assert owner_conversation.get() is None
    iterator.close()
    assert store.create('legacy', 'draw')['owner_conversation_id'] is None


def test_reference_and_manual_claim_do_not_transfer_ownership(tmp_path):
    store = CreativeProjectStore(tmp_path / 'projects.json')
    project = store.create('legacy', 'draw')
    assert store.lifecycle('claim', [project['id']], 'chat-a')['ok']
    assert not store.lifecycle('claim', [project['id']], 'chat-b')['ok']
    assert store.lifecycle('reference', [project['id']], 'chat-b')['ok']
    assert store.get(project['id'])['owner_conversation_id'] == 'chat-a'
    assert store.get(project['id'])['referenced_conversation_ids'] == ['chat-b']


def test_batch_block_restore_and_purge_preserve_saved_records(tmp_path):
    from app.database import xline_database
    from app.conversation_archive import archived_chats
    database = type(xline_database)(tmp_path / 'lifecycle.db')
    store = CreativeProjectStore(tmp_path / 'projects.json')
    first = store.create('first', 'draw', owner_conversation_id='chat-a')
    second = store.create('second', 'draw', owner_conversation_id='chat-a')
    store._projects[second['id']]['status'] = 'executing'
    with patch('app.routers.agent.get_creative_project_store', return_value=store), patch('app.routers.agent.xline_database', database), patch('app.conversation_archive.xline_database', database):
        command = {'action': 'trash', 'conversation_ids': ['chat-a'], 'snapshots': {'chat-a': {'id': 'a', 'messages': []}}}
        assert not conversation_lifecycle(command)['ok']
        assert store.get(first['id']) is not None
        assert not archived_chats()
        store._projects[second['id']]['status'] = 'completed'
        assert conversation_lifecycle(command)['ok']
        assert store.get(first['id']) is None
        assert len(store.lifecycle_items(deleted=True)) == 2
        assert 'chat-a' in archived_chats()
        restored = conversation_lifecycle({'action': 'restore', 'conversation_ids': ['chat-a']})
        assert restored['ok'] and restored['snapshots']['chat-a']['id'] == 'a'
        assert store.get(first['id'])['owner_conversation_id'] == 'chat-a'
        assert conversation_lifecycle(command)['ok']
        assert conversation_lifecycle({'action': 'purge', 'conversation_ids': ['chat-a']})['ok']
        assert not store.lifecycle_items(deleted=True)


def test_project_trash_persists_and_keeps_owner(tmp_path):
    path = tmp_path / 'projects.json'
    store = CreativeProjectStore(path)
    project = store.create('project', 'draw', owner_conversation_id='chat-a')
    assert store.lifecycle('trash', [project['id']])['ok']
    loaded = CreativeProjectStore(path)
    assert loaded.get(project['id']) is None
    assert loaded.list() == []
    assert loaded.lifecycle('restore', [project['id']])['ok']
    assert loaded.get(project['id'])['owner_conversation_id'] == 'chat-a'


def test_reference_chat_deletion_never_trashes_owned_project(tmp_path):
    from app.database import XLineDatabase
    store = CreativeProjectStore(tmp_path / 'projects.json')
    database = XLineDatabase(tmp_path / 'db.sqlite')
    project = store.create('original', 'draw', owner_conversation_id='owner')
    store.lifecycle('reference', [project['id']], 'reference')
    with patch('app.routers.agent.get_creative_project_store', return_value=store), patch('app.routers.agent.xline_database', database), patch('app.conversation_archive.xline_database', database):
        result = conversation_lifecycle({'action': 'trash', 'conversation_ids': ['reference'], 'snapshots': {'reference': {'id': 'ref'}}})
    assert result['ok']
    assert store.get(project['id']) is not None


def test_failed_transaction_keeps_every_project_active(tmp_path):
    import pytest
    from app.database import XLineDatabase
    database = XLineDatabase(tmp_path / 'db.sqlite')
    store = CreativeProjectStore(tmp_path / 'projects.json')
    first = store.create('first', 'draw', owner_conversation_id='owner')
    second = store.create('second', 'draw', owner_conversation_id='owner')
    with patch('app.routers.agent.get_creative_project_store', return_value=store), patch('app.routers.agent.xline_database', database), patch('app.conversation_archive.xline_database', database), patch.object(database, 'save_project_lifecycle', side_effect=OSError('disk full')):
        with pytest.raises(OSError):
            conversation_lifecycle({'action': 'trash', 'conversation_ids': ['owner'], 'snapshots': {'owner': {'id': 'owner'}}})
    assert store.get(first['id']) is not None
    assert store.get(second['id']) is not None


def test_trashed_project_rejects_edits(tmp_path):
    store = CreativeProjectStore(tmp_path / 'projects.json')
    project = store.create('project', 'draw')
    store.lifecycle('trash', [project['id']])
    assert store.update(project['id'], name='changed') is None


def test_scoped_list_filters_before_limit_and_includes_explicit_references(tmp_path):
    store = CreativeProjectStore(tmp_path / 'projects.json')
    owned = store.create('owned', 'draw', owner_conversation_id='a')
    shared = store.create('shared', 'draw', owner_conversation_id='b')
    legacy = store.create('legacy', 'draw')
    store.lifecycle('reference', [shared['id']], 'a')
    store.create('other', 'draw', owner_conversation_id='c')
    assert {p['id'] for p in store.list(conversation_id='a')} == {owned['id'], shared['id']}
    assert {p['id'] for p in store.list(conversation_id='a', include_unowned=True, summary=True)} == {owned['id'], shared['id'], legacy['id']}
    assert len(store.list(limit=1, conversation_id='a')) == 1


def test_archived_chat_blocks_claim_reference_and_individual_restore(tmp_path):
    from app.database import XLineDatabase
    database = XLineDatabase(tmp_path / 'db.sqlite')
    database.save_project_lifecycle([], {'archived': {'id': 'archived'}})
    store = CreativeProjectStore(tmp_path / 'projects.json')
    legacy = store.create('legacy', 'draw')
    owned = store.create('owned', 'draw', owner_conversation_id='archived')
    with patch('app.conversation_archive.xline_database', database):
        for action in ('claim', 'reference'):
            assert not store.lifecycle(action, [legacy['id']], 'archived')['ok']
        store.lifecycle('trash', [owned['id']])
        assert not store.lifecycle('restore', [owned['id']])['ok']
    assert store.get(owned['id']) is None
    assert store.get(legacy['id'])['owner_conversation_id'] is None


def test_permanent_chat_deletion_detaches_individually_trashed_project(tmp_path):
    from app.database import XLineDatabase
    database = XLineDatabase(tmp_path / 'db.sqlite')
    store = CreativeProjectStore(tmp_path / 'projects.json')
    project = store.create('independent trash', 'draw', owner_conversation_id='owner')
    store.lifecycle('trash', [project['id']])
    shared = store.create('shared', 'draw', owner_conversation_id='other')
    store.lifecycle('reference', [shared['id']], 'owner')
    with patch('app.routers.agent.get_creative_project_store', return_value=store), patch('app.routers.agent.xline_database', database), patch('app.conversation_archive.xline_database', database):
        assert conversation_lifecycle({'action': 'trash', 'conversation_ids': ['owner'], 'snapshots': {'owner': {'id': 'owner'}}})['ok']
        assert conversation_lifecycle({'action': 'purge', 'conversation_ids': ['owner']})['ok']
        assert store.lifecycle('restore', [project['id']])['ok']
    assert store.get(project['id'])['owner_conversation_id'] is None
    assert store.get(shared['id'])['referenced_conversation_ids'] == []

