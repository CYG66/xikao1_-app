"""Consume source text only for independently measured semantic contracts.

The existing semantic verifier establishes geometry; this layer proves that
its measurements cover every supported clause. It never creates geometry.
"""
from .cad_length_units import length_factors
import math
import re

from .cad_source_acceptance import N, P, source_texts


def semicircular_source_requirements(source):
    """Parse source dimensions once, without consulting candidate geometry."""
    from .cad_source_intent import partition_preview_intent
    original='\n'.join(source_texts(source))
    text,intents=partition_preview_intent(original)
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    if not ('拱门' in text and '半圆' in text):return partial
    unit=r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'
    factors=length_factors('mm');rest=text;checks=[];fields=set()
    for label,field in [(r'(?:整体|总)?(?:宽度|宽)','width_mm'),
                        (r'(?:从底边到拱顶的)?(?:整体|总)?(?:高度|高)','height_mm'),
                        (r'半径','radius_mm'),(r'两侧直墙各长','wall_height_mm'),
                        (r'(?:半圆)?直径','width_mm')]:
        pattern=label+r'(?:为|是)?\s*('+N+r')\s*'+unit
        matches=list(re.finditer(pattern,rest,re.I))
        for match in matches:
            expected=float(match[1])*factors[match[2].lower()]
            if expected<=0 or not math.isfinite(expected):return partial
            fields.add(field)
            checks.append({'field':field,'expected_mm':expected,'source_evidence':match[0]})
        rest=re.sub(pattern,' ',rest,flags=re.I)
    # Width+total height determine radius and wall height. Optional explicit
    # radius/wall dimensions above remain independent checks, never assumptions.
    if not {'width_mm','height_mm'}<=fields:return partial
    origin_pattern=r'(?:水平)?底边(?:左端(?:在|为)?|从)\s*'+P
    origins=list(re.finditer(origin_pattern,rest))
    if origins:
        units=re.findall(r'坐标单位(?:为|是)?\s*'+unit,text,re.I)
        if not units or len(set(u.lower() for u in units))!=1:return partial
        for m in origins:
            expected=[float(m[1])*factors[units[0].lower()],float(m[2])*factors[units[0].lower()]]
            checks.append({'field':'bottom_left','expected_mm':expected,'source_evidence':m[0]})
        rest=re.sub(origin_pattern,' ',rest)
    rest=re.sub(r'坐标单位(?:为|是)?\s*'+unit,' ',rest,flags=re.I)
    # Every phrase below is established by the measured single arch identity:
    # upper semicircle, equal vertical walls, horizontal floor, no extra edges.
    phrases=[r'两侧直墙等高且竖直',r'两侧是等高竖直墙',r'顶部为连接两墙的上半圆',
        r'顶部为上半圆',r'直径等于总宽',r'总高包含半圆',r'高度已包含在总高中',
        r'只画外边界',r'不画内部线',r'不要内部线',r'底边水平',r'水平向右',r'底边闭合',
        r'左右(?:两段)?直墙竖直且等高',r'顶上用\s*的上半圆连接',r'整体高度包含这段半圆']
    for phrase in phrases:rest=re.sub(phrase,' ',rest)
    rest=re.sub(r'生成|创建|绘制|画出|画|请|一个|半圆拱门|拱门|外轮廓|轮廓|闭合|顶部为|上半圆|边界|的',' ',rest)
    if rest.strip(' \t\r\n，,、。；;：:'):
        return {**partial,'unconsumed_text':rest.strip()}
    return {'status':'parsed','coverage':'complete','requirements':checks,'intent_evidence':intents}


