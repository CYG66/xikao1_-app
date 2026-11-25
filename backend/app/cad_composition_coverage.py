"""Connect existing composition measurements to fully consumed source text.

No coordinates are generated and no model plan or label is used as proof.
Unrecognized requirements keep partial coverage even when known checks pass.
"""
from .cad_length_units import length_factors
import math
import re


def verify_composition_coverage(source, geometries, *, evidence_context=None):
    from .cad_source_acceptance import source_texts
    from .cad_structure_contract import explicit_composition, validate_explicit_composition, _frame, _points, _corners
    text='\n'.join(source_texts(source))
    contract=explicit_composition(text)
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    if contract and contract['kind']=='named_components':
        return _verify_named_coverage(source,geometries,contract,evidence_context=evidence_context)
    if not contract or contract['kind'] not in {'corner_placement','rectangular_array','component_count'}:
        return partial
    kind=contract['kind']
    number=r'\d+(?:\.\d+)?'
    unit=r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'
    factors=length_factors('m')
    values={};evidence=[];rest=text
    labels={'宽':'width_m','宽度':'width_m','高':'height_m','高度':'height_m',
            '半径':'radius_m','行距':'row_pitch_m','列距':'column_pitch_m',
            '圆心距离':'center_distance_m','圆心相距':'center_distance_m'}
    scalar=r'(?:相邻中心(?=行距|列距))?(圆心距离|圆心相距|宽度|高度|半径|行距|列距|宽|高)(?:均为|均|都为|都|为|是|改为)?\s*('+number+r')\s*'+unit
    for match in re.finditer(scalar,text,re.I):
        value=float(match[2])*factors[match[3].lower()]
        if not math.isfinite(value) or value<=0:
            return partial
        key=labels[match[1]]
        if key in values and abs(values[key]-value)>1e-9:
            return partial
        values[key]=value
        evidence.append(match[0])
    rest=re.sub(scalar,' ',rest,flags=re.I)
    if kind=='corner_placement':
        rest=re.sub(r'在(?:四|4)个角各(?:放置|放|画|绘制)(?:一|1)个\s*的?圆',' ',rest)
        rest=re.sub(r'圆心分别位于矩形(?:四|4)个顶点',' ',rest)
        rest=re.sub(r'(?:四|4)个圆',' ',rest)
        rest=re.sub(r'(?:生成|创建|绘制|画出|画)?(?:一|1)?个?矩形',' ',rest)
        required={'width_m','height_m','radius_m'}
    elif kind=='rectangular_array':
        inventories=re.findall(r'(\d+)\s*行\s*(\d+)\s*列',rest)
        if not inventories or any((int(a),int(b))!=(contract['rows'],contract['columns']) for a,b in inventories):
            return partial
        rest=re.sub(r'(?:生成|创建|绘制|画出|画)?\d+\s*行\s*\d+\s*列(?:(?:的)?矩形阵列)?',' ',rest)
        rest=re.sub(r'每个矩形|各矩形',' ',rest)
        required={'width_m','height_m','row_pitch_m','column_pitch_m'}
    else:
        if set(contract['counts'])!={'circle'}:
            return partial
        counts=re.findall(r'(两个|两|二|[2-9]\d*)个?\s*(?:相交的?|相同的?|等大的?)?圆',rest)
        if not counts or any((2 if n in {'两个','两','二'} else int(n))!=contract['counts']['circle'] for n in counts):
            return partial
        if re.search(r'相同|等大',text):
            return partial
        rest=re.sub(r'(?:生成|创建|绘制|画出|画)?(?:两个|两|二|[2-9]\d*)个?\s*(?:相交的?|相同的?|等大的?)?圆',' ',rest)
        required=set(values)
        if not required or not required<={'radius_m','center_distance_m'}:
            return partial
        if (contract.get('intersecting') or 'center_distance_m' in values) and contract['counts']['circle']!=2:
            return partial
    if rest.strip(' \t\r\n，,、。；;') or not required<=values.keys():
        return partial
    # Every consumed scalar must be covered by the existing measurement,
    # including later source revisions; do not silently accept stale values.
    dimensions=contract.get('dimensions') or {}
    if any(key not in dimensions or abs(value-dimensions[key])>1e-9 for key,value in values.items()):
        return partial
    measured=validate_explicit_composition(contract,geometries)
    if not measured or measured['status']!='passed':
        return partial
    checks=[{'field':'component_counts_and_types','status':'passed',
             'expected':contract['counts'],'actual':measured['observed_counts']}]
    rectangles=[g for g in geometries if _frame(g) is not None]
    circles=[g for g in geometries if g.get('type')=='circle']
    for field,value in values.items():
        actual=None
        if field in {'width_m','height_m'}:
            actual=[_frame(g)[2 if field=='width_m' else 3] for g in rectangles]
        elif field=='radius_m':actual=[g['radius'] for g in circles]
        elif field=='center_distance_m' and len(circles)==2:
            actual=[math.dist([circles[0]['center']['x'],circles[0]['center']['y']],
                              [circles[1]['center']['x'],circles[1]['center']['y']])]
        if actual is not None:
            checks.append({'field':field,'status':'passed','expected_mm':value*1000,'actual_mm':actual})
    if kind=='corner_placement':
        checks.append({'field':'corner_center_bijection','status':'passed',
            'rectangle_vertices_mm':_corners(_points(rectangles[0])),
            'circle_centers_mm':[[g['center']['x'],g['center']['y']] for g in circles]})
    elif kind=='rectangular_array':
        checks.append({'field':'array_grid_and_pitch','status':'passed',
            'rows':contract['rows'],'columns':contract['columns'],
            'row_pitch_mm':values['row_pitch_m']*1000,'column_pitch_mm':values['column_pitch_m']*1000,
            'measured_frames_mm':[_frame(g) for g in rectangles]})
    if contract.get('intersecting'):
        checks.append({'field':'circle_intersection','status':'passed'})
    return {'status':'passed','coverage':'complete','checks':checks,
            'source_evidence':text,'scalar_evidence':evidence,
            'authority':'backend_measured_geometry',
            'measurement_scope':'fully_consumed_existing_composition_contract'}


