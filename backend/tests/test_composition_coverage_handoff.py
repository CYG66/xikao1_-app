from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.cad_composition_coverage import verify_composition_coverage
from app.cad_construction import execute_construction_plan
from app.cad_structure_contract import StructureContractError

FIXTURE=json.loads((Path(__file__).parent/'fixtures/recorded_component_scope.json').read_text(encoding='utf-8'))[0]


def test_recorded_corner_composition_proves_each_requested_feature():
    gs=execute_construction_plan(FIXTURE['plan'])['geometries']
    report=verify_composition_coverage(FIXTURE['source'],gs)
    assert report['coverage']=='complete'
    assert {c['field'] for c in report['checks']}=={
        'component_counts_and_types','width_m','height_m','radius_m','corner_center_bijection'}
    assert verify_composition_coverage(FIXTURE['source'],list(reversed(gs)))['coverage']=='complete'


@pytest.mark.parametrize('mutation',['missing','extra','radius','corner','duplicate_corner','rectangle'])
def test_existing_count_size_and_placement_gates_are_not_bypassed(mutation):
    gs=execute_construction_plan(FIXTURE['plan'])['geometries']
    if mutation=='missing':gs.pop()
    elif mutation=='extra':gs.append({**deepcopy(gs[1]),'id':99})
    elif mutation=='radius':gs[1]['radius']+=10
    elif mutation=='corner':gs[1]['center']['x']+=10
    elif mutation=='duplicate_corner':gs[2]['center']=deepcopy(gs[1]['center'])
    else:
        for p in gs[0]['vertices']:p['x']*=.9
    with pytest.raises(StructureContractError):verify_composition_coverage(FIXTURE['source'],gs)


@pytest.mark.parametrize('extra',['，再画一个三角形','，整体向右平移1米',
    '，圆必须不相交','，矩形面积为9平方米','，所有线宽0.1米'])
def test_unknown_additional_requirements_cannot_be_marked_complete(extra):
    gs=execute_construction_plan(FIXTURE['plan'])['geometries']
    assert verify_composition_coverage(FIXTURE['source']+extra,gs)['coverage']=='partial'


def test_full_interpreter_and_commit_deliver_composition_evidence(tmp_path):
    from app.cad_construction_interpreter import interpret_construction_request
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    result=interpret_construction_request(FIXTURE['source'],lambda *_:{
        'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
        'confidence':.99,'evidence_text':[FIXTURE['original']],'plan':FIXTURE['plan']},
        force_structured_model=True)
    assert result['status']=='ready',result.get('error')
    assert result['acceptance_summary']['status']=='passed'
    store=CreativeProjectStore(tmp_path/'projects.json')
    saved=commit_construction_interpretation(FIXTURE['source'],result,store=store)
    variant=store.get(saved['project_id'])['variants'][0]
    assert len(variant['geometries'])==5
    assert variant['construction_record']['source_acceptance']['composition_acceptance']['checks']


def test_array_pitch_and_cell_inventory_are_proven_by_existing_validator():
    source='生成3行4列矩形阵列，每个矩形宽1米高0.6米，行距1.2米列距1.5米'
    plan={'units':'m','steps':[{'op':'add_rectangle','step_id':'base','output_ref':'base',
        'semantic':{'label':'单元'},'origin':{'x':0,'y':0},'width':1,'height':.6},
        {'op':'rectangular_array','step_id':'array','output_ref':'array',
         'semantic':{'label':'阵列'},'source_ref':'base','rows':3,'columns':4,
         'row_spacing':1.2,'column_spacing':1.5,'include_source':True}]}
    gs=execute_construction_plan(plan)['geometries']
    report=verify_composition_coverage(source,gs)
    assert report['coverage']=='complete'
    wrong=deepcopy(gs)
    for p in wrong[-1]['vertices']:p['x']+=100
    with pytest.raises(StructureContractError):verify_composition_coverage(source,wrong)


def test_intersecting_pair_requires_actual_intersection_and_center_distance():
    source='画两个相交圆，半径1米，圆心距离1.5米'
    gs=[{'id':i,'type':'circle','center':{'x':x,'y':0},'radius':1000}
        for i,x in [(1,0),(2,1500)]]
    assert verify_composition_coverage(source,gs)['coverage']=='complete'
    gs[1]['center']['x']=2500
    with pytest.raises(StructureContractError):verify_composition_coverage(source,gs)


def test_unmeasured_three_circle_relations_remain_partial():
    source='画3个相交圆，半径1米，圆心距离1.5米'
    assert verify_composition_coverage(source,[])['coverage']=='partial'


@pytest.mark.parametrize('source', [
    '画两个圆，半径1米\n画3个圆，半径1米',
    '生成3行4列矩形阵列，每个矩形宽1米高0.6米，行距1.2米列距1.5米\n生成2行5列矩形阵列',
    '画两个相同圆，圆心距离1.5米', '画两个相同圆，半径1米'])
def test_revised_counts_or_unmeasured_equality_cannot_reuse_stale_contract(source):
    assert verify_composition_coverage(source,[])['coverage']=='partial'


@pytest.mark.parametrize('complete,executed,expected', [
    (True,True,'passed'),(False,True,'review_required'),(True,False,'review_required')])
def test_preflight_uncertainty_requires_both_measured_execution_and_source_coverage(complete,executed,expected):
    from app.cad_construction_interpreter import construction_acceptance_summary
    report=construction_acceptance_summary(
        preflight_structure={'status':'unverified','review_required':True,
            'reason':'expanded_operations_require_execution_inventory'},
        structure_contract=None,structure_validation=None,
        composition_contract={'kind':'corner_placement'},
        composition_validation={'status':'passed' if executed else 'unverified'},
        source_acceptance={'coverage':'complete' if complete else 'partial',
            'checks':[{'status':'passed'}]})
    assert report['status']==expected
