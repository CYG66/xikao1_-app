"""Read-only stadium boundary measurement and fully scoped source proof."""
import math
import re

from .cad_precision import ACCEPTANCE_MM
from .cad_source_acceptance import N, P, source_texts
from .cad_length_units import length_factors


def measure_capsule(geometries):
    from .cad_path_relation_acceptance import assemble_closed_boundary
    from .cad_structure_contract import StructureContractError
    try:polygon=assemble_closed_boundary(geometries)
    except StructureContractError as exc:return {'passed':False,'reason':str(exc)}
    corners=list(polygon.minimum_rotated_rectangle.exterior.coords)[:4]
    vectors=[(corners[(i+1)%4][0]-p[0],corners[(i+1)%4][1]-p[1]) for i,p in enumerate(corners)]
    sizes=[math.hypot(*v) for v in vectors];index=max(range(4),key=lambda i:sizes[i])
    length=sizes[index];height=min(sizes);radius=height/2
    if height<=ACCEPTANCE_MM or length-height<=ACCEPTANCE_MM:
        return {'passed':False,'reason':'degenerate_or_ambiguous_long_axis'}
    u=[v/length for v in vectors[index]];center=[sum(p[k] for p in corners)/4 for k in (0,1)]
    half_spine=(length-height)/2
    def residual(p):
        x,y=p[0]-center[0],p[1]-center[1]
        axial=x*u[0]+y*u[1];normal=-x*u[1]+y*u[0]
        return abs(math.hypot(max(abs(axial)-half_spine,0),normal)-radius)
    # Check edge interiors, not just points on a theoretical circular end.
    boundary=list(polygon.exterior.coords)
    maximum=max(residual((a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t))
                for a,b in zip(boundary,boundary[1:]) for t in (0,.25,.5,.75,1))
    # Convexity plus boundary identity rules out missing arcs/interior detours.
    area_gap=polygon.convex_hull.area-polygon.area
    return {'passed':maximum<=ACCEPTANCE_MM and area_gap<=ACCEPTANCE_MM*polygon.length,
            'length_mm':length,'height_mm':height,'radius_mm':radius,'center_mm':center,
            'axis_deg':math.degrees(math.atan2(u[1],u[0]))%180,
            'maximum_boundary_residual_mm':maximum,'tolerance_mm':ACCEPTANCE_MM,
            'geometry_ids':[g['id'] for g in geometries]}


def has_local_axis_dimensions(text):
    text='\n'.join(source_texts(text))
    return bool(re.search(r'沿(?:局部)?长轴|局部(?:长轴|短轴|坐标|宽|高)|长轴相对',text))


def capsule_source_requirements(source):
    """Parse the same source contract for planning guidance and measurement."""
    from .cad_source_intent import partition_preview_intent
    text='\n'.join(source_texts(source));rest,intents=partition_preview_intent(text)
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    if '胶囊' not in rest:return partial
    factors=length_factors('mm');unit=r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'
    requirements=[]
    for label,field in [(r'总长','length_mm'),(r'总高','height_mm'),(r'半径','radius_mm')]:
        pattern=label+r'(?:为|是)?\s*('+N+r')\s*'+unit
        for m in re.finditer(pattern,rest,re.I):requirements.append((field,float(m[1])*factors[m[2].lower()],m[0]))
        rest=re.sub(pattern,' ',rest,flags=re.I)
    if not {'length_mm','height_mm'}<={r[0] for r in requirements}:return partial
    centers=list(re.finditer(r'(?:局部)?中心(?:位于|在)?\s*'+P,rest))
    units=re.findall(r'坐标单位(?:为|是)?\s*'+unit,rest,re.I)
    if len(centers)!=1 or not units or len(set(u.lower() for u in units))!=1:return partial
    center=[float(v)*factors[units[0].lower()] for v in centers[0].groups()]
    requirements.append(('center_mm',center,centers[0][0]))
    rest=re.sub(r'(?:局部)?中心(?:位于|在)?\s*'+P,' ',rest)
    angles=list(re.finditer(r'长轴相对(?:世界)?x轴(?:正向)?逆时针(?:转)?\s*('+N+r')\s*度',rest,re.I))
    if len(angles)>1:return partial
    if angles:
        requirements.append(('axis_deg',float(angles[0][1]),angles[0][0]))
        rest=re.sub(r'长轴相对(?:世界)?x轴(?:正向)?逆时针(?:转)?\s*'+N+r'\s*度',' ',rest,flags=re.I)
    if '水平' in rest:requirements.append(('axis_deg',0,'水平'))
    elif not angles:return partial  # do not invent an orientation convention
    rest=re.sub(r'坐标单位(?:为|是)?\s*'+unit,' ',rest,flags=re.I)
    phrases=['左右两端是半径相等的向外半圆','上下两条直边平行并与半圆相切','总长包含两端半圆',
        '不画整圆和内部线','两端各为向外半圆','两条直边与半圆相切','两端半径相同','总长含半圆',
        '不添加内部线','沿局部长轴','沿长轴','短轴','局部']
    for phrase in phrases:rest=rest.replace(phrase,' ')
    rest=re.sub(r'画|绘制|一个|水平|胶囊形|闭合|外轮廓|外边界|边界|轮廓',' ',rest)
    if rest.strip(' \t\n，,、。；;'):
        return {**partial,'unconsumed_text':rest.strip()}
    return {'status':'parsed','coverage':'complete','requirements':requirements,'intent_evidence':intents}


def verify_capsule_source(source,geometries,*,evidence_context=None):
    from .cad_geometry_measurements import measured
    from .cad_structure_contract import StructureContractError
    parsed=capsule_source_requirements(source)
    if parsed['coverage']!='complete':return parsed
    requirements=parsed['requirements'];intents=parsed['intent_evidence']
    facts=measured(measure_capsule,geometries,evidence_context=evidence_context)
    if not facts['passed']:
        raise StructureContractError('闭合边界未通过胶囊相切轮廓实测',facts)
    checks=[]
    for field,expected,quote in requirements:
        actual=facts[field]
        error=(math.dist(actual,expected) if isinstance(expected,list) else
               abs((actual-expected+90)%180-90) if field=='axis_deg' else abs(actual-expected))
        checks.append({'field':field,'actual':actual,'expected':expected,'source_evidence':quote,
                       'status':'passed' if error<=(.01 if field=='axis_deg' else ACCEPTANCE_MM) else 'failed',
                       'geometry_ids':facts['geometry_ids']})
    report={'checks':checks,'measurements':facts,'geometry_ids':facts['geometry_ids'],
            'source_evidence':source_texts(source),'intent_evidence':intents,'authority':'backend_measured_geometry'}
    if any(c['status']=='failed' for c in checks):raise StructureContractError('胶囊局部尺寸、中心或轴向不符合来源要求',report)
    return {**report,'status':'passed','coverage':'complete'}
