"""Sequential current-source regression and internal holdout, no code repairs."""
from copy import deepcopy
import hashlib,json,os,random,shutil,sys
from pathlib import Path
from datetime import datetime,timezone

from scripts.local_dev import ROOT,isolated_environment
from evaluations import production_contract_pilot as base

FREEZE=ROOT/'.local-dev/release-freeze-20261124-1ld_bjwj'


def holdouts():
    return [
      {'id':'L1','category':'parameter_transfer','family':'semicircle_walls','unit':'毫米','origin':[-735,415],'width':2860,'height':4320,'angle':0,
       'text':'请画一个闭合半圆拱门，总宽2860毫米、总高4320毫米。底边左端(-735,415)，底边水平；两侧直墙等高且竖直，顶部为上半圆，直径等于总宽，总高包含半圆。只画外边界，坐标单位毫米。'},
      {'id':'L2','category':'parameter_transfer','family':'capsule_tangency','unit':'厘米','origin':[-64,83],'length':572,'height':148,'angle':-26,
       'text':'绘制胶囊形闭合边界，中心位于(-64,83)，长轴相对x轴正向逆时针-26度，沿长轴总长572厘米、短轴总高148厘米。两端各为向外半圆，两条直边与半圆相切；两端半径相同，总长含半圆。不添加内部线，坐标单位厘米。'},
      {'id':'L3','category':'paraphrase','family':'relative_turn_polyline','unit':'米','origin':[-.65,.35],'a':2.15,'b':.95,'angle':24,'turn':-63,
       'text':'从(-0.65,0.35)出发画折线，先沿与x轴正向成24度的方向走2.15米，再向右转63度接着画0.95米。两段连在一起，末端不连回起点，不加其他图形。坐标单位米。'},
      {'id':'L4','category':'paraphrase','family':'circle_control','unit':'米','origin':[1.35,-.85],'radius':.72,
       'text':'请以(1.35,-0.85)为圆心作圆，直径取1.44米。图纸里只保留这个圆，不标尺寸。坐标单位米。'},
      {'id':'L5','category':'parameter_transfer','family':'rectangle_control','unit':'米','origin':[-1.45,2.25],'width':2.73,'height':1.37,
       'text':'画一个矩形，左下角(-1.45,2.25)，宽2.73米、高1.37米，边平行于坐标轴。只画矩形轮廓，坐标单位米。'},
      {'id':'L6','category':'parameter_transfer','family':'circle_control','unit':'毫米','origin':[735,-485],'radius':825,
       'text':'生成一个圆形，圆心(735,-485)，半径825毫米，坐标单位毫米。'},
      {'id':'L7','category':'new_combination','family':'explicit_geometry','expected':[
        {'type':'circle','center':{'x':-2500,'y':0},'radius':600},
        {'type':'polyline','closed':True,'vertices':[{'x':x,'y':y} for x,y in [(1000,-500),(2800,-500),(2800,600),(1000,600)]]}],
       'text':'在同一张图中画两个独立图形。左圆：圆，圆心(-2.5,0)，半径0.6米，坐标单位米；右矩形：矩形，左下角(1,-0.5)，宽1.8米，高1.1米，坐标单位米。不要增加连接线或标注。'},
      {'id':'L8','category':'new_combination','family':'explicit_geometry','expected':[
        {'type':'circle','center':{'x':400,'y':-700},'radius':1700},
        {'type':'circle','center':{'x':400,'y':-700},'radius':650}],
       'text':'绘制两个同心圆，外圆半径1.7米，内圆半径0.65米，共同圆心(0.4,-0.7)，坐标单位米。只保留内外两个圆，不加其他线条。'},
    ]


def holdout_oracle(row,geometries):
    from evaluations.relation_pilot.oracle import boundary
    from evaluations.relation_pilot.cases import expected_entities
    if 'expected' in row:expected=row['expected']
    elif row['family']=='circle_control':
        factor={'米':1000,'厘米':10,'毫米':1}[row['unit']]
        expected=[{'type':'circle','center':dict(zip(('x','y'),[v*factor for v in row['origin']])),'radius':row['radius']*factor}]
    elif row['family']=='rectangle_control':
        x,y=[v*1000 for v in row['origin']];w=row['width']*1000;h=row['height']*1000
        expected=[{'type':'polyline','closed':True,'vertices':[{'x':a,'y':b} for a,b in [(x,y),(x+w,y),(x+w,y+h),(x,y+h)]]}]
    else:expected=expected_entities(row)
    target=boundary(expected);actual=boundary(geometries)
    missing=not target.difference(actual.buffer(.45,quad_segs=32)).is_empty
    extra=not actual.difference(target.buffer(.45,quad_segs=32)).is_empty
    duplicated=sum(boundary([g]).length for g in geometries)-actual.length>.5
    return {'passed':not missing and not extra and not duplicated,'boundary_hausdorff_mm':target.hausdorff_distance(actual),
            'missing_boundary':missing,'extra_boundary':extra,'duplicate_boundary':duplicated,'sampled_limit_mm':.45}


