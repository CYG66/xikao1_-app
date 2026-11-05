from copy import deepcopy
from unittest.mock import Mock

from app.cad_requirement_ledger import project_requirement_ledger,candidate_requirement_snapshot,requirement_ledger
from app.cad_construction_interpreter import interpret_construction_request


def contract(original,followups=()):
    return project_requirement_ledger(original,followups)['requirement_contract']


def test_scoped_updates_preserve_other_part_and_exact_source_evidence():
    original='生成一个爱心和一个五角星，爱心宽4米高4米，五角星外接圆半径2米'
    ledger=project_requirement_ledger(original,['爱心宽度改为500厘米'])
    c=ledger['requirement_contract'];active=[f for f in c['facts'] if f['status']=='effective']
    assert {(f['subject'],f['field'],f['value_mm']) for f in active}=={
        ('爱心','width',5000),('爱心','height',4000),('五角星','circumradius',2000)}
    old=next(f for f in c['facts'] if f['field']=='width' and f['value_mm']==4000)
    assert old['status']=='superseded' and old['superseded_by'] in c['effective_fact_ids']
    for f in c['facts']:
        source=next(s for s in ledger['sources'] if s['source_id']==f['source_id'])
        e=f['evidence'];assert source['text'][e['start']:e['end']]==e['text']
    from app.cad_structure_contract import explicit_composition
    composition=explicit_composition(original+'\n爱心宽度改为500厘米')
    assert composition['component_dimensions']['爱心']['width_m']==5
    assert composition['component_dimensions']['五角星']['circumradius_m']==2


def test_unscoped_and_nested_dimensions_never_become_global():
    c=contract('生成一个爱心和一个五角星',['宽度5米','爱心内部小圆半径1米'])
    assert not c['effective_fact_ids']
    assert all(f['status']=='unresolved' for f in c['facts'])
    shared=contract('生成一个爱心和一个五角星',['它们的宽高均为5米'])
    assert len(shared['effective_fact_ids'])==4
    nested=contract('画一个圆，半径1米',['小圆半径0.1米'])
    assert [f['value_mm'] for f in nested['facts'] if f['status']=='effective']==[1000]
    assert nested['facts'][-1]['status']=='unresolved'


def test_bounds_conflicts_stop_before_model_and_consistent_bounds_do_not_conflict():
    source='生成一个矩形，矩形宽度4米，矩形宽度不超过3米'
    model=Mock();result=interpret_construction_request(source,model)
    assert result['error']['code']=='conflicting_user_dimensions'
    assert result['status']=='clarification_required'
    model.assert_not_called()
    assert contract('生成一个矩形，矩形宽度4米，矩形宽度不超过5米')['consistent']


def test_model_assumptions_cannot_override_user_contract_and_restart_is_stable():
    ledger=project_requirement_ledger('画一个圆，半径1米')
    original=deepcopy(ledger)
    candidate=candidate_requirement_snapshot(ledger,requirement_ledger('画一个圆',assumptions=['半径改为2米']))
    assert candidate['requirement_contract']==ledger['requirement_contract']
    assert candidate['model_assumptions'][0]['confirmed_by_user'] is False
    assert ledger==original
    assert project_requirement_ledger('画一个圆，半径1米',previous=ledger)==ledger


def test_later_subject_declarations_do_not_change_prior_fact_scope():
    old=contract('画一个圆，半径1米')['facts']
    new=contract('画一个圆，半径1米',['再说明一个对象：圆孔：半径2米'])['facts']
    assert new[0]==old[0]


def test_negative_dimensions_and_examples_do_not_become_active_user_values():
    assert not contract('画一个圆，半径-1米')['consistent']
    c=contract('画一个圆',['例如半径2米','不要半径3米'])
    assert not c['effective_fact_ids']


def test_effective_contract_survives_project_store_reload(tmp_path):
    from app.creative_projects import CreativeProjectStore
    path=tmp_path/'projects.json';store=CreativeProjectStore(path)
    source='画一个圆，半径1米'
    first=project_requirement_ledger(source)
    project=store.create('圆',source,requirements={'requirement_ledger':first})
    updated=project_requirement_ledger(source,['圆半径改为20厘米'],previous=first)
    store.update(project['id'],requirements={'source_followups':['圆半径改为20厘米'],'requirement_ledger':updated})
    restored=CreativeProjectStore(path).get(project['id'])['requirements']['requirement_ledger']
    assert restored==updated
    assert [f['value_mm'] for f in restored['requirement_contract']['facts'] if f['status']=='effective']==[200]