def verify_semicircular_outline_source(source, geometries, *, evidence_context=None):
    from .cad_curve_fit_acceptance import verify_semicircular_arch, verify_native_semicircular_arch
    from .cad_geometry_measurements import measured
    from .cad_precision import ACCEPTANCE_MM
    parsed=semicircular_source_requirements(source)
    if parsed['coverage']!='complete':return parsed
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    facts=(measured(verify_semicircular_arch,geometries[0],evidence_context=evidence_context) if len(geometries)==1
        else measured(verify_native_semicircular_arch,geometries,evidence_context=evidence_context))
    if not facts['passed']:
        if facts.get('reason')=='non_semicircular_boundary_edge':
            from .cad_structure_contract import StructureContractError
            raise StructureContractError('实际边不属于源要求的竖直墙、水平底边或上半圆',{
                'reason':facts['reason'],'measurements':facts,'source_requirements':parsed['requirements'],
                'geometry_ids':[g['id'] for g in geometries],
                'repair_instruction':'按原文起点、宽度和总高修复实际墙弧连接；复用来源尺寸关系，保持等高竖直墙、水平底边及上半圆，不能仅修改断言。'})
        return {**partial,'reason':'unverified_semicircular_boundary'}
    checks=[]
    for requirement in parsed['requirements']:
        field=requirement['field'];expected=requirement['expected_mm']
        actual=([facts['center_mm'][0]-facts['radius_mm'],facts['center_mm'][1]-facts['wall_height_mm']]
                if field=='bottom_left' else facts[field])
        error=math.dist(actual,expected) if isinstance(expected,list) else abs(actual-expected)
        if error>ACCEPTANCE_MM:
            return {**partial,'reason':'source_origin_mismatch' if field=='bottom_left' else 'source_dimension_mismatch',
                    'field':field,'actual_mm':actual,'expected_mm':expected}
        checks.append({**requirement,'actual_mm':actual,'status':'passed',
                       'geometry_ids':facts.get('geometry_ids',[g['id'] for g in geometries])})
    return {'status':'passed','coverage':'complete','authority':'backend_measured_geometry',
            'source_evidence':source_texts(source),'intent_evidence':parsed['intent_evidence'],'checks':[*checks,
                {'field':'sampled_semicircle_walls_and_floor','status':'passed','measurements':facts}]}


def source_dimension_relation_guidance(source):
    """Solve scalar relations from existing source parsers, never build a plan.

    These are source-derived facts shared with acceptance. Candidate geometry
    still has to pass the original independent measurements and coverage gate.
    """
    from .cad_capsule_acceptance import capsule_source_requirements
    output=[]
    arch=semicircular_source_requirements(source)
    if arch['coverage']=='complete':
        values={}
        for r in arch['requirements']:
            if r['field'] in values and values[r['field']]!=r['expected_mm']:return []
            values[r['field']]=r['expected_mm']
        w,h=values['width_mm'],values['height_mm'];radius=w/2;wall=h-radius
        if wall<=0 or ('radius_mm' in values and abs(values['radius_mm']-radius)>.5
                      or 'wall_height_mm' in values and abs(values['wall_height_mm']-wall)>.5):return []
        facts={'kind':'semicircle_equal_walls','units':'mm','source_requirements':arch['requirements'],
               'derived_relations':{'radius_mm':radius,'wall_height_mm':wall},
               'instruction':'总高是相对底边的距离，不是顶部绝对y坐标。半径=总宽/2，直墙高度=总高-半径；禁止将底边y从总高中再减一次。'}
        if 'bottom_left' in values:
            bottom=values['bottom_left'][1]
            facts['derived_relations'].update(floor_y_mm=bottom,top_y_mm=bottom+h,arc_center_y_mm=bottom+wall)
        output.append(facts)
    capsule=capsule_source_requirements(source)
    if capsule['coverage']=='complete':
        values={}
        for field,value,_ in capsule['requirements']:
            if field in values and values[field]!=value:return []
            values[field]=value
        length,height=values['length_mm'],values['height_mm']
        if not math.isfinite(length+height) or not length>height>0:return []
        if 'radius_mm' in values and abs(values['radius_mm']-height/2)>.5:return []
        output.append({'kind':'parallel_lines_tangent_semicircles','units':'mm',
            'source_requirements':capsule['requirements'],'derived_relations':{
                'radius_mm':height/2,'straight_length_mm':length-height,
                'end_center_offset_from_midpoint_mm':(length-height)/2},
            'instruction':'直边长=总长-短轴总高；两个端帽圆心在局部长轴上距整体中心±直边长/2。先在局部坐标满足相切与闭合，再围绕给定中心整体旋转一次。世界外包框不等于局部长高；圆弧角度也须同步旋转。'})
    return output



