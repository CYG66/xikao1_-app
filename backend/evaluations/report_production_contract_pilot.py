"""Predeclared full-production pilot analysis; no model calls or rescoring."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import statistics

from evaluations.production_contract_pilot import tree_hashes, dump
from scripts.local_dev import ROOT


def report(output):
    read=lambda name:json.loads((output/name).read_text(encoding='utf-8'))
    m=read('manifest.json');rows=read('results.json');done=read('completed.json');ledger=read('budget.json')
    expected={(r['case'],r['repeat'],r['arm']) for r in m['schedule']}
    assert len(rows)==48 and len({r['trial'] for r in rows})==48
    assert {(r['case'],r['repeat'],r['arm']) for r in rows}==expected
    assert done['frozen_versions_unchanged'] and all(tree_hashes(output/'versions'/a)==m['versions'][a] for a in ('A','B'))
    for rel,key in [('evaluations/production_contract_pilot.py','runner_sha256'),('evaluations/report_production_contract_pilot.py','reporter_sha256'),('tests/test_production_contract_pilot.py','offline_test_sha256'),('docs/FULL_PRODUCTION_CONTRACT_PILOT_PROTOCOL_20261123.md','protocol_sha256')]:
        assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==m[key],rel
    for rel,value in m['oracle_source_sha256'].items():assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==value
    usage=[u for r in rows for u in r['usage']];ids=[u['request_id'] for u in usage]
    settled=[e for e in ledger['events'] if e['event']=='settled']
    assert len(ids)==len(set(ids))==ledger['used']['requests']==len(settled)
    assert not ledger['pending'] and not ledger['stopped']
    assert {e['request_id'] for e in settled}==set(ids)
    assert all(u['model']=='deepseek-flash' for u in usage)
    assert all(r['requests']<=12 for r in rows)
    stats={};case_diffs=[];pairs=defaultdict(dict)
    for r in rows:pairs[(r['case'],r['repeat'])][r['arm']]=r
    for arm in ('A','B'):
        group=[r for r in rows if r['arm']==arm];us=[u for r in group for u in r['usage']]
        inp=sum(u['usage']['prompt_tokens'] for u in us);out=sum(u['usage']['completion_tokens'] for u in us)
        stats[arm]={'trials':24,'formal_passed':sum(r['passed'] for r in group),
            'first_http_result_passed':sum(r['first_turn_passed'] for r in group),
            'geometry_any_stored':sum(r['geometry_any_stored'] for r in group),
            'stable_cases_3_of_3':sum(all(r['passed'] for r in group if r['case']==case['id']) for case in m['cases']),
            'requests':len(us),'input_tokens':inp,'output_tokens':out,'estimated_usd':inp*.3/1e6+out*1.2/1e6,
            'mean_seconds':statistics.mean(r['seconds'] for r in group),'failure_categories':dict(Counter(r['failure_category'] for r in group))}
    assert sum(v['input_tokens'] for v in stats.values())==ledger['used']['input_tokens']
    assert sum(v['output_tokens'] for v in stats.values())==ledger['used']['output_tokens']
    assert abs(sum(v['estimated_usd'] for v in stats.values())-ledger['used']['cost_usd'])<1e-8
    per_case=[]
    for c in m['cases']:
        row={'case':c['id'],'family':c['family']}
        for a in ('A','B'):
            group=[r for r in rows if r['case']==c['id'] and r['arm']==a]
            row[a]=sum(r['passed'] for r in group);row[a+'_geometry']=sum(r['geometry_any_stored'] for r in group)
        per_case.append(row);case_diffs.append((row['B']-row['A'])/3)
    rng=random.Random(41309);samples=sorted(statistics.mean(rng.choices(case_diffs,k=8)) for _ in range(10000))
    ci=[samples[249],samples[9749]];gain=(stats['B']['formal_passed']-stats['A']['formal_passed'])/24
    ratio=stats['B']['estimated_usd']/stats['A']['estimated_usd'] if stats['A']['estimated_usd'] else None
    control={a:sum(row[a] for row in per_case if row['family'].endswith('_control')) for a in ('A','B')}
    criteria={'gain_at_least_10pp':gain>=.1,'case_bootstrap_lower_positive':ci[0]>0,
              'basic_controls_no_regression':control['B']>=control['A'],'cost_ratio_at_most_1_25':ratio is not None and ratio<=1.25}
    result={'scope':m['scope'],'arms':stats,'per_case':per_case,'formal_rate_B_minus_A':gain,'case_bootstrap_95_interval':ci,
        'B_only_wins':sum(p['B']['passed'] and not p['A']['passed'] for p in pairs.values()),
        'A_only_wins':sum(p['A']['passed'] and not p['B']['passed'] for p in pairs.values()),
        'estimated_cost_ratio':ratio,'predeclared_criteria':criteria,'eligible_for_expanded_validation':all(criteria.values()),
        'verification':{'48_trials_unique_balanced':True,'all_flash':True,'all_requests_settled':True,
                        'frozen_inputs_unchanged':True,'request_count':len(ids)}}
    dump(output/'analysis.json',result);dump(output/'failure-details.json',[r for r in rows if not r['passed']])
    lines=['# 完整生产链路真实对照结果','',
        '**结论：'+('达到预定扩大验证条件，仍不能外推任意CAD。' if all(criteria.values()) else '未达到预定优势条件，不能证明本轮修复提高端到端成功率。')+'**','',
        '|指标|A：修复前冻结源码|B：契约整合后源码|','|---|---:|---:|']
    for label,key in [('正式交付','formal_passed'),('首个HTTP结果正式交付','first_http_result_passed'),('已保存版本中几何正确，含草稿','geometry_any_stored')]:
        lines.append(f"|{label}|{stats['A'][key]}/24（{stats['A'][key]/24:.2%}）|{stats['B'][key]}/24（{stats['B'][key]/24:.2%}）|")
    for label,key in [('3次正式通过的案例数','stable_cases_3_of_3'),('真实请求','requests'),('输入token','input_tokens'),('输出token','output_tokens'),('估算美元，非供应商账单','estimated_usd'),('平均每试次秒','mean_seconds')]:
        lines.append(f"|{label}|{stats['A'][key]}|{stats['B'][key]}|")
    lines+=['',f'正式交付B-A：{gain:+.2%}；按案例为块的95%区间：[{ci[0]:+.2%}, {ci[1]:+.2%}]。',
        '', '|案例|类型|A正式/3|B正式/3|A几何/3|B几何/3|','|---|---|---:|---:|---:|---:|']
    for r in per_case:lines.append(f"|{r['case']}|{r['family']}|{r['A']}|{r['B']}|{r['A_geometry']}|{r['B_geometry']}|")
    lines+=['','## 全部未通过试次','']
    for r in rows:
        if r['passed']:continue
        failed=[{'id':v['id'],'geometry':v['geometry'],'acceptance_summary':v['acceptance_summary']} for v in r['saved_variants']]
        lines.append(f"- **{r['trial']}**：{r['failure_category']}；模型调用{r['requests']}次。末次回复：{r['last_message']}。执行异常：{r['error']}。")
        if failed:lines.append('  保存版本核验：`'+json.dumps(failed,ensure_ascii=False)+'`。')
    lines+=['','## 边界与核验','',
        '- 两版均走完整生产HTTP流式聊天与确认、项目保存及预览；无历史计划、工具强制路由或标准坐标注入。虚拟硬件，不测Flutter渲染，不执行小车。',
        '- 8个开发者选择的生成案例，每案例重复3次；不是盲测或任意自然语言CAD分布。独立几何通过与正式来源覆盖分列，不将草稿算交付。',
        '- 使用相同固定确认消息、模型和预算。供应商内部模型版本及采样随机性不可冻结；不能从单次转败直接证明源码回归。',
        '- 冻结源码、协议、执行器、oracle、48次唯一覆盖和账本结算核验通过。详细API请求/响应、HTTP结果、项目文件、逐试次原因均保留在运行目录。',
        '- 生产源码未在测试期间修正，原70条成绩未改，未上传GitHub。', '', '预定条件：'+json.dumps(criteria,ensure_ascii=False), '', '证据目录：`'+str(output)+'`。']
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    report(p.parse_args().run.resolve())
