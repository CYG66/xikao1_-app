from copy import deepcopy
import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('cad_history_replay',Path(__file__).parent/'manual/replay_cad_history.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_missing_geometry_is_not_execution_failure():
    assert module.verify('画图',[],{})['classification']=='not_available'


def test_historical_pass_cannot_fill_missing_source_coverage():
    gs=[{'id':1,'type':'circle','center':{'x':0,'y':0},'radius':1000,'layer_id':1}]
    before=deepcopy(gs)
    result=module.verify('画一个圆',gs,{'acceptance_summary':{'status':'passed'}})
    assert result['classification']=='geometry_valid_review_required'
    assert not result['permissions']['formal_selectable']
    assert gs==before


def test_constraint_without_symbol_provenance_is_not_reported_satisfied():
    gs=[{'id':1,'type':'circle','center':{'x':0,'y':0},'radius':1000,'layer_id':1}]
    result=module.verify('画一个圆',gs,{'plan':{'constraints':[{'kind':'concentric'}]}})
    assert result['classification']=='insufficient_evidence'
    assert result['constraint_evidence']=='insufficient_evidence'
