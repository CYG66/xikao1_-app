"""Measure fully specified primitive layouts without using model labels or plans."""
from .cad_length_units import length_factors
import math
import re

from .cad_source_acceptance import N,P,source_texts,nested_circle_roles
from .cad_structure_contract import StructureContractError,_frame
from .cad_relation_acceptance import extract_named_relations,verify_named_relations

UNIT=r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'
FACTORS=length_factors('mm')


def verify_primitive_layout(source,geometries, *, evidence_context=None):
    from .cad_validation_evidence import ConstructionEvidence
    if evidence_context is None:evidence_context=ConstructionEvidence()
    from .cad_geometry_measurements import measured,circle_facts
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    text='\n'.join(source_texts(source));rest=text
    if '圆柱体' in text and '两个独立正投影视图' in text:return _cylinder_views_source(source,geometries,evidence_context=evidence_context)
    if '圆角矩形' in text:return _rounded_source(source,geometries,evidence_context=evidence_context)
    if '十字形' in text:return _cross_source(source,geometries,evidence_context=evidence_context)
    if '禁止标志' in text:return _diameter_source(source,geometries,evidence_context=evidence_context)
    if '笑脸图案' in text:return _face_source(source,geometries,evidence_context=evidence_context)
    ring=bool(re.search(r'圆环',text))
    circle=r'(?:一|1)个(?:圆形|圆)'
    rectangle=r'(?:一|1)个(?:矩形|长方形)'
    inventory=r'(?:'+circle+r'(?:和|与)'+rectangle+r'|'+rectangle+r'(?:和|与)'+circle+r')'
    if not ring and not re.search(inventory,text):return partial
    units=re.findall(r'坐标单位(?:为|是|[:：])?\s*'+UNIT,text,re.I)
    scales={FACTORS[u.lower()] for u in units}
    if len(scales)>1:return partial
    scale=next(iter(scales)) if scales else None
    values={};evidence=[];conflict=False
    def assign(key,value):
        nonlocal conflict
        if key in values:
            old=values[key]
            difference=math.dist(old,value) if isinstance(value,list) else abs(old-value)
            if difference>1e-9:conflict=True
        values[key]=value
    def consume(pattern,body,callback):
        for match in re.finditer(pattern,body,re.I):
            callback(match);evidence.append(match[0])
        return re.sub(pattern,' ',body,flags=re.I)
    rest=re.sub(r'坐标单位(?:为|是|[:：])?\s*'+UNIT,' ',rest,flags=re.I)
    relations=[]
    if ring:
        for role in ('外圆','内圆'):
            rest=consume(role+r'半径(?:为|是)?\s*('+N+r')\s*'+UNIT,rest,
                lambda m,role=role:assign(role+'.radius',float(m[1])*FACTORS[m[2].lower()]))
        centers=list(re.finditer(r'均圆心(?:为|是|在)?\s*'+P,rest))
        if centers and scale is None:return partial
        if centers:
            rest=consume(r'均圆心(?:为|是|在)?\s*'+P,rest,
                lambda m:assign('center',[float(m[1])*scale,float(m[2])*scale]))
        rest=re.sub(r'圆环',' ',rest)
        if not {'外圆.radius','内圆.radius'}<=values.keys():return partial
    else:
        if scale is None:return partial
        rest=re.sub(inventory,' ',rest)
        relations=extract_named_relations(text,['圆','矩形'])
        for relation in relations:rest=rest.replace(relation['evidence']['text'],' ')
        rest=re.sub(r'两个独立图形',' ',rest)
        bodies=[]
        for clause in re.split(r'[；;。\n]',rest):
            body=clause.strip(' ，,、\t')
            head=re.match(r'(圆形|圆(?!心|环|弧)|矩形|长方形)',body)
            if not head:bodies.append(clause);continue
            kind='圆' if head[1] in {'圆','圆形'} else '矩形'
            body=body[head.end():]
            scalar=r'(半径)' if kind=='圆' else r'(宽度|高度|宽|高)'
            body=consume(scalar+r'(?:为|是)?\s*('+N+r')\s*'+UNIT,body,
                lambda m,kind=kind:assign(kind+'.'+('radius' if m[1]=='半径' else 'width' if m[1].startswith('宽') else 'height'),
                                         float(m[2])*FACTORS[m[3].lower()]))
            coordinate='圆心' if kind=='圆' else '左下角'
            body=consume(coordinate+r'(?:为|是|在)?\s*'+P,body,
                lambda m,kind=kind:assign(kind+'.point',[float(m[1])*scale,float(m[2])*scale]))
            bodies.append(body)
        rest='\n'.join(bodies)
        if not {'圆.radius','圆.point','矩形.point','矩形.width','矩形.height'}<=values.keys():return partial
    if conflict or any(not math.isfinite(v) or v<=0 for key,v in values.items() if not isinstance(v,list)):
        return partial
    rest=re.sub(r'生成|创建|绘制|画出|画|请|一个|的',' ',rest)
    if rest.strip(' \t\r\n，,、。；;'):
        return {**partial,'unconsumed_text':rest.strip(),'source_evidence':source_texts(source)}
    gs=[g for g in geometries if g.get('selected') is not False
        and g.get('role') not in {'annotation','reference','ignored'}]
    circles=[g for g in gs if g.get('type')=='circle']
    rectangles=[(g,frame) for g in gs if (frame:=_frame(g,evidence_context=evidence_context)) is not None]
    if len(gs)!=2 or len(circles)!=(2 if ring else 1) or (not ring and len(rectangles)!=1):
        raise StructureContractError('原文部件数量或类型不匹配',{
            'geometry_ids':[g['id'] for g in gs],'expected':{'circle':2} if ring else {'circle':1,'rectangle':1},
            'observed_geometry_count':len(gs),'observed_circle_count':len(circles),'observed_rectangle_count':len(rectangles)})
    checks=[{'field':'primitive_type_and_count','status':'passed'}]
    def check(field,actual,expected,ok=None):
        if ok is None:
            error=math.dist(actual,expected) if isinstance(expected,list) else abs(actual-expected)
            ok=error<=.5
        checks.append({'field':field,'status':'passed' if ok else 'failed','actual_mm':actual,'expected_mm':expected})
    if ring:
        inner,outer=sorted(circles,key=lambda g:g['radius'])
        facts=[measured(circle_facts,g,evidence_context=evidence_context) for g in (inner,outer)]
        check('outer_radius',facts[1]['radius_mm'],values['外圆.radius'])
        check('inner_radius',facts[0]['radius_mm'],values['内圆.radius'])
        centers=[list(f['center_mm']) for f in facts]
        check('concentric_centers',centers[0],centers[1])
        check('strict_circle_containment',math.dist(*centers)+inner['radius'],outer['radius'],bool(nested_circle_roles(gs)))
        if 'center' in values:
            for point in centers:check('source_circle_center',point,values['center'])
    else:
        circle=circles[0];rectangle,frame=rectangles[0]
        fact=measured(circle_facts,circle,evidence_context=evidence_context)
        check('circle_radius',fact['radius_mm'],values['圆.radius'])
        check('circle_center',list(fact['center_mm']),values['圆.point'])
        check('rectangle_origin',list(frame[:2]),values['矩形.point'])
        check('rectangle_width',frame[2],values['矩形.width'])
        check('rectangle_height',frame[3],values['矩形.height'])
    if any(c['status']=='failed' for c in checks):
        raise StructureContractError('实际部件坐标、尺寸或包含关系不符合原文',{'geometry_ids':[g['id'] for g in gs],
            'checks':checks,'source_evidence':source_texts(source),'authority':'backend_measured_geometry'})
    if not ring:
        bindings=[{'subject':'圆','geometry_ids':[circle['id']]},{'subject':'矩形','geometry_ids':[rectangle['id']]}]
        relational=verify_named_relations(text,gs,bindings,evidence_context=evidence_context)
        if relational['review_required']:return partial
        checks+=relational['checks']
    return {'status':'passed','coverage':'complete','checks':checks,'geometry_ids':[g['id'] for g in gs],
            'source_evidence':source_texts(source),'consumed_evidence':evidence,
            'authority':'backend_measured_geometry','measurement_scope':'fully_consumed_primitive_layout_source'}


