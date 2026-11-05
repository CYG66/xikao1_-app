from app.cad_requirement_ledger import requirement_ledger
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_requirement_ledger import bind_geometry_acceptance
from app.cad_structure_contract import explicit_composition, StructureContractError
import pytest
from app.cad_requirement_ledger import project_requirement_ledger, candidate_requirement_snapshot


def test_content_hash_is_recomputable_without_self_or_parent_dependency():
    from app.cad_requirement_ledger import _revision
    first=project_requirement_ledger("画一个圆")
    second=project_requirement_ledger("画一个圆",["半径1米"],previous=first)
    assert _revision(second)==second["revision_sha256"]
    changed={**second,"previous_revision_sha256":"different-parent"}
    assert _revision(changed)==_revision(second)
    assert _revision({**second,"sources":[]})!=_revision(second)


def test_snapshot_derivations_reference_existing_user_sources():
    project=project_requirement_ledger("画两个圆",["半径1米"])
    construction=requirement_ledger("画两个圆，半径1米",composition_contract={"kind":"component_count"})
    snapshot=candidate_requirement_snapshot(project,construction)
    known={s["source_id"] for s in snapshot["sources"]}
    for derived in snapshot["derived_requirements"]:
        refs=derived.get("source_ids") or [derived.get("source_id")]
        assert refs and set(refs)<=known


def test_project_sources_have_local_offsets_and_stable_revision():
    original="画一个笑脸，两个圆点眼睛"
    first=project_requirement_ledger(original,missing=["dimensions"])
    second=project_requirement_ledger(original,["外圆半径1米，眼睛半径0.09米"],previous=first)
    assert second["previous_revision_sha256"]==first["revision_sha256"]
    assert second["pending_clarifications"]==[]
    for item in second["evidence_items"]:
        source=next(s for s in second["sources"] if s["source_id"]==item["source_id"])
        e=item["evidence"]
        assert source["text"][e["start"]:e["end"]]==e["text"]
    restored=project_requirement_ledger(original,["外圆半径1米，眼睛半径0.09米"],previous=second)
    assert restored==second
    snapshot=candidate_requirement_snapshot(second,requirement_ledger(original,assumptions=["嘴巴宽0.5米"]))
    assert not snapshot["model_assumptions"][0]["confirmed_by_user"]
    assert second["model_assumptions"]==[]


def test_acceptance_uses_actual_geometry_and_preserves_partial_coverage():
    text="画两个相交圆，半径1米"
    contract=explicit_composition(text)
    source=requirement_ledger(text,composition_contract=contract)
    circles=[{"id":i+1,"type":"circle","center":{"x":x,"y":0},"radius":1000} for i,x in enumerate((0,1500))]
    result=bind_geometry_acceptance(source,contract,circles)
    check=result["geometry_acceptance"]["checks"][0]
    assert check["result"]["status"]=="passed"
    assert check["geometry_ids"]==[1,2]
    assert result["geometry_acceptance"]["status"]=="partial"
    assert all(i["verification_status"]=="not_checked" for i in result["evidence_items"])
    assert "geometry_acceptance" not in source
    with pytest.raises(StructureContractError):
        bind_geometry_acceptance(source,contract,circles[:1])


def test_unsupported_semantics_do_not_acquire_acceptance_status():
    result=bind_geometry_acceptance(requirement_ledger("画一个笑脸"),None,[])
    assert result["geometry_acceptance"]=={"status":"not_checked","checks":[]}


def test_assumptions_are_not_confirmed_user_requirements():
    ledger=requirement_ledger("画一个笑脸，半径1米",assumptions=["眼睛半径0.09米"])
    assert ledger["model_assumptions"][0]["confirmed_by_user"] is False
    assert ledger["coverage"]["status"]=="partial"
    assert "眼睛" not in ledger["sources"][0]["text"]


def test_retry_feedback_does_not_change_source_revision():
    text="画两个圆，半径1米"
    assert requirement_ledger(text)==requirement_ledger(text+"\n后端试算反馈：数量错误")
    assert requirement_ledger(text)["revision_sha256"]!=requirement_ledger(text+"，半径改成2米")["revision_sha256"]


def test_ready_interpretation_keeps_source_ledger():
    text="画一个矩形，宽5米高3米，左下角(0,0)"
    result=interpret_construction_request(text)
    assert result["status"]=="ready"
    assert result["requirement_ledger"]["sources"][0]["text"]==text


def test_local_quantity_and_size_are_evidence_not_global_counts():
    text="生成一个笑脸，外圆半径1米，两个圆点眼睛，眼睛半径0.09米，嘴巴闭合"
    ledger=requirement_ledger(text,assumptions=["眼睛在上方"])
    items=ledger["evidence_items"]
    for item in items:
        e=item["evidence"]
        assert text[e["start"]:e["end"]]==e["text"]
        assert item["binding_status"]=="unresolved"
        assert item["verification_status"]=="not_checked"
    eyes=next(i for i in items if i["evidence"]["text"]=="两个")
    assert eyes["clause"]=="两个圆点眼睛"
    assert not any(i["kind"]=="position" for i in items)
    assert len([i for i in items if i["kind"]=="dimension"])==2


def test_generated_summary_is_not_promoted_to_user_evidence():
    text=('新建 CAD 图纸：画一个笑脸\n最新已确认要求（覆盖原描述中同名参数）：半径1米\n'
          '{"assumptions":["眼睛半径9米"]}\n'
          '用户逐轮补充的原文约束（按时间排序，后文覆盖同名约束；必须保留全部组成）：\n半径2米')
    items=requirement_ledger(text)["evidence_items"]
    dims=[i["evidence"]["text"] for i in items if i["kind"]=="dimension"]
    assert dims==["半径2米"]
