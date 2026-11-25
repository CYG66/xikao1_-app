"""Source-scoped primitive checks. No geometry creation or model assertions.

Supported explicit syntax: 名称：圆/矩形/线段/圆弧，... coordinates
and dimensions. Unsupported prose remains unverified, never a full pass.
"""
from .cad_length_units import length_factors
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


def verify_single_round_primitive(text, geometries):
    """Independently measure fully consumed single-circle/arc source clauses.

    This constructs no geometry and reads no plan or model assertions. Unknown
    prose declines full coverage rather than ignoring an extra requirement.
    """
    from .cad_source_intent import partition_preview_intent
    from .cad_precision import ACCEPTANCE_MM
    factors = length_factors('mm')
    unit = r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'
    fields = {}; kinds = set(); evidence = []; output_checks=[]
    intent_evidence=[]
    for source in source_texts(text):
        source,intents=partition_preview_intent(source);intent_evidence.extend(intents)
        for clause in source.splitlines():
            if not clause.strip():
                continue
            rest = clause
            local = {}
            def consume(pattern, callback):
                nonlocal rest
                matches = list(re.finditer(pattern, rest, re.I))
                for match in matches:
                    callback(match)
                    evidence.append(match[0])
                rest = re.sub(pattern, ' ', rest, flags=re.I)
            def assign(key, value):
                if key in local and local[key] != value:
                    raise ValueError('conflicting source fields')
                local[key] = value
            try:
                coordinate_units = re.findall(r'坐标单位(?:为|是|[:：])?\s*'+unit, rest, re.I)
                metric_units = re.findall(N+r'\s*'+unit, rest, re.I)
                coordinate_unit = coordinate_units[-1].lower() if coordinate_units else (
                    metric_units[0].lower() if metric_units and len(set(u.lower() for u in metric_units)) == 1 else None)
                consume(r'(半径|直径)(?:为|是|取|改为|=|[:：])?\s*('+N+r')\s*'+unit,
                    lambda m: assign('radius', float(m[2])*factors[m[3].lower()] / (2 if m[1]=='直径' else 1)))
                if re.search(r'圆心|中心', rest):
                    if coordinate_unit is None:
                        return {'status': 'not_checked', 'coverage': 'partial', 'checks': []}
                    consume(r'(?:圆心|中心)(?:位于|在|为|是|=|[:：])?\s*'+P,
                        lambda m: assign('center', [float(m[1])*factors[coordinate_unit], float(m[2])*factors[coordinate_unit]]))
                    consume(r'以\s*'+P+r'\s*为(?:圆心|中心)',
                        lambda m: assign('center', [float(m[1])*factors[coordinate_unit], float(m[2])*factors[coordinate_unit]]))
                consume(r'起始角(?:为|是)?\s*('+N+r')\s*度', lambda m: assign('start_angle', float(m[1])))
                consume(r'终止角(?:为|是)?\s*('+N+r')\s*度', lambda m: assign('end_angle', float(m[1])))
                consume(r'从\s*('+N+r')\s*度\s*到\s*('+N+r')\s*度',
                    lambda m: (assign('start_angle', float(m[1])), assign('end_angle', float(m[2]))))
                consume(r'坐标单位(?:为|是|[:：])?\s*'+unit, lambda m: None)
            except (ValueError, OverflowError):
                return {'status': 'not_checked', 'coverage': 'partial', 'checks': []}
            # This scope clause is proved by the type/count measurement below.
            rest=re.sub(r'只画(?:这)?(?:一|1)个(?:圆形|圆)(?=[，,。；;\s]|$)','圆',rest)
            rest=re.sub(r'(?:图纸里)?只保留(?:这)?(?:一|1)?个(?:圆形|圆)(?=[，,。；;\s]|$)','圆',rest)
            from .cad_source_intent import partition_outline_scope,verify_output_restrictions
            rest,scope_intents=partition_outline_scope(rest,['圆形','圆'],source=source)
            output_checks.extend(verify_output_restrictions(geometries,scope_intents))
            intent_evidence.extend(scope_intents)
            kinds.update('circle' for i in scope_intents if i.get('subject') in {'圆','圆形'})
            names = re.findall(r'圆弧|圆形|圆', rest)
            kinds.update('arc' if name=='圆弧' else 'circle' for name in names)
            rest = re.sub(r'新建图纸|生成|创建|绘制|画出|画|作|请|一个|一条|圆弧|圆形|圆|的', ' ', rest)
            if rest.strip(' \t\r\n，,、。；;：:'):
                return {'status': 'not_checked', 'coverage': 'partial', 'checks': [],
                        'unconsumed_text':rest.strip(),'source_text':source}
            fields.update(local)
    if len(kinds) != 1 or not fields.get('radius') or not math.isfinite(fields['radius']) or fields['radius'] <= 0:
        return {'status': 'not_checked', 'coverage': 'partial', 'checks': []}
    kind = next(iter(kinds))
    if re.search(r'不标尺寸|不加标注', '\n'.join(source_texts(text))) and any(
            g.get('role') == 'annotation' for g in geometries):
        raise StructureContractError('原文要求不加标注但存在标注图元')
    if kind == 'arc' and not all(k in fields for k in ('center', 'start_angle', 'end_angle')):
        return {'status': 'not_checked', 'coverage': 'partial', 'checks': []}
    if kind == 'circle' and any(k in fields for k in ('start_angle', 'end_angle')):
        return {'status': 'not_checked', 'coverage': 'partial', 'checks': []}
    gs = [g for g in geometries if g.get('selected') is not False and g.get('role') not in {'annotation','reference','ignored'}]
    checks = [{'field': 'single_primitive_type_and_count', 'status': 'passed' if len(gs)==1 and gs[0].get('type')==kind else 'failed'},*output_checks]
    if checks[0]['status']=='passed':
        g = gs[0]
        checks.append({'field':'radius','actual_mm':g['radius'],'expected_mm':fields['radius'],
                       'status':'passed' if abs(g['radius']-fields['radius'])<=ACCEPTANCE_MM else 'failed'})
        if 'center' in fields:
            actual = [g['center']['x'], g['center']['y']]
            checks.append({'field':'center','actual_mm':actual,'expected_mm':fields['center'],
                           'status':'passed' if math.dist(actual,fields['center'])<=ACCEPTANCE_MM else 'failed'})
        if kind=='arc':
            def sweep(start, end):
                delta=end-start
                return delta if delta>0 else delta+360*max(1,math.ceil(-delta/360))
            angles_ok = all(abs((g[k]-fields[k]+180)%360-180)<=.001 for k in ('start_angle','end_angle'))
            angles_ok = angles_ok and abs(sweep(g['start_angle'],g['end_angle'])-sweep(fields['start_angle'],fields['end_angle']))<=.001
            checks.append({'field':'arc_angles_and_sweep','status':'passed' if angles_ok else 'failed'})
    ids = [g['id'] for g in gs]
    if any(c['status']=='failed' for c in checks):
        raise StructureContractError('单图元几何不符合完整源需求',
            {'geometry_ids':ids, 'checks':checks, 'source_evidence':evidence})
    return {'status':'passed','coverage':'complete','checks':checks,
            'geometry_ids':ids,'source_evidence':evidence,'authority':'backend_measured_geometry',
            'measurement_scope':'fully_consumed_single_primitive_source','intent_evidence':intent_evidence}