def cylinder_view_requirements(source):
    text='\n'.join(source_texts(source))
    if not ('圆柱体' in text and '两个独立正投影视图' in text):return None
    radius=re.search(r'底面半径\s*('+N+r')\s*'+UNIT,text,re.I)
    height=re.search(r'高\s*('+N+r')\s*'+UNIT,text,re.I)
    if not radius or not height:return None
    r=float(radius[1])*FACTORS[radius[2].lower()];h=float(height[1])*FACTORS[height[2].lower()]
    if min(r,h)<=0:return None
    return {'top_radius_mm':r,'side_width_mm':2*r,'side_height_mm':h,
            'separate_nonoverlapping_views':True,
            'instruction':'俯视圆和侧视矩形是两个独立视图，均须存在且不重叠。圆用原生center/radius表达；侧视轮廓可复用矩形原语。自由轮廓布局只修改闭合多段线，原生圆可作只读right_of_ref参照。尺寸单位为毫米，坐标仍遵守plan.units。不要额外添加轴线或用一个视图替代另一个。'}


def _cylinder_views_source(source,gs,*,evidence_context=None):
    from .cad_geometry_measurements import measured,circle_facts
    from .cad_relation_acceptance import _region,_disjoint
    partial={'status':'not_checked','coverage':'partial','checks':[]};p=_SourceProof(source,gs)
    circles=[g for g in gs if g.get('type')=='circle']
    rectangles=[(g,f) for g in gs if (f:=_frame(g,evidence_context=evidence_context)) is not None]
    if len(gs)!=2 or len(circles)!=1 or len(rectangles)!=1:return partial
    circle=circles[0];rectangle,frame=rectangles[0]
    radius=measured(circle_facts,circle,evidence_context=evidence_context)['radius_mm']
    disjoint=_disjoint(_region(circle,evidence_context=evidence_context),_region(rectangle,evidence_context=evidence_context),.5)
    if abs(frame[2]-2*radius)>.5 or not disjoint:
        raise StructureContractError('圆柱正投影需独立不重叠的俯视圆和侧视轮廓，侧视宽须等于底面直径',
                                     {'authority':'backend_measured_geometry','geometry_ids':p.ids,'side_frame_mm':frame,'radius_mm':radius,
                                      'circle_center_mm':circle['center'],'side_width_matches_diameter':abs(frame[2]-2*radius)<=.5,
                                      'source_view_requirements':cylinder_view_requirements(source),
                                      'views_disjoint':disjoint,'requires_structural_replan':True,
                                      'repair_instruction':'保留两个视图及原文尺寸，修正未通过的宽度或视图分离关系。测量覆盖全部视图时允许同步修正全局布局；不要保留导致重叠的旧布局，不要把原生圆当作可缩放多段线。'})
    for label,actual in [(r'底面半径',radius),(r'高',frame[3])]:
        if not p.consume(label+r'\s*('+N+r')\s*'+UNIT,lambda m,actual=actual:abs(actual-float(m[1])*FACTORS[m[2].lower()])<=.5,label):return partial
    result=p.finish(r'圆柱体|轮廓|俯视顶圆可见|俯视圆|侧视轮廓|两个独立正投影视图|采用|生成|创建|绘制|画出|画|请|一个|的|与|＋|\+')
    result['view_bindings']={'top_geometry_id':circle['id'],'side_geometry_id':rectangle['id']}
    result['view_requirements']=cylinder_view_requirements(source)
    return result