def verify_polygonal_outline_source(source, geometries, *, evidence_context=None):
    """Ground existing polygonal radial and circumcircle tools in source clauses."""
    from .cad_construction_interpreter import outline_requirements
    from .cad_geometry_measurements import measured,polygon_circumcircle,closed_polyline_points,straight_polyline_corners
    from .cad_construction import RadialPatternAssertion,_run_assertions
    from .cad_structure_contract import StructureContractError
    text='\n'.join(source_texts(source));contract=outline_requirements(text)
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    if not contract or contract['profile']!='polygonal' or len(geometries)!=1:return partial
    g=geometries[0];circle=measured(polygon_circumcircle,g,evidence_context=evidence_context)
    if not circle:return partial
    radius=circle['radius_mm'];center=circle['center_mm'];count=contract['radial_lobes']
    points=straight_polyline_corners(closed_polyline_points(g))
    def fail(reason):
        raise StructureContractError('星形轮廓不符合原文：'+reason,{
            'authority':'backend_measured_geometry','geometry_ids':[g['id']],
            'requires_structural_replan':True,'reason':reason,'circumcircle':circle,
            'repair_instruction':'使用已确认外接圆、内外半径比和朝向核对实际顶点；保持外峰内谷沿边界交替，不能只更改断言。'})
    _run_assertions([RadialPatternAssertion(kind='radial_pattern',assertion_id='source-polygonal',target_ref='outline',lobes=count,profile='polygonal')],[g],{'outline':[g['id']]},1)
    if len(points)!=count*2:fail('外峰内谷数量不符')
    radii=[math.dist(p,center) for p in points]
    outer=[abs(value-radius)<=.5 for value in radii]
    if sum(outer)!=count or any(outer[i]==outer[i-1] for i in range(len(points))):fail('外峰内谷未交替')
    inner=[value for value,is_outer in zip(radii,outer) if not is_outer]
    if max(inner)-min(inner)>.5:fail('内谷半径不一致')
    angles=[math.atan2(p[1]-center[1],p[0]-center[0]) for p in points]
    deltas=[(angles[(i+1)%len(points)]-a+math.pi)%math.tau-math.pi for i,a in enumerate(angles)]
    if any(abs(abs(d)-math.pi/count)>.5/max(radius,1) or d*deltas[0]<=0 for d in deltas):fail('顶点角间隔或顺序错误')
    rest=text;checks=[];unit=r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'
    pattern=r'外接圆半径\s*('+N+r')\s*'+unit
    sizes=list(re.finditer(pattern,rest,re.I))
    if not sizes:return partial
    for m in sizes:
        if abs(radius-float(m[1])*length_factors('mm')[m[2].lower()])>.5:fail('外接圆半径错误')
    rest=re.sub(pattern,' ',rest,flags=re.I)
    ratio=sum(inner)/len(inner)/radius
    for m in re.finditer(r'内外半径比(?:为|是)?\s*('+N+r')',rest):
        if abs(ratio-float(m[1]))*radius>.5:fail('内外半径比错误')
    rest=re.sub(r'内外半径比(?:为|是)?\s*'+N,' ',rest)
    for word,angle in [('上',math.pi/2),('下',-math.pi/2),('左',math.pi),('右',0)]:
        if '尖角朝'+word in rest:
            if min(abs((a-angle+math.pi)%math.tau-math.pi) for a,is_outer in zip(angles,outer) if is_outer)>.5/max(radius,1):fail('尖角朝向错误')
            rest=rest.replace('尖角朝'+word,' ')
    rest=re.sub(r'坐标单位(?:为|是)?\s*'+unit,' ',rest,flags=re.I)
    rest=re.sub(r'(\d+|[二三四五六七八九十])\s*角星|生成|创建|绘制|画出|画|请|一个|轮廓|闭合|封闭|的',' ',rest)
    if rest.strip(' \t\r\n，,、。；;：:'):return {**partial,'unconsumed_text':rest.strip()}
    checks.append({'field':'source_polygonal_outline','status':'passed','geometry_ids':[g['id']],
                   'circumcircle':circle,'inner_outer_ratio':ratio,'outer_tip_count':count})
    return {'status':'passed','coverage':'complete','authority':'backend_measured_geometry',
            'source_evidence':source_texts(source),'checks':checks}


