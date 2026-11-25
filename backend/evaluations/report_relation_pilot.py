"""Analyze the predeclared paired pilot; does not select best-of-round results."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import statistics


def analyze(root):
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    if not (root/'completed.json').exists():raise ValueError('Pilot is incomplete')
    manifest=read(root/'manifest.json');rows=read(root/'results.json');completed=read(root/'completed.json')
    if len(rows)!=72 or len({r['trial'] for r in rows})!=72:raise ValueError('Expected 72 unique arm trials')
    expected={(c['id'],repeat+1,arm) for c in manifest['cases'] for repeat in range(3) for arm in ('A','B')}
    if {(r['case'],r['repeat'],r['arm']) for r in rows}!=expected:raise ValueError('Unbalanced coverage')
    hashes=manifest['source_hashes'];repo=Path(__file__).resolve().parents[1]
    changed=[name for name,value in hashes.items() if hashlib.sha256((repo/name).read_bytes()).hexdigest()!=value]
    if changed or not completed['source_unchanged']:raise ValueError('Frozen inputs changed: '+str(changed))
    usages=[json.loads(line) for line in (root/'model-usage.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    budget=read(root/'budget.json');ids=[u['request_id'] for u in usages]
    if budget.get('pending') or budget.get('stopped'):raise ValueError('Ledger incomplete or stopped')
    if len(ids)!=len(set(ids)) or len(ids)!=budget['used']['requests'] or len(ids)!=sum(r['requests'] for r in rows):raise ValueError('Usage mismatch')
    if any(u['model']!='deepseek-flash' for u in usages):raise ValueError('Unexpected model')
    usage_by_trial=Counter(u['trial'] for u in usages)
    if any(r['requests']>2 or usage_by_trial[r['trial']]!=r['requests'] for r in rows):raise ValueError('Per-trial budget mismatch')
    for u in usages:
        if u['usage'].get('completion_tokens',0)>4096:raise ValueError('Output limit exceeded')
    arms={}
    for arm in ('A','B'):
        group=[r for r in rows if r['arm']==arm]
        stages=Counter(a.get('failure',{}).get('stage','independent_geometry') for r in group for a in r['attempts'] if not a['passed'])
        arms[arm]={'trials':len(group),'passed':sum(r['passed'] for r in group),'first_call_passed':sum(r['first_call_passed'] for r in group),
            'requests':sum(r['requests'] for r in group),'input_tokens':sum(r['input_tokens'] for r in group),'output_tokens':sum(r['output_tokens'] for r in group),
            'estimated_cost_usd':sum(r['estimated_cost_usd'] for r in group),'mean_seconds':statistics.mean(r['seconds'] for r in group),
            'failed_attempt_stages':dict(stages),
            'production_accepted_among_geometry_passed':sum(r['production_acceptance']=='passed' for r in group),
            'stable_cases_3_of_3':sum(all(r['passed'] for r in group if r['case']==case['id']) for case in manifest['cases'])}
    paired=defaultdict(dict)
    for r in rows:paired[(r['case'],r['repeat'])][r['arm']]=r
    wins=sum(pair['B']['passed'] and not pair['A']['passed'] for pair in paired.values())
    losses=sum(pair['A']['passed'] and not pair['B']['passed'] for pair in paired.values())
    discordant=wins+losses
    exact_p=min(1,2*sum(math.comb(discordant,k) for k in range(min(wins,losses)+1))/2**discordant) if discordant else 1
    case_diffs=[];per_case=[]
    for case in manifest['cases']:
        a=sum(paired[(case['id'],repeat)]['A']['passed'] for repeat in (1,2,3))
        b=sum(paired[(case['id'],repeat)]['B']['passed'] for repeat in (1,2,3))
        case_diffs.append((b-a)/3);per_case.append({'case':case['id'],'family':case['family'],'A_passed':a,'B_passed':b,'total_each':3})
    rng=random.Random(41309)
    samples=sorted(statistics.mean(rng.choices(case_diffs,k=len(case_diffs))) for _ in range(10000))
    interval=[samples[249],samples[9749]]
    families=[]
    for family in sorted({r['family'] for r in rows}):
        families.append({'family':family,**{arm:sum(r['passed'] for r in rows if r['family']==family and r['arm']==arm) for arm in ('A','B')},'total_each':9})
    gain=(arms['B']['passed']-arms['A']['passed'])/36
    cost_ratio=arms['B']['estimated_cost_usd']/arms['A']['estimated_cost_usd'] if arms['A']['estimated_cost_usd'] else None
    criteria={'gain_at_least_10pp':gain>=.10,'case_bootstrap_lower_bound_positive':interval[0]>0,
        'no_family_loses_more_than_one_trial':all(f['B']>=f['A']-1 for f in families),
        'mean_cost_ratio_at_most_1_25':cost_ratio is not None and cost_ratio<=1.25}
    eligible=all(criteria.values())
    report={'schema':'cad.relation-pilot-report.v1','scope':manifest['scope'],'arms':arms,'families':families,'per_case':per_case,
        'paired_B_only_wins':wins,'paired_A_only_wins':losses,'final_rate_difference_B_minus_A':gain,
        'case_cluster_bootstrap_95_interval':interval,'mcnemar_exact_two_sided_p_descriptive_only':exact_p,
        'estimated_cost_ratio_B_over_A':cost_ratio,'predeclared_criteria':criteria,
        'eligible_for_expanded_validation':eligible,'production_default_changed':False,
        'verification':{'frozen_inputs_unchanged':True,'balanced_72_trials':True,'usage_ids_unique_and_settled':True,
            'requests':len(ids),'all_deepseek_flash':True,'same_request_and_output_caps':True},
        'reporter_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'caveat':'A scoped planner versus a bundled B protocol/compiler; not a full production success rate. Twelve visible cases/four related families; no claim about arbitrary CAD.'}
    (root/'analysis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 关系计算小范围对照结果','',
        '**结论：'+('达到预先规定的扩大验证条件，仍不切换生产默认链路。' if eligible else '未达到预先规定的扩大验证条件，不建议切换生产默认链路。')+'**','',
        '|指标|A：当前规划器|B：关系接口与编译器|','|---|---:|---:|']
    for label,key in [('最终几何规划通过','passed'),('首次API调用通过','first_call_passed')]:
        lines.append(f"|{label}|{arms['A'][key]}/36（{arms['A'][key]/36:.2%}）|{arms['B'][key]}/36（{arms['B'][key]/36:.2%}）|")
    for label,key in [('3次均通过的案例','stable_cases_3_of_3'),('真实模型请求','requests'),('输入tokens','input_tokens'),('输出tokens','output_tokens'),('估算费用USD','estimated_cost_usd'),('平均时延秒','mean_seconds')]:
        lines.append(f"|{label}|{arms['A'][key]}|{arms['B'][key]}|")
    lines+=['',f"B−A最终通过率差：{gain:+.2%}；按案例为块的配对bootstrap 95%区间：[{interval[0]:+.2%}, {interval[1]:+.2%}]。",
        f"同一案例同一重复中，B独有成功{wins}次，A独有成功{losses}次；McNemar描述性p={exact_p:.4g}，不将重复试次视为独立新需求。",
        '', '|类型|A|B|','|---|---:|---:|']
    for f in families:lines.append(f"|{f['family']}|{f['A']}/9|{f['B']}/9|")
    lines+=['','## 失败阶段','',f"- A：`{json.dumps(arms['A']['failed_attempt_stages'],ensure_ascii=False)}`。",
        f"- B：`{json.dumps(arms['B']['failed_attempt_stages'],ensure_ascii=False)}`。",
        '- 阶段计数包含已恢复失败；各试次result.json和request/response保留全部尝试，不能将这些计数当作最终失败项数。',
        '', '## 结论边界','',
        '- 主指标只测规划、Schema、执行及独立几何检查，不是正式业务交付。A仍可使用原有表达式、共享点与约束；两组原语范围相同。',
        '- 生产回放只对几何已通过的输出执行：A正式验收数量'+str(arms['A']['production_accepted_among_geometry_passed'])+'，B为'+str(arms['B']['production_accepted_among_geometry_passed'])+'。未评估原生产路由的所有回退或确定性修复，不能当完整后端对照。',
        '- B额外承担参数引用和表达式协议成本；失败需区分提取、编译、几何关系错误，不能把整体效果归因到算术求值器。',
        '- B只是标量表达式DAG编译，不是从相切、重合等几何谓词自动求解未知量的完整约束系统。此实验不能否定或证明后者。',
        '- 两组均未执行完整生产解释器的全部归一化与确定性修复。主指标是受限回调模块的成功率，不能拿本表数字替代已完成的70条业务验收成绩。',
        '- 十二条开发者可见的新需求、四个相关类型，样本少且不是第三方盲测；统计区间不覆盖任务选择偏差。',
        '- 费用为项目固定公式内部估算，未按缓存折扣计账，不是供应商发票。实际token和时延如实记录。',
        '- 冻结文件、模型、预算及72试次唯一覆盖核验通过。未修改生产代码或默认链路，未更新70条成绩，未上传GitHub。',
        '', '## 预先规定条件','']
    for key,value in criteria.items():lines.append(f"- {key}：{'满足' if value else '不满足'}。")
    lines+=['','## 逐案例稳定性','', '|案例|类型|A三次|B三次|','|---|---|---:|---:|']
    for r in per_case:lines.append(f"|{r['case']}|{r['family']}|{r['A_passed']}/3|{r['B_passed']}/3|")
    lines+=['',f'原始证据：`{root.resolve()}`。']
    (root/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'per_case','families'}},ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,required=True)
    analyze(parser.parse_args().run)