class _SourceProof:
    """Keep source consumption separate from geometry identity and generation."""
    def __init__(self,source,geometries):
        self.source=source;self.rest='\n'.join(source_texts(source));self.checks=[]
        self.ids=[g['id'] for g in geometries]

    def consume(self,pattern,test,field,required=True):
        matches=list(re.finditer(pattern,self.rest,re.I))
        if not matches:return not required
        for m in matches:
            if not test(m):raise StructureContractError('来源几何关系不满足：'+field,
                {'geometry_ids':self.ids,'source_evidence':m[0],'field':field,'authority':'backend_measured_geometry'})
            self.checks.append({'field':field,'status':'passed','source_evidence':m[0],'geometry_ids':self.ids})
        self.rest=re.sub(pattern,' ',self.rest,flags=re.I)
        return True

    def finish(self,noise):
        self.rest=re.sub(noise,' ',self.rest,flags=re.I)
        if self.rest.strip(' \t\r\n，,、。；;：:'):
            return {'status':'not_checked','coverage':'partial','checks':self.checks,'unconsumed_text':self.rest.strip()}
        return {'status':'passed','coverage':'complete','checks':self.checks,
                'source_evidence':source_texts(self.source),'authority':'backend_measured_geometry','geometry_ids':self.ids}

    def point(self,label,actual):
        units=re.findall(r'坐标单位(?:为|是)?\s*'+UNIT,self.rest,re.I)
        scales={FACTORS[u.lower()] for u in units}
        pattern=label+r'(?:位于|在|为|是)?\s*'+P
        if re.search(pattern,self.rest) and len(scales)!=1:return False
        if scales:
            scale=next(iter(scales))
            if not self.consume(pattern,lambda m:math.dist(actual,[float(m[1])*scale,float(m[2])*scale])<=.5,'explicit_center',False):return False
        self.rest=re.sub(r'坐标单位(?:为|是)?\s*'+UNIT,' ',self.rest,flags=re.I)
        return True