def nested_circle_roles(geometries):
    """Bind a unique enclosing circle; never guess among several inner roles."""
    circles=[g for g in geometries if g.get('type')=='circle']
    if len(circles)<2 or any(g['radius']<=0 for g in circles):return {}
    def contains(a,b):
        return math.dist([a['center']['x'],a['center']['y']],
                         [b['center']['x'],b['center']['y']])+b['radius']<a['radius']
    outer=[a for a in circles if all(a is b or contains(a,b) for b in circles)]
    if len(outer)!=1:return {}
    result={'外圆':outer[0]}
    if len(circles)==2:result['内圆']=next(g for g in circles if g is not outer[0])
    return result


def verify_final_source_contract(text,geometries,logical_objects=None,*,evidence_context=None):
    """Read-only final measurement of unambiguously scoped user facts."""
    from .cad_capsule_acceptance import verify_capsule_source, has_local_axis_dimensions
    capsule=verify_capsule_source(text,geometries,evidence_context=evidence_context)
    if capsule['coverage']=='complete':return capsule
    from .cad_requirement_contract import requirement_contract
    from .cad_validation_evidence import ConstructionEvidence
    if evidence_context is None:evidence_context=ConstructionEvidence()
    from .cad_geometry_measurements import measured
    from .cad_construction import construction_geometry_bounds
    sources=source_texts(text)
    contract=requirement_contract([{'source_id':f'user:{i}','text':s} for i,s in enumerate(sources)])
    gs=[g for g in geometries if g.get('selected') is not False and g.get('role') not in {'annotation','reference','ignored'}]
    checks=[];unknown=[];failures=[]
    if not gs:return {'status':'not_checked','coverage':'partial','checks':[]}
    bounds=measured(construction_geometry_bounds,gs,evidence_context=evidence_context)
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
        if fact['field'] in {'width','height'} and has_local_axis_dimensions(text):
            unknown.append({'source_requirement_id':fact['fact_id'],'reason':'局部轴尺寸不能使用世界外包框验证'})
            continue
        if (fact['subject'] in {'墙体','门'} and fact['field'] in {'width','height'}
                and not any(o.get('label')==fact['subject'] for o in logical_objects or [])):
            from .cad_semantic_acceptance import verify_semantic_requirements
            semantic=evidence_context.measure(verify_semantic_requirements,text,gs)
            house=semantic.get('measured_contracts',{}).get('house_parts')
            if house:
                boxes=[house['wall_bounds_mm']] if fact['subject']=='墙体' else house['door_bounds_mm']
                if len(boxes)==1:
                    measure(fact['field'],boxes[0][2 if fact['field']=='width' else 3],fact['value_mm'],
                            fact['operator'],fact['fact_id'],fact['evidence'],house['geometry_ids'])
                    continue
        selected=gs
        if len(contract['subjects'])!=1 or fact['binding']!='single_subject':
            if fact['subject'] in {'内圆','外圆'}:
                roles=nested_circle_roles(gs)
                if not roles and fact['subject']=='外圆':
                    from .cad_symmetric_divider_acceptance import verify_symmetric_divider_source
                    divider=evidence_context.measure(verify_symmetric_divider_source,text,gs,evidence_context=evidence_context)
                    if divider['status']=='passed':
                        roles={'外圆':next(g for g in gs if g['id']==divider['outer_circle_id'])}
                if fact['subject'] not in roles:
                    unknown.append({'source_requirement_id':fact['fact_id'],'reason':'内外圆角色尚未由唯一包含关系确认'})
                    continue
                matches=[{'geometry_refs':[roles[fact['subject']]['id']]}]
            elif fact['subject'] in {'俯视圆','侧视轮廓'} and '两个独立正投影视图' in text and '圆柱体' in text:
                from .cad_structure_contract import _frame
                candidates=[g for g in gs if (g.get('type')=='circle' if fact['subject']=='俯视圆' else _frame(g,evidence_context=evidence_context) is not None)]
                matches=[{'geometry_refs':[candidates[0]['id']]}] if len(candidates)==1 else []
            elif fact['subject']=='外环' and fact['field'] in {'radius','diameter'}:
                from .cad_radial_attachment_acceptance import verify_radial_attachment_source
                proof=evidence_context.measure(verify_radial_attachment_source,text,gs)
                circles=[g for g in gs if g.get('type')=='circle']
                matches=([{'geometry_refs':[circles[0]['id']]}]
                         if proof['status']=='passed' and len(circles)==1 else [])
            else:
                matches=[obj for obj in logical_objects or [] if obj.get('label')==fact['subject']]
            if not matches:
                # A named whole may consist of several primitive objects.
                # Bind only one exact assembly identity, never a fuzzy label
                # match or an arbitrary union of similarly named drawings.
                def whole_name(label):return re.sub(r'(?:的)?轮廓$','',str(label or ''))
                sole_whole=len(contract['subjects'])==1 and fact['subject']==contract['subjects'][0]
                assemblies={obj.get('assembly_id') for obj in logical_objects or []
                            if (obj.get('assembly_label')==fact['subject'] or
                                sole_whole and whole_name(obj.get('assembly_label'))==whole_name(fact['subject']))
                            and obj.get('assembly_id')}
                if len(assemblies)==1:
                    assembly_id=next(iter(assemblies))
                    members=[obj for obj in logical_objects if obj.get('assembly_id')==assembly_id]
                    refs=[obj.get('geometry_refs') or obj.get('geometry_ids') for obj in members]
                    if all(refs):
                        matches=[{'geometry_refs':list(dict.fromkeys(i for ids in refs for i in ids))}]
            # A sole explicitly named primitive can be bound by its measured
            # type even when a model adds adjectives to its label. Multiple
            # geometric candidates stay unresolved; labels never select one.
            if not matches and fact['subject'] in {'矩形','长方形','圆','圆形','圆弧'}:
                from .cad_structure_contract import _frame
                kind = {'圆':'circle','圆形':'circle','圆弧':'arc'}.get(fact['subject'])
                candidates = [g for g in gs if (g.get('type')==kind if kind else _frame(g,evidence_context=evidence_context) is not None)]
                if len(candidates)==1:
                    matches=[{'geometry_refs':[candidates[0]['id']]}]
            if len(matches)!=1 or not (matches[0].get('geometry_refs') or matches[0].get('geometry_ids')):
                unknown.append({'source_requirement_id':fact['fact_id'],'reason':'对象范围尚未唯一绑定'});continue
            ids = matches[0].get('geometry_refs') or matches[0]['geometry_ids']
            selected=[g for g in gs if g['id'] in ids]
            if len(selected)!=len(set(ids)):
                unknown.append({'source_requirement_id':fact['fact_id'],'reason':'逻辑对象引用不完整'});continue
        local_bounds=measured(construction_geometry_bounds,selected,evidence_context=evidence_context)
        field=fact['field'];actual=None
        if field in {'radius','diameter'} and len(selected)>1:
            # The source explicitly names a circle's size, and exactly one
            # native circle exists in the bound assembly. Other radii remain
            # unresolved rather than inheriting an arbitrary component.
            native=[g for g in selected if g.get('type')=='circle']
            if len(native)==1 and re.search(r'圆(?:半径|直径)',text):
                selected=native
        if field in {'width','height'}:
            axis='x' if field=='width' else 'y'
            actual=local_bounds['max_'+axis]-local_bounds['min_'+axis]
        elif len(selected)==1 and selected[0].get('type') in {'circle','arc'} and field in {'radius','diameter'}:
            from .cad_geometry_measurements import measured,circle_facts
            actual=measured(circle_facts,selected[0],evidence_context=evidence_context)['radius_mm']*(2 if field=='diameter' else 1)
        elif field=='side_length' and len(selected)>1 and '六边形' in text and re.search('无缝|共边',text):
            from .cad_repetition_acceptance import verify_repetition_requirements
            tiling=evidence_context.measure(verify_repetition_requirements,text,selected).get('measured_contracts',{}).get('hexagonal_tiling')
            if tiling:actual=tiling['side_length_mm']
        elif field=='side_length' and len(selected)==12 and all(g.get('type')=='line' for g in selected) and '投影棱长' in text:
            from .cad_projection_acceptance import verify_projection_requirements
            projection=evidence_context.measure(verify_projection_requirements,text,selected)
            if projection['status']=='passed':actual=projection['projected_edge_length_mm']
        elif field=='radius' and len(selected)>1 and '最大半径' in fact['evidence']['text']:
            # A group's radial extent is not a native circle radius. Bind
            # this scalar to the independently recovered rotational centre
            # and endpoint distances, preserving its original fact/evidence.
            from .cad_repetition_acceptance import branch_structure_requirements, verify_repetition_requirements
            if branch_structure_requirements(text):
                radial=evidence_context.measure(verify_repetition_requirements,text,selected).get('measured_contracts',{}).get('radial_branches')
                if radial:actual=radial['maximum_radius_mm']
        elif field=='diameter' and '外径' in fact['evidence']['text']:
            from .cad_repetition_acceptance import tooth_boundary_requirements,verify_repetition_requirements
            if tooth_boundary_requirements(text):
                gear=evidence_context.measure(verify_repetition_requirements,text,selected).get('measured_contracts',{}).get('tooth_boundary')
                if gear:actual=gear['outer_diameter_mm']
        elif len(selected)==1 and selected[0].get('type')=='polyline' and field=='radius':
            from .cad_parametric import polar_requirements
            if re.search(r'圆角半径',text):
                from .cad_geometry_measurements import rounded_rectangle_facts
                rounded=measured(rounded_rectangle_facts,selected[0],fact['value_mm'],evidence_context=evidence_context)
                if rounded:actual=rounded['radius_mm']
            elif polar_requirements(text):
                # Explicit origin-based winding fixes the radial reference;
                # arbitrary free curves must not inherit an origin or radius.
                actual=max(math.hypot(p['x'],p['y']) for p in selected[0]['vertices'])
        elif len(selected)==1 and field in {'circumradius','side_length'}:
            # Measure the bound scalar directly instead of clearing an
            # unresolved source fact merely because another verifier passed.
            from .cad_structure_contract import _points, _corners
            geometry=selected[0]
            points=_corners(_points(geometry))
            straight=not any(p.get('bulge',0)!=0 for p in geometry.get('vertices',[]))
            if len(points)>=3 and straight:
                from shapely.geometry import Polygon
                shape=Polygon(points)
                if shape.is_valid and shape.area>0:
                    if field=='side_length':
                        lengths=[math.dist(p,q) for p,q in zip(points,points[1:]+points[:1])]
                        if max(lengths)-min(lengths)<=.5:
                            actual=sum(lengths)/len(lengths)
                    else:
                        from .cad_geometry_measurements import polygon_circumcircle
                        circle=measured(polygon_circumcircle,geometry,evidence_context=evidence_context)
                        if circle:actual=circle['radius_mm']
                        else:
                            from .cad_geometry_measurements import polygon_circumcircle_diagnostics
                            diagnostic=measured(polygon_circumcircle_diagnostics,geometry,evidence_context=evidence_context)
                            from .cad_construction_interpreter import outline_requirements
                            radial=outline_requirements(text)
                            if diagnostic and not diagnostic['cyclic_hull'] and radial and radial['profile']=='polygonal':
                                raise StructureContractError('原文外接圆要求不满足：外轮廓顶点不共圆',{
                                    'authority':'backend_measured_geometry','geometry_ids':[geometry['id']],
                                    'source_requirement':fact,'measurements':diagnostic,
                                    'requires_structural_replan':True,
                                    'repair_instruction':'按已确认外接圆半径核对全部外顶点；修复实际顶点及其连接，保留内外比例、朝向和原始来源要求。不能把不共圆当成不支持测量，也不能改断言掩盖错误。'})
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
                match=matches[-1];factor=length_factors('mm')[units[-1].lower()]
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
            unit_pattern=r"毫米|厘米|米|mm|cm|m"
            factors=length_factors('mm')
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
            # Parsing a prefix never proves the rest of the clause. Preserve
            # unrecognized suffixes so coverage adapters cannot swallow them
            # by removing the full primitive evidence string.
            rest=body
            rest=re.sub(r'坐标单位(?:为|是)?\s*(?:'+unit_pattern+r')',' ',rest)
            rest=re.sub(r'(?:圆心|左下角|起点|终点)(?:为|是)?\s*'+P,' ',rest)
            rest=re.sub(r'(?:半径|宽|高)(?:为|是)?\s*'+N+r'\s*(?:'+unit_pattern+r')',' ',rest)
            rest=re.sub(r'(?:起始角|终止角)\s*'+N+r'\s*度',' ',rest)
            if rest.strip(' \t，,、：:'):spec['unconsumed_text']=rest.strip()
            # Later revisions override only the same explicitly named subject.
            specs[spec["subject"]]=spec
    # Also accept one unambiguous primitive described in ordinary command
    # syntax.  This is an independent source parser: it measures the executed
    # geometry and never reads the construction plan or its assertions.
    if not specs:
        source="\n".join(source_texts(text))
        unit_pattern=r"毫米|厘米|米|mm|cm|m"
        factors=length_factors('mm')
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


