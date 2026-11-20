"""Source-scoped primitive checks. No geometry creation or model assertions.

Supported explicit syntax: 名称：圆/矩形/线段/圆弧，... coordinates
and dimensions. Unsupported prose remains unverified, never a full pass.
"""
import math
import re
from copy import deepcopy

from .cad_structure_contract import StructureContractError

N=r"[-+]?\d+(?:\.\d+)?"
P=rf"[（(]\s*({N})\s*[,，]\s*({N})\s*[）)]"
INVENTORY_MARKER=r"(?:完整部件清单|全部图元清单)[：:]"


def _clause_field_matches(kind,body):
    """Find the exact field matches this parser will consume, once.

    The parser uses the first match for each named field.  Returning those
    match objects lets residual calculation remove only the consumed span;
    a second center/radius or unit therefore remains unresolved instead of
    being silently erased by a broader cleanup regex.
    """
    unit_pattern=r"毫米|厘米|米|mm|cm|m"
    matches={};spans=[]
    def first(key,pattern,flags=0):
        match=re.search(pattern,body,flags)
        if match:
            matches[key]=match
            spans.append(match.span())
        return match
    first("units",r"坐标单位(?:为|是)?\s*("+unit_pattern+r")")
    if kind in {"圆","圆弧"}:
        first("圆心","圆心"+P)
        first("半径",r"半径(?:为|是)?\s*("+N+r")\s*("+unit_pattern+r")")
        if kind=="圆弧":
            first("角度",rf"起始角\s*({N})\s*度[，,\s]+终止角\s*({N})\s*度")
    elif kind=="矩形":
        first("左下角","左下角"+P)
        first("宽",r"宽(?:为|是)?\s*("+N+r")\s*("+unit_pattern+r")")
        first("高",r"高(?:为|是)?\s*("+N+r")\s*("+unit_pattern+r")")
    else:
        first("起点","起点"+P)
        first("终点","终点"+P)
    return matches,spans


def _unsupported_clause_residue(body,consumed_spans):
    """Return clause text left after removing the spans actually consumed."""
    text=body
    for start,end in sorted(set(consumed_spans),reverse=True):
        text=text[:start]+text[end:]
    return text.strip(" \t\r\n，,；;。:：")


def _object_geometry_refs(obj):
    """Read the executor's canonical object scope without guessing a field.

    ``geometry_refs`` is the executor/logical-object channel; legacy callers
    and stored records may still carry ``geometry_ids``.  When both exist they
    must agree, and a missing, malformed, duplicate or conflicting reference
    stays unresolved so the caller emits ``unknown`` instead of measuring the
    wrong geometry.
    """
    refs=obj.get('geometry_refs') if isinstance(obj,dict) else None
    legacy=obj.get('geometry_ids') if isinstance(obj,dict) else None
    if refs is None:refs=legacy
    elif legacy is not None and refs!=legacy:return None
    if not isinstance(refs,list) or not refs:return None
    normalized=[]
    for value in refs:
        if isinstance(value,bool):return None
        if isinstance(value,int):normalized.append(value)
        elif isinstance(value,str) and value.strip().isdigit():normalized.append(int(value.strip()))
        else:return None
    if len(normalized)!=len(set(normalized)):return None
    return normalized


def source_texts(text):
    source=text.split("\n后端试算反馈：",1)[0]
    marker="\n最新已确认要求（"
    if marker not in source:return [source]
    first=source.split(marker,1)[0]
    followup="\n用户逐轮补充的原文约束（按时间排序，后文覆盖同名约束；必须保留全部组成）：\n"
    return [first,source.split(followup,1)[1]] if followup in source else [first]