def verify_periodic_outline_source(source, geometries, *, evidence_context=None):
    """Bind source-derived repetition checks to the existing radial verifier.

    Never trust assertion IDs or a plan's success flag as source evidence.
    Unknown clauses prevent full coverage even when the radial check passes.
    """
    from .cad_construction_interpreter import outline_requirements
    from .cad_construction import EntityCountAssertion, ClosedAssertion, RadialPatternAssertion, _run_assertions
    from .cad_source_acceptance import verify_final_source_contract
    from .cad_geometry_measurements import measured
    text = '\n'.join(source_texts(source))
    contract = outline_requirements(text)
    partial = {'status': 'not_checked', 'coverage': 'partial', 'checks': []}
    # Radius, orientation and star ratios need additional geometric proofs.
    # This adapter covers sized smooth periodic boundaries only.
    if not contract or contract['profile'] != 'smooth':
        return partial
    rest = re.sub(r'(\d+|[二三四五六七八九十])\s*(?:片花瓣|瓣花|个凸瓣|个波瓣)', ' ', text)
    unit = r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'
    rest = re.sub(r'(?:宽度|高度|宽|高)(?:为|是)?\s*' + N + r'\s*' + unit, ' ', rest, flags=re.I)
    rest = re.sub(r'坐标单位(?:为|是)?\s*' + unit, ' ', rest, flags=re.I)
    rest = re.sub(r'生成|创建|绘制|画出|画|请|一朵|一个|花瓣|花|轮廓|闭合|封闭|曲线|的', ' ', rest)
    if rest.strip(' \t\r\n，,、。；;：:'):
        return {**partial, 'unconsumed_text': rest.strip()}
    scalar = measured(verify_final_source_contract, source, geometries, evidence_context=evidence_context)
    if scalar.get('unknown_requirements') or not {'width', 'height'} <= {c['field'] for c in scalar['checks']}:
        return partial
    assertions = [EntityCountAssertion(kind='entity_count', assertion_id='source-count', equals=1),
                  ClosedAssertion(kind='closed', assertion_id='source-closure', target_ref='boundary'),
                  RadialPatternAssertion(kind='radial_pattern', assertion_id='source-repetition',
                                         target_ref='boundary', lobes=contract['radial_lobes'], profile=contract['profile'])]
    _run_assertions(assertions, geometries, {'boundary': [g['id'] for g in geometries]}, 1)
    return {'status': 'passed', 'coverage': 'complete', 'authority': 'backend_measured_geometry',
            'source_evidence': source_texts(source), 'checks': [*scalar['checks'],
                {'field': 'single_closed_periodic_boundary', 'status': 'passed',
                 'lobes': contract['radial_lobes'], 'profile': contract['profile'],
                 'geometry_ids': [g['id'] for g in geometries]}]}


