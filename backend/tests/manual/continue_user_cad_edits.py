"""Continue recorded clarification turns without rewriting original evidence."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tests.manual.run_user_cad_corpus import call,dump,edit_checks

ANSWERS={
 'B6':'以选中圆的圆心为缩放基点，圆心保持不变，放大到原来的2倍。',
 'B13':'以左侧圆形为基准，让右侧圆形圆心的Y坐标与左侧圆形圆心的Y坐标相同。',
 'B18':'上下两个新增矩形各宽4米高2米，分别与篮球场上、下边线中点对齐，矩形边缘与球场相接。',
 'D5':'以当前选中样条曲线的包围盒中心为缩放基点，放大到原来的1.5倍。',
}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);args=p.parse_args()
    source=Path(args.source).resolve();root=Path(args.output).resolve();results=[]
    for case,answer in ANSWERS.items():
        folder=root/case;shutil.copytree(source/case,folder,dirs_exist_ok=True)
        old=json.loads((folder/'corpus-report.json').read_text(encoding='utf-8'))
        fixture=json.loads((folder/'ui-fixture.json').read_text(encoding='utf-8'))
        step=fixture['selection_before_step'];selection=fixture['drawing_selection']
        request=json.loads((folder/f'request-{step}.json').read_text(encoding='utf-8'))
        before=json.loads((folder/f'step-{step-1}.json').read_text(encoding='utf-8'))['variant']
        response=json.loads((folder/f'step-{step}.json').read_text(encoding='utf-8'))
        body={**request,'message':answer,'history':request['history']+[
            {'role':'user','content':request['message']},{'role':'assistant','content':response.get('message','')} ]}
        response=call(folder,step+1,body)
        confirmation=None
        if response.get('pending_action'):
            confirmation=step+2
            response=call(folder,confirmation,{'action_id':response['pending_action']['id'],'approved':True},'confirm')
        checks=edit_checks(case,before,response.get('variant') or {},selection['geometry_ids'])
        report={'case':case,'kind':'edit_followup','base':old['base'],'messages':old['messages']+[answer],
            'checks':checks,'passed':all(c['passed'] for c in checks),'reply':response.get('message'),
            'has_candidate':bool(response.get('variant')),'app':'not_run'}
        fixture.update(messages=report['messages'],confirmation_step=confirmation,
            expected_preview_count=len(response.get('preview_paths') or []))
        dump(folder/'ui-fixture.json',fixture);dump(folder/'corpus-report.json',report)
        results.append(report);dump(root/'summary.json',{'reports':results})
        print(json.dumps(report,ensure_ascii=False),flush=True)
