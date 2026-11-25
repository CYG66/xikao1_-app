import json
from pathlib import Path
from copy import deepcopy
import pytest
from app.cad_construction_interpreter import interpret_construction_request

ROW=json.loads((Path(__file__).parent/'fixtures/recorded_radial_attachments.json').read_text(encoding='utf-8'))

def interpret(source,plan=None):
    return interpret_construction_request(source,lambda *_:{
        'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
        'plan':deepcopy(plan or ROW['plan']),'confidence':.99,'evidence_text':[source],'assumptions':[]},
        force_structured_model=True)

@pytest.mark.parametrize('supplement',[False,True])
def test_recorded_circle_and_spokes_deliver_only_with_complete_source(supplement):
    source='\n'.join([ROW['original'],*(ROW['followups'] if supplement else [])])
    result=interpret(source)
    assert result['status']=='ready',result.get('error')
    assert result['acceptance_summary']['status']=='passed',result['source_acceptance']
    assert interpret(source+'，增加一条连接桥')['acceptance_summary']['status']!='passed'

@pytest.mark.parametrize('mutation',['floating','inward','wrong_length','duplicate','extra','wrong_radius'])
def test_geometric_errors_remain_rejected(mutation):
    plan=deepcopy(ROW['plan']);line=plan['steps'][1]
    if mutation=='floating':line['start']['y']+=.1;line['end']['y']+=.1
    elif mutation=='inward':line['end']['y']=1
    elif mutation=='wrong_length':line['end']['y']+=.1
    elif mutation=='duplicate':plan['steps'][2]['start']=deepcopy(line['start']);plan['steps'][2]['end']=deepcopy(line['end'])
    elif mutation=='wrong_radius':plan['steps'][0]['radius']=2.9
    else:
        extra=deepcopy(line);extra.update(step_id='extra',output_ref='extra');extra['semantic']['object_id']='extra';plan['steps'].append(extra)
    assert interpret(ROW['original'],plan)['status']=='invalid'
