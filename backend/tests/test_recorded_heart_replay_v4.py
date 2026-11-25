import json
from evaluations.replay_recorded_hearts_v4 import collect


def test_replay_never_uses_future_followups_or_assistant_assumptions(tmp_path):
    confirmation='确认需求并生成CAD候选，只预览，不执行小车。'
    for turn,request in [(1,{'message':'生成平滑爱心','history':[]}),
        (3,{'message':confirmation,'history':[{'role':'user','content':'生成平滑爱心'},
            {'role':'assistant','content':'底部尖点为建模假设'}, {'role':'user','content':'中心(2,3)，宽4米、高4米'}]})]:
        (tmp_path/f'request-{turn}.json').write_text(json.dumps(request),encoding='utf-8')
    lines=[{'step':1,'response':json.dumps({'plan':{'steps':[]}})},
        {'step':3,'response':json.dumps({'plan':{'steps':[]}})}, {'step':3,'response':'invalid'}]
    (tmp_path/'model-responses.jsonl').write_text('\n'.join(json.dumps(r) for r in lines),encoding='utf-8')
    records,skipped=collect(tmp_path)
    assert records[0]['source']=='生成平滑爱心'
    assert records[1]['source']=='生成平滑爱心\n中心(2,3)，宽4米、高4米'
    assert records[0]['fingerprint']!=records[1]['fingerprint']
    assert skipped==[{'response_index':3,'reason':'not_json'}]
