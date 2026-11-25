"""Resolve a two-valued arc traversal from source-required tangent joints."""
import math
import re


def resolve_tangent_arc_directions(step,source):
    from .cad_source_acceptance import source_texts,N
    from .cad_construction import (CompositeArcSegment,CompositeLineSegment,ConstructionPoint,
        _segment_start,_segment_end,_segment_tangent,_vector_angle_degrees)
    text='\n'.join(source_texts(source))
    if not re.search(r'相切|切向连续|平滑',text) or re.search(r'不相切|不平滑|不切向连续|(?:不要|不要求|无需|不必).{0,4}(?:相切|平滑|切向连续)',text):return []
    # An explicitly declared object-axis rotation is not arc traversal. All
    # other source winding declarations remain authoritative and disable this.
    text=re.sub(r'长轴相对(?:世界)?x轴(?:正向)?(?:逆时针|顺时针)(?:转)?\s*'+N+r'\s*度',' ',text,re.I)
    if re.search(r'顺时针|逆时针|clockwise',text,re.I):return []
    if re.search(r'起始角|终止角|起点|终点|从\s*'+N+r'\s*度\s*(?:到|至)',text):return []
    if step.get('op')!='add_composite_path':return []
    segments=step.get('segments') or [];changes=[]
    gap_tolerance=ConstructionPoint.model_validate({'x':step.get('connection_tolerance',1e-6),'y':0}).x
    angle_tolerance=min(.01,ConstructionPoint.model_validate({'x':step.get('tangent_tolerance_deg',1),'y':0}).x)
    for i,raw in enumerate(segments):
        if raw.get('kind')!='arc':continue
        if (i==0 or i==len(segments)-1) and not step.get('closed'):continue
        previous,following=segments[i-1],segments[(i+1)%len(segments)]
        if previous.get('kind')!='line' or following.get('kind')!='line':continue
        left,right=CompositeLineSegment.model_validate(previous),CompositeLineSegment.model_validate(following)
        candidates=[]
        for swap in (False,True):
            angles={'start_angle':raw['end_angle'],'end_angle':raw['start_angle']} if swap else {}
            for flag in (False,True):
                arc=CompositeArcSegment.model_validate({**raw,**angles,'clockwise':flag})
                if math.isclose(arc.start_angle,arc.end_angle,abs_tol=1e-12):continue
                a,b=_segment_start(arc),_segment_end(arc)
                if math.hypot(a.x-left.end.x,a.y-left.end.y)>gap_tolerance or math.hypot(b.x-right.start.x,b.y-right.start.y)>gap_tolerance:continue
                errors=[_vector_angle_degrees(_segment_tangent(left,at_end=True),_segment_tangent(arc,at_end=False)),
                        _vector_angle_degrees(_segment_tangent(arc,at_end=True),_segment_tangent(right,at_end=False))]
                if max(errors)<=angle_tolerance:candidates.append((flag,swap,errors))
        if not candidates:
            # Line endpoints are existing geometric evidence. If both lie on
            # the unchanged circle, they determine the arc angles; only its
            # traversal remains two-valued. Never move endpoints onto a circle.
            arc=CompositeArcSegment.model_validate(raw)
            points=[left.end,right.start]
            if all(abs(math.hypot(p.x-arc.center.x,p.y-arc.center.y)-arc.radius)<=gap_tolerance for p in points):
                angles=[math.degrees(math.atan2(p.y-arc.center.y,p.x-arc.center.x)) for p in points]
                solutions=[]
                if math.dist((points[0].x,points[0].y),(points[1].x,points[1].y))>gap_tolerance:
                    for flag in (False,True):
                        proposed=CompositeArcSegment.model_validate({**raw,'start_angle':angles[0],'end_angle':angles[1],'clockwise':flag})
                        errors=[_vector_angle_degrees(_segment_tangent(left,at_end=True),_segment_tangent(proposed,at_end=False)),
                                _vector_angle_degrees(_segment_tangent(proposed,at_end=True),_segment_tangent(right,at_end=False))]
                        if max(errors)<=angle_tolerance:solutions.append((flag,errors))
                if len(solutions)==1:
                    before={k:raw.get(k) for k in ('start_angle','end_angle','clockwise')}
                    raw.update(start_angle=angles[0],end_angle=angles[1],clockwise=solutions[0][0])
                    changes.append({'kind':'resolve_source_tangent_arc_angles','step_id':step.get('step_id'),
                        'segment_index':i,'from':before,'to':{k:raw[k] for k in before},
                        'tangent_errors_deg':solutions[0][1],
                        'centers_radii_and_line_endpoints_preserved':True})
        if len(candidates)==1 and (bool(raw.get('clockwise',False))!=candidates[0][0] or candidates[0][1]):
            old=bool(raw.get('clockwise',False));raw['clockwise']=candidates[0][0]
            if candidates[0][1]:raw['start_angle'],raw['end_angle']=raw['end_angle'],raw['start_angle']
            changes.append({'kind':'resolve_source_tangent_arc_direction','step_id':step.get('step_id'),
                'segment_index':i,'from':old,'to':raw['clockwise'],'endpoint_roles_reversed':candidates[0][1],
                'tangent_errors_deg':candidates[0][2],'centers_radii_and_endpoint_set_preserved':True})
    return changes
