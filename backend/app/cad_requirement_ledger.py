"""Immutable source ledger; model assumptions never become user requirements."""
from copy import deepcopy
import hashlib
import json
import re


def project_requirement_ledger(original, followups=(), *, missing=(), previous=None):
    """Retain source-local evidence; never infer global parameter ownership."""
    sources,items=[],[]
    for index,text in enumerate([original,*followups]):
        source_id=f"user-{index+1}"
        sources.append({"source_id":source_id,"origin":"user","sequence":index+1,
                        "text":text,"sha256":hashlib.sha256(text.encode("utf-8")).hexdigest()})
        for item in evidence_items(text):
            item["source_id"]=source_id
            item["requirement_id"]=f"{source_id}:{item['requirement_id']}"
            items.append(item)
    payload={"schema":"cad.requirement-ledger.v1","sources":sources,"evidence_items":items,
             "model_assumptions":deepcopy((previous or {}).get("model_assumptions",[])),
             "pending_clarifications":[{"field":field,"status":"pending"} for field in missing],
             "coverage":{"status":"partial","note":"逐轮原文完整保存；参数归属未解析时不自动覆盖或宣称已验收"}}
    from .cad_requirement_contract import requirement_contract
    payload['requirement_contract']=requirement_contract(sources)
    payload["revision_sha256"]=_revision(payload)
    # Keep ancestry out of the content hash so identical reconstruction is
    # stable after restart and does not create spurious revisions.
    if previous:
        ancestry=(previous.get("previous_revision_sha256")
            if previous.get("revision_sha256")==payload["revision_sha256"] else previous.get("revision_sha256"))
        if ancestry is not None:payload['previous_revision_sha256']=ancestry
    return payload


def _revision(payload):
    content={k:v for k,v in payload.items() if k not in {"revision_sha256","previous_revision_sha256"}}
    return hashlib.sha256(json.dumps(content,sort_keys=True,ensure_ascii=False).encode("utf-8")).hexdigest()


def candidate_requirement_snapshot(project_ledger, construction_ledger):
    result=deepcopy(project_ledger)
    from .cad_requirement_contract import requirement_contract
    result['requirement_contract']=requirement_contract([s for s in result.get('sources',[]) if s.get('origin')=='user'])
    result["model_assumptions"]=deepcopy((construction_ledger or {}).get("model_assumptions",[]))
    for key in ("geometry_acceptance","derived_requirements","source_geometry_acceptance"):
        if key in (construction_ledger or {}):result[key]=deepcopy(construction_ledger[key])
    source_ids=[s["source_id"] for s in result.get("sources",[])]
    for item in result.get("derived_requirements",[]):
        if item.get("source_id") not in source_ids:
            item.pop("source_id",None)
            item["source_ids"]=source_ids.copy()
    result["bound_requirements"]=[]
    for check in (result.get("source_geometry_acceptance") or {}).get("checks",[]):
        evidence=check["source_requirement"]["evidence"]
        matches=[(s,s["text"].find(evidence)) for s in result.get("sources",[]) if evidence in s["text"]]
        if matches:
            source,start=matches[-1]
            result["bound_requirements"].append({"subject":check["subject"],
                "source_id":source["source_id"],"evidence":{"start":start,"end":start+len(evidence),"text":evidence},
                "geometry_ids":deepcopy(check["geometry_ids"]),"verification_status":"passed",
                "object_ids":deepcopy(check.get("object_ids") or []),
                "assembly_ids":deepcopy(check.get("assembly_ids") or []),
                "scope":"explicit_type_coordinates_dimensions_only"})
            binding=result['bound_requirements'][-1]
            binding['dimension_requirements']=[]
            for field,detail in check['source_requirement'].get('dimension_evidence',{}).items():
                fragment=detail['evidence']['text']
                origins=[(s,s['text'].rfind(fragment)) for s in result.get('sources',[]) if fragment in s['text']]
                if origins:
                    origin,offset=origins[-1]
                    binding['dimension_requirements'].append({'field':field,'value_mm':check['source_requirement'][field],
                        'source_id':origin['source_id'],'evidence':{'start':offset,'end':offset+len(fragment),'text':fragment},
                        'verification_status':'passed'})
    result['bound_relations']=[]
    relation_report=(result.get('source_geometry_acceptance') or {}).get('relation_acceptance') or {}
    for check in relation_report.get('checks',[]):
        fragment=check['evidence']['text']
        origins=[(s,s['text'].rfind(fragment)) for s in result.get('sources',[]) if fragment in s['text']]
        if origins:
            origin,start=origins[-1]
            result['bound_relations'].append({'subjects':deepcopy(check['subjects']),'kind':check['kind'],
                'geometry_ids':deepcopy(check['geometry_ids']),'verification_status':check['status'],
                'source_id':origin['source_id'],'evidence':{'start':start,'end':start+len(fragment),'text':fragment},
                'authority':check['authority']})
    result.pop("revision_sha256",None)
    result["revision_sha256"]=_revision(result)
    return result