def verify_measured_semantic_coverage(source, measured, geometries=None, *, evidence_context=None):
    partial = {'status': 'not_checked', 'coverage': 'partial', 'checks': []}
    scopes = {'explicit_nested_square_frames', 'explicit_regular_polygon_and_concentric_hole',
              'cardioid_shape_and_declared_direction', 'heart_outline_features_measured_features',
              'astroid_identity_radius_and_four_cusps'}
    if measured.get('coverage')=='triangle_roof_house_structural_relations_only':
        return _house_source_coverage(source,measured)
    if measured.get('status') != 'passed' or measured.get('coverage') not in scopes:
        return partial
    checks = measured.get('checks') or []
    if not checks or any(check.get('status') != 'passed' for check in checks):
        return partial
    from .cad_semantic_acceptance import nested_frame_requirement, regular_polygon_requirement
    text = '\n'.join(source_texts(source))
    rest = text
    evidence = []
    factors = length_factors('mm')
    unit = r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'

    def scalar(label, expected, required=True):
        nonlocal rest
        pattern = label + r'(?:为|是|[:：])?\s*(' + N + r')\s*' + unit
        matches = list(re.finditer(pattern, rest, re.I))
        if not matches:
            return not required
        if expected is None:
            return False
        values = [float(m[1]) * factors[m[2].lower()] for m in matches]
        if any(not math.isfinite(v) or v <= 0 or abs(v - expected) > 1e-6 for v in values):
            return False
        evidence.extend(m[0] for m in matches)
        rest = re.sub(pattern, ' ', rest, flags=re.I)
        return True

    if measured['coverage'] == 'astroid_identity_radius_and_four_cusps':
        details=checks[0].get('measurements') or {}
        if not details.get('passed') or not details.get('four_cusps_present'):
            return partial
        if not scalar('最大半径', details.get('radius_mm')):
            return partial
        if re.search(r'参数式|[xy]\s*=',rest,re.I):
            consumed=_astroid_formula_source(rest,details)
            if consumed is None:return partial
            rest=consumed
        rest=re.sub(r'星形线|astroid|内凹四角星|闭合', ' ',rest,flags=re.I)
    elif measured['coverage'] in {'cardioid_shape_and_declared_direction', 'heart_outline_features_measured_features'}:
        heart = measured['coverage'] == 'heart_outline_features_measured_features'
        details=checks[0].get('measurements') or {}
        bounds=details.get('bounds_mm') or []
        if len(bounds)!=4 or not details.get('simple_closed_outline' if heart else 'checked_between_vertices'):return partial
        sizes={'width':bounds[2]-bounds[0],'height':bounds[3]-bounds[1]}
        pattern=r'(最大宽度|最大高度|最大宽|最大高|宽度|高度|宽|高)(?:为|是)?\s*('+N+r')\s*'+unit
        dimensions=list(re.finditer(pattern,rest,re.I))
        if not dimensions:return partial
        for match in dimensions:
            field='height' if '高' in match[1] else 'width'
            expected=float(match[2])*factors[match[3].lower()]
            if expected<=0 or (sizes[field]-expected>.5 if match[1].startswith('最大') else abs(sizes[field]-expected)>.5):
                return partial
        rest=re.sub(pattern,' ',rest,flags=re.I)
        if heart and geometries is not None:
            from .cad_source_acceptance import verify_final_source_contract
            from .cad_geometry_measurements import measured as measure
            final=measure(verify_final_source_contract,source,geometries,evidence_context=evidence_context)
            centers=list(re.finditer(r'中心(?:位于|在|为|是)?\s*'+P,rest))
            if centers:
                if not any(c['field']=='center' and c['status']=='passed' for c in final['checks']):return partial
                rest=re.sub(r'中心(?:位于|在|为|是)?\s*'+P,' ',rest)
            if '左右对称' in rest and details.get('left_right_symmetry_error_mm') is not None:
                rest=rest.replace('左右对称',' ')
            if re.search('平滑|光滑',rest) and details.get('maximum_sample_turn_degrees') is not None:
                rest=re.sub('平滑|光滑',' ',rest)
        units=re.findall(r'坐标单位(?:为|是)?\s*'+unit,rest,re.I)
        if len({factors[u.lower()] for u in units})>1:return partial
        rest=re.sub(r'坐标单位(?:为|是)?\s*'+unit,' ',rest,flags=re.I)
        rest=re.sub(r'爱心|心形|闭合' if heart else r'心形线|cardioid|尖点朝下|闭合',' ',rest,flags=re.I)
    elif measured['coverage'] == 'explicit_nested_square_frames':
        contract = nested_frame_requirement(text)
        if not contract or not (scalar('外框边长', contract['outer_side_mm'])
                                and scalar('内框边长', contract['inner_side_mm'])):
            return partial
        rest = re.sub(r'内框居中|同心', ' ', rest)
        rest = re.sub(r'回字形|嵌套正方形', ' ', rest)
    else:
        contract = regular_polygon_requirement(text)
        if not contract:
            return partial
        n = contract['sides']
        count_tokens = {str(n)}
        chinese = dict(zip(range(3, 11), '三四五六七八九十'))
        if n in chinese:
            count_tokens.add(chinese[n])
        count = '(?:' + '|'.join(map(re.escape, sorted(count_tokens))) + ')'
        name_pattern = r'正' + count + r'边形|外' + count + r'角|' + count + r'角螺母'
        if not re.search(name_pattern, rest):
            return partial
        rest = re.sub(name_pattern, ' ', rest)
        radius = contract['circumradius_mm']
        expected_side = 2 * radius * math.sin(math.pi / n)
        # At least one size is guaranteed by the measured contract. Every
        # restated size is checked, including additional or conflicting ones.
        if not (scalar('外接圆半径', radius, required=False)
                and scalar('边长', expected_side, required=False)
                and scalar('中心圆孔半径', contract.get('hole_radius_mm'),
                           required=contract.get('hole_radius_mm') is not None)):
            return partial
        centers = list(re.finditer(r'中心(?:位于|在|为|是)?\s*' + P, rest))
        if centers:
            units = re.findall(r'坐标单位(?:为|是|[:：])?\s*' + unit, rest, re.I)
            scales = {factors[u.lower()] for u in units}
            if len(scales) != 1:
                return partial
            actual = checks[0].get('center_mm')
            scale = next(iter(scales))
            if actual is None or any(math.dist(actual, [float(m[1])*scale, float(m[2])*scale]) > .5
                                     for m in centers):
                return partial
            evidence.extend(m[0] for m in centers)
            rest = re.sub(r'中心(?:位于|在|为|是)?\s*' + P, ' ', rest)
            rest = re.sub(r'坐标单位(?:为|是|[:：])?\s*' + unit, ' ', rest, flags=re.I)
    rest = re.sub(r'生成|创建|绘制|画出|画|请|一个|轮廓|的', ' ', rest)
    if rest.strip(' \t\r\n，,、。；;（()）'):
        return {**partial, 'unconsumed_text': rest.strip(), 'source_evidence': source_texts(source)}
    return {'status': 'passed', 'coverage': 'complete', 'checks': checks,
            'authority': 'backend_measured_geometry', 'source_evidence': source_texts(source),
            'scalar_evidence': evidence, 'measurement_scope': 'fully_consumed_measured_semantic_contract'}


