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


# ---------------------------------------------------------------------------
# Requirement -> verifier -> measurement coverage closure
# ---------------------------------------------------------------------------
# This layer does not recognize requirements and does not create geometry.  It
# consumes the already measured *_acceptance reports and binds each source
# clause to the backend check that measured it.  A clause is complete only
# when every applicable check passed and no unresolved/unsupported item
# remains.  A failed, partial or unbound clause stays a blocking requirement.
#
# The table below is a bridge for semantic verifiers that expose their
# recognized scope through ``coverage`` but omit source spans.  It is keyed by
# the verifier's own coverage value, not by a case id, and carries no pass
# authority: the semantic report itself must be ``passed``.

_SEMANTIC_COVERAGE_SOURCE_TERMS = {
    "cardioid_shape_and_declared_direction": [
        {"role": "shape_identity", "pattern": r"cardioid|心形线",
         "check": "cardioid_polar_identity"},
        {"role": "declared_direction", "pattern": r"尖点朝下",
         "check": "cardioid_polar_identity"},
    ],
    "astroid_identity_radius_and_four_cusps": [
        {"role": "shape_identity", "pattern": r"astroid|星形线",
         "check": None},
    ],
    "explicit_nested_square_frames": [
        {"role": "shape_identity", "pattern": r"嵌套[^，,；;。\n]*正方形",
         "check": None},
    ],
    "explicit_regular_polygon_and_concentric_hole": [
        {"role": "shape_identity", "pattern": r"正\s*\d+\s*边形",
         "check": None},
    ],
}

_ADMIN_SEGMENT = re.compile(
    r"^(?:完整部件清单|全部图元清单|坐标单位(?:为|是)?\s*"
    r"(?:毫米|厘米|米|mm|cm|m))[：:]?$", re.I)

# A second requirement can be attached to the previous one without any comma,
# e.g. "直角连接并在墙上加一扇门".  Split before these top-level connectors so
# the added component cannot inherit the previous clause's verified status.
_SUBREQUIREMENT_BOUNDARY = re.compile(
    r"(?=(?:并在|且在|并且|同时|然后|另外|还要|以及|并加|并带|且加|且带|再在|再加))")
_PATH_SHAPE_CLAUSE = re.compile(
    r"^(?:请|帮我|麻烦|给我)?(?:画|绘制|生成|制作|创建|设计|建|做)?"
    r"(?:一个|一条|一座|个|条)?\s*"
    r"(?:L\s*[形型](?:走廊|通道|路径|轮廓|线)?"
    r"|直角折形(?:走廊|通道)?"
    r"|折形(?:走廊|通道)?)$", re.I)
_PATH_RIGHT_ANGLE_CLAUSE = re.compile(
    r"^(?:请|帮我|麻烦)?(?:两臂|两段|两条臂|边界|拐角|转角|连接"
    r"|并|且|同时)?(?:以|成|为|是)?直角(?:连接|相连|相接|拐角|转角)?$")
_PATH_ARM_CLAUSE = re.compile(
    rf"^(?:两条臂|两臂|两段|两条)?(?:分别|各)?(?:长|长度为|为)?\s*"
    rf"({N})\s*(毫米|厘米|米|mm|cm|m)\s*(?:和|、|,|，)\s*"
    rf"({N})\s*(毫米|厘米|米|mm|cm|m)$", re.I)
_WIDTH_CLAUSE = re.compile(
    rf"宽(?:度)?(?:为|是|取|设为)?\s*({N})\s*(毫米|厘米|米|mm|cm|m)",
    re.I)
# Only syntax that decorates a measurement is removable when checking whether
# a verified claim really covers the whole source clause.  Everything else is
# left as residual and blocks the clause.
_REQUEST_PREFIX = re.compile(
    r"^(?:请|帮我|麻烦|给我)?(?:画|绘制|生成|制作|创建|设计|建|做)?"
    r"(?:一个|一条|一座|一张|一幅|个|条)?\s*")
_ASCII_ALIAS_PAREN = re.compile(
    r"[（(]\s*[A-Za-z][A-Za-z0-9 _./+-]*\s*[）)]")
