"""Read real-run evidence and report corpus-aligned and unchanged legacy scores."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    args=parser.parse_args();root=args.run.resolve()
    summary=read(root/'summary.json');manifest=read(root/'manifest.json')
    if summary['completed']!=70 or not (root/'completed.json').exists():
        raise ValueError('The 70-case run is incomplete; do not publish a full-corpus rate.')
    budget=read(root/'budget.json')
    if budget.get('pending') or budget.get('stopped'):raise ValueError('Budget ledger not cleanly settled')
    cases=[];request_ids={};models=Counter();adjustments=[]
    for raw in summary['reports']:
        case=raw['case'];row=dict(raw);folder=root/case
        final=read(Path(raw['last_response'])) if raw.get('last_response') else {}
        aligned=raw['formal_passed'] and final.get('ok') is True
        correction=None
        # Original C2 specifies five controls and smooth closure, with no
        # requested degree. Its legacy oracle adds an unsupported cubic-only
        # restriction. Verify the native periodic basis and every source point.
        if case=='C2' and raw.get('accepted_candidate'):
            gs=(final.get('variant') or {}).get('geometries') or []
            expected=[(0,0),(1000,2000),(2000,-1000),(3000,2000),(4000,0)]
            g=gs[0] if len(gs)==1 else {}
            controls=g.get('control_points') or []
            degree=g.get('degree')
            valid=(g.get('type')=='spline' and g.get('closed') is True and g.get('periodic') is True
                and isinstance(degree,int) and 2<=degree<5 and len(controls)==5
                and not any(g.get(k) for k in ('knots','weights','vertices','fit_points','fitPoints'))
                and all(math.dist((p['x'],p['y']),q)<2 and abs(p.get('z',0))<2 for p,q in zip(controls,expected)))
            others=[c for c in raw.get('checks',[]) if c['name']!='closed_cubic_spline_exact_control_points']
            if valid and others and all(c['passed'] for c in others) and final.get('ok') is True:
                aligned=True
                correction={'case':case,'legacy_check':'closed_cubic_spline_exact_control_points',
                    'reason':'原文未指定三次；保留全部五个控制点、闭合及平滑要求。原生均匀周期样条degree>=2具备接缝连续性，已有独立预览切向检查同时通过。',
                    'actual_degree':degree,'native_basis':'implicit_uniform_periodic','original_prompt':manifest['prompts'][case].strip()}
                adjustments.append(correction)
        row['corpus_aligned_passed']=aligned
        row['oracle_adjustment']=correction
        category='passed' if aligned else raw['category']
        row['final_category']=category
        if not aligned:
            reasons=[]
            if raw.get('blocked_by'):reasons.append('前置生成案例未交付候选：'+raw['blocked_by'])
            if raw.get('runner_error'):reasons.append('评测执行异常：'+raw['runner_error'])
            for check in raw.get('failed_checks',[]):
                reasons.append('独立检查未通过：'+check['name']+'；实测='+json.dumps(check.get('observed'),ensure_ascii=False))
            if raw.get('last_message'):reasons.append(raw['last_message'])
            store=read(folder/'projects.json') if (folder/'projects.json').exists() else {}
            variants=[v for p in store.get('projects',[]) for v in p.get('variants',[])]
            diagnostics=[]
            for variant in variants[-2:]:
                record=variant.get('construction_record') or {}
                acceptance=variant.get('acceptance_summary') or {}
                if acceptance.get('status')=='review_required':
                    reasons.append('草稿待复核：'+json.dumps(acceptance.get('unknown_requirements',[]),ensure_ascii=False))
                source=record.get('source_acceptance') or {}
                diagnostics.append({'variant_id':variant.get('id'),'acceptance':acceptance,
                    'source_proofs':{key:value for key,value in source.items()
                        if key.endswith('_acceptance') and isinstance(value,dict)}})
            row['failure_reasons']=list(dict.fromkeys(reasons))
            row['stored_diagnostics']=diagnostics
            runs_path=folder/'agent-runs.json'
            production_errors=[];seen_errors=set()
            def visit(value):
                if isinstance(value,dict):
                    if isinstance(value.get('code'),str) and value.get('message'):
                        signature=json.dumps(value,ensure_ascii=False,sort_keys=True)
                        if signature not in seen_errors:
                            seen_errors.add(signature);production_errors.append(value)
                    for child in value.values():visit(child)
                elif isinstance(value,list):
                    for child in value:visit(child)
            if runs_path.exists():visit(read(runs_path))
            row['production_errors']=production_errors[-30:]
            if production_errors:
                row['failure_reasons']+=list(dict.fromkeys('生产错误：'+e['code']+'：'+str(e['message']) for e in production_errors[-5:]))
        usages=[]
        usage_path=folder/'model-usage.jsonl'
        if usage_path.exists():
            for line in usage_path.read_text(encoding='utf-8').splitlines():
                usage=json.loads(line);rid=usage['request_id']
                if rid in request_ids:raise ValueError('Duplicate model usage request ID across cases')
                request_ids[rid]=case;models[usage['model']]+=1;usages.append(usage)
        row['model_calls']=len(usages)
        cases.append(row)
    source_order={case:index for index,case in enumerate(manifest['prompts'])}
    cases.sort(key=lambda row:source_order[row['case']])
    if len(request_ids)!=budget['used']['requests']:raise ValueError('Usage files and settled request count differ')
    code=hashlib.sha256()
    for path in sorted((ROOT/'app').rglob('*.py')):
        code.update(path.relative_to(ROOT).as_posix().encode());code.update(path.read_bytes())
    unchanged=code.hexdigest()==manifest['backend_code_sha256']
    if not unchanged:raise ValueError('Production code changed during the real run')
    first=read(root/'A10/step-1.json')
    message=str(first.get('message') or '')
    expected_clarification=('缺少尺寸' in message and '请提供' in message and not first.get('variant'))
    for row in cases:
        row['original_expectation_passed']=row['corpus_aligned_passed'] or (row['case']=='A10' and expected_clarification)
        row['edit_precondition_blocked']=(row['kind']=='edit' and
            (bool(row.get('blocked_by')) or '不能作为修改基线' in str(row.get('last_message') or '')))
    totals={}
    for name,rows in [('all',cases),('generation',[r for r in cases if r['kind']=='create']),
                      ('editing',[r for r in cases if r['kind']=='edit'])]:
        passed=sum(r['corpus_aligned_passed'] for r in rows)
        totals[name]={'passed':passed,'total':len(rows),'rate':passed/len(rows),
                      'original_expectation_passed':sum(r['original_expectation_passed'] for r in rows),
                      'legacy_passed':sum(r['legacy_passed'] for r in rows),
                      'formal_without_oracle_adjustment':sum(r['formal_passed'] for r in rows)}
    task_passed=totals['all']['passed']+int(expected_clarification and not next(r for r in cases if r['case']=='A10')['corpus_aligned_passed'])
    result={'scope':manifest['scope'],'totals':totals,'original_expectation_passed':task_passed,
        'original_expectation_rate':task_passed/70,'A10_expected_clarification':expected_clarification,
        'A10_first_message':message,'categories':dict(Counter(r['final_category'] for r in cases)),
        'model_calls':len(request_ids),'models':dict(models),'usage':budget['used'],
        'budget_cost_note':'Ledger cost is an internal estimate, not the provider invoice.',
        'backend_code_unchanged':unchanged,'source_sha256':manifest['source_sha256'],
        'started_utc':manifest['started_utc'],'finished_utc':read(root/'completed.json')['finished_utc'],
        'editing_precondition_blocked':sum(r['edit_precondition_blocked'] for r in cases),
        'editing_with_eligible_base':{'passed':totals['editing']['passed'],
            'total':sum(r['kind']=='edit' and not r['edit_precondition_blocked'] for r in cases)},
        'generation_first_turn_delivery':sum(r['kind']=='create' and r['corpus_aligned_passed']
                                             and r.get('candidate_step')==1 for r in cases),
        'oracle_adjustments':adjustments,'reports':cases}
    dump(root/'final-results.json',result)
    dump(root/'final-failure-details.json',[r for r in cases if not r['original_expectation_passed']])
    dump(root/'undelivered-details.json',[r for r in cases if not r['corpus_aligned_passed']])
    lines=['# 70条语料 DeepSeek Flash 真实重测','',
        f"- 后端：`{ROOT}`；Python：`{manifest['python']}`。",
        '- 原语料原句、既定补参和确认流程；真实生产流式/确认处理器与真实模型，无历史计划回放。',
        '- 主分数允许原有固定补参和确认；不是仅发送原句一次的通过率。',
        '- 未运行Flutter画布或Android APK；硬件为virtual_sim。',
        f"- 原文预期口径（含A10合理澄清）：**{task_passed}/70，{task_passed/70:.2%}**。",
        f"- 正式候选/编辑交付并通过语料一致的独立检查：**{totals['all']['passed']}/70，{totals['all']['rate']:.2%}**。",
        f"- 旧严格检查原始分数：{totals['all']['legacy_passed']}/70。原始结果完整保留。",
        f"- 模型请求：{len(request_ids)}，返回模型：`{dict(models)}`；生产代码哈希未变化。",'',
        '| 分组 | 交付并验收通过 | 总数 | 通过率 |','|---|---:|---:|---:|']
    for label,key in [('生成','generation'),('编辑','editing')]:
        v=totals[key];lines.append(f"| {label} | {v['passed']} | {v['total']} | {v['rate']:.2%} |")
    lines+=['',f"编辑前置阻塞：{result['editing_precondition_blocked']}条；具备合格前置的编辑成功{result['editing_with_eligible_base']['passed']}/{result['editing_with_eligible_base']['total']}。这项条件成功率不替代25条编辑端到端分母。"]
    lines+=[f"生成原句首次交付：{result['generation_first_turn_delivery']}/45；其余交付包含固定补参或确认。"]
    lines+=['','评分说明：保留旧检查；正式评分额外要求后端验收通过。模板的template_semantics_review是旧脚本固定false人工复核标记，单独列出，模板实际执行验收与尺寸检查仍须通过。',
        'C2原文未指定三次；其原生均匀周期样条、五个原控制点、闭合及预览接缝切向检查均独立验证，允许合法的更高次数；具体校准见final-results.json。',
        'A10原文预期为澄清/不支持提示，首次合理澄清单列；不把随后待复核草稿当作候选交付成功。','',
        '## 逐条结果','', '| 案例 | 类型 | 交付验收 | 模型调用 | 原因/说明 |','|---|---|---|---:|---|']
    for row in cases:
        reason='；'.join(row.get('failure_reasons',[])) if not row['corpus_aligned_passed'] else '通过'
        if row.get('oracle_adjustment'):reason+='（原文未限定三次样条）'
        reason=reason.replace('|','/').replace('\n',' ')[:1000]
        lines.append(f"| {row['case']} | {row['kind']} | {'通过' if row['corpus_aligned_passed'] else row['final_category']} | {row['model_calls']} | {reason} |")
    lines+=['','完整诊断：final-failure-details.json；逐轮请求、回复、模型输出、原始检查和持久化证据位于各案例目录。']
    (root/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='reports'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
