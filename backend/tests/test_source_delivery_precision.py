from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.cad_source_acceptance import verify_single_round_primitive
from app.cad_rectangle_acceptance import verify_single_rectangle
from app.cad_construction import execute_construction_plan, CadConstructionPlan
from app.cad_structure_contract import StructureContractError


@pytest.mark.parametrize('case',['Q1','Q2'])
def test_recorded_correct_draft_can_complete_source_evidence_and_persist(case,tmp_path):
    from evaluations.production_contract_pilot import cases
    from app.cad_construction_interpreter import interpret_construction_request
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    from app.cad_candidate_state import candidate_is_accepted
    source=next(r['text'] for r in cases() if r['id']==case)+'只生成预览，不执行小车。'
    plan=json.loads((Path(__file__).parent/'fixtures/source_delivery_plans.json').read_text(encoding='utf-8'))[case]
    result=interpret_construction_request(source,lambda *_:{'schema_version':'cad.construction-interpretation.v1',
        'is_construction_request':True,'confidence':.99,'evidence_text':[source],'assumptions':[],
        'plan':deepcopy(plan)},force_structured_model=True)
    assert result['status']=='ready',result.get('error')
    assert result['acceptance_summary']['status']=='passed',result['acceptance_summary']
    store=CreativeProjectStore(tmp_path/'projects.json')
    commit=commit_construction_interpretation(source,result,store=store)
    variant=store.get(commit['project_id'])['variants'][0]
    assert candidate_is_accepted(variant)
    assert variant['geometries']==result['trial_result']['geometries']


@pytest.mark.parametrize('extra',['，再画一个矩形','，不要圆心在原点','，面积3平方米','，改成红色','。执行小车'])
def test_unknown_requirements_remain_partial(extra):
    gs=[{'id':1,'type':'circle','center':{'x':0,'y':0},'radius':1000}]
    assert verify_single_round_primitive('画一个圆，圆心(0,0)，半径1米，坐标单位米。只生成预览，不执行小车。'+extra,gs)['coverage']=='partial'


@pytest.mark.parametrize('radius,center',[(.73,(-2.1,4.3)),(2.3,(1.7,-.4)),(.16,(0,0))])
def test_unseen_circle_values_bind_to_actual_geometry(radius,center):
    text=f'画一个圆，圆心({center[0]},{center[1]})，半径{radius}米，只画这一个圆，坐标单位米。只生成预览，不执行小车。'
    gs=[{'id':7,'type':'circle','center':{'x':center[0]*1000,'y':center[1]*1000},'radius':radius*1000}]
    proof=verify_single_round_primitive(text,gs)
    assert proof['coverage']=='complete' and proof['intent_evidence']
    gs[0]['center']['x']+=3
    with pytest.raises(StructureContractError):verify_single_round_primitive(text,gs)


def test_rectangle_origin_and_extra_geometry_are_not_ignored():
    text='画一个矩形，左下角(-2,3)，宽4米、高2米，边平行于坐标轴。只画矩形轮廓，坐标单位米。只生成预览，不执行小车。'
    plan={'steps':[{'op':'add_rectangle','step_id':'r','output_ref':'r','semantic':{'label':'矩形'},'origin':{'x':-2,'y':3},'width':4,'height':2}]}
    gs=execute_construction_plan(plan)['geometries']
    assert verify_single_rectangle(text,gs)['coverage']=='complete'
    with pytest.raises(StructureContractError):verify_single_rectangle(text,gs+deepcopy(gs))
    for p in gs[0]['vertices']:p['x']+=2
    with pytest.raises(StructureContractError):verify_single_rectangle(text,gs)


@pytest.mark.parametrize('units,scale',[('m',1),('mm',1000)])
def test_composite_sampling_budget_is_invariant_under_units(units,scale):
    from evaluations.relation_pilot.oracle import boundary
    plan={'units':units,'steps':[{'op':'add_composite_path','step_id':'a','output_ref':'a',
        'semantic':{'label':'arc'},'segments':[{'kind':'arc','center':{'x':0,'y':0},'radius':1.3*scale,'start_angle':0,'end_angle':180}]}]}
    before=deepcopy(plan);result=execute_construction_plan(plan)
    assert plan==before
    assert result['plan']['steps'][0]['max_sampling_error']==pytest.approx(.2/(1000 if units=='m' else 1))
    expected=[{'type':'arc','center':{'x':0,'y':0},'radius':1300,'start_angle':0,'end_angle':180}]
    assert boundary(expected).hausdorff_distance(boundary(result['geometries']))<.21
