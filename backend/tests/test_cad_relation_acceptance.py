import pytest

from app.cad_source_acceptance import verify_scoped_primitives
from app.cad_relation_acceptance import extract_named_relations
from app.cad_structure_contract import StructureContractError


def circles(x=3,r=1):
    text=f'甲：圆，圆心(0,0)，半径1米，坐标单位米；乙：圆，圆心({x},0)，半径{r}米，坐标单位米'
    gs=[{'id':1,'type':'circle','center':{'x':0,'y':0},'radius':1000},
        {'id':2,'type':'circle','center':{'x':x*1000,'y':0},'radius':r*1000}]
    return text,gs


@pytest.mark.parametrize('phrase,x,r,passed',[
    ('甲与乙不重叠',3,1,True),('甲与乙不重叠',1,1,False),
    ('甲与乙外切',2,1,True),('甲与乙外切',3,1,False),('甲与乙外切',0,1,False),
    ('甲完全位于乙左侧',3,1,True),('甲完全位于乙左侧',1,1,False),
    ('甲位于乙内部',0,2,True),('甲位于乙内部',3,2,False),
    ('甲完全位于乙右侧',-3,1,True),('甲完全位于乙右侧',3,1,False)])
def test_relations_reject_contradictions_even_when_all_individual_parts_match(phrase,x,r,passed):
    text,gs=circles(x,r)
    if not passed:
        with pytest.raises(StructureContractError,match='部件关系') as error:
            verify_scoped_primitives(text+'；'+phrase,gs)
        assert error.value.details['relation_check']['status']=='failed'
    else:
        report=verify_scoped_primitives(text+'；'+phrase,gs)['relation_acceptance']
        assert report['checks'][0]['status']=='passed'
        assert report['checks'][0]['geometry_ids']==[1,2]


def test_endpoint_connection_is_not_proximity_of_bounding_boxes():
    text='甲：线段，起点(0,0)，终点(1,1)，坐标单位米；乙：线段，起点(0,1)，终点(1,0)，坐标单位米；甲与乙端点相接'
    gs=[{'id':1,'type':'line','start':{'x':0,'y':0},'end':{'x':1000,'y':1000}},
        {'id':2,'type':'line','start':{'x':0,'y':1000},'end':{'x':1000,'y':0}}]
    with pytest.raises(StructureContractError,match='部件关系'):verify_scoped_primitives(text,gs)
    gs[1]['start']={'x':1000,'y':1000}
    text=text.replace('乙：线段，起点(0,1)','乙：线段，起点(1,1)')
    assert verify_scoped_primitives(text,gs)['relation_acceptance']['checks'][0]['status']=='passed'


def test_unsupported_pair_is_unverified_and_not_a_false_pass():
    text,gs=circles()
    report=verify_scoped_primitives(text+'；甲与乙端点相接',gs)
    assert report['relation_acceptance']['checks'][0]['status']=='unverified'
    assert report['review_required'] is True


def test_complete_inventory_with_relation_still_rejects_extra_geometry():
    text,gs=circles()
    gs.append({'id':3,'type':'circle','center':{'x':10000,'y':0},'radius':1000})
    with pytest.raises(StructureContractError,match='额外可见图元'):
        verify_scoped_primitives('完整部件清单：'+text+'；甲与乙不重叠',gs)


def test_metadata_negatives_and_unknown_subjects_cannot_create_user_relations():
    text,gs=circles()
    assert not extract_named_relations('不要甲与乙外切；丙与乙不重叠',['甲','乙'])
    source=text+'\n最新已确认要求（摘要）：甲与乙外切'
    assert not verify_scoped_primitives(source,gs)['relation_acceptance']['checks']


def test_relation_binding_preserves_original_source_offsets():
    from app.cad_requirement_ledger import project_requirement_ledger,candidate_requirement_snapshot
    text,gs=circles();followup='甲与乙不重叠'
    report=verify_scoped_primitives(text+'；'+followup,gs)
    snapshot=candidate_requirement_snapshot(project_requirement_ledger(text,[followup]),{'source_geometry_acceptance':report})
    binding=snapshot['bound_relations'][0]
    assert binding['source_id']=='user-2'
    assert binding['geometry_ids']==[1,2]
    assert binding['verification_status']=='passed'
    e=binding['evidence'];assert followup[e['start']:e['end']]==e['text']


@pytest.mark.parametrize('center,passed',[(1,True),(3,False)])
def test_circle_inside_rectangle_checks_full_radius_not_only_center(center,passed):
    text=f'框：矩形，左下角(0,0)，宽4米，高4米，坐标单位米；孔：圆，圆心({center},2)，半径1.5米，坐标单位米；孔位于框内部'
    # At x=1 and x=3 the circle center is inside, but part lies outside.
    text=text.replace('半径1.5米','半径0.5米') if passed else text
    gs=[{'id':1,'type':'polyline','closed':True,'vertices':[{'x':x,'y':y} for x,y in [(0,0),(4000,0),(4000,4000),(0,4000)]]},
        {'id':2,'type':'circle','center':{'x':center*1000,'y':2000},'radius':500 if passed else 1500}]
    if passed:assert verify_scoped_primitives(text,gs)['relation_acceptance']['checks'][0]['status']=='passed'
    else:
        with pytest.raises(StructureContractError,match='部件关系'):verify_scoped_primitives(text,gs)


def test_model_prompt_and_execution_gate_both_receive_source_relations():
    from app.cad_construction_interpreter import interpret_construction_request
    text,gs=circles(x=1)
    source='生成一个图案。'+text+'；甲与乙不重叠'
    def callback(message,schema):
        assert 'interiors_disjoint' in message
        return {'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
            'confidence':.99,'evidence_text':[text],'plan':{'units':'m','steps':[
                {'op':'add_circle','step_id':f's{i}','output_ref':f'r{i}',
                 'semantic':{'label':name,'assembly_id':'whole','assembly_label':'图案'},
                 'center':{'x':g['center']['x']/1000,'y':0},'radius':g['radius']/1000}
                for i,(name,g) in enumerate(zip(['甲','乙'],gs))]}}
    result=interpret_construction_request(source,callback,force_structured_model=True)
    assert result['status']=='invalid'
    assert '部件关系' in result['error']['message']
