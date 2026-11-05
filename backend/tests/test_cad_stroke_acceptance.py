import pytest
from app.cad_stroke_acceptance import stroke_requirements,verify_stroke_requirements
from app.cad_structure_contract import StructureContractError

SOURCE='生成一个折线图案。两斜笔端点(-1,0)(0,3)(1,0)，横笔在高度1.5米处，坐标单位米。'


def lines():
    return [{'id':i,'type':'line','start':{'x':a[0],'y':a[1]},'end':{'x':b[0],'y':b[1]}}
        for i,(a,b) in enumerate([((-1000,0),(0,3000)),((0,3000),(1000,0)),((-500,1500),(500,1500))],1)]


def test_contract_uses_user_points_and_units_without_font_or_model_labels():
    contract=stroke_requirements(SOURCE)
    assert contract['chain_points_mm']==[[-1000,0],[0,3000],[1000,0]]
    assert contract['crossbar_endpoints_mm']==[[-500,1500],[500,1500]]
    assert verify_stroke_requirements(SOURCE,lines())['checks'][0]['status']=='passed'
    cm=SOURCE.replace('(-1,0)(0,3)(1,0)','(-100,0)(0,300)(100,0)').replace('坐标单位米','坐标单位厘米')
    assert stroke_requirements(cm)['chain_points_mm']==contract['chain_points_mm']


@pytest.mark.parametrize('mutation',['missing_crossbar','wrong_height','short_crossbar','extra_base','closed_font_outline'])
def test_rejects_missing_shifted_or_reinterpreted_strokes(mutation):
    gs=lines()
    if mutation=='missing_crossbar':gs.pop()
    elif mutation=='wrong_height':gs[-1]['start']['y']=gs[-1]['end']['y']=1000
    elif mutation=='short_crossbar':gs[-1]['end']['x']=300
    elif mutation=='extra_base':gs.append({'id':4,'type':'line','start':{'x':-1000,'y':0},'end':{'x':1000,'y':0}})
    else:gs=[{'id':1,'type':'polyline','closed':True,'vertices':[{'x':-1000,'y':0},{'x':0,'y':3000},{'x':1000,'y':0}]}]
    with pytest.raises(StructureContractError):verify_stroke_requirements(SOURCE,gs)


def test_subdivision_reversal_and_multiple_open_polylines_preserve_linework():
    gs=lines();first=gs.pop(0);mid={'x':-500,'y':1500}
    gs.extend([{'id':10,'type':'line','start':first['end'],'end':mid},
        {'id':11,'type':'polyline','closed':False,'vertices':[first['start'],mid]}])
    assert verify_stroke_requirements(SOURCE,gs)['checks'][0]['status']=='passed'


def test_generated_feedback_and_multi_object_inputs_do_not_define_skeleton():
    assert stroke_requirements('生成一个圆\n后端试算反馈：'+SOURCE) is None
    assert stroke_requirements(SOURCE.replace('生成一个折线图案','生成一个爱心和一个折线图案')) is None
    assert stroke_requirements(SOURCE+'笔画宽度0.1米') is None


def test_missing_bar_is_rejected_even_if_candidate_claims_valid_semantics():
    from app.cad_construction_interpreter import interpret_construction_request
    source=SOURCE.replace('折线图案','大写字母A的轮廓')
    def callback(text,schema):
        assert 'explicit_two_stroke_chain_and_crossbar' in text
        return {'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
            'confidence':.99,'evidence_text':[source],'plan':{'units':'m','steps':[
                {'op':'add_polyline','step_id':'outline','output_ref':'outline','semantic':{'label':'字母A，已验证'},
                 'vertices':[{'x':-1,'y':0},{'x':0,'y':3},{'x':1,'y':0}],'closed':True}]}}
    result=interpret_construction_request(source,callback,force_structured_model=True)
    assert result['status']=='invalid'
    assert '开放笔画端点' in result['error']['message']