def summarize(folder):
    rows=json.loads((folder/'results.json').read_text(encoding='utf-8'))
    usage=[u for r in rows for u in r['usage']];ledger=json.loads((folder/'budget.json').read_text(encoding='utf-8'))
    assert len(rows)==24 and len({r['trial'] for r in rows})==24
    assert len(usage)==ledger['used']['requests'] and not ledger['pending'] and not ledger['stopped']
    assert len({u['request_id'] for u in usage})==len(usage)
    assert all(u['model']=='deepseek-flash' for u in usage)
    report={'trials':24,'formal_passed':sum(r['passed'] for r in rows),'geometry_any_stored':sum(r['geometry_any_stored'] for r in rows),
        'per_case':{c:{'formal':sum(r['passed'] for r in rows if r['case']==c),'geometry':sum(r['geometry_any_stored'] for r in rows if r['case']==c),'total':3}
                    for c in dict.fromkeys(r['case'] for r in rows)},'usage':ledger['used']}
    base.dump(folder/'analysis.json',report);base.dump(folder/'failure-details.json',[r for r in rows if not r['passed']])
    return report


def main():
    from evaluations.run_live_user_corpus import load_key
    load_key();env,state=isolated_environment('frozen-release-live',True)
    # Set the coordinator's environment before run_trial creates isolated children.
    os.environ.update({k:v for k,v in env.items() if k not in {'PATH'}})
    output=base.prepare(state)
    frozen=json.loads((FREEZE/'freeze.json').read_text(encoding='utf-8'))
    assert base.tree_hashes(FREEZE/'app')==frozen['app_files']==base.tree_hashes(ROOT/'app')
    assert base.tree_hashes(output/'versions/B/app')==frozen['app_files']
    datasets={'regression':base.cases(),'holdout':holdouts()}
    manifest={'frozen_source':str(FREEZE),'source_files':frozen['app_files'],'source_frozen_utc':frozen['frozen_utc'],
        'datasets':datasets,'rules':'Same production run_trial and formal oracle gate, 3 repeats, no oracle feedback; regression then holdout',
        'protocol_sha256':hashlib.sha256((ROOT/'docs/FROZEN_RELEASE_AND_HOLDOUT_PROTOCOL_20261124.md').read_bytes()).hexdigest(),
        'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'base_runner_sha256':hashlib.sha256((ROOT/'evaluations/production_contract_pilot.py').read_bytes()).hexdigest()}
    base.dump(output/'release-manifest.json',manifest)
    sys.path.insert(0,str(ROOT/'tests/manual'))
    from eval_budget_store import BudgetLedger
    original_oracle=base.oracle
    print('RELEASE OUTPUT '+str(output),flush=True)
    for stage,data in datasets.items():
        folder=output/stage;folder.mkdir();shutil.copytree(output/'versions/B',folder/'versions/B')
        stage_hashes=base.tree_hashes(folder/'versions/B')
        base.dump(folder/'manifest.json',{'cases':data,'versions':{'B':stage_hashes},'stage':stage})
        os.environ.update(P12_MAX_REQUESTS='288',P12_MAX_INPUT_TOKENS='5000000',P12_MAX_OUTPUT_TOKENS='750000',P12_MAX_COST_USD='2')
        ledger=BudgetLedger(folder/'budget.json');rows=[];base.oracle=original_oracle if stage=='regression' else holdout_oracle
        rng=random.Random(241124 if stage=='regression' else 241125)
        for repeat in range(1,4):
            order=deepcopy(data);rng.shuffle(order)
            for row in order:
                entry={'case':row['id'],'repeat':repeat,'arm':'B'}
                print('START '+stage+' '+str(entry),flush=True)
                result=base.run_trial(folder,entry,row);rows.append(result);base.dump(folder/'results.json',rows)
                print(json.dumps({'stage':stage,**{k:result[k] for k in ('trial','passed','failure_category','requests')}},ensure_ascii=False),flush=True)
                status=ledger.snapshot()
                if status['stopped'] or status['pending']:raise RuntimeError('ledger stopped')
        assert base.tree_hashes(folder/'versions/B')==stage_hashes
        report=summarize(folder);base.dump(folder/'completed.json',{'source_unchanged':True,'finished_utc':datetime.now(timezone.utc).isoformat()})
        print('FINISHED '+stage+' '+json.dumps(report,ensure_ascii=False),flush=True)
    assert base.tree_hashes(ROOT/'app')==frozen['app_files']
    base.dump(output/'release-completed.json',{'source_unchanged':True,'finished_utc':datetime.now(timezone.utc).isoformat()})
    return 0


if __name__=='__main__':raise SystemExit(main())
