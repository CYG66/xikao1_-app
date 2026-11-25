from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_source_acceptance import verify_single_round_primitive
from app.cad_structure_contract import StructureContractError

DATA=json.loads((Path(__file__).parent/'fixtures/recorded_output_intent_b.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case',['U1','U5'])
def test_recorded_geometry_reaches_formal_persistence(case,tmp_path):
    from app.creative_projects import CreativeProjectStore
    from app.cad_construction_commit import commit_construction_interpretation
    from app.cad_candidate_state import candidate_is_accepted
    row=DATA[case];result=interpret_construction_request(row['source'],lambda *_:deepcopy(row['payload']),force_structured_model=True)
    assert result.get('acceptance_summary',{}).get('status')=='passed',result
    store=CreativeProjectStore(tmp_path/'projects.json');saved=commit_construction_interpretation(row['source'],result,store=store)
    assert candidate_is_accepted(store.get(saved['project_id'])['variants'][0])


@pytest.mark.parametrize('phrase',['只保留圆的外边界，不要任何标注','仅保留圆形外边界，不加任何标注','只画圆的轮廓，不要尺寸标注'])
def test_scope_synonyms_are_measured_not_ignored(phrase):
    text=f'画圆，圆心(25,-36)，半径113毫米。{phrase}。坐标单位毫米。'
    gs=[{'id':1,'type':'circle','center':{'x':25,'y':-36},'radius':113}]
    assert verify_single_round_primitive(text,gs)['coverage']=='complete'
    assert verify_single_round_primitive(text+'面积3平方米。',gs)['coverage']=='partial'
    with pytest.raises(StructureContractError):verify_single_round_primitive(text,gs+[{'id':2,'type':'text','role':'annotation'}])


def test_circle_scope_cannot_override_an_explicit_arc_request():
    text='画圆弧，圆心(0,0)，半径2米，从0度到90度。只保留圆的外边界。坐标单位米。'
    gs=[{'id':1,'type':'arc','center':{'x':0,'y':0},'radius':2000,'start_angle':0,'end_angle':90}]
    assert verify_single_round_primitive(text,gs)['coverage']=='partial'


@pytest.mark.parametrize('extra',['执行小车。','面积1平方米。'])
def test_vertex_preview_adapter_preserves_other_unknown_intents(extra):
    from app.cad_vertex_acceptance import verify_vertex_path
    from app.cad_construction import execute_construction_plan
    row=DATA['U5'];gs=execute_construction_plan(row['payload']['plan'])['geometries']
    assert verify_vertex_path(row['source'],gs)['coverage']=='complete'
    assert verify_vertex_path(row['source']+extra,gs)['coverage']=='partial'
    bad=deepcopy(gs);bad[0]['vertices'][0]['x']+=10
    with pytest.raises(StructureContractError):verify_vertex_path(row['source'],bad)


@pytest.mark.parametrize('fake_question',[None,{'question_key':'shape','question':'给出图形'}])
def test_grounding_failure_retains_original_source_without_fake_missing(fake_question,monkeypatch,tmp_path):
    from app.agent_service import RobotAgentService
    from app.creative_projects import CreativeProjectStore
    source='绘制胶囊形闭合边界，中心位于(1.27,-0.94)，长轴相对x轴正向逆时针63度，沿长轴总长6.38米、短轴总高1.26米。两端各为向外半圆，两条直边与半圆相切；两端半径相同，总长含半圆。不添加内部线，坐标单位米。'
    store=CreativeProjectStore(tmp_path/'projects.json');monkeypatch.setattr('app.agent_service.get_creative_project_store',lambda:store)
    service=RobotAgentService(restore_pending_actions=False)
    monkeypatch.setattr(service,'_interpret_cad_construction_plan',lambda *a,**kw:{'status':'clarification_required',
        'provider_attempted':True,'clarification':fake_question,'error':{'code':'ungrounded_model_output','message':'not grounded'}})
    result=service._formal_cad_construction(source,{'name':'drawing_design','operation':'create'},mode='advanced')
    assert not result['ok'] and not result.get('variant') and not result.get('clarification')
    p=store.get(result['project_id']);assert p['original_prompt']==source and not p['variants'] and not p['missing_parameters']


def test_real_missing_radius_is_still_a_clarification(monkeypatch,tmp_path):
    from app.agent_service import RobotAgentService
    from app.creative_projects import CreativeProjectStore
    store=CreativeProjectStore(tmp_path/'projects.json');monkeypatch.setattr('app.agent_service.get_creative_project_store',lambda:store)
    service=RobotAgentService(restore_pending_actions=False)
    monkeypatch.setattr(service,'_interpret_cad_construction_plan',lambda *a,**kw:{'status':'clarification_required',
        'provider_attempted':True,'error':{'code':'ungrounded_model_output','message':'not grounded'}})
    result=service._formal_cad_construction('画一个圆',{'name':'drawing_design','operation':'create'},mode='advanced')
    assert not result['ok'] and result.get('clarification',{}).get('question_key')=='size'
    assert store.get(result['project_id'])['missing_parameters']
