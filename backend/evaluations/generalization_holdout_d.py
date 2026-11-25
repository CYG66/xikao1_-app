"""New internal parameter/language holdout after production freeze."""
import hashlib
import math
from scripts.local_dev import ROOT
from evaluations import generalization_holdout_b as batch
from evaluations import production_contract_pilot as base

FREEZE=ROOT/'.local-dev/generalization-d-freeze-vszv2yie'


def cases():
    points=[{'x':260,'y':-830}]
    for length,angle in [(1370,-23),(690,34),(1040,-12)]:
        p=points[-1];a=math.radians(angle)
        points.append({'x':p['x']+length*math.cos(a),'y':p['y']+length*math.sin(a)})
    return [
        {'id':'W1','family':'explicit_geometry','category':'diameter_paraphrase',
         'expected':[{'type':'circle','center':{'x':-910,'y':1370},'radius':685}],
         'text':'画圆：圆心(-0.91,1.37)，直径1.37米。仅保留圆形外边界，不加任何标注。坐标单位米。'},
        {'id':'W2','family':'explicit_geometry','category':'concentric_transfer',
         'expected':[{'type':'circle','center':{'x':-470,'y':920},'radius':r} for r in (1190,455)],
         'text':'绘制两个同心圆，共享圆心(-47,92)，内圆半径45.5厘米，外圆半径119厘米。只保留内外两个圆的轮廓，不要尺寸标注。坐标单位厘米。'},
        {'id':'W3','family':'explicit_geometry','category':'six_vertex_transfer',
         'expected':[{'type':'polyline','closed':True,'vertices':[{'x':x,'y':y} for x,y in [(-510,-170),(430,-310),(1260,290),(1110,1060),(190,1540),(-680,790)]]}],
         'text':'按顺序连接顶点(-51,-17)、(43,-31)、(126,29)、(111,106)、(19,154)、(-68,79)，最后连接回第一个顶点，形成一个闭合六边形。坐标单位厘米。'},
        {'id':'W4','family':'explicit_geometry','category':'walk_transfer',
         'expected':[{'type':'polyline','closed':False,'vertices':points}],
         'text':'从(26,-83)出发画折线，先沿与x轴正向成-23度的方向走1.37米，再向左转57度接着画690毫米，再向右转46度接着画104厘米。三段依次连接，末端不连回起点，不加其他图形。坐标单位厘米。'},
        {'id':'W5','family':'semicircle_walls','category':'arch_transfer','unit':'厘米',
         'origin':[-84,39],'width':298,'height':437,'angle':0,
         'text':'画一个闭合半圆拱门，整体宽298厘米，从底边到拱顶的整体高437厘米。水平底边左端为(-84,39)；左右两段直墙竖直且等高，顶上用直径298厘米的上半圆连接，整体高度包含这段半圆。不要内部线。坐标单位厘米。'},
        {'id':'W6','family':'capsule_tangency','category':'rotated_capsule_transfer','unit':'毫米',
         'origin':[830,-1170],'length':5790,'height':1420,'angle':102,
         'text':'绘制胶囊形闭合边界，中心位于(830,-1170)，长轴相对x轴正向逆时针102度，沿长轴总长5790毫米、短轴总高1420毫米。两端各为向外半圆，两条直边与半圆相切；两端半径相同，总长含半圆。不添加内部线，坐标单位毫米。'},
    ]


def main():
    original_dump=base.dump
    def dump(path,value):
        if path.name=='holdout-manifest.json':
            value={**value,'scope':'New W1-W6 developer-authored internal holdout after source freeze; limited existing families, not third-party blind testing.'}
            for name in ['evaluations/generalization_holdout_d.py','docs/GENERALIZATION_D_PROTOCOL_20261125.md']:
                value['hashes'][name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        original_dump(path,value)
    base.dump=dump;batch.FREEZE=FREEZE;batch.cases=cases
    batch.main()


if __name__=='__main__':main()
