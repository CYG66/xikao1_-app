"""Batch production Flutter response replays; retain raw JSON test events."""
import argparse
import json
from pathlib import Path
import re
import subprocess


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--cases',nargs='*');args=p.parse_args()
    root=Path(args.root).resolve();report_path=root/'app-replays.json'
    report=json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {'scope':'Production Flutter response replay, virtual hardware, not tablet APK','cases':{},'batches':[]}
    cases=[]
    for folder in root.iterdir():
        path=folder/'corpus-report.json'
        if not path.exists():continue
        case=folder.name
        if args.cases and case not in args.cases:continue
        if not args.cases and case in report['cases']:continue
        if json.loads(path.read_text(encoding='utf-8')).get('has_candidate'):cases.append(case)
    cases.sort()
    if not cases:
        print('No new candidate-bearing fixtures');raise SystemExit(0)
    log=root/f'app-batch-{len(report["batches"])+1}.jsonl';tests={};results={}
    process=subprocess.Popen(['D:/flutter/bin/flutter.bat','test','test/live_cad_preview_test.dart',
        '--dart-define=CAD_LIVE_FIXTURE_ROOT='+str(root),
        '--dart-define=CAD_LIVE_FIXTURE_CASES='+','.join(cases),'--reporter','json'],
        cwd=Path(__file__).resolve().parents[3]/'xikao1_-app',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
        text=True,encoding='utf-8',errors='replace')
    with log.open('w',encoding='utf-8') as out:
        for line in process.stdout:
            out.write(line);out.flush()
            try:event=json.loads(line)
            except ValueError:continue
            if event.get('type')=='testStart':
                test=event['test'];match=re.search(r'([ABCD]\d+)$',test['name'])
                if match:tests[test['id']]=match[1]
            if event.get('type')=='testDone' and event.get('testID') in tests:
                case=tests[event['testID']];results[case]='passed' if event.get('result')=='success' else 'failed'
                print(json.dumps({'case':case,'app_replay':results[case]}),flush=True)
    code=process.wait()
    for case in cases:report['cases'][case]=results.get(case,'runner_error')
    report['batches'].append({'cases':cases,'returncode':code,'log':str(log)})
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'app_replay_counts':{s:list(report['cases'].values()).count(s) for s in ('passed','failed','runner_error')}}),flush=True)