def evidence_items(source):
    """Conservative lexical evidence, never an inferred object assignment.

    Offsets address the immutable input, including when generated context
    summaries are masked. A partial extractor must not claim full coverage.
    """
    text=source
    start=source.find("\n最新已确认要求（")
    if start>=0:
        marker="\n用户逐轮补充的原文约束（按时间排序，后文覆盖同名约束；必须保留全部组成）：\n"
        end=source.find(marker,start)
        end=end+len(marker) if end>=0 else len(source)
        text=source[:start]+" "*(end-start)+source[end:]
    number=r"\d+(?:\.\d+)?"
    unit=r"毫米|厘米|米|mm|cm|m"
    patterns={
        "quantity":r"(?:\d+|[一二两三四五六七八九十]+)\s*(?:个|条|根|片|朵|颗|扇)",
        "dimension":rf"(?:长宽|宽高|宽度|高度|直径|半径|边长|间距|净距|宽|高|长)(?:均|都)?(?:为|是|不超过|至少|最大|最小)?\s*{number}\s*(?:{unit})",
        "position":r"(?:在左|在右|上方|下方|左上|左下|右上|右下|居中|圆心|中心)",
        "orientation":r"逆时针|顺时针|朝向|向上|向下|向左|向右|旋转\s*[-+]?\d+(?:\.\d+)?\s*(?:度|°)",
        "connection":r"不相交|相交|相连|连接|闭合|开口|相切|同心|平行|垂直",
        "units":rf"(?:坐标)?单位(?:为|是|：|:)?\s*(?:{unit})",
    }
    found=[]
    for kind,pattern in patterns.items():
        for match in re.finditer(pattern,text):
            left=max(source.rfind(c,0,match.start()) for c in "，,。；;\n")+1
            ends=[source.find(c,match.end()) for c in "，,。；;\n"]
            right=min((n for n in ends if n>=0),default=len(source))
            found.append({"kind":kind,"source_id":"request",
                          "evidence":{"start":match.start(),"end":match.end(),"text":source[match.start():match.end()]},
                          "clause":source[left:right],"binding_status":"unresolved",
                          "verification_status":"not_checked"})
    found.sort(key=lambda item:(item["evidence"]["start"],item["kind"]))
    for index,item in enumerate(found):item["requirement_id"]=f"req-{index+1}"
    return found


def requirement_ledger(source_text, *, assumptions=(), clarification=None,
                       structure_contract=None, composition_contract=None):
    # Retry feedback is execution evidence, never another user instruction.
    source = source_text.split("\n后端试算反馈：", 1)[0]
    sources = [{"source_id":"request", "origin":"user_request_context",
                "text":source, "sha256":hashlib.sha256(source.encode("utf-8")).hexdigest()}]
    derived = []
    for kind, contract in (("reference_structure",structure_contract),
                           ("explicit_composition",composition_contract)):
        if contract:
            derived.append({"kind":kind,"source_id":"request","value":deepcopy(contract)})
    payload = {"schema":"cad.requirement-ledger.v1", "sources":sources,
               "evidence_items":evidence_items(source),
               "derived_requirements":derived,
               "model_assumptions":[{"origin":"model","text":str(a),"confirmed_by_user":False} for a in assumptions],
               "pending_clarifications":[deepcopy(clarification)] if clarification else [],
               "coverage":{"status":"partial","note":"原文完整留存；尚未逐项结构化所有语义，不代表全部需求已独立验收"}}
    payload["revision_sha256"] = hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode("utf-8")).hexdigest()
    return payload


def bind_geometry_acceptance(ledger, composition_contract, geometries):
    """Bind a supported source contract to measured geometry, not model claims.

    Evidence linkage is weaker than per-item acceptance and is deliberately
    recorded separately. Unsupported semantics remain unverified.
    """
    from .cad_structure_contract import validate_explicit_composition
    result=deepcopy(ledger)
    result["geometry_acceptance"]={"status":"not_checked","checks":[]}
    if composition_contract is not None:
        measured=validate_explicit_composition(composition_contract,geometries)
        check_id="source-composition-1"
        result["geometry_acceptance"]={"status":"partial","checks":[{
            "check_id":check_id,"authority":"backend_measured_geometry",
            "contract":deepcopy(composition_contract),"result":measured,
            "geometry_ids":[g["id"] for g in geometries if "id" in g],
            "scope":"supported_composition_contract_only",
        }]}
        evidence=str(composition_contract.get("evidence") or "")
        for item in result["evidence_items"]:
            if item["evidence"]["text"] in evidence:
                item["binding_status"]="evidence_linked"
                item["related_check_ids"]=[check_id]
                # A lexical mention inside a checked contract does not prove
                # the individual requirement's subject or semantic coverage.
    result.pop("revision_sha256",None)
    result["revision_sha256"]=hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False).encode("utf-8")).hexdigest()
    return result