def _verify_named_coverage(source,geometries,contract,*,evidence_context=None):
    """Consume only clauses backed by existing component shape measurements."""
    from .cad_source_acceptance import source_texts, verify_final_source_contract, N
    from .cad_structure_contract import validate_explicit_composition
    from .cad_construction import construction_geometry_bounds
    from .cad_geometry_measurements import measured,polygon_circumcircle
    text='\n'.join(source_texts(source));rest=text
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    names=contract['names']
    # Existing positional shape proofs cover these families only; labels
    # cannot establish the identity of arbitrary named components.
    if (not contract['left_to_right'] or len(names)!=2
            or any(n not in {'爱心','心形','五角星'} for n in names)):
        return partial
    unit=r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'
    size=r'(?:外接圆半径|宽度|高度|宽|高)(?:为|是)?\s*'+N+r'\s*'+unit
    if any(not contract.get('component_dimensions',{}).get(n) for n in names):return partial
    for i,name in enumerate(names):
        rest=rest.replace(name+('在左' if i==0 else '在右'),' ')
    rest=re.sub(size,' ',rest,flags=re.I)
    bounds=[measured(construction_geometry_bounds,[g],evidence_context=evidence_context) for g in geometries]
    ordered=sorted(zip(geometries,bounds),key=lambda item:item[1]['min_x'])
    if len(ordered)!=len(names):return partial
    extra_checks=[]
    tips=list(re.finditer(r'(?:固定为)?(\d+)个(?:外)?尖角(?:且尖角朝上)?',rest))
    top='尖角朝上' in rest
    if tips or top:
        stars=[(g,b) for name,(g,b) in zip(names,ordered) if name=='五角星']
        if len(stars)!=1 or any(int(m[1])!=5 for m in tips):return partial
        g,b=stars[0]
        circle=measured(polygon_circumcircle,g,evidence_context=evidence_context)
        if circle is None:return partial
        if top and not any(abs(p['x']-circle['center_mm'][0])<=.5
                           and abs(p['y']-circle['center_mm'][1]-circle['radius_mm'])<=.5
                           for p in g['vertices']):return partial
        extra_checks.append({'field':'declared_outer_tips_and_direction','status':'passed',
                             'count':5,'upward':top,'geometry_ids':[g['id']]})
        rest=re.sub(r'(?:固定为)?\d+个(?:外)?尖角(?:且尖角朝上)?|尖角朝上',' ',rest)
    spacing=r'两者(?:几何)?中心水平相距\s*('+N+r')\s*'+unit
    distances=list(re.finditer(spacing,rest,re.I))
    if not distances or contract.get('gap_reference')!='center':return partial
    centers=[((b['min_x']+b['max_x'])/2,(b['min_y']+b['max_y'])/2) for _,b in ordered]
    factors=length_factors('mm')
    dx=centers[1][0]-centers[0][0];dy=centers[1][1]-centers[0][1]
    if abs(dy)>.5 or any(abs(dx-float(m[1])*factors[m[2].lower()])>.5 for m in distances):return partial
    rest=re.sub(spacing,' ',rest,flags=re.I)
    rest=re.sub(r'坐标单位(?:为|是)?\s*'+unit,' ',rest,flags=re.I)
    for name in names:rest=rest.replace(name,' ')
    rest=re.sub(r'生成|创建|绘制|画出|画|请|一个|轮廓|和|的',' ',rest)
    if rest.strip(' \t\r\n，,、。；;：:'):
        return {**partial,'unconsumed_text':rest.strip()}
    validation=(validate_explicit_composition(contract,geometries) if evidence_context is None else
                evidence_context.measure(validate_explicit_composition,contract,geometries,evidence_context=evidence_context))
    if validation.get('status')!='passed':return partial
    # Shapes are measured in positional order, not inferred from model labels.
    bindings=[{'label':name,'geometry_refs':[g['id']]} for name,(g,_) in zip(names,ordered)]
    scalar=(verify_final_source_contract(source,geometries,bindings) if evidence_context is None else
            evidence_context.measure(verify_final_source_contract,source,geometries,bindings,evidence_context=evidence_context))
    if scalar.get('unknown_requirements'):return partial
    return {'status':'passed','coverage':'complete','authority':'backend_measured_geometry',
            'source_evidence':source_texts(source),'checks':[*scalar['checks'],*extra_checks,
                {'field':'named_component_shapes_and_horizontal_layout','status':'passed',
                 'component_names':names,'centers_mm':centers,'horizontal_distance_mm':dx}],
            'measurement_scope':'fully_consumed_existing_named_composition_contract'}