def _rounded_source(source,gs,*,evidence_context=None):
    from .cad_geometry_measurements import rounded_rectangle_facts,measured
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    p=_SourceProof(source,gs)
    radii=list(re.finditer(r'(?:四角)?圆角半径\s*('+N+r')\s*'+UNIT,p.rest,re.I))
    if not radii or len(gs)!=1:return partial
    radius=float(radii[0][1])*FACTORS[radii[0][2].lower()]
    facts=measured(rounded_rectangle_facts,gs[0],radius,evidence_context=evidence_context)
    if facts is None:raise StructureContractError('实际轮廓不满足四角等半径圆角矩形',{'geometry_ids':p.ids,'required_radius_mm':radius})
    for pattern,key in [(r'(?:四角)?圆角半径','radius_mm'),(r'(?:外包)?宽','width_mm'),(r'高','height_mm')]:
        if not p.consume(pattern+r'\s*('+N+r')\s*'+UNIT,lambda m,key=key:abs(facts[key]-float(m[1])*FACTORS[m[2].lower()])<=.5,key):return partial
    result=p.finish(r'圆角矩形|闭合|生成|创建|绘制|画出|画|请|一个')
    result['measurements']=facts
    return result


def _cross_source(source,gs,*,evidence_context=None):
    partial={'status':'not_checked','coverage':'partial','checks':[]};p=_SourceProof(source,gs)
    frames=[_frame(g,evidence_context=evidence_context) for g in gs]
    if len(frames)!=2 or any(f is None for f in frames):return partial
    horizontal=[f for f in frames if f[2]>f[3]];vertical=[f for f in frames if f[3]>f[2]]
    if len(horizontal)!=1 or len(vertical)!=1:return partial
    a=horizontal[0];b=vertical[0];center=[a[0]+a[2]/2,a[1]+a[3]/2]
    if math.dist(center,[b[0]+b[2]/2,b[1]+b[3]/2])>.5 or abs(a[3]-b[2])>.5:
        raise StructureContractError('等宽垂直矩形必须在共同中心相交',{'geometry_ids':p.ids,'frames_mm':frames})
    for pattern,actual in [(r'总宽',a[2]),(r'总高',b[3]),(r'(?:臂宽|水平与竖直两臂宽度均)',a[3])]:
        if not p.consume(pattern+r'\s*('+N+r')\s*'+UNIT,lambda m,actual=actual:abs(actual-float(m[1])*FACTORS[m[2].lower()])<=.5,pattern):return partial
    if not p.point('中心',center):return partial
    return p.finish(r'由两条等宽矩形垂直交叉组成|十字形|生成|创建|绘制|画出|画|请|一个')