def verify_final_source_contract(text,geometries,logical_objects=None):
    """Read-only final measurement of unambiguously scoped user facts."""
    from .cad_requirement_contract import requirement_contract
    from .cad_construction import construction_geometry_bounds
    sources=source_texts(text)
    contract=requirement_contract([{'source_id':f'user:{i}','text':s} for i,s in enumerate(sources)])
    gs=[g for g in geometries if g.get('selected') is not False and g.get('role') not in {'annotation','reference','ignored'}]
    checks=[];unknown=[];failures=[]
    if not gs:return {'status':'not_checked','coverage':'partial','checks':[]}
    bounds=construction_geometry_bounds(gs)
    def measure(field,actual,expected,operator,source_id,evidence,ids=None):
        delta=max(abs(a-b) for a,b in zip(actual,expected)) if isinstance(actual,list) else actual-expected
        passed=(abs(delta)<=.5 if operator=='eq' else delta<=.5 if operator=='lte' else delta>=-.5)
        check={'field':field,'actual_mm':actual,'expected_mm':expected,'operator':operator,
               'tolerance_mm':.5,'source_requirement_id':source_id,'source_evidence':evidence,
               'status':'passed' if passed else 'failed','geometry_ids':ids if ids is not None else [g['id'] for g in gs]}
        checks.append(check)
        if not passed:failures.append(check)
    for fact in contract['facts']:
        if fact['status']!='effective':continue
        selected=gs
        if len(contract['subjects'])!=1 or fact['binding']!='single_subject':
            matches=[obj for obj in logical_objects or [] if obj.get('label')==fact['subject']]
            refs=_object_geometry_refs(matches[0]) if len(matches)==1 else None
            if len(matches)!=1 or not refs:
                unknown.append({'source_requirement_id':fact['fact_id'],'reason':'对象范围尚未唯一绑定'});continue
            selected=[g for g in gs if g['id'] in refs]
            if len(selected)!=len(refs):
                unknown.append({'source_requirement_id':fact['fact_id'],'reason':'逻辑对象引用不完整'});continue
        local_bounds=construction_geometry_bounds(selected)
        field=fact['field'];actual=None
        if field in {'width','height'}:
            axis='x' if field=='width' else 'y'
            actual=local_bounds['max_'+axis]-local_bounds['min_'+axis]
        elif len(selected)==1 and selected[0].get('type')=='circle' and field in {'radius','diameter'}:
            actual=selected[0]['radius']*(2 if field=='diameter' else 1)
        if actual is not None:measure(field,actual,fact['value_mm'],fact['operator'],fact['fact_id'],fact['evidence'],[g['id'] for g in selected])
        else:unknown.append({'source_requirement_id':fact['fact_id'],'reason':'当前测量器不支持此要求'})
    # Coordinates are not inferred from assumptions, control points or a
    # multi-object layout. Later explicit source centers supersede earlier ones.
    if len(contract['subjects'])==1:
        center=None
        for i,source in enumerate(sources):
            if re.search('控制点|顶点|端点',source):continue
            matches=list(re.finditer(r'(?:几何中心|中心点|中心)(?:位于|在|为|是)?\s*'+P,source))
            units=re.findall(r'坐标单位(?:为|是)?\s*(毫米|厘米|米|mm|cm|m)',source,re.I)
            if not units:units=re.findall(N+r'\s*(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])',source,re.I)
            if matches and len(set(u.lower() for u in units))==1:
                match=matches[-1];factor={'米':1000,'m':1000,'厘米':10,'cm':10,'毫米':1,'mm':1}[units[-1].lower()]
                center=([float(match[1])*factor,float(match[2])*factor],f'user:{i}:center',match[0])
        if center:
            actual=[(bounds['min_x']+bounds['max_x'])/2,(bounds['min_y']+bounds['max_y'])/2]
            measure('center',actual,center[0],'eq',center[1],center[2])
    if failures:
        raise StructureContractError('最终几何不符合明确的源需求',{
            'authority':'backend_measured_geometry','geometry_ids':sorted({i for f in failures for i in f['geometry_ids']}),
            'failures':failures,'local_repair_possible':True,
            'repair_instruction':'只修正失败源需求绑定的对象和参数；不得删除源要求或改变未受影响对象。'})
    return {'status':'partial' if checks else 'not_checked','coverage':'partial','checks':checks,
            'unknown_requirements':unknown,'review_required':bool(unknown)}


