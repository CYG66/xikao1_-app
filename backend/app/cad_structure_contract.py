"""Source-backed component contracts. Checks geometry; never constructs it."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
from .cad_creation_intent import local_creation_objects


class StructureContractError(ValueError):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


def validate_plan_structure(contract, plan):
    """Check the model's component inventory before coordinates are executed."""
    if hasattr(plan,'model_dump'):
        plan=plan.model_dump(mode='json')
    if not contract or not isinstance(plan, dict):
        return None
    steps=plan.get('steps') or []
    literal_ops={'add_line','add_polyline','add_circle','add_arc','add_rectangle'}
    if any(s.get('op') not in literal_ops for s in steps):
        return {'status':'unverified','phase':'preflight_structure',
                'reason':'expanded_operations_require_execution_inventory','review_required':True}
    if not steps:
        raise StructureContractError('结构计划没有组成步骤', {'phase':'preflight_structure'})
    if contract.get('kind') == 'named_components':
        expected=len(contract.get('names') or [])
        if len(steps)!=expected:
            raise StructureContractError('结构计划组成数量与需求不一致',
                {'phase':'preflight_structure','expected_components':contract.get('names'),
                 'observed_steps':len(steps)})
    elif contract.get('counts'):
        expected=sum(contract['counts'].values())
        if len(steps)!=expected:
            raise StructureContractError('结构计划组成数量与需求不一致',
                {'phase':'preflight_structure','expected_count':expected,'observed_steps':len(steps)})
    refs=[s.get('output_ref') for s in steps]
    if any(not isinstance(ref,str) or not ref for ref in refs) or len(set(refs))!=len(refs):
        raise StructureContractError('结构计划存在缺失或重复的组成标识', {'phase':'preflight_structure'})
    if any(s.get('op') not in {'add_line','add_polyline','add_circle','add_arc','add_rectangle'} for s in steps):
        raise StructureContractError('结构计划包含未声明的几何组成类型', {'phase':'preflight_structure'})
    # Relationship declarations are part of the structure contract. Validate
    # references before coordinates are calculated, so a missing branch or a
    # typo in a symmetry/connection target cannot silently become geometry.
    relation_kinds={'coincident','connected','connection','symmetric','symmetry',
                    'repeat','array','mirror','radial_pattern','equal'}
    relationships=[]
    for key in ('constraints','relations','connections','symmetry','repetition'):
        value=plan.get(key) or []
        if isinstance(value,dict): value=[value]
        if isinstance(value,list): relationships.extend(value)
    unknown=[]
    unsupported=[]
    for relation in relationships:
        if not isinstance(relation,dict):
            raise StructureContractError('结构关系声明格式无效', {'phase':'preflight_structure'})
        kind=str(relation.get('kind') or relation.get('type') or '').lower()
        if not kind or kind not in relation_kinds:
            unsupported.append(kind or '<missing>')
        else:
            refs_in=[]
            for key in ('target_ref','source_ref','output_ref','geometry_ref','from_ref','to_ref'):
                if isinstance(relation.get(key),str): refs_in.append(relation[key])
            for key in ('refs','targets','source_refs','target_refs','geometry_refs'):
                if isinstance(relation.get(key),list): refs_in.extend(x for x in relation[key] if isinstance(x,str))
            unknown.extend(x for x in refs_in if x not in refs)
            declared_count=relation.get('count',relation.get('expected_count'))
            if declared_count is not None:
                if isinstance(declared_count,bool) or not isinstance(declared_count,int) or declared_count<2:
                    raise StructureContractError('结构关系数量声明无效',
                        {'phase':'preflight_structure','relation':relation})
                if kind in {'symmetric','symmetry','repeat','array','mirror','radial_pattern'} and len(set(refs_in))<declared_count:
                    raise StructureContractError('结构关系引用数量少于声明数量',
                        {'phase':'preflight_structure','kind':kind,'expected_count':declared_count,
                         'observed_refs':sorted(set(refs_in))})
            if kind in {'coincident','connected','connection','symmetric','symmetry','equal'} and len(set(refs_in))<2:
                raise StructureContractError('结构关系缺少两个独立组成',
                    {'phase':'preflight_structure','relation':relation})
    if unknown:
        raise StructureContractError('结构关系引用了不存在的组成',
            {'phase':'preflight_structure','unknown_refs':sorted(set(unknown))})
    if unsupported:
        return {'status':'unverified','phase':'preflight_structure',
                'reason':'unsupported_relation_kinds_require_execution_acceptance',
                'unsupported_relation_kinds':sorted(set(unsupported)),
                'review_required':True}
    return {'status':'passed','phase':'preflight_structure','step_count':len(steps),'refs':refs}


