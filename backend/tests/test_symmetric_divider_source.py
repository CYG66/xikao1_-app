import json
from pathlib import Path
from copy import deepcopy
import pytest
from app.cad_construction_interpreter import interpret_construction_request

ROW=json.loads((Path(__file__).parent/'fixtures/recorded_symmetric_divider.json').read_text(encoding='utf-8'))
def run(source,plan=None):
    return interpret_construction_request(source,lambda *_:{
        'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
        'plan':deepcopy(plan or ROW['plan']),'confidence':.99,'evidence_text':[source],'assumptions':[]},force_structured_model=True)

@pytest.mark.parametrize('extra',[False,True])
def test_recorded_native_geometry_proves_entire_source(extra):
    source='\n'.join([ROW['original'],*(ROW['followups'] if extra else [])])
    result=run(source)
    assert result['status']=='ready',result.get('error')
    assert result['acceptance_summary']['status']=='passed',result['source_acceptance']
    assert run(source+'，再添加文字')['acceptance_summary']['status']!='passed'

@pytest.mark.parametrize('damage',['disconnect','same_bend','dot_position','dot_size','outer_radius'])
def test_incorrect_structure_still_fails(damage):
    plan=deepcopy(ROW['plan'])
    if damage=='disconnect':plan['steps'][1]['center']['y']+=.1
    elif damage=='same_bend':plan['steps'][2]['start_angle']=90;plan['steps'][2]['end_angle']=270
    elif damage=='dot_position':plan['steps'][3]['center']['x']+=.1
    elif damage=='dot_size':plan['steps'][3]['radius']*=1.2
    else:plan['steps'][0]['radius']=1.9
    assert run(ROW['original'],plan)['status']=='invalid'
