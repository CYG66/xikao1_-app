"""Predeclared new pilot cases. Oracle specifications never enter model input."""
import math


def cases():
    rows=[]
    for i,(unit,origin,length,angle,radius,sweep) in enumerate([
        ('米',[.37,-.62],2.35,37,.83,123),
        ('厘米',[-43,72],187,-28,64,97),
        ('毫米',[315,-425],1637,63,573,109),
    ],1):
        rows.append({'id':f'J{i}','family':'line_arc_joint','unit':unit,'origin':origin,'length':length,'angle':angle,'radius':radius,'sweep':sweep,
            'text':f'坐标单位为{unit}。从({origin[0]},{origin[1]})画长度{length}{unit}的直线，与x轴正向夹角{angle}度。以直线末点为圆弧起点，圆心在该点正左方{radius}{unit}，半径{radius}{unit}，从起点逆时针扫过{sweep}度。只画相接的这条直线与圆弧，保持开放，不增加其他图形。'})
    for i,(unit,origin,width,height,angle) in enumerate([
        ('米',[.73,-1.21],3.4,4.7,0),
        ('厘米',[-65,43],246,318,19),
        ('毫米',[375,-285],1830,2575,-31),
    ],1):
        rows.append({'id':f'H{i}','family':'semicircle_walls','unit':unit,'origin':origin,'width':width,'height':height,'angle':angle,
            'text':f'坐标单位为{unit}。建立局部坐标系，局部原点位于世界坐标({origin[0]},{origin[1]})，局部x轴相对世界x轴逆时针转{angle}度。画闭合拱门边界：局部底边左端为局部原点，宽{width}{unit}、总高{height}{unit}；上方是连接两侧竖墙的上半圆，半圆直径等于宽度，左右直墙等高，总高含半圆。只画两侧墙、半圆顶和闭合底边，无内部线。宽高均沿局部轴测量。'})
    for i,(unit,origin,length,height,angle) in enumerate([
        ('米',[-.81,.46],5.7,1.46,23),
        ('厘米',[37,-58],483,127,-17),
        ('毫米',[-425,315],3765,1135,41),
    ],1):
        rows.append({'id':f'R{i}','family':'capsule_tangency','unit':unit,'origin':origin,'length':length,'height':height,'angle':angle,
            'text':f'坐标单位为{unit}。画一个闭合胶囊形外边界，局部中心在世界坐标({origin[0]},{origin[1]})，长轴相对世界x轴逆时针转{angle}度。沿局部长轴总长{length}{unit}，短轴总高{height}{unit}。左右两端各一个向外的半圆，两条平行直边与两端半圆相切连接；两端半圆半径相同，总长包含两个半圆。只画一条闭合外边界，不画完整圆或内部线。'})
    for i,(unit,origin,a,b,angle,turn) in enumerate([
        ('米',[.29,-.71],2.73,1.37,29,67),
        ('厘米',[-52,41],237,163,-36,113),
        ('毫米',[245,-365],1723,937,51,-74),
    ],1):
        rows.append({'id':f'P{i}','family':'relative_turn_polyline','unit':unit,'origin':origin,'a':a,'b':b,'angle':angle,'turn':turn,
            'text':f'坐标单位为{unit}。只画两段首尾相接的开放折线：起点({origin[0]},{origin[1]})，第一段长{a}{unit}，相对x轴正向角为{angle}度；第二段长{b}{unit}，从第一段末点出发，方向在第一段方向基础上再逆时针转{turn}度。不要闭合，不添加尺寸线或其他图形。'})
    return rows


def expected_entities(row):
    """Analytic test oracle only; never imported by the relation compiler."""
    factor={'米':1000,'厘米':10,'毫米':1}[row['unit']]
    ox,oy=[v*factor for v in row['origin']];angle=math.radians(row['angle'])
    def world(x,y):return {'x':ox+x*math.cos(angle)-y*math.sin(angle),'y':oy+x*math.sin(angle)+y*math.cos(angle)}
    def line(a,b):return {'type':'line','start':world(*a),'end':world(*b)}
    def arc(cx,cy,r,start,end):return {'type':'arc','center':world(cx,cy),'radius':r,'start_angle':start+row['angle'],'end_angle':end+row['angle']}
    family=row['family']
    if family=='line_arc_joint':
        length=row['length']*factor;r=row['radius']*factor
        ex=ox+length*math.cos(angle);ey=oy+length*math.sin(angle)
        entities=[{'type':'line','start':{'x':ox,'y':oy},'end':{'x':ex,'y':ey}},
                  {'type':'arc','center':{'x':ex-r,'y':ey},'radius':r,'start_angle':0,'end_angle':row['sweep']}]
    elif family=='semicircle_walls':
        w=row['width']*factor;h=row['height']*factor;r=w/2;wall=h-r
        entities=[line((0,0),(w,0)),line((w,0),(w,wall)),arc(r,wall,r,0,180),line((0,wall),(0,0))]
    elif family=='capsule_tangency':
        length=row['length']*factor;r=row['height']*factor/2;c=length/2-r
        entities=[line((-c,-r),(c,-r)),arc(c,0,r,-90,90),line((c,r),(-c,r)),arc(-c,0,r,90,270)]
    else:
        a=row['a']*factor;b=row['b']*factor;t=math.radians(row['turn'])
        entities=[line((0,0),(a,0)),line((a,0),(a+b*math.cos(t),b*math.sin(t)))]
    return [{'id':i+1,**g} for i,g in enumerate(entities)]