def reference_contract(text):
    """Resolve vetted reference data, not model-authored assertions."""
    source = text.split("\n后端试算反馈：", 1)[0]
    for path in sorted(Path(__file__).with_name("cad_reference_data").glob("*.json")):
        raw = path.read_bytes()
        data = json.loads(raw)
        alias = next((a for a in data["aliases"] if a in source), None)
        if alias:
            return {**deepcopy(data), "matched_object": alias,
                    "reference_sha256": hashlib.sha256(raw).hexdigest()}
    return None


def explicit_dimensions(text):
    """Only use user-supplied dimensions; a reference ratio is not a size."""
    source = text.split("\n后端试算反馈：", 1)[0]
    def value(label):
        matches = re.findall("(?:"+label+r")(?:度)?\s*(?:为|是|=|：|:)?\s*(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)", source)
        if not matches:
            return None
        number, unit = matches[-1]
        return float(number)*{"毫米":.001,"mm":.001,"厘米":.01,"cm":.01,"米":1,"m":1}[unit]
    width,height=value("宽|长"),value("高")
    shared=re.search(r"(?:长宽|宽高|长和宽|宽和高)(?:均|都)?(?:为|是)?\s*(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)",source)
    if shared:
        size=float(shared[1])*{"毫米":.001,"mm":.001,"厘米":.01,"cm":.01,"米":1,"m":1}[shared[2]]
        width=width if width is not None else size
        height=height if height is not None else size
    return width,height


