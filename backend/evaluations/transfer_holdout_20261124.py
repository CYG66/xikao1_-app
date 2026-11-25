"""Internal holdout authored after production freeze; no oracle feedback."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys

from scripts.local_dev import ROOT, isolated_environment
from evaluations import production_contract_pilot as base
from evaluations.frozen_release_validation import holdout_oracle

FREEZE=ROOT/'.local-dev/transfer-holdout-freeze-elw88_g9'


def cases():
    points=[{'x':380,'y':-470}]
    for length,angle in [(1730,-32),(920,46),(1370,5)]:
        p=points[-1];a=math.radians(angle)
        points.append({'x':p['x']+length*math.cos(a),'y':p['y']+length*math.sin(a)})
    return [
        {'id':'T1','category':'parameter_transfer','family':'semicircle_walls','unit':'毫米','origin':[-1120,-635],
         'width':3180,'height':4950,'angle':0,
         'text':'请画一个闭合半圆拱门，总宽3180毫米、总高4950毫米。底边左端(-1120,-635)，底边水平；两侧直墙等高且竖直，顶部为上半圆，直径等于总宽，总高包含半圆。只画外边界，坐标单位毫米。'},
        {'id':'T2','category':'parameter_transfer','family':'capsule_tangency','unit':'厘米','origin':[-125.5,64.2],
         'length':625,'height':174,'angle':-38,
         'text':'绘制胶囊形闭合边界，中心位于(-125.5,64.2)，长轴相对x轴正向逆时针-38度，沿长轴总长625厘米、短轴总高174厘米。两端各为向外半圆，两条直边与半圆相切；两端半径相同，总长含半圆。不添加内部线，坐标单位厘米。'},
        {'id':'T3','category':'paraphrase','family':'circle_control','unit':'米','origin':[-.72,1.48],'radius':.93,
         'text':'画圆：圆心(-0.72,1.48)，直径1.86米。只要圆的轮廓，不要尺寸标注。坐标单位米。'},
        {'id':'T4','category':'longer_relation_chain','family':'explicit_geometry',
         'expected':[{'type':'polyline','closed':False,'vertices':points}],
         'text':'从(38,-47)出发画折线，先沿与x轴正向成-32度的方向走173厘米，再向左转78度接着画92厘米，再向右转41度接着画137厘米。三段连在一起，末端不连回起点，不加其他图形。坐标单位厘米。'},
        {'id':'T5','category':'parameter_transfer','family':'rectangle_control','unit':'米','origin':[.83,-1.27],'width':1.93,'height':.87,
         'text':'画一个矩形，左下角(0.83,-1.27)，宽1.93米、高0.87米，边平行于坐标轴。只画矩形轮廓，坐标单位米。'},
        {'id':'T6','category':'new_combination','family':'explicit_geometry','expected':[
             {'type':'circle','center':{'x':-2800,'y':1200},'radius':480},
             {'type':'polyline','closed':True,'vertices':[{'x':x,'y':y} for x,y in [(-900,400),(500,400),(500,1200),(-900,1200)]]},
             {'type':'circle','center':{'x':2100,'y':1200},'radius':310}],
         'text':'在同一张图中画三个独立图形。左圆：圆，圆心(-2.8,1.2)，半径0.48米，坐标单位米；中矩形：矩形，左下角(-0.9,0.4)，宽1.4米，高0.8米，坐标单位米；右圆：圆，圆心(2.1,1.2)，半径0.31米，坐标单位米。不要增加连接线或标注。'},
    ]


def main():
    from evaluations.run_live_user_corpus import load_key
    load_key();env,state=isolated_environment('transfer-holdout-live',True)
    os.environ.update({k:v for k,v in env.items() if k!='PATH'})
    frozen=json.loads((FREEZE/'freeze.json').read_text(encoding='utf-8'))
    assert base.tree_hashes(ROOT/'app')==frozen['source_files']==base.tree_hashes(FREEZE/'app')
    output=base.prepare(state);staged=base.tree_hashes(output/'versions/B');data=cases()
    manifest={'scope':'Six developer-authored internal holdout cases, two repeats; not third-party blind testing.',
        'cases':data,'source_files':frozen['source_files'],'frozen_source':str(FREEZE),'source_frozen_utc':frozen['frozen_utc'],
        'staged_files':staged,'created_utc':datetime.now(timezone.utc).isoformat(),
        'hashes':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in [
            'evaluations/transfer_holdout_20261124.py','evaluations/production_contract_pilot.py',
            'evaluations/frozen_release_validation.py','evaluations/relation_pilot/oracle.py','evaluations/relation_pilot/cases.py',
            'docs/TRANSFER_HOLDOUT_PROTOCOL_20261124.md']}}
    base.dump(output/'holdout-manifest.json',manifest)
    sys.path.insert(0,str(ROOT/'tests/manual'))
    from eval_budget_store import BudgetLedger
    os.environ.update(P12_MAX_REQUESTS='144',P12_MAX_INPUT_TOKENS='3200000',P12_MAX_OUTPUT_TOKENS='360000',P12_MAX_COST_USD='2')
    ledger=BudgetLedger(output/'budget.json');base.oracle=holdout_oracle;rows=[];rng=random.Random(2411242)
    print('HOLDOUT OUTPUT '+str(output),flush=True)
    for repeat in (1,2):
        order=data.copy();rng.shuffle(order)
        for row in order:
            result=base.run_trial(output,{'case':row['id'],'repeat':repeat,'arm':'B'},row)
            rows.append(result);base.dump(output/'results.json',rows)
            print(json.dumps({k:result[k] for k in ('trial','passed','first_turn_passed','failure_category','requests')},ensure_ascii=False),flush=True)
            assert not ledger.snapshot()['pending'] and not ledger.snapshot()['stopped']
    assert base.tree_hashes(ROOT/'app')==frozen['source_files'] and base.tree_hashes(output/'versions/B')==staged
    base.dump(output/'holdout-analysis.json',{'trials':12,'formal_passed':sum(r['passed'] for r in rows),
        'first_turn_passed':sum(r['first_turn_passed'] for r in rows),'geometry_any_stored':sum(r['geometry_any_stored'] for r in rows),
        'per_case':{c['id']:{'formal':sum(r['passed'] for r in rows if r['case']==c['id']),
            'geometry':sum(r['geometry_any_stored'] for r in rows if r['case']==c['id'])} for c in data},
        'source_unchanged':True,'usage':ledger.snapshot()['used'],'finished_utc':datetime.now(timezone.utc).isoformat()})
    base.dump(output/'failure-details.json',[r for r in rows if not r['passed']])
    print('FINISHED '+(output/'holdout-analysis.json').read_text(encoding='utf-8'),flush=True)


if __name__=='__main__':main()
