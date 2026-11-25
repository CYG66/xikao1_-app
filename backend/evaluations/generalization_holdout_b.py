"""Second developer-authored holdout, frozen before corpus creation."""
from copy import deepcopy
import hashlib
import math
from pathlib import Path
from scripts.local_dev import ROOT
from evaluations import transfer_holdout_20261124 as run
from evaluations import production_contract_pilot as base
from evaluations.frozen_release_validation import holdout_oracle
from evaluations.relation_pilot.cases import expected_entities

FREEZE=ROOT/'.local-dev/generalization-b-freeze-lba2zl_z'


def cases():
    points=[{'x':-610,'y':240}]
    for length,angle in [(1450,27),(870,-25),(630,66),(1120,32)]:
        p=points[-1];a=math.radians(angle)
        points.append({'x':p['x']+length*math.cos(a),'y':p['y']+length*math.sin(a)})
    return [
        {'id':'U1','category':'paraphrase','family':'circle_control','unit':'米','origin':[2.36,-1.14],'radius':.57,
         'text':'请画一个圆，圆心(2.36,-1.14)，半径0.57米。只保留圆的外边界，不要任何标注。坐标单位米。'},
        {'id':'U2','category':'parameter_transfer','family':'capsule_tangency','unit':'米','origin':[1.27,-.94],
         'length':6.38,'height':1.26,'angle':63,
         'text':'绘制胶囊形闭合边界，中心位于(1.27,-0.94)，长轴相对x轴正向逆时针63度，沿长轴总长6.38米、短轴总高1.26米。两端各为向外半圆，两条直边与半圆相切；两端半径相同，总长含半圆。不添加内部线，坐标单位米。'},
        {'id':'U3','category':'parameter_transfer','family':'semicircle_walls','unit':'厘米','origin':[27.4,-86.2],
         'width':284,'height':413,'angle':0,
         'text':'请画一个闭合半圆拱门，总宽284厘米、总高413厘米。底边左端(27.4,-86.2)，底边水平；两侧直墙等高且竖直，顶部为上半圆，直径等于总宽，总高包含半圆。只画外边界，坐标单位厘米。'},
        {'id':'U4','category':'mixed_units_longer_chain','family':'explicit_geometry',
         'expected':[{'type':'polyline','closed':False,'vertices':points}],
         'text':'从(-61,24)出发画折线，先沿与x轴正向成27度的方向走1.45米，再向右转52度接着画870毫米，再向左转91度接着画63厘米，再向右转34度接着画1.12米。四段连在一起，末端不连回起点，不加其他图形。坐标单位厘米。'},
        {'id':'U5','category':'vertex_polygon','family':'explicit_geometry',
         'expected':[{'type':'polyline','closed':True,'vertices':[{'x':x,'y':y} for x,y in [(-140,220),(940,-160),(1510,830),(160,1210)]]}],
         'text':'生成一个闭合多边形，顶点(-140,220)(940,-160)(1510,830)(160,1210)，坐标单位毫米。'},
        {'id':'U6','category':'new_combination','family':'explicit_geometry','expected':[
             {'type':'circle','center':{'x':-1800,'y':-300},'radius':420},
             {'type':'polyline','closed':True,'vertices':[{'x':x,'y':y} for x,y in [(500,-700),(1800,-700),(1800,250),(500,250)]]},
             {'type':'line','start':{'x':-800,'y':1500},'end':{'x':1900,'y':1500}}],
         'text':'在同一张图中画三个独立图形。左圆：圆，圆心(-1800,-300)，半径420毫米，坐标单位毫米；右矩形：矩形，左下角(500,-700)，宽1300毫米，高950毫米，坐标单位毫米；上横线：线段，起点(-800,1500)，终点(1900,1500)，坐标单位毫米。不要增加连接线或标注。'},
    ]


def self_check():
    records=[]
    def shift(obj):
        if isinstance(obj,list):return [shift(v) for v in obj]
        if isinstance(obj,dict):return {k:(v+20 if k=='x' else shift(v)) for k,v in obj.items()}
        return obj
    for row in cases():
        if 'expected' in row:gold=deepcopy(row['expected'])
        elif row['family']=='circle_control':gold=[{'type':'circle','center':dict(zip(('x','y'),[v*1000 for v in row['origin']])),'radius':row['radius']*1000}]
        else:gold=expected_entities(row)
        assert holdout_oracle(row,gold)['passed']
        assert not holdout_oracle(row,shift(gold))['passed']
        records.append({'case':row['id'],'golden_passed':True,'shifted_20mm_rejected':True})
    base.dump(FREEZE/'oracle-self-check.json',records)


def main():
    self_check()
    original_dump=base.dump
    def dump(path,value):
        if path.name=='holdout-manifest.json':
            value={**value,'scope':'Second new internal holdout U1-U6, authored after freeze; not third-party blind testing.'}
            value['hashes'].pop('docs/TRANSFER_HOLDOUT_PROTOCOL_20261124.md',None)
            for name in ['evaluations/generalization_holdout_b.py','docs/GENERALIZATION_B_PROTOCOL_20261124.md']:
                value['hashes'][name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        original_dump(path,value)
    base.dump=dump;run.FREEZE=FREEZE;run.cases=cases
    run.main()


if __name__=='__main__':main()