def explicit_composition(text):
    """Bind explicit primitive counts/placements independently of a plan.

    This conservative grammar declines expressions it cannot fully scope;
    it is not a catalog of objects and does not manufacture geometry.
    """
    source=text.split("\n后端试算反馈：",1)[0]
    number=r"(\d+|[一二两三四五六七八九十])"
    def count(token):
        return int(token) if token.isdigit() else 2 if token=="两" else "零一二三四五六七八九十".index(token)
    def metric(label):
        match=re.search("(?:"+label+r")(?:均|都)?(?:为|是|=|：|:)?\s*(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)",source)
        return float(match[1])*{"毫米":.001,"mm":.001,"厘米":.01,"cm":.01,"米":1,"m":1}[match[2]] if match else None
    width,height=explicit_dimensions(source)
    dimensions={"width_m":width,"height_m":height,"radius_m":metric("半径"),
                "row_pitch_m":metric("行距"),"column_pitch_m":metric("列距"),
                "center_distance_m":metric("圆心距离|圆心相距|圆心距")}
    dimensions={k:v for k,v in dimensions.items() if v is not None}
    # A dimension attached to a named primitive is not a shared dimension of
    # every primitive of that type. The scoped gate measures these separately.
    from .cad_source_acceptance import extract_scoped_primitives
    scoped_primitives=extract_scoped_primitives(text)
    for field,key in (('radius','radius_m'),('width','width_m'),('height','height_m')):
        if any(field in part for part in scoped_primitives):
            dimensions.pop(key,None)
    array=re.search(number+r"\s*行\s*"+number+r"\s*列",source)
    if array and "矩形" in source:
        rows,cols=map(count,array.groups())
        if min(rows,cols)>0 and rows*cols<=500:
            return {"kind":"rectangular_array","counts":{"rectangle":rows*cols},"rows":rows,"columns":cols,
                    "evidence":array.group(0),"dimensions":dimensions}
    if "矩形" in source and re.search(r"(?:四|4)\s*个?角.*(?:圆|circle)",source):
        return {"kind":"corner_placement","counts":{"rectangle":1,"circle":4},"evidence":source,"dimensions":dimensions}
    circles=re.search(number+r"\s*个\s*(?:相交的?|相同的?|等大的?)?圆",source)
    if circles and count(circles[1])>=2:
        # A noun-modified count (e.g. circles serving as eyes) describes a
        # subset, not the inventory of the whole drawing. Likewise an arc
        # is an additional primitive. Decline this narrow grammar instead
        # of inventing an exact whole-drawing count or sharing its radius.
        suffix=source[circles.end():]
        if re.match(r"点|形|作为|用作|的?(?:眼|孔|窗|灯|轮)",suffix) or "圆弧" in source:
            return None
        counts={"circle":count(circles[1])}
        if re.search(r"矩形|长方形|正方形",source):
            rectangle=re.search(number+r"\s*个\s*(?:竖直|水平|相同|等大|的)*\s*(?:矩形|长方形|正方形)",source)
            if not rectangle:
                # A circle-only inventory is not authoritative for a mixed
                # drawing. Decline rather than reject legitimate extra parts.
                return None
            counts["rectangle"]=count(rectangle[1])
        if re.search(r"三角形|线段|刻度线|五角星",source):
            return None
        return {"kind":"component_count","counts":counts,"evidence":circles.group(0),
                "dimensions":dimensions,"intersecting":"相交" in source}
    # A plainly enumerated line inventory is independently measurable.  Keep
    # this grammar narrow: a line count in a mixed drawing is only a subset,
    # not authority to reject the other required primitives.
    lines=re.search(
        number+r"\s*(?:条|个)?\s*(竖直|垂直|水平)?\s*(?:的)?\s*(?:直线|线段|线)(?!条)",
        source,
    )
    if lines and count(lines[1]) >= 2:
        if re.search(r"矩形|长方形|正方形|圆(?:形|弧)?|三角形|多边形|五角星", source):
            return None
        return {
            "kind": "line_inventory",
            "counts": {"line": count(lines[1])},
            "evidence": lines.group(0),
            "dimensions": dimensions,
            "dimension_scope": "overall",
            "orientation": (
                "vertical" if lines[2] in {"竖直", "垂直"}
                else "horizontal" if lines[2] == "水平"
                else None
            ),
        }
    names=local_creation_objects(source)
    if len(names)>=2:
        from .cad_source_acceptance import source_texts
        user_source='\n'.join(source_texts(text))
        scoped={};shared={}
        for clause in re.split(r'[；;。\n]',user_source):
            if re.search(r'(?:它们|两者|每个(?:图形|对象)?|各自)[^；;。]{0,12}(?:长宽|宽高|宽|高)|(?:长宽|宽高)(?:均|都)',clause):
                w,h=explicit_dimensions(clause)
                shared.update({k:v for k,v in (('width_m',w),('height_m',h)) if v is not None})
            for name in names:
                start=clause.find(name)
                if start<0:continue
                end=min([pos for other in names if other!=name and (pos:=clause.find(other,start+len(name)))>=0] or [len(clause)])
                part=clause[start+len(name):end];w,h=explicit_dimensions(part)
                radius=re.search(r'外接圆半径\s*(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)',part)
                values={k:v for k,v in (('width_m',w),('height_m',h)) if v is not None}
                if radius:values['circumradius_m']=float(radius[1])*{'毫米':.001,'厘米':.01,'米':1,'mm':.001,'cm':.01,'m':1}[radius[2]]
                if values:scoped.setdefault(name,{}).update(values)
        from .cad_requirement_contract import requirement_contract
        scalar=requirement_contract([{'source_id':f'part-source-{i+1}','text':s} for i,s in enumerate(source_texts(text))])
        fields={'width':'width_m','height':'height_m','circumradius':'circumradius_m'}
        for fact in scalar['facts']:
            if fact['status']=='effective' and fact['operator']=='eq' and fact['subject'] in names and fact['field'] in fields:
                scoped.setdefault(fact['subject'],{})[fields[fact['field']]]=fact['value_mm']/1000
        for key in list(shared):
            values=[scoped.get(name,{}).get(key) for name in names]
            if any(v is not None for v in values) and (any(v is None for v in values) or len(set(values))!=1):
                shared.pop(key)
        center_spacing=re.findall(r'中心(?:水平)?(?:相距|距离|间距|距)(?:为|是)?\s*(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)',user_source)
        spacing=re.search(r"(?:间距|净距)(?:为|是)?\s*(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)",user_source)
        gap_m=float(spacing[1])*{'毫米':.001,'厘米':.01,'米':1,'mm':.001,'cm':.01,'m':1}[spacing[2]] if spacing else None
        if center_spacing:
            value,unit=center_spacing[-1];gap_m=float(value)*{'毫米':.001,'厘米':.01,'米':1,'mm':.001,'cm':.01,'m':1}[unit]
        return {"kind":"named_components","counts":{"closed_path":len(names)},"names":names,
                "dimensions":shared,"component_dimensions":scoped,"evidence":user_source,
                "gap_m":gap_m,
                "gap_reference":"center" if center_spacing or re.search(r"中心(?:间)?距",user_source) else "edge",
                "left_to_right":bool(re.search(re.escape(names[0])+r"在左",source) and re.search(re.escape(names[1])+r"在右",source))}
    return None


