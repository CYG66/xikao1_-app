from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.cad_construction_interpreter import interpret_construction_request

ROWS={r['case']:r for r in json.loads((Path(__file__).parent/'fixtures/recorded_regression_source_handoff.json').read_text(encoding='utf-8'))}


def interpret(row,source=None):
    return interpret_construction_request(source or row['source'],lambda *_:{
        'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
        'confidence':.99,'evidence_text':[row['original']],'plan':deepcopy(row['plan'])},force_structured_model=True)


@pytest.mark.parametrize('case',['C18','C26'])
def test_recorded_valid_geometry_reaches_formal_persistence(case,tmp_path):
    from app.cad_construction import execute_construction_plan
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    row=ROWS[case];result=interpret(row)
    assert result['status']=='ready',result.get('construction_error')
    assert result['acceptance_summary']['status']=='passed',result['source_acceptance']
    assert result['trial_result']['geometries']==execute_construction_plan(row['plan'])['geometries']
    store=CreativeProjectStore(tmp_path/'projects.json');saved=commit_construction_interpretation(row['source'],result,store=store)
    assert store.get(saved['project_id'])['variants'][-1]['acceptance_summary']['status']=='passed'


@pytest.mark.parametrize('extra',['，面积为20平方米','，再画一个圆','，整体旋转20度'])
@pytest.mark.parametrize('case',['C18','C26'])
def test_unknown_source_still_blocks_delivery(case,extra):
    assert interpret(ROWS[case],ROWS[case]['source']+extra).get('acceptance_summary',{}).get('status')!='passed'


@pytest.mark.parametrize('before,after',[('x=2*cos(t)^3','x=3*cos(t)^3'),('t从0到2*pi','t从0到pi'),
    ('x=2*cos(t)^3','x=2*cos(t)^3+1'),('坐标单位米','坐标单位厘米')])
def test_formula_coverage_requires_exact_supported_identity_units_and_period(before,after):
    row=ROWS['C18'];assert interpret(row,row['source'].replace(before,after)).get('acceptance_summary',{}).get('status')!='passed'


ORIGINAL='生成一个雪花图案，6条对称分支，每条分支带2个侧枝，最大半径2米'
ANSWER='中心(0,0)，6条主枝半径均2米、角间隔60度；每条主枝在半径1.2米处有两条长度0.5米、与主枝夹角60度的对称侧枝，坐标单位米。'


@pytest.mark.parametrize('omit',['','在半径1.2米处','长度0.5米','与主枝夹角60度','对称侧枝'])
def test_branch_followup_clears_stale_question_only_after_required_details(omit,tmp_path):
    from app.creative_projects import CreativeProjectStore
    from app.agent_service import RobotAgentService
    store=CreativeProjectStore(tmp_path/'projects.json')
    p=store.create('图案',ORIGINAL,requirements={'shape':'generic_2d_cad','curve_constraints':'pending'},missing_parameters=['curve_constraints'])
    with patch('app.agent_service.get_creative_project_store',return_value=store):
        result=RobotAgentService(restore_pending_actions=False)._apply_design_requirement_followup(ANSWER.replace(omit,'') if omit else ANSWER,{'selected_project_id':p['id']})
    assert ('curve_constraints' not in result['missing_parameters'])==(not omit)


def test_source_verified_branch_network_does_not_inherit_model_square_bounds():
    row=json.loads((Path(__file__).parent/'fixtures/recorded_branch_wrong_bounds.json').read_text(encoding='utf-8'))
    result=interpret(row)
    assert result['status']=='ready',result.get('construction_error')
    assert result['acceptance_summary']['status']=='passed',result.get('source_acceptance')
    assert any(r['kind']=='source_branch_acceptance_replaces_unrequested_bounds' and r['geometry_unchanged'] for r in result['deterministic_repairs'])
    assert interpret(row,row['source']+'整体宽4米高4米').get('acceptance_summary',{}).get('status')!='passed'
