from copy import deepcopy
import json
from pathlib import Path
from app.cad_construction_interpreter import interpret_construction_request
ROW=json.loads((Path(__file__).parent/'fixtures/recorded_projection_dimension_snapshot.json').read_text(encoding='utf-8'))


def test_existing_side_length_does_not_gain_inferred_global_bounding_dimensions():
    snapshot={'original_prompt':ROW['original'],'requirements':deepcopy(ROW['requirements'])}
    text='[CAD_REQUIREMENT_CONTRACT_SNAPSHOT.v1]\n'+json.dumps(snapshot,ensure_ascii=False)
    seen=[]
    def model(prompt,schema):
        seen.append(prompt)
        return deepcopy(ROW['previous_success_payload'])
    result=interpret_construction_request(text,model,force_structured_model=True)
    assert result.get('acceptance_summary',{}).get('status')=='passed',result.get('construction_error') or result.get('error')
    tail=seen[0].split('[CAD_REQUIREMENT_CONTRACT_SNAPSHOT.v1]',1)[1].lstrip()
    cleaned,_=json.JSONDecoder().raw_decode(tail)
    assert 'width_m' not in cleaned['requirements']['dimensions']
    assert 'height_m' not in cleaned['requirements']['dimensions']
    constraints=json.loads(seen[0].split('[原文投影棱线约束，与独立测量使用同一来源；不提供生成坐标]\n',1)[1].split('\n',1)[0])
    assert constraints['projected_edge_length_mm']==2000
    assert constraints['edge_count']==12
    assert constraints['absolute_axis_dot_product']==0.5


def test_real_edge_length_error_is_still_rejected_after_false_dimension_is_removed():
    snapshot={'original_prompt':ROW['original'],'requirements':deepcopy(ROW['requirements'])}
    text='[CAD_REQUIREMENT_CONTRACT_SNAPSHOT.v1]\n'+json.dumps(snapshot,ensure_ascii=False)
    result=interpret_construction_request(text,lambda *_:deepcopy(ROW['payload']),force_structured_model=True)
    assert result['status']=='invalid'
    assert result['construction_error']['code']=='structure_requirement_failed'


def test_explicit_user_bounding_dimensions_still_apply():
    requirements=deepcopy(ROW['requirements'])
    requirements['source_followups'].append('整体宽度2米、高度2米。')
    text='[CAD_REQUIREMENT_CONTRACT_SNAPSHOT.v1]\n'+json.dumps({'original_prompt':ROW['original'],'requirements':requirements},ensure_ascii=False)
    result=interpret_construction_request(text,lambda *_:deepcopy(ROW['previous_success_payload']),force_structured_model=True)
    assert result.get('acceptance_summary',{}).get('status')!='passed'
