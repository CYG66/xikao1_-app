from copy import deepcopy
import pytest
from app.cad_source_acceptance import extract_scoped_primitives, verify_scoped_primitives
from app.cad_structure_contract import StructureContractError

TEXT="外圆：圆，圆心(0,0)，半径1米，坐标单位米；左眼：圆，圆心(-0.35,0.35)，半径0.09米，坐标单位米；右眼：圆，圆心(0.35,0.35)，半径0.09米，坐标单位米"


def geometry():
    return [{"id":i+1,"type":"circle","center":{"x":x,"y":y},"radius":r}
            for i,(x,y,r) in enumerate([(0,0,1000),(-350,350,90),(350,350,90)])]


def test_local_sizes_and_count_are_independent_of_model_labels():
    specs=extract_scoped_primitives(TEXT)
    assert [s["radius"] for s in specs]==[1000,90,90]
    report=verify_scoped_primitives(TEXT,geometry())
    assert [c["geometry_ids"] for c in report["checks"]]==[[1],[2],[3]]
    assert report["status"]=="partial"


def test_extra_visible_geometry_cannot_hide_behind_matching_required_parts():
    gs=geometry()
    extra=deepcopy(gs[0]);extra["id"]=4
    gs.append(extra)
    with pytest.raises(StructureContractError,match="额外可见图元"):
        verify_scoped_primitives("完整部件清单：\n"+TEXT,gs)


def test_partial_eye_requirements_do_not_authorize_or_delete_other_parts():
    eyes="；".join(TEXT.split("；")[1:])
    gs=geometry()
    original=deepcopy(gs)
    report=verify_scoped_primitives(eyes,gs)
    assert report['unverified_geometry_ids']==[1]
    assert report['review_required'] is True
    assert report['inventory_scope']=='partial'
    assert gs==original
    assert verify_scoped_primitives(TEXT,gs)["status"]=="partial"


def test_unsupported_inventory_clause_cannot_turn_into_false_exact_count():
    report=verify_scoped_primitives('完整部件清单：'+TEXT+'；嘴巴为一条微笑曲线',geometry())
    assert report['inventory_scope']=='partial'


@pytest.mark.parametrize("role",["reference","annotation","ignored"])
def test_non_executable_reference_is_not_an_extra_visible_part(role):
    gs=geometry()
    extra=deepcopy(gs[0]);extra.update(id=4,role=role)
    assert len(verify_scoped_primitives(TEXT,gs+[extra])["checks"])==3


@pytest.mark.parametrize("mutation",["missing","radius","position","type"])
def test_model_cannot_pass_by_claiming_its_own_assertions(mutation):
    gs=geometry()
    if mutation=="missing":gs.pop()
    elif mutation=="radius":gs[1]["radius"]=1000
    elif mutation=="position":gs[1]["center"]["x"]+=100
    else:gs[1]["type"]="arc"
    with pytest.raises(StructureContractError):verify_scoped_primitives(TEXT,gs)


def test_scoped_revision_updates_only_named_subject():
    updated=extract_scoped_primitives(TEXT+"；左眼：圆，圆心(-0.35,0.35)，半径0.12米，坐标单位米")
    assert [s["radius"] for s in updated]==[1000,120,90]
    assert verify_scoped_primitives("画一个笑脸",geometry())["status"]=="not_checked"


def test_coordinate_and_dimension_units_are_independent():
    text="孔：圆，圆心(35,35)，半径9厘米，坐标单位厘米"
    report=verify_scoped_primitives(text,[{"id":1,"type":"circle","center":{"x":350,"y":350},"radius":90}])
    assert report["checks"][0]["status"]=="passed"


def test_partial_scalar_revision_updates_acceptance_without_losing_other_parts():
    text=TEXT+'；左眼半径改为12厘米'
    specs=extract_scoped_primitives(text)
    assert [s['radius'] for s in specs]==[1000,120,90]
    assert specs[1]['center']==[-350,350]
    with pytest.raises(StructureContractError):
        verify_scoped_primitives(text,geometry())
    gs=geometry();gs[1]['radius']=120
    report=verify_scoped_primitives(text,gs)
    assert len(report['checks'])==3
    assert specs[1]['dimension_evidence']['radius']['evidence']['text']=='半径改为12厘米'


def test_generated_metadata_cannot_override_partial_source_revision():
    text=(TEXT+'\n最新已确认要求（后端摘要）：左眼半径8米'
          '\n用户逐轮补充的原文约束（按时间排序，后文覆盖同名约束；必须保留全部组成）：\n'
          '左眼半径改为12厘米')
    assert [s['radius'] for s in extract_scoped_primitives(text)]==[1000,120,90]


def test_revised_dimension_binding_points_to_followup_not_old_source():
    from app.cad_requirement_ledger import project_requirement_ledger, candidate_requirement_snapshot
    followup='左眼半径改为12厘米'
    gs=geometry();gs[1]['radius']=120
    report=verify_scoped_primitives(TEXT+'；'+followup,gs)
    snapshot=candidate_requirement_snapshot(project_requirement_ledger(TEXT,[followup]),
        {'source_geometry_acceptance':report})
    left=next(b for b in snapshot['bound_requirements'] if b['subject']=='左眼')
    revision=next(d for d in left['dimension_requirements'] if d['field']=='radius')
    assert revision['source_id']=='user-2'
    assert revision['value_mm']==120
    e=revision['evidence']
    assert followup[e['start']:e['end']]==e['text']