def extract_scoped_primitives(text):
    specs={}
    for source in source_texts(text):
        source=re.sub(INVENTORY_MARKER,"\n",source)
        for clause in re.split(r"[；;。\n]",source):
            m=re.fullmatch(r"\s*([^：:，,]{1,40})[：:]\s*(圆弧|圆|矩形|线段)[，,\s]+(.+?)\s*",clause)
            if not m:continue
            label,kind,body=m.groups()
            # Explicit per-clause unit required; never borrow another part's
            # radius, dimensions, or units.
            factors={"毫米":1,"mm":1,"厘米":10,"cm":10,"米":1000,"m":1000}
            matches,consumed=_clause_field_matches(kind,body)
            units=matches.get("units")
            if not units:continue
            spec={"subject":label.strip(),"kind":kind,"evidence":clause.strip()}
            def scalar(name):
                match=matches.get(name)
                return float(match[1])*factors[match[2]] if match else None
            def point(name):
                match=matches.get(name)
                return [float(match[1])*factors[units[1]],float(match[2])*factors[units[1]]] if match else None
            if kind in {"圆","圆弧"}:
                spec.update(center=point("圆心"),radius=scalar("半径"))
                if spec["center"] is None or spec["radius"] is None:continue
                if kind=="圆弧":
                    angles=matches.get("角度")
                    if not angles:continue
                    spec.update(start_angle=float(angles[1]),end_angle=float(angles[2]))
            elif kind=="矩形":
                spec.update(origin=point("左下角"),width=scalar("宽"),height=scalar("高"))
                if any(spec[k] is None for k in ("origin","width","height")):continue
            else:
                spec.update(start=point("起点"),end=point("终点"))
                if spec["start"] is None or spec["end"] is None:continue
            residue=_unsupported_clause_residue(body,consumed)
            if residue:spec["unresolved_evidence"]=residue
            # Later revisions override only the same explicitly named subject.
            specs[spec["subject"]]=spec
    # Also accept one unambiguous primitive described in ordinary command
    # syntax.  This is an independent source parser: it measures the executed
    # geometry and never reads the construction plan or its assertions.
    if not specs:
        source="\n".join(source_texts(text))
        unit_pattern=r"毫米|厘米|米|mm|cm|m"
        factors={"毫米":1,"mm":1,"厘米":10,"cm":10,"米":1000,"m":1000}
        units=re.findall(r"坐标单位(?:为|是)?\s*("+unit_pattern+r")",source,re.I)
        unit=units[-1].lower() if units else None
        if unit:
            line=re.search(r"(?:画|绘制|生成|创建)?\s*(?:一|1)?\s*条?\s*(?:线段|直线)\s*(?:从|起点(?:为|是)?)\s*"+P+r"\s*(?:到|至|终点(?:为|是)?)\s*"+P,source)
            if line:
                values=[float(value)*factors[unit] for value in line.groups()]
                specs["线段"]={"subject":"线段","kind":"线段","evidence":line[0],
                    "start":values[:2],"end":values[2:]}
            rectangle=re.search(
                r"(?:画|绘制|生成|创建)?\s*(?:一|1)?\s*个?\s*(?:矩形|长方形)"
                r"[^；;。\n]{0,80}?宽(?:为|是)?\s*("+N+r")\s*("+unit_pattern+r")"
                r"[^；;。\n]{0,40}?高(?:为|是)?\s*("+N+r")\s*("+unit_pattern+r")"
                r"[^；;。\n]{0,80}?左下角(?:为|是)?\s*"+P,
                source,re.I,
            )
            if rectangle:
                width=float(rectangle[1])*factors[rectangle[2].lower()]
                height=float(rectangle[3])*factors[rectangle[4].lower()]
                origin=[float(rectangle[5])*factors[unit],float(rectangle[6])*factors[unit]]
                specs["矩形"]={"subject":"矩形","kind":"矩形","evidence":rectangle[0],
                    "origin":origin,"width":width,"height":height}
    # Reuse the source contract for partial later revisions. Keep the original
    # type and coordinates; a scalar correction never creates a new part.
    from .cad_requirement_contract import requirement_contract
    contract=requirement_contract([{'source_id':f'source-{i+1}','text':s}
                                   for i,s in enumerate(source_texts(text))])
    for fact in contract['facts']:
        spec=specs.get(fact['subject'])
        if (spec is not None and fact['status']=='effective' and fact['operator']=='eq'
                and fact['field'] in spec and fact['field'] in {'radius','width','height'}):
            spec[fact['field']]=fact['value_mm']
            spec.setdefault('dimension_evidence',{})[fact['field']]={
                'source_id':fact['source_id'],'evidence':fact['evidence']}
    return list(specs.values())