def validate_explicit_composition(contract, geometries):
    if contract is None:
        return None
    # Independent topology gate: component counts and dimensions are not
    # enough to prove that a closed component is actually drawable. Reject
    # open, self-intersecting, or degenerate outlines before persistence.
    from shapely.geometry import LineString
    for geometry in geometries:
        if geometry.get("type") != "polyline":
            continue
        vertices = geometry.get("vertices") or []
        if geometry.get("closed") is not True or len(vertices) < 3:
            raise StructureContractError("组成图形必须是至少三点的闭合轮廓", {
                "geometry_id": geometry.get("id")
            })
        points = [(float(point["x"]), float(point["y"])) for point in vertices]
        if len({(round(x, 9), round(y, 9)) for x, y in points}) < 3:
            raise StructureContractError("组成图形存在重复点或退化轮廓", {
                "geometry_id": geometry.get("id")
            })
        ring = LineString(points + [points[0]])
        if not ring.is_simple:
            raise StructureContractError("组成图形存在自交，无法通过几何验收", {
                "geometry_id": geometry.get("id")
            })
    rectangles=[g for g in geometries if _frame(g) is not None]
    circles=[g for g in geometries if g.get("type")=="circle"]
    lines=[g for g in geometries if g.get("type")=="line"]
    observed={"rectangle":len(rectangles),"circle":len(circles),"line":len(lines),
              "closed_path":sum(bool(_points(g)) or g.get("type") in {"circle","ellipse"} for g in geometries)}
    if len(geometries)!=sum(contract["counts"].values()) or any(observed[k]!=n for k,n in contract["counts"].items()):
        raise StructureContractError("实际组成数量或类型不符合原文要求",
                                     {"expected_counts":contract["counts"],"observed_counts":observed})
    dimensions=contract.get("dimensions",{})
    if contract["kind"] == "line_inventory":
        tolerance = .5
        orientation = contract.get("orientation")
        for geometry in lines:
            start, end = geometry.get("start") or {}, geometry.get("end") or {}
            dx = abs(float(end.get("x", 0)) - float(start.get("x", 0)))
            dy = abs(float(end.get("y", 0)) - float(start.get("y", 0)))
            if orientation == "vertical" and (dx > tolerance or dy <= tolerance):
                raise StructureContractError("线段方向不符合原文要求：应为竖直线")
            if orientation == "horizontal" and (dy > tolerance or dx <= tolerance):
                raise StructureContractError("线段方向不符合原文要求：应为水平线")
        if dimensions:
            from .cad_construction import construction_geometry_bounds
            bounds = construction_geometry_bounds(geometries)
            actual = {
                "width_m": (bounds["max_x"] - bounds["min_x"]) / 1000,
                "height_m": (bounds["max_y"] - bounds["min_y"]) / 1000,
            }
            for key in ("width_m", "height_m"):
                if key in dimensions and abs(actual[key] - dimensions[key]) > tolerance / 1000:
                    raise StructureContractError(
                        "线段组合的整体尺寸不符合原文要求",
                        {"dimension": key, "expected_m": dimensions[key], "actual_m": actual[key]},
                    )
        return {
            "status": "passed",
            "expected_counts": contract["counts"],
            "observed_counts": observed,
            "orientation": orientation,
            "measured_dimensions": actual if dimensions else {},
        }
    if contract["kind"]=="named_components":
        from .cad_construction import construction_geometry_bounds, RadialPatternAssertion, _run_assertions
        bounds=[construction_geometry_bounds([g]) for g in geometries]
        for b in bounds:
            if any(key in dimensions and abs(actual-dimensions[key]*1000)>.5 for key,actual in (
                ("width_m",b["max_x"]-b["min_x"]),("height_m",b["max_y"]-b["min_y"]))):
                raise StructureContractError("每个组成的宽高均须符合用户尺寸，不能把组成尺寸当成整体尺寸")
        if contract["left_to_right"]:
            ordered=sorted(zip(geometries,bounds),key=lambda item:item[1]["min_x"])
            for name,(g,b) in zip(contract["names"],ordered):
                local=contract.get('component_dimensions',{}).get(name,{})
                for key,actual in (('width_m',b['max_x']-b['min_x']),('height_m',b['max_y']-b['min_y'])):
                    if key in local and abs(actual-local[key]*1000)>.5:
                        raise StructureContractError('部件尺寸不符合原文：'+name,{'component':name,'dimension':key,'actual_mm':actual,'expected_mm':local[key]*1000})
                if 'circumradius_m' in local:
                    from shapely import minimum_bounding_radius
                    from shapely.geometry import MultiPoint
                    actual=float(minimum_bounding_radius(MultiPoint(_points(g))))
                    if abs(actual-local['circumradius_m']*1000)>.5:
                        raise StructureContractError('部件外接圆半径不符合原文：'+name)
                if "五角星" in name:
                    try:
                        assertion=RadialPatternAssertion(kind="radial_pattern",assertion_id="source-star",target_ref="target",lobes=5,profile="polygonal")
                        _run_assertions([assertion],[g],{"target":[g["id"]]},1)
                    except ValueError as exc:
                        raise StructureContractError("指定位置的五角星形状不符合五角结构") from exc
                elif "爱心" in name or "心形" in name:
                    points=_points(g)
                    w,h=b["max_x"]-b["min_x"],b["max_y"]-b["min_y"]
                    normalized=[((x-b["min_x"])/w,(y-b["min_y"])/h) for x,y in points]
                    features={
                        'center_notch':any(abs(x-.5)<.03 and .5<y<.98 for x,y in normalized),
                        'left_upper_lobe':any(x<.45 and y>.98 for x,y in normalized),
                        'right_upper_lobe':any(x>.55 and y>.98 for x,y in normalized),
                        'lower_tip':any(abs(x-.5)<.1 and y<.01 for x,y in normalized),
                    }
                    if not all(features.values()):
                        raise StructureContractError(
                            "指定位置的爱心缺少双侧上凸、中央凹口或下方尖点",
                            {'authority':'backend_measured_geometry',
                             'check':'heart_bilateral_lobes_notch_and_lower_tip',
                             'component':name,'geometry_id':g.get('id'),
                             'measured_features':features,
                             'required_features':{
                                 'center_notch':'上方中心内凹且低于左右峰值',
                                 'left_upper_lobe':'中心左侧独立上凸峰',
                                 'right_upper_lobe':'中心右侧独立上凸峰',
                                 'lower_tip':'下方中心尖点'},
                             'repair_scope':'仅修正失败部件的轮廓；保留其他已通过部件、尺寸和布局'} )
            if contract["gap_m"] is not None:
                for (_,a),(_,b) in zip(ordered,ordered[1:]):
                    actual=(b["min_x"]+b["max_x"]-a["min_x"]-a["max_x"])/2 if contract["gap_reference"]=="center" else b["min_x"]-a["max_x"]
                    if abs(actual-contract["gap_m"]*1000)>.5:
                        raise StructureContractError("组成间距不符合用户要求（未注明中心距时按边缘净距校验）")
        _validate_geometric_relationships(contract, geometries)
        return {"status":"passed","component_names":contract["names"],"gap_reference":contract["gap_reference"],"observed_counts":observed}
    for g in rectangles:
        x,y,w,h=_frame(g)
        if any(key in dimensions and abs(actual-dimensions[key]*1000)>.5 for key,actual in (("width_m",w),("height_m",h))):
            raise StructureContractError("矩形组成尺寸不符合原文要求")
    if "radius_m" in dimensions and any(abs(g["radius"]-dimensions["radius_m"]*1000)>.5 for g in circles):
        raise StructureContractError("圆的半径不符合原文要求")
    if len(circles)==2:
        a,b=circles
        distance=math.dist((a["center"]["x"],a["center"]["y"]),(b["center"]["x"],b["center"]["y"]))
        if "center_distance_m" in dimensions and abs(distance-dimensions["center_distance_m"]*1000)>.5:
            raise StructureContractError("两圆圆心距离不符合原文要求")
        if contract.get("intersecting") and not abs(a["radius"]-b["radius"])<distance<a["radius"]+b["radius"]:
            raise StructureContractError("要求相交的圆没有相交")
    if contract["kind"]=="corner_placement":
        expected=_corners(_points(rectangles[0]))
        remaining=list(circles)
        for p in expected:
            matches=[g for g in remaining if math.dist(p,(g["center"]["x"],g["center"]["y"]))<=.5]
            if len(matches)!=1:
                raise StructureContractError("圆必须与矩形四个顶点一一对应，不能重叠或漏角")
            remaining.remove(matches[0])
    elif contract["kind"]=="rectangular_array":
        frames=[_frame(g) for g in rectangles]
        xs=sorted({round(x+w/2,2) for x,y,w,h in frames})
        ys=sorted({round(y+h/2,2) for x,y,w,h in frames})
        if len(xs)!=contract["columns"] or len(ys)!=contract["rows"]:
            raise StructureContractError("矩形阵列行数或列数不符合原文要求")
        cells={(round(x+w/2,2),round(y+h/2,2)) for x,y,w,h in frames}
        if len(cells)!=len(frames):
            raise StructureContractError("阵列中存在重叠单元")
        for key,axis in (("column_pitch_m",xs),("row_pitch_m",ys)):
            if key in dimensions and any(abs(b-a-dimensions[key]*1000)>.5 for a,b in zip(axis,axis[1:])):
                raise StructureContractError("阵列中心间距不符合原文要求")
    _validate_geometric_relationships(contract, geometries)
    return {"status":"passed","expected_counts":contract["counts"],"observed_counts":observed}


