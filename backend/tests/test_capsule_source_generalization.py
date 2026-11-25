from copy import deepcopy
import pytest
from evaluations.relation_pilot.cases import expected_entities
from app.cad_capsule_acceptance import verify_capsule_source,measure_capsule
from app.cad_construction import execute_construction_plan
from app.cad_structure_contract import StructureContractError


def fixture(angle=17,representation='native',unit='毫米',length=3470,height=930,x=210,y=-370):
    row={'family':'capsule_tangency','angle':angle,'unit':unit,'length':length,'height':height,'origin':[x,y]}
    gs=expected_entities(row)
    if representation=='native':
        steps=[{'op':'add_'+g['type'],'step_id':str(i),'output_ref':str(i),'semantic':{'label':'capsule part'},
                **{k:v for k,v in g.items() if k not in {'id','type'}}} for i,g in enumerate(gs)]
    else:
        segments=[{'kind':g['type'],**{k:v for k,v in g.items() if k not in {'id','type'}}} for g in gs]
        steps=[{'op':'add_composite_path','step_id':'c','output_ref':'c','semantic':{'label':'胶囊'},'closed':True,'segments':segments}]
    source=f'绘制胶囊形闭合边界，中心位于({x},{y})，长轴相对x轴正向逆时针{angle}度，沿长轴总长{length}{unit}、短轴总高{height}{unit}。两端各为向外半圆，两条直边与半圆相切；两端半径相同，总长含半圆。不添加内部线，坐标单位{unit}。只生成预览，不执行小车。'
    return source,{'units':'mm','steps':steps}


@pytest.mark.parametrize('representation',['native','sampled'])
@pytest.mark.parametrize('angle',[0,17,-31,90])
@pytest.mark.parametrize('unit,length,height,x,y',[('毫米',3470,930,210,-370),('米',4.83,1.27,-.37,.61)])
def test_rotated_local_dimensions_and_representation_reach_persistence(representation,angle,unit,length,height,x,y,tmp_path):
    source,plan=fixture(angle,representation,unit,length,height,x,y)
    gs=execute_construction_plan(plan)['geometries'];before=deepcopy(gs)
    report=verify_capsule_source(source,gs)
    assert report['coverage']=='complete' and gs==before
    from app.cad_construction_interpreter import interpret_construction_request
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    from app.cad_candidate_state import candidate_is_accepted
    result=interpret_construction_request(source,lambda *_:{'schema_version':'cad.construction-interpretation.v1',
        'is_construction_request':True,'confidence':.99,'evidence_text':[source],'assumptions':[],'plan':deepcopy(plan)},force_structured_model=True)
    assert result.get('acceptance_summary',{}).get('status')=='passed',result.get('construction_error') or result.get('source_acceptance') or result.get('error')
    from evaluations.relation_pilot.oracle import boundary
    actual=result['trial_result']['geometries']
    assert len(actual)==len(gs)
    # Existing source-center binding may introduce floating-point roundoff.
    assert boundary(actual).hausdorff_distance(boundary(gs))<1e-9
    store=CreativeProjectStore(tmp_path/'projects.json');saved=commit_construction_interpretation(source,result,store=store)
    assert candidate_is_accepted(store.get(saved['project_id'])['variants'][0])


@pytest.mark.parametrize('mutation',['radius','gap','extra','center','angle','height','duplicate'])
def test_bad_geometry_or_source_dimensions_are_rejected(mutation):
    source,plan=fixture();gs=execute_construction_plan(plan)['geometries']
    if mutation=='radius':gs[1]['radius']+=10
    elif mutation=='gap':gs[0]['end']['x']+=10
    elif mutation=='extra':gs.append({'id':5,'type':'circle','center':{'x':0,'y':0},'radius':10})
    elif mutation=='center':source=source.replace('(210,-370)','(310,-370)')
    elif mutation=='angle':source=source.replace('17度','27度')
    elif mutation=='height':source=source.replace('930毫米','940毫米')
    else:gs.append({**deepcopy(gs[0]),'id':5})
    with pytest.raises(StructureContractError):verify_capsule_source(source,gs)


@pytest.mark.parametrize('extra',['，再画一个圆','，标注全部尺寸','，面积6平方米','，两端半径不相等'])
def test_unconsumed_source_never_gains_complete_coverage(extra):
    source,plan=fixture();gs=execute_construction_plan(plan)['geometries']
    assert verify_capsule_source(source+extra,gs)['coverage']=='partial'


def test_rectangle_is_not_a_capsule_even_when_dimensions_match():
    gs=[{'id':1,'type':'polyline','closed':True,'vertices':[{'x':x,'y':y} for x,y in [(0,0),(5000,0),(5000,1000),(0,1000)]]}]
    assert not measure_capsule(gs)['passed']


def test_unsupported_local_axis_dimensions_are_not_checked_as_world_bounds():
    from app.cad_source_acceptance import verify_final_source_contract
    from app.cad_construction_interpreter import normalize_explicit_outline_size_once
    source,plan=fixture()
    unknown=source+'，画额外标记'
    gs=execute_construction_plan(plan)['geometries']
    report=verify_final_source_contract(unknown,gs)
    assert report['coverage']=='partial'
    payload={'plan':deepcopy(plan)};before=deepcopy(payload)
    result,repairs=normalize_explicit_outline_size_once(payload,unknown)
    assert result==before and not repairs


@pytest.mark.parametrize('representation',['native','sampled'])
def test_horizontal_wording_uses_same_measured_contract(representation):
    _,plan=fixture(0,representation,'毫米',5200,1600,0,0)
    source='画一个水平胶囊形闭合外轮廓，中心(0,0)，总长5.2米，总高1.6米。左右两端是半径相等的向外半圆，上下两条直边平行并与半圆相切，总长包含两端半圆。不画整圆和内部线，坐标单位米。只生成预览，不执行小车。'
    gs=execute_construction_plan(plan)['geometries']
    assert verify_capsule_source(source,gs)['coverage']=='complete'


def test_backend_feedback_cannot_change_source_coordinate_frame():
    from app.cad_capsule_acceptance import has_local_axis_dimensions
    source='画一个矩形，宽3米、高2米，坐标单位米'
    assert not has_local_axis_dimensions(source+'\n后端试算反馈：沿长轴检查局部宽高')
    assert has_local_axis_dimensions('沿局部长轴总长3米，短轴总高1米')


def test_conflicting_axis_requirements_are_both_measured():
    source,plan=fixture(17)
    gs=execute_construction_plan(plan)['geometries']
    with pytest.raises(StructureContractError):
        verify_capsule_source(source.replace('绘制胶囊','绘制水平胶囊'),gs)