def test_partial_rectangle_revision_preserves_type_position_and_other_axis():
    text='底板：矩形，左下角(1,2)，宽4米，高3米，坐标单位米；底板宽度改为500厘米'
    spec=extract_scoped_primitives(text)[0]
    assert (spec['width'],spec['height'],spec['origin'])==(5000,3000,[1000,2000])


@pytest.mark.parametrize('stale_model',[False,True])
def test_constructor_prompt_and_independent_gate_share_latest_partial_revision(stale_model):
    from app.cad_construction_interpreter import interpret_construction_request
    text='生成一个由三个圆组成的图案。'+TEXT+'；左眼半径改为12厘米'
    def model(message,schema):
        assert '120.0' in message
        return {'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
            'confidence':.99,'evidence_text':[TEXT],'plan':{'steps':[
                {'op':'add_circle','step_id':f's{i}','output_ref':f'r{i}',
                 'semantic':{'label':s['subject'],'assembly_id':'whole','assembly_label':'图案'},
                 'center':{'x':s['center'][0]/1000,'y':s['center'][1]/1000},'radius':s['radius']/1000}
                for i,s in enumerate(extract_scoped_primitives(TEXT if stale_model else text))]}}
    result=interpret_construction_request(text,model,force_structured_model=True)
    if stale_model:
        assert result['status']!='ready',result
        assert result['error']['code']=='trial_execution_failed',result
        assert '左眼' in result['error']['message'],result
    else:
        assert result['status']=='ready',result


@pytest.mark.parametrize("hidden",[{"selected":False},{"role":"reference"},{"role":"annotation"},{"role":"ignored"}])
def test_hidden_geometry_cannot_satisfy_a_required_visible_part(hidden):
    gs=geometry()
    gs[1].update(hidden)
    with pytest.raises(StructureContractError):verify_scoped_primitives(TEXT,gs)


def test_extra_arc_turn_is_not_equivalent_to_matching_endpoint_angles():
    text="嘴：圆弧，圆心(0,0)，半径1米，起始角200度，终止角340度，坐标单位米"
    arc={"id":1,"type":"arc","center":{"x":0,"y":0},"radius":1000,"start_angle":200,"end_angle":340}
    verify_scoped_primitives(text,[arc])
    arc["end_angle"]+=360
    with pytest.raises(StructureContractError):verify_scoped_primitives(text,[arc])
    arc["start_angle"]+=360
    verify_scoped_primitives(text,[arc])


def test_scoped_acceptance_rejects_missing_whole_ownership():
    with pytest.raises(StructureContractError,match="整体归属"):
        verify_scoped_primitives(TEXT,geometry(),[{"object_id":str(i),"geometry_refs":[i]} for i in (1,2,3)])


def test_verified_subject_bindings_survive_candidate_reload(tmp_path):
    from app.cad_construction_interpreter import interpret_construction_request
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    source="生成一个图案。"+TEXT
    specs=extract_scoped_primitives(source)
    payload={"schema_version":"cad.construction-interpretation.v1","is_construction_request":True,
        "confidence":.99,"evidence_text":[TEXT],"plan":{"steps":[
            {"op":"add_circle","step_id":f"s{i}","output_ref":f"r{i}",
             "semantic":{"label":s["subject"],"assembly_id":"whole","assembly_label":"图案"},
             "center":{"x":s["center"][0]/1000,"y":s["center"][1]/1000},"radius":s["radius"]/1000}
            for i,s in enumerate(specs)]}}
    result=interpret_construction_request(source,lambda *_:payload,force_structured_model=True)
    assert result["status"]=="ready",result
    store=CreativeProjectStore(tmp_path/'projects.json')
    committed=commit_construction_interpretation(source,result,store=store)
    variant=CreativeProjectStore(tmp_path/'projects.json').get(committed["project_id"])["variants"][0]
    ledger=variant["requirement_ledger"]
    assert len(ledger["bound_requirements"])==3
    for item in ledger["bound_requirements"]:
        s=next(s for s in ledger["sources"] if s["source_id"]==item["source_id"])
        e=item["evidence"]
        assert s["text"][e["start"]:e["end"]]==e["text"]
        assert item["assembly_ids"]==["whole"]
        assert item["object_ids"]
def test_ordinary_single_primitive_commands_are_independently_measured():
    line_text="画一条线段从(0,0)到(5,3)，坐标单位米"
    line={"id":1,"type":"line","start":{"x":0,"y":0},"end":{"x":5000,"y":3000}}
    assert verify_scoped_primitives(line_text,[line])["checks"][0]["status"]=="passed"
    rect_text="画一个矩形，宽5米高3米，左下角(0,0)，坐标单位米"
    rect={"id":1,"type":"polyline","closed":True,"vertices":[
        {"x":0,"y":0},{"x":5000,"y":0},{"x":5000,"y":3000},{"x":0,"y":3000}]}
    assert verify_scoped_primitives(rect_text,[rect])["checks"][0]["status"]=="passed"