def verify_scoped_primitives(text, geometries, logical_objects=None):
    from .cad_structure_contract import _frame
    specs=extract_scoped_primitives(text)
    if not specs:return {"status":"not_checked","checks":[],"coverage":"partial"}
    geometries=[g for g in geometries if g.get("selected") is not False and g.get("role") not in {"reference","annotation","ignored"}]
    def point(p):return [p["x"],p["y"]]
    def near(a,b):return math.dist(a,b)<=.5
    def matches(s,g):
        if s["kind"] in {"圆","圆弧"}:
            if g.get("type")!=({"圆":"circle","圆弧":"arc"}[s["kind"]]):return False
            if not near(s["center"],point(g["center"])) or abs(s["radius"]-g["radius"])>.5:return False
            if s["kind"]=="圆弧":
                def sweep(start,end):
                    delta=end-start
                    if abs(delta)<1e-9:return 360.0
                    if delta<0:delta+=360*math.ceil(-delta/360)
                    return delta
                return (all(abs((g[k]-s[k]+180)%360-180)<.001 for k in ("start_angle","end_angle"))
                    and abs(sweep(g["start_angle"],g["end_angle"])-sweep(s["start_angle"],s["end_angle"]))<.001)
            return True
        if s["kind"]=="矩形":
            frame=_frame(g)
            return bool(frame and near(s["origin"],frame[:2]) and abs(s["width"]-frame[2])<=.5 and abs(s["height"]-frame[3])<=.5)
        return g.get("type")=="line" and near(s["start"],point(g["start"])) and near(s["end"],point(g["end"]))
    # Bipartite assignment avoids a greedy match stealing a repeated component.
    options=[[i for i,g in enumerate(geometries) if matches(s,g)] for s in specs]
    owner={}
    def assign(index,visited):
        for candidate in options[index]:
            if candidate in visited:continue
            visited.add(candidate)
            if candidate not in owner or assign(owner[candidate],visited):
                owner[candidate]=index
                return True
        return False
    for i,s in enumerate(specs):
        if not assign(i,set()):
            raise StructureContractError("原文指定部件的类型、坐标或尺寸不匹配："+s["subject"],{"source_requirement":s})
    unmatched=[g["id"] for i,g in enumerate(geometries) if i not in owner]
    # Only an explicitly closed, fully parseable source inventory authorizes
    # exact cardinality. An unsupported clause must not become a missing part.
    inventories=[re.split(INVENTORY_MARKER,s,maxsplit=1)[1] for s in source_texts(text)
                 if re.search(INVENTORY_MARKER,s)]
    evidence={s['evidence'] for s in specs if not s.get('unresolved_evidence')}
    from .cad_relation_acceptance import extract_named_relations
    evidence.update(r['evidence']['text'] for r in extract_named_relations(text,[s['subject'] for s in specs]))
    complete_inventory=bool(inventories) and all(
        all(c.strip() in evidence for c in re.split(r"[；;。\n]",body) if c.strip())
        for body in inventories)
    if unmatched and complete_inventory:
        raise StructureContractError(
            "完整部件清单之外存在额外可见图元",
            {"reason":"extra_geometry","geometry_ids":unmatched,
             "inventory_scope":"complete","required_subjects":[s["subject"] for s in specs]})
    ids={index:geometries[i]["id"] for i,index in owner.items()}
    report={"status":"partial","coverage":"explicit_scoped_primitives_only",
        "inventory_scope":"complete" if complete_inventory else "partial",
        "unverified_geometry_ids":unmatched,"review_required":bool(unmatched),"checks":[
        {"subject":s["subject"],"source_requirement":s,"geometry_ids":[ids[i]],
         "status":"passed","authority":"backend_measured_geometry"} for i,s in enumerate(specs)]}
    ownership_complete=True
    if logical_objects is not None:
        ownership_complete=False
        subjects={s["subject"] for s in specs}
        for check in report["checks"]:
            owners=[o for o in logical_objects if check["geometry_ids"][0] in (_object_geometry_refs(o) or [])]
            if not owners or any(not o.get("assembly_id") for o in owners):
                raise StructureContractError("部件缺少明确整体归属："+check["subject"])
            # A model label is never positive identity proof.  It is only a
            # contradiction signal: if an owner is labelled as a different
            # declared source subject while owning this subject's measured
            # geometry, the object binding is internally inconsistent.
            for owner in owners:
                label=str(owner.get("label") or "")
                if label in subjects and label!=check["subject"]:
                    raise StructureContractError(
                        "部件归属与来源主体不一致："+check["subject"],
                        {"reason":"object_binding_conflict","subject":check["subject"],
                         "owner_label":label,"geometry_ids":check["geometry_ids"],
                         "object_id":owner.get("object_id")})
            check["object_ids"]=[o["object_id"] for o in owners]
            check["assembly_ids"]=sorted({o["assembly_id"] for o in owners})
            ownership_complete=True
    from .cad_relation_acceptance import verify_named_relations
    report['relation_acceptance']=verify_named_relations(text,geometries,report['checks'])
    report['review_required']=report['review_required'] or report['relation_acceptance']['review_required']

    category_for_kind={"圆":"circle","圆弧":"arc","矩形":"rectangle","线段":"line"}
    scope_entries=[];all_object_ids=set()
    for check in report["checks"]:
        spec=check["source_requirement"]
        entry={"requirement_id":f"source-scope:{spec['subject']}","subject":spec["subject"],
               "category":category_for_kind.get(spec["kind"],"named_subject"),
               "quantity":1,"geometry_ids":deepcopy(check["geometry_ids"]),
               "object_ids":deepcopy(check.get("object_ids") or []),
               "assembly_ids":deepcopy(check.get("assembly_ids") or []),
               "evidence":spec["evidence"],"authority":"backend_measured_geometry",
               "measurement":{"kind":spec["kind"]}}
        for key in ("center","radius","origin","width","height","start","end","start_angle","end_angle"):
            if key in spec:entry["measurement"][key]=deepcopy(spec[key])
        if spec.get("unresolved_evidence"):
            entry["unresolved_evidence"]=spec["unresolved_evidence"]
        scope_entries.append(entry)
        all_object_ids.update(entry["object_ids"])
    grouping="object"
    grouped_ids=all_object_ids
    reasons=[]
    unresolved=[s for s in specs if s.get("unresolved_evidence")]
    if not complete_inventory:reasons.append("来源完整清单未声明或包含未解析条款")
    if unresolved:reasons.append("条款包含未解释、未测量的片段")
    if unmatched:reasons.append("存在完整清单之外的可见图元")
    if not ownership_complete:reasons.append("部件缺少唯一逻辑对象和整体归属")
    if report['relation_acceptance']['review_required']:reasons.append("存在未验证的原文部件关系")
    complete_scope=(complete_inventory and not unmatched and ownership_complete
                    and not unresolved
                    and not report['relation_acceptance']['review_required']
                    and all(c["status"]=="passed" for c in report["checks"]))
    report["scope_evidence"]={"schema":"cad.source-scope-evidence.v1",
        "state":"complete" if complete_scope else "partial","entries":scope_entries,
        "count_baseline":{"expected_object_count":len(grouped_ids) if complete_scope else None,
                          "grouping":grouping},
        "unmatched_geometry_ids":deepcopy(unmatched),"reasons":reasons}
    if complete_scope:
        report["status"]="passed"
        report["coverage"]="complete"
        report["review_required"]=False
    return report
