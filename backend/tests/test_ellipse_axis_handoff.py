from copy import deepcopy
from unittest.mock import Mock, patch

import pytest

from app.agent_skills import parameterize_design
from app.cad_axis_requirements import ellipse_axes, verify_ellipse_axes
from app.cad_construction_interpreter import interpret_construction_request, clarify_construction_request
from app.cad_structure_contract import StructureContractError

SOURCE = '画一个长轴4米短轴2米的椭圆'


@pytest.mark.parametrize('source', [SOURCE,
    '画一个椭圆，长半轴2米，短半轴1米',
    '画一个椭圆，短轴200厘米，长轴4000毫米',
    SOURCE+'\n长轴全长4米，短轴全长2米，中心(0,0)，坐标单位米。'])
def test_axis_aliases_and_units_deliver_existing_primitive_without_model(source):
    callback = Mock(side_effect=AssertionError('complete ellipse used provider'))
    result = interpret_construction_request(source, callback)
    assert result['status']=='ready',result.get('error')
    assert result['parser']=='deterministic_rules'
    assert result['acceptance_summary']['status']=='passed'
    step=result['plan']['steps'][0]
    assert step['op']=='add_ellipse'
    assert (step['major_radius'],step['minor_radius'])==(2,1)
    callback.assert_not_called()


def test_ellipse_is_not_classified_as_circle_or_missing_size():
    parsed=parameterize_design(SOURCE)
    assert parsed['shape']=='ellipse'
    assert parsed['dimensions']=={'major_radius_m':2,'minor_radius_m':1}
    assert 'dimensions' not in parsed['missing']
    assert clarify_construction_request(SOURCE)['recognized_shape']=='椭圆'
    from app.cad_project_candidates import normalize_design_requirements
    normalized,missing=normalize_design_requirements({'shape':'椭圆','dimensions':parsed['dimensions']},SOURCE)
    assert normalized['shape']=='ellipse'
    assert 'dimensions' not in missing


@pytest.mark.parametrize('source', ['画一个椭圆，长轴2米短轴4米',
    '画一个椭圆，长轴4米长半轴3米短轴2米',
    '画一个椭圆，长轴-4米短轴2米'])
def test_conflicting_axes_clarify_before_model(source):
    callback=Mock(side_effect=AssertionError('conflict reached provider'))
    result=interpret_construction_request(source,callback)
    assert result['status']=='clarification_required'
    assert result['error']['code']=='conflicting_axis_dimensions'
    callback.assert_not_called()


@pytest.mark.parametrize('mutation',['double_axes','ratio','center','rotation','partial_arc','extra'])
def test_actual_geometry_axes_are_checked_independently(mutation):
    source='画一个椭圆，长轴4米短轴2米，中心(1,2)，坐标单位米，旋转30度'
    result=interpret_construction_request(source)
    gs=deepcopy(result['trial_result']['geometries'])
    if mutation=='double_axes':
        gs[0]['major_axis']['x']*=2; gs[0]['major_axis']['y']*=2
    elif mutation=='ratio': gs[0]['ratio']=.9
    elif mutation=='center': gs[0]['center']['x']+=10
    elif mutation=='rotation': gs[0]['major_axis'].update(x=2000,y=0)
    elif mutation=='partial_arc': gs[0]['end_angle']=180
    else: gs.append({**deepcopy(gs[0]),'id':2})
    with pytest.raises(StructureContractError):verify_ellipse_axes(source,gs)


@pytest.mark.parametrize('extra',['，再画一个圆','，位于矩形上方','，面积10平方米'])
def test_extra_requirements_cannot_be_silently_consumed(extra):
    spec=ellipse_axes(SOURCE+extra)
    assert not spec['full_source']


def test_formal_creation_and_partial_project_followup_keep_axis_dimensions(tmp_path):
    from app.agent_service import robot_agent
    from app.creative_projects import CreativeProjectStore
    store=CreativeProjectStore(tmp_path/'projects.json')
    with patch('app.agent_service.get_creative_project_store',return_value=store), \
         patch.object(robot_agent,'_structured_review_text',side_effect=AssertionError('LLM called')):
        result=robot_agent._formal_cad_construction(SOURCE,
            {'name':'drawing_design','operation':'create'},mode='advanced')
        assert result['ok'] and result['variant']['geometries'][0]['type']=='ellipse'
        assert result['variant']['acceptance_summary']['status']=='passed'
        project=store.create('椭圆','画一个椭圆',requirements={'shape':'ellipse'},
                             constraints={},missing_parameters=['dimensions'])
        reply=robot_agent._apply_design_requirement_followup('长轴全长4米，短轴全长2米，坐标单位米。',
            {'selected_project_id':project['id'],'mode':'advanced'})
        assert reply is not None
        updated=store.get(project['id'])
        assert updated['requirements']['dimensions']['major_radius_m']==2
        assert 'dimensions' not in updated['missing_parameters']
        confirmed=robot_agent.generate_project_candidate(project['id'])
        assert confirmed['ok'], confirmed.get('message')
        assert confirmed['project_id']==project['id']
        assert confirmed['variant']['geometries'][0]['type']=='ellipse'
        assert confirmed['variant']['acceptance_summary']['status']=='passed'
        assert len(store.get(project['id'])['variants'])==1
