from copy import deepcopy
import math
import pytest

from app.cad_vertex_acceptance import verify_open_straight_path
from app.cad_structure_contract import StructureContractError


def fixture(unit='米',a=1.9,b=1.3,angle=31,turn=-74,x=.4,y=-.8,style='lines'):
    scale={'米':1000,'厘米':10,'毫米':1}[unit]
    points=[(x*scale,y*scale)]
    for length,direction in [(a,angle),(b,angle+turn)]:
        p=points[-1];r=math.radians(direction);points.append((p[0]+length*scale*math.cos(r),p[1]+length*scale*math.sin(r)))
    p=lambda v:{'x':v[0],'y':v[1]}
    if style=='polyline':gs=[{'id':1,'type':'polyline','closed':False,'vertices':[p(v) for v in points]}]
    else:gs=[{'id':i+1,'type':'line','start':p(points[i]),'end':p(points[i+1])} for i in range(2)]
    direction='逆时针' if turn>=0 else '顺时针'
    source=f'只画两段首尾相接的开放折线。起点({x},{y})，第一段长{a}{unit}，与x轴正向夹角{angle}度；第二段从第一段末点出发，长{b}{unit}，在第一段方向基础上{direction}转{abs(turn)}度。不闭合，不加标注，坐标单位{unit}。只生成预览，不执行小车。'
    return source,gs


@pytest.mark.parametrize('style',['lines','polyline','reversed','subdivided'])
@pytest.mark.parametrize('unit,a,b,angle,turn,x,y',[
    ('米',1.9,1.3,31,-74,.4,-.8),('厘米',173,81,-27,113,-43,28),('毫米',2317,983,57,82,375,-413)])
def test_geometry_representation_and_units_do_not_change_source_proof(style,unit,a,b,angle,turn,x,y,tmp_path):
    source,gs=fixture(unit,a,b,angle,turn,x,y,'polyline' if style=='polyline' else 'lines')
    if style=='reversed':
        gs.reverse()
        for g in gs:g['start'],g['end']=g['end'],g['start']
    elif style=='subdivided':
        first=gs.pop(0);middle={k:(first['start'][k]+first['end'][k])/2 for k in ('x','y')}
        gs.extend([{**first,'end':middle},{**first,'id':3,'start':middle}])
    before=deepcopy(gs);report=verify_open_straight_path(source,gs)
    assert report['coverage']=='complete' and gs==before
    # The real interpreter and commit gate must agree with read-only proof.
    from app.cad_construction_interpreter import interpret_construction_request
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    from app.cad_candidate_state import candidate_is_accepted
    steps=[{'op':'add_'+g['type'],'step_id':str(i),'output_ref':str(i),'semantic':{'label':'path part'},
            **{k:v for k,v in g.items() if k not in {'id','type'}}} for i,g in enumerate(gs)]
    result=interpret_construction_request(source,lambda *_:{'schema_version':'cad.construction-interpretation.v1',
        'is_construction_request':True,'confidence':.99,'evidence_text':[source],'assumptions':[],
        'plan':{'units':'mm','steps':steps}},force_structured_model=True)
    assert result.get('acceptance_summary',{}).get('status')=='passed',result.get('construction_error') or result.get('source_acceptance')
    store=CreativeProjectStore(tmp_path/'projects.json');saved=commit_construction_interpretation(source,result,store=store)
    assert candidate_is_accepted(store.get(saved['project_id'])['variants'][0])


@pytest.mark.parametrize('mutation',['gap','branch','extra','wrong_turn','length','origin','duplicate','closed'])
def test_invalid_geometry_is_rejected(mutation):
    source,gs=fixture()
    if mutation=='gap':gs[1]['start']['x']+=3
    elif mutation=='branch':gs.append({'id':3,'type':'line','start':deepcopy(gs[0]['end']),'end':{'x':8000,'y':6000}})
    elif mutation=='extra':gs.append({'id':3,'type':'circle','center':{'x':0,'y':0},'radius':10})
    elif mutation=='wrong_turn':gs[1]['end']['y']+=20
    elif mutation=='length':gs[0]['start']['x']-=20
    elif mutation=='origin':
        for g in gs:
            for k in ['start','end']:g[k]['x']+=10
    elif mutation=='duplicate':gs.append({**deepcopy(gs[0]),'id':3})
    else:gs.append({'id':3,'type':'line','start':deepcopy(gs[1]['end']),'end':deepcopy(gs[0]['start'])})
    with pytest.raises(StructureContractError):verify_open_straight_path(source,gs)


@pytest.mark.parametrize('extra',['，再画一个圆','，顺时针旋转20度','，标注长度','，面积为5平方米','，改变颜色'])
def test_unknown_source_is_never_declared_fully_covered(extra):
    source,gs=fixture()
    assert verify_open_straight_path(source+extra,gs)['coverage']=='partial'


def test_three_segments_reuse_same_ordered_relation_measurement():
    source='画三段首尾相接的开放折线。起点(10,-20)，第一段长700毫米，相对x轴正向为15度；第二段从第一段末点出发，长450毫米，在第一段方向基础上逆时针转80度；第三段从第二段末点出发，长630毫米，在第二段方向基础上顺时针转35度。不闭合，不加标注，坐标单位毫米。'
    points=[(10,-20)]
    for length,angle in [(700,15),(450,95),(630,60)]:
        x,y=points[-1];r=math.radians(angle);points.append((x+length*math.cos(r),y+length*math.sin(r)))
    gs=[{'id':1,'type':'polyline','closed':False,'vertices':[{'x':x,'y':y} for x,y in points]}]
    assert verify_open_straight_path(source,gs)['coverage']=='complete'
    assert verify_open_straight_path(source.replace('从第二段末点','从第一段末点'),gs)['coverage']=='partial'


def test_alternate_relative_angle_wording_from_live_pilot():
    source,gs=fixture('毫米',2140,860,-23,102,-330,270)
    source='绘制两段相接的开放折线，起点(-330,270)。第一段长度2140毫米，相对x轴正向为-23度；第二段从前一段终点开始，长度860毫米，方向再相对第一段逆时针转102度。不要闭合或增加其他图形，坐标单位毫米。只生成预览，不执行小车。'
    assert verify_open_straight_path(source,gs)['coverage']=='complete'


def test_ambiguous_collinear_junction_is_not_falsely_called_bad_geometry():
    source,gs=fixture(turn=0)
    proof=verify_open_straight_path(source,gs)
    assert proof['coverage']=='partial' and proof['reason']=='collinear_source_junction_requires_explicit_binding'
