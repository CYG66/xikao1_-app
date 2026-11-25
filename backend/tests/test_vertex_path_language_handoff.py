from copy import deepcopy
import json
import math
from pathlib import Path
import pytest

from app.cad_vertex_acceptance import verify_vertex_path, verify_open_straight_path, open_straight_path_requirements
from app.cad_structure_contract import StructureContractError

ROWS=json.loads((Path(__file__).parent/'fixtures/recorded_vertex_path_c.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('row',ROWS)
def test_real_plans_retain_geometry_and_reach_formal_save_or_keep_original_error(row,tmp_path):
    from app.cad_construction import execute_construction_plan
    from app.cad_construction_interpreter import interpret_construction_request
    from app.cad_construction_commit import commit_construction_interpretation
    from app.cad_candidate_state import candidate_is_accepted
    from app.creative_projects import CreativeProjectStore
    result=interpret_construction_request(row['source'],lambda *_:deepcopy(row['payload']),force_structured_model=True)
    if not row['independent_geometry']['passed']:
        # The recorded unsupported cm plan remains invalid; do not normalize it here.
        assert result['status']=='invalid'
        return
    assert result.get('acceptance_summary',{}).get('status')=='passed',result
    store=CreativeProjectStore(tmp_path/'projects.json')
    saved=commit_construction_interpretation(row['source'],result,store=store)
    variant=store.get(saved['project_id'])['variants'][0]
    assert candidate_is_accepted(variant)
    assert variant['geometries']==execute_construction_plan(row['payload']['plan'])['geometries']


def polygon(count=5,separator='、',shape='五边形'):
    points=[{'x':round(700*math.cos(i*2*math.pi/count)+125,6),'y':round(700*math.sin(i*2*math.pi/count)-240,6)} for i in range(count)]
    coords=separator.join(f"({p['x']},{p['y']})" for p in points)
    source=f'依次连接顶点{coords}，最后连接回第一个顶点，形成一个闭合{shape}。坐标单位毫米。只生成预览，不执行小车。'
    return source,[{'id':1,'type':'polyline','closed':True,'vertices':points}]


@pytest.mark.parametrize('count,separator,shape',[(3,'、','三角形'),(4,'，','四边形'),(5,',','5边形'),(8,' ','八边形'),(10,'','十边形')])
def test_coordinate_lists_counts_and_cyclic_adjacency_have_shared_proof(count,separator,shape):
    text,gs=polygon(count,separator,shape)
    proof=verify_vertex_path(text,gs)
    assert proof['coverage']=='complete'
    clauses=proof['source_clause_evidence']
    assert clauses['declared_vertex_count']==count
    assert clauses['vertex_list'] in text
    assert all(c in text for c in clauses['connections'])
    gs[0]['vertices']=list(reversed(gs[0]['vertices'][2:]+gs[0]['vertices'][:2]))
    assert verify_vertex_path(text,gs)['coverage']=='complete'


@pytest.mark.parametrize('mutation',['coordinate','order','count','closed','bulge','extra'])
def test_geometry_cannot_satisfy_only_the_polygon_name(mutation):
    text,gs=polygon()
    if mutation=='coordinate':gs[0]['vertices'][0]['x']+=10
    elif mutation=='order':gs[0]['vertices'][1],gs[0]['vertices'][2]=gs[0]['vertices'][2],gs[0]['vertices'][1]
    elif mutation=='count':gs[0]['vertices'].pop()
    elif mutation=='closed':gs[0]['closed']=False
    elif mutation=='bulge':gs[0]['vertices'][0]['bulge']=.3
    else:gs.append({'id':2,'type':'line','start':{'x':0,'y':0},'end':{'x':100,'y':100}})
    with pytest.raises(StructureContractError):verify_vertex_path(text,gs)


@pytest.mark.parametrize('extra',['面积2平方米。','所有边长相等。','先旋转30度。','执行小车。','另接一条线到(0,0)。'])
def test_list_grammar_does_not_consume_unmeasured_clauses(extra):
    text,gs=polygon()
    assert verify_vertex_path(text+extra,gs)['coverage']=='partial'


def test_contradictory_vertex_counts_and_ambiguous_separators_remain_partial():
    text,gs=polygon()
    for bad in [text.replace('五边形','四边形'),text+'使用六个顶点。',text.replace('闭合五边形','不闭合五边形'),text.replace('、','或者',1)]:
        assert verify_vertex_path(bad,gs)['coverage']=='partial'


@pytest.mark.parametrize('count,join',[(2,'连续连接'),(5,'依次连接'),(10,'连在一起')])
def test_walk_connection_synonyms_share_planning_and_measurement(count,join):
    from app.cad_length_units import planning_unit_contract
    names='一二三四五六七八九十'
    text='从(-21,37)出发画折线，先沿与x轴正向成17度的方向走1.23米'
    points=[{'x':-210,'y':370}];angle=17
    lengths=[1230]
    for i in range(1,count):
        turn=29+i;left=i%2==1;angle+=turn if left else -turn
        length=510+i*11;lengths.append(length)
        text+=f'，再向{"左" if left else "右"}转{turn}度接着画{length}毫米'
    text+=f'。{names[count-1]}段{join}，末端不连回起点，不加其他图形。坐标单位厘米。'
    angle=17
    for i,length in enumerate(lengths):
        if i:angle+=(29+i)*(1 if i%2==1 else -1)
        p=points[-1];a=math.radians(angle)
        points.append({'x':p['x']+length*math.cos(a),'y':p['y']+length*math.sin(a)})
    gs=[{'id':1,'type':'polyline','closed':False,'vertices':points}]
    parsed=open_straight_path_requirements(text)
    assert parsed['coverage']=='complete' and parsed['count']==count
    assert planning_unit_contract(text)['ordered_path']['segment_count']==count
    assert verify_open_straight_path(text,gs)['coverage']=='complete'
    for bad in [text+'另画一个圆。',text.replace('段'+join,'段断开连接'),text.replace('末端不连回起点','末端连接回起点')]:
        assert open_straight_path_requirements(bad)['coverage']=='partial'
    gs[0]['vertices'][-1]['y']+=10
    with pytest.raises(StructureContractError):verify_open_straight_path(text,gs)