def verify_scoped_primitives(text, geometries, logical_objects=None, *, evidence_context=None):
    from .cad_structure_contract import _frame
    from .cad_geometry_measurements import measured,circle_facts
    from .cad_validation_evidence import ConstructionEvidence
    if evidence_context is None:evidence_context=ConstructionEvidence()
    specs=extract_scoped_primitives(text)
    if not specs:return {"status":"not_checked","checks":[],"coverage":"partial"}
    has_annotations=any(g.get('selected') is not False and g.get('role')=='annotation' for g in geometries)
    geometries=[g for g in geometries if g.get("selected") is not False and g.get("role") not in {"reference","annotation","ignored"}]
    def point(p):return [p["x"],p["y"]]
    def near(a,b):return math.dist(a,b)<=.5
    def matches(s,g):
        if s["kind"] in {"圆","圆弧"}:
            if g.get("type")!=({"圆":"circle","圆弧":"arc"}[s["kind"]]):return False
            fact=measured(circle_facts,g,evidence_context=evidence_context)
            if not near(s["center"],fact['center_mm']) or abs(s["radius"]-fact['radius_mm'])>.5:return False
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
            frame=_frame(g,evidence_context=evidence_context)
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
    # Ordinary complete enumerations use the same measured bindings. Coverage
    # is established by consuming every clause, never by absence of failures.
    from .cad_source_intent import partition_preview_intent
    rest,intents=partition_preview_intent('\n'.join(source_texts(text)))
    for spec in specs:
        if not spec.get('unconsumed_text'):
            rest=rest.replace(spec['evidence'],' ',1)
    declarations=list(re.finditer(r'(?:在同一张图中)?(?:请)?(?:画|绘制|生成)([二三四五六七八九十]|两|\d+)个独立图形',rest))
    number=lambda s:int(s) if s.isdigit() else 2 if s=='两' else '零一二三四五六七八九十'.index(s)
    closed_enumeration=bool(declarations) and all(number(m[1])==len(specs) for m in declarations)
    rest=re.sub(r'(?:在同一张图中)?(?:请)?(?:画|绘制|生成)(?:[二三四五六七八九十]|两|\d+)个独立图形',' ',rest)
    no_extra=bool(re.search(r'不要增加连接线或标注|不加其他图形',rest))
    rest=re.sub(r'不要增加连接线或标注|不加其他图形',' ',rest)
    ordinary_complete=(closed_enumeration and no_extra and not rest.strip(' \t\r\n，,。；;')
                       and not any(s.get('unconsumed_text') for s in specs))
    complete_inventory=complete_inventory or ordinary_complete
    if ordinary_complete and has_annotations:
        raise StructureContractError('原文完整清单要求不加标注')
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
    report['relation_acceptance']=verify_named_relations(text,geometries,report['checks'],evidence_context=evidence_context)
    report['review_required']=report['review_required'] or report['relation_acceptance']['review_required']
    if ordinary_complete and not report['review_required']:
        report.update(status='passed',coverage='complete',intent_evidence=intents,
                      measurement_scope='fully_consumed_measured_scoped_inventory')
        report['inventory_check']={'field':'complete_visible_inventory','status':'passed',
            'expected':len(specs),'actual':len(geometries),'geometry_ids':[g['id'] for g in geometries]}
    return report
