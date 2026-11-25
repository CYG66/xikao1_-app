"""Shared output proof and role binding, including recorded real model plans."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from app.cad_circle_group_acceptance import verify_circle_group_source
from app.cad_structure_contract import StructureContractError

RECORDS=json.loads((Path(__file__).parent/'fixtures/recorded_circle_group_c.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('record',RECORDS)
def test_recorded_plans_reach_formal_persistence_without_geometry_repair(record,tmp_path):
    from app.cad_construction import execute_construction_plan
    from app.cad_construction_interpreter import interpret_construction_request
    from app.cad_construction_commit import commit_construction_interpretation
    from app.cad_candidate_state import candidate_is_accepted
    from app.creative_projects import CreativeProjectStore
    row=deepcopy(record)
    original=execute_construction_plan(row['payload']['plan'])['geometries']
    result=interpret_construction_request(row['source'],lambda *_:deepcopy(row['payload']),force_structured_model=True)
    assert result.get('acceptance_summary',{}).get('status')=='passed',result
    store=CreativeProjectStore(tmp_path/'projects.json')
    saved=commit_construction_interpretation(row['source'],result,store=store)
    variant=store.get(saved['project_id'])['variants'][0]
    assert candidate_is_accepted(variant)
    assert variant['geometries']==original
    assert row==record


@pytest.mark.parametrize('alias,unit,scale,x,y,outer,inner',[
    ('共同','毫米',1,-573,182,723,184),
    ('共用','厘米',10,43.8,-28.1,127,51),
    ('共享','米',1000,-1.62,.93,.74,.29),
])
def test_pair_roles_and_output_scope_share_measured_evidence(alias,unit,scale,x,y,outer,inner):
    text=f'画两个同心圆，{alias}圆心({x},{y})，外圆半径{outer}{unit}，内圆半径{inner}{unit}。仅保留两个圆的轮廓，不加任何标注。坐标单位{unit}。只生成预览，不执行小车。'
    gs=[{'id':i+1,'type':'circle','center':{'x':x*scale,'y':y*scale},'radius':r*scale} for i,r in enumerate((inner,outer))]
    # Reverse radius ordering: role binding must depend on measured containment.
    proof=verify_circle_group_source(text,gs)
    assert proof['coverage']=='complete'
    assert any(c.get('field')=='no_visible_annotations' for c in proof['checks'])
    assert len(proof['output_intent_evidence'])==2
    for intent in proof['output_intent_evidence']:
        assert text[intent['start']:intent['end']]==intent['text']
        assert intent['source_text']==text
    assert all(c['status']=='passed' for c in proof['checks'])


def pair():
    return [{'id':i+1,'type':'circle','center':{'x':740,'y':-1260},'radius':r} for i,r in enumerate((860,320))]


def source(): return RECORDS[0]['source']


@pytest.mark.parametrize('change',['both_centers','inner_center','outer_radius','inner_radius','equal_radii','third_circle','annotation'])
def test_wrong_pair_or_extra_output_cannot_get_full_proof(change):
    gs=pair()
    if change=='both_centers':
        for g in gs:g['center']['x']+=13
    elif change=='inner_center':gs[1]['center']['y']+=12
    elif change=='outer_radius':gs[0]['radius']+=14
    elif change=='inner_radius':gs[1]['radius']+=17
    elif change=='equal_radii':gs[1]['radius']=gs[0]['radius']
    elif change=='third_circle':gs.append({'id':3,'type':'circle','center':{'x':5000,'y':1000},'radius':20})
    else:gs.append({'id':3,'type':'text','role':'annotation'})
    try: proof=verify_circle_group_source(source(),gs)
    except StructureContractError:return
    assert proof['coverage']!='complete'


@pytest.mark.parametrize('extra',[
    '面积3平方米。','执行小车。','另画一条连接线。',
    '内圆圆心(0,0)。','只保留两个矩形的轮廓。',
])
def test_unknown_or_conflicting_source_is_not_erased(extra):
    assert verify_circle_group_source(source()+extra,pair())['coverage']=='partial'


def test_conflicting_duplicate_radius_is_rejected():
    with pytest.raises(StructureContractError):
        verify_circle_group_source(source()+'内圆半径0.45米。',pair())


def test_shared_center_is_not_inferred_when_source_omits_it():
    text=source().replace('共用圆心(0.74,-1.26)，','')
    assert verify_circle_group_source(text,pair())['coverage']=='partial'