def _astroid_formula_source(text,details):
    """Prove a narrow formula identity, not just sampled expression values."""
    import ast
    from .cad_parametric import expression
    unit=r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'
    units=re.findall(r'坐标单位(?:为|是)?\s*'+unit,text,re.I)
    if len(set(u.lower() for u in units))!=1:return None
    scale=length_factors('mm')[units[0].lower()]
    assignments=list(re.finditer(r'([xy])\s*=\s*([^、，,；;。\n]+)',text,re.I))
    if {m[1].lower() for m in assignments}!={'x','y'}:return None
    for match in assignments:
        raw=match[2].strip().replace('^','**')
        try:
            expression(raw)
            tree=ast.parse(raw,mode='eval').body
            coefficient=1
            if isinstance(tree,ast.BinOp) and isinstance(tree.op,ast.Mult):
                left,right=tree.left,tree.right
                if isinstance(left,ast.BinOp) and isinstance(left.op,ast.Pow):left,right=right,left
                if any(isinstance(n,ast.Name) and n.id=='t' for n in ast.walk(left)):return None
                coefficient=expression(ast.unparse(left))(0);tree=right
            trig='cos' if match[1].lower()=='x' else 'sin'
            if not (isinstance(tree,ast.BinOp) and isinstance(tree.op,ast.Pow)
                    and isinstance(tree.right,ast.Constant) and tree.right.value==3
                    and isinstance(tree.left,ast.Call) and isinstance(tree.left.func,ast.Name)
                    and tree.left.func.id==trig and len(tree.left.args)==1
                    and isinstance(tree.left.args[0],ast.Name) and tree.left.args[0].id=='t'):return None
            if abs(abs(coefficient)*scale-details['radius_mm'])>.5:return None
        except (ValueError,SyntaxError,TypeError):return None
    if math.dist(details.get('center_mm',[]),[0,0])>.5:return None
    if abs((details.get('orientation_degrees',float('nan'))+45)%90-45)>.001:return None
    ranges=list(re.finditer(r't从([^、，,；;。\n]+?)到([^、，,；;。\n]+)',text,re.I))
    if not ranges:return None
    for match in ranges:
        try:
            start=expression(match[1].strip())(0);end=expression(match[2].strip())(0)
        except (ValueError,TypeError):return None
        if abs(abs(end-start)-math.tau)>1e-9:return None
    rest=re.sub(r'[xy]\s*=\s*[^、，,；;。\n]+',' ',text,flags=re.I)
    rest=re.sub(r't从[^、，,；;。\n]+?到[^、，,；;。\n]+',' ',rest,flags=re.I)
    rest=re.sub(r'坐标单位(?:为|是)?\s*'+unit,' ',rest,flags=re.I)
    return re.sub('使用参数式',' ',rest)


