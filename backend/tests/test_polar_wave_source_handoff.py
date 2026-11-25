from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from app.cad_construction_interpreter import interpret_construction_request
from app.cad_parametric import polar_requirements, verify_polar_requirements, ParametricError
from app.cad_curve_fit_acceptance import verify_cardioid, verify_astroid

ROWS = {row['case']: row for row in json.loads((Path(__file__).parent / 'fixtures' /
                  'recorded_polar_wave_source.json').read_text(encoding='utf-8'))}


def interpret(case, extra='', plan=None):
    row=ROWS[case]
    return interpret_construction_request(row['source']+extra, lambda *_: {
        'schema_version':'cad.construction-interpretation.v1',
        'is_construction_request':True,'confidence':.99,
        'evidence_text':[row['original']],'plan':deepcopy(plan or row['plan']),
    })


@pytest.mark.parametrize('case', ['C12','C19'])
def test_existing_curve_measurements_deliver_and_persist_source_proof(case,tmp_path):
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    result=interpret(case)
    assert result['status']=='ready',result.get('error')
    assert result['acceptance_summary']['status']=='passed'
    store=CreativeProjectStore(tmp_path/'projects.json')
    saved=commit_construction_interpretation(ROWS[case]['source'],result,store=store)
    assert store.get(saved['project_id'])['variants'][0]['acceptance_summary']['status']=='passed'


@pytest.mark.parametrize('case', ['C12','C19'])
@pytest.mark.parametrize('extra', ['，再画一个圆','，整体向右平移1米','，标注全部尺寸','，面积10平方米'])
def test_partial_curve_proofs_cannot_consume_extra_requirements(case,extra):
    assert interpret(case,extra).get('acceptance_summary',{}).get('status')!='passed'


@pytest.mark.parametrize('extra',['，旋转4圈','，最大半径3米','，顺时针旋转3圈','，半径从0线性增长到3米'])
def test_conflicting_spiral_restatements_never_gain_full_coverage(extra):
    assert interpret('C12',extra).get('acceptance_summary',{}).get('status')!='passed'


def test_sparse_spiral_chords_are_not_proven_by_correct_vertices_alone():
    source=ROWS['C12']['source']
    gs=[{'id':1,'type':'polyline','closed':False,'vertices':[
        {'x':2000*i/24*math.cos(i*math.pi/4),
         'y':2000*i/24*math.sin(i*math.pi/4)} for i in range(25)]}]
    with pytest.raises(ParametricError):
        verify_polar_requirements(polar_requirements(source),gs)


def test_sparse_cardioid_chords_are_not_proven_by_correct_vertices_alone():
    points=[(1000*(1+math.cos(t))*math.cos(t),1000*(1+math.cos(t))*math.sin(t))
            for t in [i*math.tau/20 for i in range(20)]]
    g={'id':1,'type':'polyline','closed':True,'vertices':[{'x':x,'y':y} for x,y in points]}
    assert not verify_cardioid(g)['passed']


@pytest.mark.parametrize('kind',['cardioid','astroid'])
def test_retracing_a_closed_identity_twice_does_not_make_one_valid_boundary(kind):
    points=[]
    for i in range(256):
        t=i*math.tau/256
        x,y=((1000*(1+math.cos(t))*math.cos(t),1000*(1+math.cos(t))*math.sin(t))
             if kind=='cardioid' else (2000*math.cos(t)**3,2000*math.sin(t)**3))
        points.append({'x':x,'y':y})
    g={'id':1,'type':'polyline','closed':True,'vertices':points+deepcopy(points)}
    assert not (verify_cardioid(g) if kind=='cardioid' else verify_astroid(g,2000))['passed']


def test_historical_half_amplitude_wave_is_rejected():
    result=interpret('C11')
    assert result['status']=='invalid'
    assert '振幅' in result['error']['message']


def test_measured_sine_can_accept_correct_amplitude_without_any_new_generator():
    plan=deepcopy(ROWS['C11']['plan'])
    plan['steps'][0]['y_expression']='0.5*sin(2*pi*t)'
    result=interpret('C11',plan=plan)
    assert result['status']=='ready',result.get('error')
    assert result['acceptance_summary']['status']=='passed'


def test_conflicting_model_helper_is_removed_only_after_geometry_proof():
    from app.cad_construction import execute_construction_plan
    plan=deepcopy(ROWS['C11']['plan'])
    plan['steps'][0]['y_expression']='0.5*sin(2*pi*t)'
    result=interpret('C11',plan=plan)
    repair=next(r for r in result['deterministic_repairs']
                if r['kind']=='source_wave_acceptance_replaces_unrequested_bounds')
    assert repair['geometry_unchanged'] and repair['all_acceptance_reexecuted']
    plan['assertions']=[]
    assert result['trial_result']['geometries']==execute_construction_plan(plan)['geometries']


def test_actual_user_height_is_never_removed_as_an_unrequested_helper():
    plan=deepcopy(ROWS['C11']['plan'])
    plan['steps'][0]['y_expression']='0.5*sin(2*pi*t)'
    result=interpret('C11','，整体高度0.5米',plan=plan)
    assert result['status']=='invalid'


def test_wave_normalization_explains_amplitude_and_wavelength_to_the_planner():
    from app.cad_construction_interpreter import normalize_construction_request
    _,facts=normalize_construction_request(ROWS['C11']['source'])
    assert any('振幅' in fact and '峰谷' in fact and '波距' in fact for fact in facts)