_UNIT_FACTORS = {"毫米": 1.0, "mm": 1.0, "厘米": 10.0, "cm": 10.0,
                 "米": 1000.0, "m": 1000.0}


def _split_subrequirements(raw):
    """Split top-level attached requirements while preserving offsets."""
    depths = []
    depth = 0
    for char in raw:
        depths.append(depth)
        if char in "(（":
            depth += 1
        elif char in ")）":
            depth = max(0, depth - 1)
    boundaries = [match.start() for match in _SUBREQUIREMENT_BOUNDARY.finditer(raw)
                  if match.start() > 0 and depths[match.start()] == 0]
    if not boundaries:
        return [(0, len(raw))]
    starts = [0] + boundaries
    ends = boundaries + [len(raw)]
    return [(start, end) for start, end in zip(starts, ends) if end > start]


def _source_segments(text):
    """Split source into top-level clauses without breaking coordinates.

    Commas inside parentheses belong to a point, not to a new requirement.
    The inventory header and a stand-alone unit declaration are administrative
    and never count as user requirements.
    """
    segments = []
    for source_index, source in enumerate(source_texts(text)):
        pieces = []
        begin = 0
        depth = 0
        for index, char in enumerate(source):
            if char in "(（":
                depth += 1
            elif char in ")）":
                depth = max(0, depth - 1)
            elif depth == 0 and char in "，,；;。\n":
                pieces.append((begin, index))
                begin = index + 1
        pieces.append((begin, len(source)))
        expanded = []
        for piece_begin, piece_end in pieces:
            raw = source[piece_begin:piece_end]
            expanded.extend((piece_begin + start, piece_begin + end)
                            for start, end in _split_subrequirements(raw))
        for begin, end in expanded:
            raw = source[begin:end]
            stripped = raw.strip()
            if not stripped:
                continue
            offset = len(raw) - len(raw.lstrip())
            begin += offset
            end = begin + len(stripped)
            if _ADMIN_SEGMENT.match(stripped):
                continue
            segments.append({
                "source_index": source_index,
                "text": source[begin:end],
                "start": begin,
                "end": end,
                "administrative": False,
            })
    return segments


def _segment_for_span(segments, source_index, start, end=None):
    for segment in segments:
        if segment["source_index"] != source_index:
            continue
        if end is None:
            if segment["start"] <= start < segment["end"]:
                return segment
        elif start >= segment["start"] and end <= segment["end"]:
            return segment
        if start < segment["end"] and end is not None and end > segment["start"]:
            return segment
    return None


def _numbers_mm(text):
    factors = {"毫米": 1.0, "mm": 1.0, "厘米": 10.0, "cm": 10.0,
               "米": 1000.0, "m": 1000.0}
    values = []
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])",
                             text, re.I):
        values.append(float(match.group(1)) * factors[match.group(2).lower()])
    return values


def _near_mm(left, right, tolerance=0.5):
    return abs(float(left) - float(right)) <= tolerance


def _claim_residual(text, evidence):
    """Return source text not covered by a claim's actual evidence phrase.

    This is deliberately syntax-only: command prefixes and ASCII alias
    parentheses are decoration, while any remaining content is substantive and
    must keep the clause partial.  No list of requirement connectors is used.
    """
    if not isinstance(text, str) or not isinstance(evidence, str) or not evidence:
        return (text or "").strip()
    index = text.find(evidence)
    if index < 0:
        return text.strip()
    residual = text[:index] + text[index + len(evidence):]
    residual = _REQUEST_PREFIX.sub("", residual, count=1)
    residual = _ASCII_ALIAS_PAREN.sub("", residual)
    return re.sub(r"[\s，,；;。:：、（）()]", "", residual)