def _house_source_coverage(source, measured):
    """Associate already measured regions and vertices with explicit clauses."""
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    house=measured.get('measured_contracts',{}).get('house_parts')
    if not house or len(house['door_bounds_mm'])!=1 or any(c['status']!='passed' for c in measured['checks']):return partial
    text='\n'.join(source_texts(source));rest=text;checks=[]
    unit=r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])';factors=length_factors('mm')
    units=re.findall(r'坐标单位(?:为|是)?\s*'+unit,text,re.I)
    if len(set(units))!=1:return partial
    scale=factors[units[0].lower()]
    pattern=r'(墙体|门)左下角\s*'+P+r'[，,\s]*宽\s*('+N+r')\s*'+unit+r'\s*高\s*('+N+r')\s*'+unit
    parts=list(re.finditer(pattern,rest,re.I))
    if {m[1] for m in parts}!={'墙体','门'}:return partial
    for m in parts:
        box=house['wall_bounds_mm'] if m[1]=='墙体' else house['door_bounds_mm'][0]
        expected=[float(m[2])*scale,float(m[3])*scale,float(m[4])*factors[m[5].lower()],float(m[6])*factors[m[7].lower()]]
        if any(abs(a-b)>.5 for a,b in zip(box,expected)):return partial
        checks.append({'field':'source_region_dimensions_and_origin','subject':m[1],'actual_mm':box,
                       'expected_mm':expected,'source_evidence':m[0],'status':'passed'})
    rest=re.sub(pattern,' ',rest,flags=re.I)
    roof_pattern=r'屋顶顶点\s*'+P+r'\s*'+P+r'\s*'+P
    roofs=list(re.finditer(roof_pattern,rest))
    if not roofs:return partial
    for m in roofs:
        expected=[(float(m[i])*scale,float(m[i+1])*scale) for i in (1,3,5)]
        actual=house['roof_vertices_mm']
        if any(min(math.dist(p,q) for q in actual)>.5 for p in expected) or len(set(expected))!=3:return partial
        checks.append({'field':'source_roof_vertices','actual_mm':actual,'expected_mm':expected,'status':'passed'})
    rest=re.sub(roof_pattern,' ',rest)
    pattern=r'(?:总)?(宽|高)\s*('+N+r')\s*'+unit
    for m in re.finditer(pattern,rest,re.I):
        if abs(house['whole_bounds_mm'][2 if m[1]=='宽' else 3]-float(m[2])*factors[m[3].lower()])>.5:return partial
    rest=re.sub(pattern,' ',rest,flags=re.I)
    rest=re.sub(r'坐标单位(?:为|是)?\s*'+unit,' ',rest,flags=re.I)
    rest=re.sub(r'下面加一个门|生成|创建|画|绘制|一个|房子轮廓|屋顶是三角形',' ',rest)
    if rest.strip(' \t\r\n，,、。；;：:'):return {**partial,'unconsumed_text':rest.strip()}
    return {'status':'passed','coverage':'complete','checks':measured['checks']+checks,
            'source_evidence':source_texts(source),'authority':'backend_measured_geometry','measured_contracts':measured['measured_contracts']}
