from copy import deepcopy
from app.cad_edit_session import binding_matches,continuation,remember_edit
from app.conversation_memory import ConversationMemoryStore
from app.incremental_cad import parse_incremental_edit

SELECTION={'scope':'group','project_id':'p','variant_id':'v','geometry_ids':[1]}
PROJECT={'id':'p','variants':[{'id':'v'}],'design_base_variant_id':'v'}


def test_unfinished_edit_survives_restart_and_restores_target_and_all_turns(tmp_path):
    store=ConversationMemoryStore(tmp_path/'memory.json')
    source='把当前样条曲线放大到原来的1.5倍'
    route={'operation':'modify','drawing_selection':SELECTION,'user_message':source}
    store.remember('chat',source,{'ok':True,'message':'请确认缩放基点'},route)
    memory=ConversationMemoryStore(tmp_path/'memory.json').context('chat')
    answer='以包围盒中心为缩放基点'
    resolved=continuation(answer,memory,None,None,lambda _:PROJECT)
    assert resolved['source_turns']==[source,answer]
    assert resolved['drawing_selection']==SELECTION
    assert parse_incremental_edit(resolved['message']+' 图形')['factor']==1.5


def test_switch_project_new_creation_or_changed_selection_does_not_resume():
    pending=remember_edit(None,'把选中的图形旋转45度',{}, {'operation':'modify','drawing_selection':SELECTION})
    memory={'pending_cad_edit':pending}
    assert continuation('顺时针',memory,'other',None,lambda _:PROJECT) is None
    assert continuation('生成一个圆',memory,None,None,lambda _:PROJECT) is None
    assert continuation('顺时针',memory,None,{**SELECTION,'variant_id':'other'},lambda _:PROJECT) is None
    changed=deepcopy(PROJECT);changed['design_base_variant_id']='new'
    assert continuation('顺时针',memory,None,None,lambda _:changed) is None


def test_direction_answer_preserves_already_supplied_angle():
    pending=remember_edit(None,'把图形旋转45度',{}, {'operation':'modify','drawing_selection':SELECTION})
    resumed=continuation('顺时针',{'pending_cad_edit':pending},'p',None,lambda _:PROJECT)
    assert parse_incremental_edit(resumed['message'])['angle_degrees']==-45


def test_saved_revision_clears_pending_operation():
    route={'operation':'modify','drawing_selection':SELECTION}
    assert remember_edit({'old':True},'确认',{'ok':True,'variant':{'id':'next'}},route) is None


def test_unrelated_conversation_cannot_inherit_edit():
    assert continuation('以中心为基点',{},None,None,lambda _:PROJECT) is None


def test_new_operation_does_not_complete_previous_operation():
    pending=remember_edit(None,'把选中的图形旋转45度',{},
        {'operation':'modify','drawing_selection':SELECTION})
    memory={'pending_cad_edit':pending}
    assert continuation('把选中的图形向右平移2米',memory,None,None,lambda _:PROJECT) is None
    assert continuation('让小车向右移动2米',memory,None,None,lambda _:PROJECT) is None


def test_latest_rotation_magnitude_overrides_old_value_but_keeps_raw_sources():
    source='把选中的图形旋转45度'
    pending=remember_edit(None,source,{}, {'operation':'modify','drawing_selection':SELECTION})
    answer='改成30度，顺时针，以当前图形中心为基点'
    resumed=continuation(answer,{'pending_cad_edit':pending},None,None,lambda _:PROJECT)
    assert resumed['source_turns']==[source,answer]
    assert parse_incremental_edit(resumed['message'])['angle_degrees']==-30


def test_switching_projects_or_cancelling_clears_pending_durably(tmp_path):
    store=ConversationMemoryStore(tmp_path/'memory.json')
    source='把选中的图形旋转45度'
    store.remember('chat',source,{'message':'请补方向'},
        {'operation':'modify','drawing_selection':SELECTION,'user_message':source})
    assert store.context('chat')['pending_cad_edit']
    store.remember('chat','切换项目',{'project_id':'other'}, {'operation':'read','selected_project_id':'other'})
    assert ConversationMemoryStore(tmp_path/'memory.json').context('chat')['pending_cad_edit'] is None
    pending=remember_edit(None,source,{}, {'operation':'modify','drawing_selection':SELECTION})
    assert continuation('顺时针',{'pending_cad_edit':pending,'objects':{'project':[{'id':'other'}]}},
        None,None,lambda _:PROJECT) is None
    assert remember_edit(pending,'换个任务',{}, {'operation':'read'}) is None


def test_constraint_metric_correction_preserves_raw_turns_and_original_selection():
    source='让两个选中的对象宽度相等，以圆形为基准'
    pending=remember_edit(None,source,{}, {'operation':'modify','drawing_selection':SELECTION})
    answer='改为高度相等，以矩形为基准'
    resumed=continuation(answer,{'pending_cad_edit':pending},'p',None,lambda _:PROJECT)
    assert resumed['source_turns']==[source,answer]
    assert resumed['drawing_selection']==SELECTION
    parsed=parse_incremental_edit(resumed['message'])
    assert parsed['constraint_type']=='equal' and parsed['dimension']=='高度'


def test_latest_constraint_kind_replaces_old_kind_without_changing_target():
    source='让选中的两个对象同心'
    pending=remember_edit(None,source,{}, {'operation':'modify','drawing_selection':SELECTION})
    resumed=continuation('改为宽度相等，以圆形为基准',{'pending_cad_edit':pending},'p',None,lambda _:PROJECT)
    parsed=parse_incremental_edit(resumed['message'])
    assert parsed['constraint_type']=='equal' and parsed['dimension']=='宽度'
    assert resumed['drawing_selection']==SELECTION


def test_reference_only_answer_is_a_continuation_but_changed_selection_is_not():
    pending=remember_edit(None,'让两个对象同心',{}, {'operation':'modify','drawing_selection':SELECTION})
    assert continuation('固定圆形',{'pending_cad_edit':pending},'p',None,lambda _:PROJECT)
    assert continuation('固定圆形',{'pending_cad_edit':pending},'p',{**SELECTION,'geometry_ids':[2]},lambda _:PROJECT) is None


def test_pending_command_persists_the_same_project_variant_and_selection_binding():
    command={'operation':'translate','dx_mm':1000}
    pending=remember_edit(None,'向右移动1米',{}, {
        'operation':'modify','drawing_selection':SELECTION,'resolved_edit':command,
    })
    assert pending['command']['project_id']=='p'
    assert pending['command']['variant_id']=='v'
    assert pending['command']['binding']==pending['binding']
    assert binding_matches(pending,SELECTION)
    assert not binding_matches(pending,{**SELECTION,'geometry_ids':[2]})


def test_binding_mismatch_clear_is_durable(tmp_path):
    store=ConversationMemoryStore(tmp_path/'memory.json')
    source='把选中的图形向右移动1米'
    store.remember('chat',source,{'message':'请确认'}, {
        'operation':'modify','drawing_selection':SELECTION,
        'resolved_edit':{'operation':'translate','dx_mm':1000},
        'user_message':source,
    })
    assert store.context('chat')['pending_cad_edit']
    store.clear_pending_cad_edit('chat',reason='cad_context_binding_mismatch')
    assert ConversationMemoryStore(tmp_path/'memory.json').context('chat')['pending_cad_edit'] is None