def _path_actual_width_mm(check, expected_mm):
    """Read the measured boundary width, not the source-parsed requirement."""
    expected = check.get("expected_boundary_lengths_m")
    actual = check.get("actual_boundary_lengths_m")
    if not isinstance(expected, list) or not isinstance(actual, list):
        return None
    if len(expected) != len(actual):
        return None
    target = float(expected_mm) / 1000.0
    candidates = [
        float(measured) * 1000.0
        for wanted, measured in zip(expected, actual)
        if _near_mm(wanted, target, tolerance=0.0005)
    ]
    if not candidates:
        return None
    if not all(_near_mm(candidate, expected_mm) for candidate in candidates):
        return None
    return min(candidates)


def _path_claim_matches_fact(claim, fact):
    if claim.get("status") != "verified" or claim.get("covers_field") != fact.get("field"):
        return None
    if fact.get("field") == "width":
        measured = _path_actual_width_mm(claim.get("check") or {}, fact.get("value_mm"))
        if measured is None or not _near_mm(measured, fact.get("value_mm")):
            return None
        return measured
    return claim.get("value_mm") if _near_mm(claim.get("value_mm"), fact.get("value_mm")) else None


def _checks_all_passed(report):
    checks = report.get("checks") if isinstance(report, dict) else None
    if not isinstance(checks, list) or not checks:
        return True
    return all(isinstance(check, dict) and check.get("status") == "passed"
               for check in checks)


def _semantic_check(report, name=None):
    checks = report.get("checks") if isinstance(report, dict) else None
    if not isinstance(checks, list):
        return None
    for check in checks:
        if not isinstance(check, dict):
            continue
        if name is None or check.get("name") == name:
            return check
    return None


def _semantic_claim_status(report):
    if not isinstance(report, dict):
        return "partial", "semantic_acceptance_report_unavailable"
    if report.get("status") != "passed":
        return "partial", f"semantic_report_status_{report.get('status') or 'missing'}"
    if report.get("review_required") is True:
        return "partial", "semantic_report_review_required"
    if not _checks_all_passed(report):
        return "partial", "semantic_checks_not_all_passed"
    return "verified", None


def _semantic_claims(report, segments):
    """Return source-bound semantic claims, never model text as evidence."""
    claims = []
    if not isinstance(report, dict):
        return claims
    status, reason = _semantic_claim_status(report)
    evidence_texts = []
    for requirement in report.get("requirements") or []:
        if not isinstance(requirement, dict):
            continue
        for evidence in requirement.get("source_evidence") or []:
            if isinstance(evidence, str) and evidence.strip():
                evidence_texts.append({
                    "text": evidence,
                    "kind": requirement.get("kind"),
                    "role": "semantic_requirement",
                    "check": None,
                })
    coverage = report.get("coverage")
    for term in _SEMANTIC_COVERAGE_SOURCE_TERMS.get(coverage, []):
        evidence_texts.append({**term, "kind": coverage})
    seen = set()
    for item in evidence_texts:
        text = item.get("text")
        pattern = item.get("pattern")
        if not text and not pattern:
            continue
        matches = []
        for segment in segments:
            source = None
            if text:
                if text in segment["text"]:
                    matches.append((segment, text))
            elif pattern and re.search(pattern, segment["text"], re.I):
                match = re.search(pattern, segment["text"], re.I)
                matches.append((segment, match.group(0)))
        for segment, evidence in matches:
            key = (segment["source_index"], segment["start"], item.get("role"),
                   item.get("check"), evidence)
            if key in seen:
                continue
            seen.add(key)
            claim = {
                "requirement": segment["text"],
                "source_evidence": evidence,
                "source_index": segment["source_index"],
                "role": item.get("role"),
                "kind": item.get("kind"),
                "verifier": "semantic_acceptance",
                "check_name": item.get("check"),
                "status": status,
            }
            check = _semantic_check(report, item.get("check"))
            if check:
                claim["check"] = deepcopy(check)
                if item.get("role") == "declared_direction":
                    vector = ((check.get("measurements") or {})
                              .get("cusp_pointing_unit_vector"))
                    if not isinstance(vector, list) or len(vector) != 2:
                        claim["status"] = "partial"
                        claim["reason"] = "direction_measurement_missing"
                    elif vector[1] > -math.cos(math.radians(10)):
                        claim["status"] = "partial"
                        claim["reason"] = "measured_direction_not_downward"
            elif item.get("check"):
                claim["status"] = "partial"
                claim["reason"] = "declared_semantic_check_missing"
            if status != "verified" and not claim.get("reason"):
                claim["reason"] = reason
            if claim.get("status") == "verified":
                residual = _claim_residual(segment["text"], evidence)
                if residual:
                    claim["status"] = "partial"
                    claim["reason"] = "局部语义证据未覆盖剩余原文：" + residual
            claims.append(claim)
    return claims


