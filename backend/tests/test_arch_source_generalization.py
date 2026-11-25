from copy import deepcopy
import pytest

from app.cad_construction import execute_construction_plan
from app.cad_semantic_source_coverage import verify_semicircular_outline_source


def plan(w,h,x,y,representation):
    p=lambda a,b:{'x':a,'y':b}
    r=w/2;t=h-r
    segments=[{'kind':'line','start':p(x,y),'end':p(x+w,y)},
        {'kind':'line','start':p(x+w,y),'end':p(x+w,y+t)},
        {'kind':'arc','center':p(x+r,y+t),'radius':r,'start_angle':0,'end_angle':180},
        {'kind':'line','start':p(x,y+t),'end':p(x,y)}]
    if representation=='sampled':
        steps=[{'op':'add_composite_path','step_id':'a','output_ref':'a','semantic':{'label':'拱门'},'segments':segments,'closed':True}]
    else:
        steps=[{'op':'add_'+s['kind'],'step_id':str(i),'output_ref':str(i),'semantic':{'label':str(i)},
                **{k:v for k,v in s.items() if k!='kind'}} for i,s in enumerate(segments)]
    return {'units':'mm','steps':steps}


@pytest.mark.parametrize('representation',['native','sampled'])
@pytest.mark.parametrize('w,h,x,y',[(2600,3700,0,0),(1740,2860,-370,420),(3320,4510,230,-175)])
def test_dimensions_and_origin_use_existing_measured_boundary(representation,w,h,x,y,tmp_path):
    source=f'生成一个闭合拱门轮廓，总宽{w}毫米、总高{h}毫米。底边左端({x},{y})，底边水平；两侧直墙等高且竖直，顶部为上半圆，直径等于总宽，总高包含半圆。只画外边界，坐标单位毫米。只生成预览，不执行小车。'
    gs=execute_construction_plan(plan(w,h,x,y,representation))['geometries']
    proof=verify_semicircular_outline_source(source,gs)
    assert proof['coverage']=='complete',proof
    from app.cad_construction_interpreter import interpret_construction_request
    result=interpret_construction_request(source,lambda *_:{'schema_version':'cad.construction-interpretation.v1',
        'is_construction_request':True,'confidence':.99,'evidence_text':[source],'assumptions':[],
        'plan':plan(w,h,x,y,representation)},force_structured_model=True)
    assert result.get('acceptance_summary',{}).get('status')=='passed',result.get('construction_error') or result.get('source_acceptance')
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    from app.cad_candidate_state import candidate_is_accepted
    store=CreativeProjectStore(tmp_path/'projects.json')
    saved=commit_construction_interpretation(source,result,store=store)
    assert candidate_is_accepted(store.get(saved['project_id'])['variants'][0])
    for extra in ['，标注全部尺寸','，再画一个圆','，整体旋转30度','，不要底边闭合']:
        assert verify_semicircular_outline_source(source+extra,gs)['coverage']=='partial'
    wrong=execute_construction_plan(plan(w,h,x+2,y,representation))['geometries']
    assert verify_semicircular_outline_source(source,wrong)['coverage']=='partial'
    wrong=execute_construction_plan(plan(w,h+10,x,y,representation))['geometries']
    assert verify_semicircular_outline_source(source,wrong)['coverage']=='partial'


def test_sampled_arch_cannot_claim_curve_identity_with_coarse_chords():
    from app.cad_curve_fit_acceptance import verify_semicircular_arch
    import math
    gs=execute_construction_plan(plan(2600,3700,0,0,'sampled'))['geometries']
    assert verify_semicircular_arch(gs[0])['passed']
    g=deepcopy(gs[0])
    # Every corner and the apex are present; only chord accuracy is wrong.
    points=[(-2000,0),(-2000,1000),*[(2000*math.cos(math.pi-i*math.pi/64),
            1000+2000*math.sin(math.pi-i*math.pi/64)) for i in range(1,65)],(2000,0)]
    g['vertices']=[{'x':x,'y':y} for x,y in points]
    assert .5<2000*(1-math.cos(math.pi/128))<2000*.005
    assert not verify_semicircular_arch(g)['passed']


@pytest.mark.parametrize('representation',['native','sampled'])
def test_alternate_phrasing_and_centimetres_preserve_full_source_proof(representation):
    source='画闭合拱门的外轮廓：底边从(-50,25)水平向右，总宽230厘米，总高315厘米；两侧是等高竖直墙，顶部为连接两墙的上半圆，半圆直径230厘米，高度已包含在总高中。不画内部线，坐标单位厘米。只生成预览，不执行小车。'
    gs=execute_construction_plan(plan(2300,3150,-500,250,representation))['geometries']
    proof=verify_semicircular_outline_source(source,gs)
    assert proof['coverage']=='complete',proof
    from app.cad_construction_interpreter import interpret_construction_request
    result=interpret_construction_request(source,lambda *_:{'schema_version':'cad.construction-interpretation.v1',
        'is_construction_request':True,'confidence':.99,'evidence_text':[source],'assumptions':[],
        'plan':plan(2300,3150,-500,250,representation)},force_structured_model=True)
    assert result.get('acceptance_summary',{}).get('status')=='passed',result.get('source_acceptance') or result.get('construction_error')
