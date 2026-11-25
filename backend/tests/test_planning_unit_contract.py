import pytest
from app.cad_length_units import planning_unit_contract


@pytest.mark.parametrize('unit,r,x,y',[('厘米',74,-64,83),('毫米',740,-640,830),('米',.74,-.64,.83),('cm',74,-64,83)])
def test_equivalent_sources_have_identical_plan_values(unit,r,x,y):
    source=f'画一个圆，半径{r}{unit}，圆心({x},{y})，坐标单位{unit}。'
    c=planning_unit_contract(source)
    assert c['scalars'][0]['plan_values']=={'m':.74,'mm':740}
    assert c['points'][0]['plan_values']=={'m':[-.64,.83],'mm':[-640,830]}
    for item in c['scalars']+c['points']:
        e=item['evidence'];assert source[e['start']:e['end']]==e['text']


@pytest.mark.parametrize('suffix',['','坐标单位米，坐标单位厘米'])
def test_missing_or_conflicting_coordinate_units_are_not_guessed(suffix):
    c=planning_unit_contract('画一个圆，半径2米，圆心(1,2)。'+suffix)
    assert not c['points'] and c['unresolved_coordinate_sources']==['user:0']
    assert c['scalars'][0]['plan_values']=={'m':2,'mm':2000}


def test_object_scope_and_source_feedback_are_preserved():
    source='绘制两个同心圆，外圆半径170厘米，内圆半径65厘米，共同圆心(40,-70)，坐标单位厘米。'
    c=planning_unit_contract(source+'\n后端试算反馈：半径900米，圆心(999,999)，坐标单位米')
    assert {(v['subject'],v['plan_values']['mm']) for v in c['scalars']}=={('内圆',650),('外圆',1700)}
    assert all(p['plan_values']['mm']==[400,-700] for p in c['points']) and c['points']


def test_real_interpreter_callback_receives_unit_contract():
    from app.cad_construction_interpreter import interpret_construction_request
    calls=[]
    def callback(text,schema):
        calls.append(text)
        return {'schema_version':'cad.construction-interpretation.v1','is_construction_request':False,'confidence':.5}
    interpret_construction_request('画一个圆，半径74厘米，圆心(-64,83)，坐标单位厘米。',callback,force_structured_model=True)
    assert calls and 'cad.planning-unit-contract.v1' in calls[0] and '830' in calls[0]