def _path_claims(report, segments):
    """Bind the existing right-angle-arm measurements to their source clauses.

    The path verifier is itself a source-scoped acceptance rule.  This bridge
    only exposes the numbers it already measured; it does not accept geometry
    and does not fill a missing measurement.
    """
    if not isinstance(report, dict) or report.get("status") != "passed":
        return []
    checks = report.get("checks") or []
    check = next((item for item in checks if isinstance(item, dict)
                  and item.get("name") == "perpendicular_arm_dimensions"), None)
    if not check or check.get("status") != "passed":
        return []
    width = check.get("required_width_m")
    arms = check.get("required_arm_extents_m")
    substantive = [segment for segment in segments
                   if not segment.get("administrative")]
    first_substantive = substantive[0] if substantive else None
    claims = []
    for segment in segments:
        text = segment["text"]
        numbers = _numbers_mm(text)
        width_match = _WIDTH_CLAUSE.search(text)
        if width is not None and width_match:
            measured_width = (float(width_match.group(1))
                              * _UNIT_FACTORS[width_match.group(2).lower()])
            if _near_mm(measured_width, float(width) * 1000):
                evidence = width_match.group(0).strip()
                residual = _claim_residual(text, evidence)
                claim = {
                    "requirement": text, "source_evidence": evidence,
                    "source_index": segment["source_index"],
                    "role": "path_width", "verifier": "path_relation_acceptance",
                    "status": "partial" if residual else "verified",
                    "check": deepcopy(check),
                    "covers_field": "width", "value_mm": float(width) * 1000,
                }
                if residual:
                    claim["reason"] = "局部尺寸证据未覆盖剩余原文：" + residual
                claims.append(claim)
                continue
        if (arms and "臂" in text and len(numbers) >= len(arms)
                and _PATH_ARM_CLAUSE.fullmatch(text.strip())):
            converted = [float(value) * 1000 for value in arms]
            if all(any(_near_mm(number, required) for number in numbers)
                   for required in converted):
                claims.append({
                    "requirement": text, "source_evidence": text,
                    "source_index": segment["source_index"],
                    "role": "path_arm_extents", "verifier": "path_relation_acceptance",
                    "status": "verified", "check": deepcopy(check),
                    "value_mm": converted,
                })
                continue
        if "直角" in text and check.get("orthogonal") is True \
                and _PATH_RIGHT_ANGLE_CLAUSE.fullmatch(text.strip()):
            claims.append({
                "requirement": text, "source_evidence": text,
                "source_index": segment["source_index"],
                "role": "path_right_angle", "verifier": "path_relation_acceptance",
                "status": "verified", "check": deepcopy(check),
            })
            continue
        actual = check.get("actual_boundary_lengths_m")
        if (segment is first_substantive and not numbers
                and _PATH_SHAPE_CLAUSE.fullmatch(text.strip())
                and check.get("polygon_count") == 1
                and check.get("orthogonal") is True
                and isinstance(actual, list) and len(actual) == 6):
            claims.append({
                "requirement": text, "source_evidence": text,
                "source_index": segment["source_index"],
                "role": "path_shape_identity", "verifier": "path_relation_acceptance",
                "status": "verified", "check": deepcopy(check),
                "note": "唯一闭合、六边直角边界与两臂/宽度测量共同确定直角折形",
            })
    return claims


