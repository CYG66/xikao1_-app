"""Account preflight and minimal paid probes; all generation is budgeted."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import urllib.request
from deepseek_flash_budget import Budget


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    root=args.output;budget=Budget()
    def write(name,data):(root/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    report={'status':'preflight','model':'deepseek-flash','thinking':{'type':'disabled'},
        'cases':{f'T{i}':'not_run' for i in range(1,7)}}
    key=os.getenv('DEEPSEEK_API_KEY')
    if not key:
        path=Path(__file__).resolve().parents[2]/'.local-ai-test/deepseek-api-key.clixml'
        command="$s=Import-Clixml -LiteralPath '"+str(path).replace("'","''")+"'; [Console]::Write(([System.Net.NetworkCredential]::new('', $s)).Password)"
        key=subprocess.check_output(['powershell','-NoProfile','-NonInteractive','-Command',command],text=True).strip()
    if not key:raise RuntimeError('credential_missing')
    def request(endpoint,payload=None):
        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'}
        req=urllib.request.Request('https://api.deepseek.com/'+endpoint,
            data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
        with urllib.request.urlopen(req,timeout=60) as response:return json.load(response)
    try:
        models=request('models');write('models.json',models)
        ids=[m.get('id') for m in models.get('data',[])]
        if 'deepseek-flash' not in ids:raise RuntimeError('approved_model_absent_from_account_model_list')
        probes=[
            {'messages':[{'role':'user','content':'Return JSON only: {"ok":true}'}],
             'response_format':{'type':'json_object'}},
            {'messages':[{'role':'user','content':'Call probe with ok=true. Do not perform any other action.'}],
             'tools':[{'type':'function','function':{'name':'probe','description':'Compatibility probe; no side effects.',
                'parameters':{'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']}}}],
             'tool_choice':{'type':'function','function':{'name':'probe'}}}
        ]
        for i,probe in enumerate(probes,1):
            payload={'model':'deepseek-flash','thinking':{'type':'disabled'},'max_tokens':128,**probe}
            reservation=budget.reserve(payload);write(f'probe-{i}-request.json',payload)
            write('budget.json',{'reservation':reservation,**budget.snapshot()})
            try:response=request('chat/completions',payload)
            except Exception:
                budget.fail_unknown();raise
            write(f'probe-{i}-response.json',response)
            budget.settle(response);write('budget.json',budget.snapshot())
            choice=response['choices'][0]
            if choice.get('finish_reason')=='length':raise RuntimeError('probe_truncated')
            if i==1 and json.loads(choice['message']['content'])!={'ok':True}:raise RuntimeError('json_probe_failed')
            if i==2 and not choice['message'].get('tool_calls'):raise RuntimeError('tool_call_probe_failed')
        report['status']='compatibility_probes_passed_formal_cases_not_started'
    except Exception as exc:
        report.update(status='stopped_preflight',reason=type(exc).__name__+': '+str(exc))
    report['budget']=budget.snapshot()
    report['pricing_source']='https://api-docs.deepseek.com/quick_start/pricing/'
    report['pricing_note']='Peak-rate reservation and cost upper bound; not an account billing receipt.'
    write('preflight.json',report)
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
