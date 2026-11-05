"""Nominal main court line paths, in millimetres; no paint-edge compensation.

Basketball basis: FIBA Official Basketball Rules 2024, article 2.
Badminton basis: Sport England Badminton Design Guidance, December 2011 fig.1.
These are main in-court markings, not a certified venue/equipment layout.
"""
import math


def template_profile(plan):
    specifications = []
    for step in plan.steps:
        if getattr(step, 'op', '') != 'add_template':
            continue
        for match in step.matches:
            if match.template not in {'basketball','badminton'}:
                continue
            width, height = (28.,15.) if match.template=='basketball' else (13.4,6.1)
            specifications.append({'template':match.template,
                'reference':'FIBA 2024 article 2' if match.template=='basketball' else 'Sport England Badminton Design Guide 2011 figure 1',
                'nominal_line_width_mm':50 if match.template=='basketball' else 40,
                'standard_dimensions':math.isclose(match.width_m or width,width) and math.isclose(match.height_m or height,height),
                'scope':'main_in_court_linework', 'paint_edge_compensation':False,
                'excluded':['external_venue_markings','equipment','certification'] +
                    (['rebound_place_ticks','throw_in_marks','dashed_free_throw_back_half'] if match.template=='basketball' else [])})
    return specifications


def court_geometries(template, width, height):
    base_width, base_height = (28., 15.) if template == 'basketball' else (13.4, 6.1)
    sx, sy = width/base_width, height/base_height
    result = []

    def point(x, y):
        return {'x': x*sx*1000, 'y': y*sy*1000, 'z': 0.}

    def add(kind, **values):
        result.append({'id':len(result)+1, 'type':kind, 'layer_id':1, **values})

    def line(a, b):
        add('line', start=point(*a), end=point(*b))

    def curve(center, radius, start=0, end=360):
        full = end-start == 360
        if math.isclose(sx, sy):
            values = {'center':point(*center), 'radius':radius*sx*1000}
            if not full:
                values.update(start_angle=start, end_angle=end)
            add('circle' if full else 'arc', **values)
        else:
            # An explicit non-standard affine fit must not distort circle joins.
            if not full:
                count = max(2, math.ceil(abs(end-start)/.5))
                add('polyline', vertices=[point(center[0]+radius*math.cos(math.radians(start+(end-start)*i/count)),
                    center[1]+radius*math.sin(math.radians(start+(end-start)*i/count)))
                    for i in range(count+1)], closed=False)
                return
            vertical = sy > sx
            add('ellipse', center=point(*center),
                major_axis={'x':0. if vertical else radius*sx*1000,
                            'y':radius*sy*1000 if vertical else 0., 'z':0.},
                ratio=min(sx,sy)/max(sx,sy),
                start_angle=start-(90 if vertical else 0),
                end_angle=end-(90 if vertical else 0))

    x, y = base_width/2, base_height/2
    add('polyline', vertices=[point(-x,-y),point(x,-y),point(x,y),point(-x,y)], closed=True)
    if template == 'badminton':
        # Net position is a reference, not a painted transverse floor line.
        for side in (-1, 1):
            line((-x,side*2.59),(x,side*2.59))
            line((side*1.98,-y),(side*1.98,y))
            line((side*(x-.76),-y),(side*(x-.76),y))
            line((side*1.98,0),(side*x,0))
        return result

    line((0,-y),(0,y))
    curve((0,0),1.8)
    theta = math.degrees(math.asin(6.6/6.75))
    joint = -12.425 + math.sqrt(6.75**2-6.6**2)
    for side in (-1, 1):
        # Reflect a complete left half by a 180 degree rotation.
        def p(a,b):
            return (a*(-side),b*(-side))
        shift = 0 if side == -1 else 180
        add('polyline', vertices=[point(*p(-14,-2.45)),point(*p(-8.2,-2.45)),
            point(*p(-8.2,2.45)),point(*p(-14,2.45))],closed=False)
        curve(p(-8.2,0),1.8,-90+shift,90+shift)
        for v in (-6.6,6.6):
            line(p(-14,v),p(joint,v))
        curve(p(-12.425,0),6.75,-theta+shift,theta+shift)
        curve(p(-12.425,0),1.3,-90+shift,90+shift)
        for v in (-1.3,1.3):
            line(p(-12.8,v),p(-12.425,v))
    return result