def _scope_claims(source_acceptance, segments):
    evidence = source_acceptance.get("scope_evidence") or {}
    if evidence.get("state") != "complete":
        return []
    claims = []
    checks = source_acceptance.get("checks") or []
    for entry in evidence.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        text = entry.get("evidence")
        if not isinstance(text, str) or not text.strip():
            continue
        segment = next((item for item in segments if text == item["text"]
                        or text in item["text"]), None)
        if segment is None:
            continue
        check = next((item for item in checks if isinstance(item, dict)
                      and item.get("source_requirement", {}).get("subject")
                      == entry.get("subject")), None)
        claims.append({
            "requirement": segment["text"],
            "source_evidence": text,
            "source_index": segment["source_index"],
            "role": "explicit_scoped_primitive",
            "verifier": "verify_scoped_primitives",
            "status": "verified" if check and check.get("status") == "passed" else "partial",
            "check": deepcopy(check) if check else None,
            "measurement": deepcopy(entry.get("measurement")),
        })
    return claims


def _generic_claims(source_acceptance, segments):
    """Bind checks that already carry a source quote or a source requirement."""
    claims = []
    for key, report in source_acceptance.items():
        if key in {"semantic_acceptance", "final_source_acceptance"}:
            continue
        if not key.endswith("_acceptance"):
            continue
        if not isinstance(report, dict):
            continue
        for check in report.get("checks") or []:
            if not isinstance(check, dict):
                continue
            evidence = check.get("source_evidence")
            if isinstance(evidence, dict):
                text = evidence.get("text")
                start = evidence.get("start")
                source_index = 0
            else:
                text = None
                start = None
                source_index = 0
            requirement = check.get("source_requirement")
            if isinstance(requirement, dict):
                text = requirement.get("evidence") or text
            if not isinstance(text, str) or not text.strip():
                continue
            segment = None
            if isinstance(start, int):
                segment = _segment_for_span(segments, source_index, start)
            if segment is None:
                segment = next((item for item in segments if text in item["text"]), None)
            if segment is None:
                continue
            claims.append({
                "requirement": segment["text"],
                "source_evidence": text,
                "source_index": segment["source_index"],
                "role": check.get("name") or check.get("field") or key,
                "verifier": key,
                "status": "verified" if check.get("status") == "passed" else "partial",
                "check": deepcopy(check),
            })
    return claims


def _top_level_check_claims(source_acceptance, segments):
    """Bind evidence-free top-level checks only when one clause can own them.

    Existing explicit Bezier bridging is the only producer of such checks.
    Requiring a single substantive clause prevents an unscoped check from
    being assigned to an arbitrary requirement.
    """
    substantive = [segment for segment in segments if not segment.get("administrative")]
    if len(substantive) != 1:
        return []
    check_fields = {"bezier_segment_count", "bezier_continuity"}
    claims = []
    for check in source_acceptance.get("checks") or []:
        if not isinstance(check, dict) or check.get("field") not in check_fields:
            continue
        claims.append({
            "requirement": substantive[0]["text"],
            "source_evidence": substantive[0]["text"],
            "source_index": substantive[0]["source_index"],
            "role": check.get("field"),
            "verifier": "source_acceptance",
            "status": "verified" if check.get("status") == "passed" else "partial",
            "check": deepcopy(check),
        })
    return claims


def _unknown_requirements(source_acceptance):
    found = []
    reports = {"source_acceptance": source_acceptance}
    for key, value in source_acceptance.items():
        if key.endswith("_acceptance") and isinstance(value, dict):
            reports[key] = value
    for key, value in reports.items():
        for item in value.get("unknown_requirements") or []:
            if isinstance(item, dict):
                found.append({"report": key, **deepcopy(item)})
    return found