def _validate_geometric_relationships(contract, geometries):
    """Validate declared branch/connection/symmetry relations on measured geometry."""
    relations = contract.get("relationships") or contract.get("relations") or []
    if isinstance(relations, dict):
        relations = [relations]
    by_id = {str(g.get("id")): g for g in geometries}
    centers = {}
    for g in geometries:
        points = _points(g)
        if points:
            centers[str(g.get("id"))] = (sum(x for x, _ in points) / len(points), sum(y for _, y in points) / len(points))
        elif isinstance(g.get("center"), dict):
            centers[str(g.get("id"))] = (float(g["center"]["x"]), float(g["center"]["y"]))
    for relation in relations:
        if not isinstance(relation, dict):
            raise StructureContractError("几何关系声明格式无效")
        kind = str(relation.get("kind") or relation.get("type") or "").lower()
        refs = relation.get("refs") or relation.get("geometry_refs") or []
        refs = [str(ref) for ref in refs]
        if len(refs) < 2 or any(ref not in by_id for ref in refs):
            raise StructureContractError("几何关系引用的组成不存在")
        if kind in {"connected", "connection", "branch"}:
            tolerance = float(relation.get("tolerance_mm") or 1.0)
            for left, right in zip(refs, refs[1:]):
                lp = _points(by_id[left]); rp = _points(by_id[right])
                if not lp or not rp:
                    raise StructureContractError("连接关系缺少可测量端点")
                if min(math.dist(a, b) for a in lp for b in rp) > tolerance:
                    raise StructureContractError("组成之间未按要求连接")
        elif kind in {"symmetric", "symmetry"}:
            axis = float(relation.get("axis_x", 0.0))
            tolerance = float(relation.get("tolerance_mm") or 1.0)
            for left, right in zip(refs[::2], refs[1::2]):
                if left not in centers or right not in centers:
                    raise StructureContractError("对称关系缺少组成位置")
                lx, ly = centers[left]; rx, ry = centers[right]
                if abs((lx + rx) / 2 - axis) > tolerance or abs(ly - ry) > tolerance:
                    raise StructureContractError("组成未按要求对称")
        elif kind in {"branch", "repeat", "array"}:
            expected = relation.get("count") or relation.get("expected_count")
            if expected is not None and len(refs) != int(expected):
                raise StructureContractError("分支或重复组成数量不符合要求")


