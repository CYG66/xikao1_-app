from copy import deepcopy
import json
from pathlib import Path
import pytest
from evaluations.heart_acceptance_candidate_v1 import compare

ROWS={r['response_index']:r for r in json.loads((Path(__file__).parent/'fixtures/recorded_shallow_notch_audit.json').read_text(encoding='utf-8'))}


@pytest.mark.parametrize('index',[3,5])
def test_shallow_notch_candidate_is_separate_from_legacy_and_preserves_geometry(index):
    row=ROWS[index];before=deepcopy(row)
    result=compare(row['source'],row['payload'])
    assert row==before
    assert not result['legacy_passed'] and result['candidate_passed']
    assert result['geometry_unchanged']
    assert not result['formal_candidate_accepted']


@pytest.mark.parametrize('extra',['，凹口深度0.1米','，凹陷要浅一些','，notch depth 10cm'])
def test_explicit_notch_requirements_never_use_default_relation(extra):
    row=ROWS[3];result=compare(row['source']+extra,row['payload'])
    assert result['candidate_status']=='unsupported'
    assert not result['candidate_passed']


def test_central_peak_still_fails():
    row=ROWS[7];result=compare(row['source'],row['payload'])
    assert not result['candidate_passed']


def test_unknown_source_clause_still_fails():
    row=ROWS[3];result=compare(row['source']+'，面积123平方米',row['payload'])
    assert not result['candidate_passed']


@pytest.mark.parametrize('kind',['u_shape','oval','self_intersection'])
def test_full_candidate_rejects_nonheart_outlines(kind):
    import math
    row=ROWS[3];payload=deepcopy(row['payload']);old=payload['plan']['steps'][0]
    if kind=='u_shape':
        points=[(0,1),(0,5),(1,5),(1,2),(3,2),(3,5),(4,5),(4,1)]
    elif kind=='oval':
        points=[(2+2*math.cos(i*math.pi/32),3+2*math.sin(i*math.pi/32)) for i in range(64)]
    else:
        points=[(0,1),(4,5),(0,5),(4,1)]
    payload['plan']['steps']=[{'step_id':old['step_id'],'output_ref':old['output_ref'],
        'semantic':old['semantic'],'op':'add_polyline','closed':True,
        'vertices':[{'x':x,'y':y} for x,y in points]}]
    payload['plan']['assertions']=[]
    assert not compare(row['source'],payload)['candidate_passed']