def _diameter_source(source,gs,*,evidence_context=None):
    from .cad_geometry_measurements import measured,circle_facts
    partial={'status':'not_checked','coverage':'partial','checks':[]};p=_SourceProof(source,gs)
    circles=[g for g in gs if g.get('type')=='circle'];lines=[g for g in gs if g.get('type')=='line']
    if len(gs)!=2 or len(circles)!=1 or len(lines)!=1:return partial
    circle=measured(circle_facts,circles[0],evidence_context=evidence_context);center=circle['center_mm'];r=circle['radius_mm']
    ends=[(lines[0][k]['x'],lines[0][k]['y']) for k in ('start','end')]
    if max(abs(math.dist(e,center)-r) for e in ends)>.5 or math.dist([(ends[0][i]+ends[1][i])/2 for i in range(2)],center)>.5:
        raise StructureContractError('贯穿斜线须为该圆的实际直径',{'geometry_ids':p.ids,'center_mm':center,'endpoints_mm':ends})
    angle=math.degrees(math.atan2(ends[1][1]-ends[0][1],ends[1][0]-ends[0][0]))%180
    if not p.consume(r'(?:圆)?半径\s*('+N+r')\s*'+UNIT,lambda m:abs(r-float(m[1])*FACTORS[m[2].lower()])<=.5,'radius'):return partial
    if not p.consume(r'(?:直径斜线方向)?('+N+r')\s*度',lambda m:abs((angle-float(m[1])+90)%180-90)<=.05,'diameter_angle'):return partial
    if not p.point('圆心',center):return partial
    return p.finish(r'禁止标志|中间一条|斜线贯穿|生成|创建|绘制|画出|画|请|一个')


def _face_source(source,gs,*,evidence_context=None):
    from .cad_source_acceptance import verify_scoped_primitives
    from .cad_geometry_measurements import measured,arc_facts
    partial={'status':'not_checked','coverage':'partial','checks':[]};p=_SourceProof(source,gs)
    scoped=(verify_scoped_primitives(source,gs,evidence_context=evidence_context) if evidence_context is None else
            evidence_context.measure(verify_scoped_primitives,source,gs,evidence_context=evidence_context))
    bindings={c['subject']:c['geometry_ids'][0] for c in scoped['checks']}
    if (set(bindings)!={'外圆','左眼','右眼','嘴巴'} or len(gs)!=4 or scoped['unverified_geometry_ids']
            or any(c['source_requirement'].get('unconsumed_text') for c in scoped['checks'])):return partial
    by_id={g['id']:g for g in gs};outer,left,right,mouth=[by_id[bindings[n]] for n in ['外圆','左眼','右眼','嘴巴']]
    roles=nested_circle_roles(gs)
    if not roles or roles['外圆']['id']!=outer['id']:return partial
    cx,cy=outer['center']['x'],outer['center']['y'];R=outer['radius']
    if not (left['center']['x']<cx<right['center']['x'] and left['center']['y']>cy and right['center']['y']>cy
            and abs(left['radius']-right['radius'])<=.5
            and math.dist([left['center']['x']+right['center']['x'],left['center']['y']-right['center']['y']],[2*cx,0])<=.5):return partial
    arc=measured(arc_facts,mouth,evidence_context=evidence_context)
    middle=math.radians(mouth['start_angle']+arc['sweep_degrees']/2)
    mx=mouth['center']['x']+mouth['radius']*math.cos(middle);my=mouth['center']['y']+mouth['radius']*math.sin(middle)
    if not (0<arc['sweep_degrees']<=180 and my<min(q[1] for q in arc['endpoints_mm']) and my<cy
            and math.dist([mx,my],[cx,cy])<R):return partial
    for check in scoped['checks']:p.rest=p.rest.replace(check['source_requirement']['evidence'],' ')
    if not p.consume(r'圆半径\s*('+N+r')\s*'+UNIT,lambda m:abs(R-float(m[1])*FACTORS[m[2].lower()])<=.5,'face_outer_radius'):return partial
    result=p.finish(r'笑脸图案|两个圆点眼睛|一个圆弧嘴巴|生成|创建|绘制|画出|画|请|一个')
    result['checks']=scoped['checks']+result['checks']
    return result