def _points(g):
    if g.get("type") != "polyline" or not g.get("closed"):
        return []
    points = [(p["x"], p["y"]) for p in g.get("vertices", [])]
    if len(points)>1 and math.dist(points[0], points[-1]) < 1e-6:
        points.pop()
    return points


def _corners(points):
    """Discard collinear sampling vertices without accepting curved edges."""
    result=[]
    for i,p in enumerate(points):
        a,b=points[i-1],points[(i+1)%len(points)]
        ux,uy=p[0]-a[0],p[1]-a[1]
        vx,vy=b[0]-p[0],b[1]-p[1]
        if abs(ux*vy-uy*vx)>1e-7*max(1,math.hypot(ux,uy)*math.hypot(vx,vy)) or ux*vx+uy*vy<0:
            result.append(p)
    return result


def _frame(g):
    points=_corners(_points(g))
    if len(points)!=4:
        return None
    xs,ys=zip(*points)
    x0,x1,y0,y1=min(xs),max(xs),min(ys),max(ys)
    if x1-x0<=0 or y1-y0<=0:
        return None
    expected=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
    if not all(any(math.dist(p,q)<1e-5 for p in points) for q in expected):
        return None
    return x0,y0,x1-x0,y1-y0


def validate_structure(contract, geometries, width_m=None, height_m=None):
    """One-to-one matching by measured shape and location, never by labels."""
    if contract is None:
        return None
    components=contract["components"]
    if len(geometries)!=len(components):
        raise StructureContractError(f"实际组成数量{len(geometries)}，要求{len(components)}；不得遗漏或增加组成部分",
                                     {"expected_components":[c["id"] for c in components],"observed_count":len(geometries)})
    frames=[(i,f) for i,g in enumerate(geometries) if (f:=_frame(g)) is not None]
    if len(frames)!=1:
        raise StructureContractError("需要唯一矩形基准框")
    frame_index,(x0,y0,w,h)=frames[0]
    tolerance=max(.1,h*.0001)  # mm; never controlled by a model's assertion
    if abs(w/h-contract["aspect_ratio"])>.0001:
        raise StructureContractError("基准框长宽比不符合来源要求")
    if (width_m is not None and abs(w-width_m*1000)>tolerance) or (height_m is not None and abs(h-height_m*1000)>tolerance):
        raise StructureContractError("基准框尺寸不符合用户确认值")
    used={frame_index}
    measurements=[]
    centers={c["id"]:(x0+c["center"][0]*w,y0+c["center"][1]*h) for c in components if "center" in c}
    for c in components:
        if c.get("frame"):
            continue
        center=centers[c["id"]]
        matches=[]
        for i,g in enumerate(geometries):
            if i in used:
                continue
            points=_corners(_points(g))
            if not points:
                continue
            actual_center=(sum(p[0] for p in points)/len(points),sum(p[1] for p in points)/len(points))
            if math.dist(center,actual_center)<=tolerance:
                matches.append((i,points))
        if len(matches)!=1:
            raise StructureContractError(f"组成{c['id']}缺失、重复或位置错误", {"component":c["id"],"expected_center_mm":center})
        i,points=matches[0]
        if c["kind"]!="radial_polygon":
            raise StructureContractError("未支持的结构检查类型，拒绝跳过")
        if len(points)!=2*c["tips"]:
            raise StructureContractError(f"组成{c['id']}角尖数量错误")
        radius=c["radius_h"]*h
        radii=[math.dist(p,center) for p in points]
        outer=[j for j,r in enumerate(radii) if abs(r-radius)<=tolerance]
        if len(outer)!=c["tips"] or any(
            abs(r-(radius if j in outer else radius*c["inner_ratio"]))>tolerance for j,r in enumerate(radii)
        ) or any((j in outer)==((j+1)%len(points) in outer) for j in range(len(points))):
            raise StructureContractError(f"组成{c['id']}外径或内外顶点比例错误")
        angles=[math.atan2(p[1]-center[1],p[0]-center[0]) for p in points]
        delta=[(angles[(j+1)%len(points)]-a+math.pi)%math.tau-math.pi for j,a in enumerate(angles)]
        if any(abs(abs(d)-math.pi/c["tips"])>math.radians(.1) or d*delta[0]<=0 for d in delta):
            raise StructureContractError(f"组成{c['id']}顶点次序或角间隔错误")
        if "tip_toward" in c:
            target=centers[c["tip_toward"]]
            desired=math.atan2(target[1]-center[1],target[0]-center[0])
        else:
            desired=math.radians(c["tip_angle_deg"])
        angle_error=min(abs((angles[j]-desired+math.pi)%math.tau-math.pi) for j in outer)
        if angle_error>math.radians(.1):
            raise StructureContractError(f"组成{c['id']}角尖朝向错误", {"component":c["id"],"angular_error_deg":math.degrees(angle_error)})
        used.add(i)
        measurements.append({"component":c["id"],"geometry_id":geometries[i]["id"],"center_mm":center,
                             "radius_mm":max(radii),"tip_error_deg":math.degrees(angle_error)})
    return {"status":"passed","reference_id":contract["id"],"source_url":contract["source_url"],
            "reference_sha256":contract["reference_sha256"],"component_count":len(used),"measurements":measurements}
