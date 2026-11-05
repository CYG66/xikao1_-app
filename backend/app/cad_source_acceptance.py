"""Source-scoped primitive checks. No geometry creation or model assertions.

Supported explicit syntax: 名称：圆/矩形/线段/圆弧，... coordinates
and dimensions. Unsupported prose remains unverified, never a full pass.
"""
import math
import re

from .cad_structure_contract import StructureContractError

N=r"[-+]?\d+(?:\.\d+)?"
P=rf"[（(]\s*({N})\s*[,，]\s*({N})\s*[）)]"
INVENTORY_MARKER=r"(?:完整部件清单|全部图元清单)[：:]"


def source_texts(text):
    source=text.split("\n后端试算反馈：",1)[0]
    marker="\n最新已确认要求（"
    if marker not in source:return [source]
    first=source.split(marker,1)[0]
    followup="\n用户逐轮补充的原文约束（按时间排序，后文覆盖同名约束；必须保留全部组成）：\n"
    return [first,source.split(followup,1)[1]] if followup in source else [first]


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
            unit_pattern=r"毫米|厘米|米|mm|cm|m"
            factors={"毫米":1,"mm":1,"厘米":10,"cm":10,"米":1000,"m":1000}
            units=re.search(r"坐标单位(?:为|是)?\s*("+unit_pattern+r")",body)
            if not units:continue
            spec={"subject":label.strip(),"kind":kind,"evidence":clause.strip()}
            def scalar(name):
                match=re.search(rf"{name}(?:为|是)?\s*({N})\s*({unit_pattern})",body)
                return float(match[1])*factors[match[2]] if match else None
            def point(name):
                match=re.search(name+P,body)
                return [float(match[1])*factors[units[1]],float(match[2])*factors[units[1]]] if match else None
            if kind in {"圆","圆弧"}:
                spec.update(center=point("圆心"),radius=scalar("半径"))
                if spec["center"] is None or spec["radius"] is None:continue
                if kind=="圆弧":
                    angles=re.search(rf"起始角\s*({N})\s*度[，,\s]+终止角\s*({N})\s*度",body)
                    if not angles:continue
                    spec.update(start_angle=float(angles[1]),end_angle=float(angles[2]))
            elif kind=="矩形":
                spec.update(origin=point("左下角"),width=scalar("宽"),height=scalar("高"))
                if any(spec[k] is None for k in ("origin","width","height")):continue
            else:
                spec.update(start=point("起点"),end=point("终点"))
                if spec["start"] is None or spec["end"] is None:continue
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
    evidence={s['evidence'] for s in specs}
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
    if logical_objects is not None:
        for check in report["checks"]:
            owners=[o for o in logical_objects if check["geometry_ids"][0] in o.get("geometry_refs",[])]
            if not owners or any(not o.get("assembly_id") for o in owners):
                raise StructureContractError("部件缺少明确整体归属："+check["subject"])
            check["object_ids"]=[o["object_id"] for o in owners]
            check["assembly_ids"]=sorted({o["assembly_id"] for o in owners})
    from .cad_relation_acceptance import verify_named_relations
    report['relation_acceptance']=verify_named_relations(text,geometries,report['checks'])
    report['review_required']=report['review_required'] or report['relation_acceptance']['review_required']
    return report
