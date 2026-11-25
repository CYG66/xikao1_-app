"""Restart the worker between edit turns; clients omit history and selection.

Uses an explicitly supplied saved production fixture as the baseline. Local
deterministic edits are not forced through an unnecessary model request.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import shutil

from tests.manual.run_user_cad_corpus import call,dump,bounds


def run(base,output):
    if output.exists():raise ValueError('Use a new output folder to preserve prior evidence')
    shutil.copytree(base,output)
    fixture=json.loads((base/'ui-fixture.json').read_text(encoding='utf-8'))
    messages=list(fixture['messages']);step=len(messages)
    initial=json.loads((base/f'step-{step}.json').read_text(encoding='utf-8'))
    before=deepcopy(initial['variant']);ids=[g['id'] for g in before['geometries']]
    selection={'scope':'group','geometry_ids':ids,'project_id':initial['project_id'],'variant_id':before['id']}
    question_text='把选中的图形旋转45度'
    request_path = base / 'request-1.json'
    if request_path.exists():
        original_request = json.loads(request_path.read_text(encoding='utf-8'))
        conversation = original_request['conversation_id']
    else:
        conversation = str(fixture.get('conversation_id') or 'cad-edit-context')
    question=call(output,step+1,{'message':question_text,'mode':'advanced','conversation_id':conversation,
        'project_id':initial['project_id'],'drawing_selection':selection})
    answer='改成30度，顺时针，以当前图形中心为基点'
    response=call(output,step+2,{'message':answer,'mode':'advanced','conversation_id':conversation})
    after=response.get('variant') or {};new={g['id']:g for g in after.get('geometries') or []}
    bb=bounds(before['geometries']);cx,cy=(bb[0]+bb[2])/2,(bb[1]+bb[3])/2
    theta=-math.pi/6
    def correct(g):
        target=new.get(g['id']) or {};points=g.get('vertices') or [];actual=target.get('vertices') or []
        return bool(points) and len(points)==len(actual) and all(math.dist(
            (q['x'],q['y']), (cx+(p['x']-cx)*math.cos(theta)-(p['y']-cy)*math.sin(theta),
                            cy+(p['x']-cx)*math.sin(theta)+(p['y']-cy)*math.cos(theta)))<.5
            for p,q in zip(points,actual))
    checks={'no_save_before_direction':(question.get('variant') or {}).get('id') in {None,before['id']},
        'same_project':response.get('project_id')==initial['project_id'],
        'new_saved_version':bool(after) and after.get('id')!=before['id'],
        'latest_30deg_clockwise':bool(new) and all(correct(g) for g in before['geometries']),
        'source_turns_preserved':(after.get('edit_plan') or {}).get('intent_grounding',{}).get('source_turns')==[question_text,answer],
        'ledger_preserves_raw_correction':[s.get('text') for s in (after.get('requirement_ledger') or {}).get('sources',[])][-2:]==[question_text,answer]}
    memory=json.loads((output/'conversation-memory.json').read_text(encoding='utf-8'))
    checks['pending_cleared']=not memory['conversations'][conversation].get('pending_cad_edit')
    report={'passed':all(checks.values()),'checks':checks,'reply':response.get('message'),
        'scope':'Production request handler; a fresh worker process per turn; no client history/selection on follow-up',
        'model_scope':'Previously generated baseline; deterministic edit policy retained'}
    dump(output/'context-acceptance.json',report)
    fixture.update(messages=messages+[question_text,answer],selection_before_step=step+1,
        drawing_selection=selection,expected_preview_count=len(response.get('preview_paths') or []))
    dump(output/'ui-fixture.json',fixture)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();print(json.dumps(run(Path(args.base),Path(args.output)),ensure_ascii=False))