def build_requirement_coverage_evidence(text, source_acceptance):
    """Build the source-clause to verifier/measurement coverage ledger."""
    from .cad_requirement_contract import requirement_contract

    source_acceptance = source_acceptance or {}
    scope = source_acceptance.get("scope_evidence") or {}
    if scope.get("state") == "complete" and source_acceptance.get("coverage") == "complete":
        entries = []
        for entry in scope.get("entries") or []:
            entries.append({
                "requirement_id": entry.get("requirement_id"),
                "requirement": entry.get("evidence"),
                "source_evidence": entry.get("evidence"),
                "status": "verified",
                "verifier": "verify_scoped_primitives",
                "measurement": deepcopy(entry.get("measurement")),
                "authority": "backend_measured_geometry",
            })
        return {
            "schema": "cad.requirement-coverage-evidence.v1",
            "state": "complete",
            "authority": "backend_measured_geometry",
            "clauses": entries,
            "verified_requirement_count": len(entries),
            "partial_requirement_count": 0,
            "unverified_requirement_count": 0,
            "blocking_requirements": [],
            "unresolved_fact_ids": [],
            "note": "显式完整部件清单已由既有来源作用域验收证明，未新增放行规则。",
        }

    sources = source_texts(text)
    contract = requirement_contract([
        {"source_id": f"user:{index}", "text": source}
        for index, source in enumerate(sources)
    ])
    segments = _source_segments(text)

    semantic_claims = _semantic_claims(source_acceptance.get("semantic_acceptance"), segments)
    path_claims = _path_claims(source_acceptance.get("path_relation_acceptance"), segments)
    scope_claims = _scope_claims(source_acceptance, segments)
    generic_claims = _generic_claims(source_acceptance, segments)
    top_level_claims = _top_level_check_claims(source_acceptance, segments)
    claims = semantic_claims + path_claims + scope_claims + generic_claims + top_level_claims

    final_report = source_acceptance.get("final_source_acceptance") or {}
    final_checks = final_report.get("checks") or []
    final_unknown = final_report.get("unknown_requirements") or []
    clauses = []
    blocking = []

    for segment in segments:
        facts = []
        for fact in contract.get("facts") or []:
            evidence = fact.get("evidence") or {}
            if _segment_for_span(segments, segment["source_index"],
                                 evidence.get("start", -1),
                                 evidence.get("end")) is segment:
                facts.append(fact)
        applicable_claims = [
            claim for claim in claims
            if claim["source_index"] == segment["source_index"]
            and claim["requirement"] == segment["text"]
        ]
        evidence_items = []
        unresolved = []
        supported = False
        failed = False
        claim_reason = None
        consumed_claims = set()
        for fact in facts:
            fact_id = fact.get("fact_id")
            if fact.get("status") != "effective" or fact.get("binding") == "unresolved":
                covered = next(
                    (claim for claim in applicable_claims
                     if _path_claim_matches_fact(claim, fact) is not None),
                    None,
                )
                if covered:
                    supported = True
                    consumed_claims.add(id(covered))
                    measured_mm = _path_claim_matches_fact(covered, fact)
                    evidence_items.append({
                        "requirement_id": fact_id,
                        "verifier": "path_relation_acceptance",
                        "status": "verified",
                        "measurement": {
                            "field": fact.get("field"),
                            "actual_mm": measured_mm,
                            "expected_mm": fact.get("value_mm"),
                            "source_evidence": fact.get("evidence"),
                            "check_name": (covered.get("check") or {}).get("name"),
                            "actual_boundary_lengths_m": deepcopy(
                                (covered.get("check") or {}).get("actual_boundary_lengths_m")),
                            "authority": "backend_measured_geometry",
                        },
                    })
                else:
                    unresolved.append({
                        "requirement_id": fact_id,
                        "field": fact.get("field"),
                        "expected_mm": fact.get("value_mm"),
                        "source_evidence": fact.get("evidence"),
                        "reason": "无法唯一绑定验证对象",
                    })
                continue
            check = next((item for item in final_checks
                          if isinstance(item, dict)
                          and item.get("source_requirement_id") == fact_id), None)
            if check and check.get("status") == "passed":
                supported = True
                evidence_items.append({
                    "requirement_id": fact_id,
                    "verifier": "verify_final_source_contract",
                    "status": "verified",
                    "measurement": deepcopy(check),
                })
            else:
                failed = True
                unknown = next((item for item in final_unknown
                                if isinstance(item, dict)
                                and item.get("source_requirement_id") == fact_id), None)
                reason = (unknown or {}).get("reason") or "无独立测量结果"
                unresolved.append({
                    "requirement_id": fact_id,
                    "field": fact.get("field"),
                    "expected_mm": fact.get("value_mm"),
                    "source_evidence": fact.get("evidence"),
                    "reason": reason,
                })
        for claim in applicable_claims:
            if id(claim) in consumed_claims:
                continue
            evidence_items.append({
                "requirement_id": f"clause:{segment['source_index']}:{segment['start']}",
                "verifier": claim.get("verifier"),
                "role": claim.get("role"),
                "status": claim.get("status"),
                "measurement": deepcopy(claim.get("check") or claim.get("measurement")),
                "reason": claim.get("reason"),
            })
            if claim.get("status") == "verified":
                supported = True
            else:
                failed = True
                claim_reason = claim_reason or claim.get("reason")
        if supported and not failed and not unresolved:
            status = "verified"
            reason = None
        elif supported:
            status = "partial"
            reason = "部分要求已有独立测量，但仍有未决或无能力项"
        elif failed and applicable_claims:
            status = "partial"
            reason = claim_reason or "已有验证器返回 partial，不能提升为逐条完整覆盖"
        elif unresolved:
            status = "unbound" if any(item.get("reason") == "无法唯一绑定验证对象"
                                      for item in unresolved) else "unverified"
            reason = unresolved[0].get("reason")
        else:
            status = "unverified"
            reason = "当前没有可用的独立验证能力"
        clause = {
            "requirement_id": f"clause:{segment['source_index']}:{segment['start']}",
            "source_index": segment["source_index"],
            "requirement": segment["text"],
            "span": {"start": segment["start"], "end": segment["end"]},
            "status": status,
            "reason": reason,
            "unsupported_evidence": deepcopy(unresolved),
            "evidence": evidence_items,
            "authority": "backend_measured_geometry",
        }
        clauses.append(clause)
        if status != "verified":
            blocking.append({
                "requirement_id": clause["requirement_id"],
                "requirement": clause["requirement"],
                "status": status,
                "reason": reason or "未获得完整、来源绑定的独立测量证据",
            })

    covered_fact_ids = {
        item.get("requirement_id")
        for clause in clauses
        for item in clause.get("unsupported_evidence") or []
    }
    for item in _unknown_requirements(source_acceptance):
        source_id = item.get("source_requirement_id")
        if source_id in covered_fact_ids:
            continue
        already = any(
            blocker.get("requirement_id") == source_id
            for blocker in blocking
        )
        if not already:
            blocking.append({
                "requirement_id": source_id or f"report:{item.get('report')}",
                "requirement": item.get("text") or item.get("source_evidence") or source_id,
                "status": "unverified",
                "reason": item.get("reason") or "报告声明了未决要求",
            })

    semantic = source_acceptance.get("semantic_acceptance") or {}
    semantic_status, semantic_reason = _semantic_claim_status(semantic)
    semantic_kinds = semantic.get("applicable_requirement_kinds") or []
    semantic_block = False
    if semantic_kinds and semantic_status != "verified":
        semantic_block = True
        blocking.append({
            "requirement_id": "semantic:" + ",".join(str(kind) for kind in semantic_kinds),
            "requirement": ",".join(str(kind) for kind in semantic_kinds),
            "status": "partial",
            "reason": semantic_reason or "语义验证器未给出 passed 完整状态",
        })

    state = "complete" if not blocking else "partial"
    return {
        "schema": "cad.requirement-coverage-evidence.v1",
        "state": state,
        "authority": "backend_measured_geometry",
        "clauses": clauses,
        "verified_requirement_count": sum(1 for item in clauses if item["status"] == "verified"),
        "partial_requirement_count": sum(1 for item in clauses if item["status"] == "partial"),
        "unverified_requirement_count": sum(
            1 for item in clauses
            if item["status"] in {"unverified", "unbound", "unsupported", "unparseable"}
        ),
        "blocking_requirements": blocking,
        "unresolved_fact_ids": [
            clause["requirement_id"] for clause in clauses
            if clause["status"] != "verified"
        ],
        "semantic_block": semantic_block,
        "note": "每条原文要求须绑定既有后端测量；未绑定、未支持或 partial 项均阻断完整覆盖。",
    }
