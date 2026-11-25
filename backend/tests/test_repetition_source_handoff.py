from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_repetition_acceptance import verify_repetition_requirements
from app.cad_structure_contract import StructureContractError

ROWS = {row['case']: row for row in json.loads((Path(__file__).parent / 'fixtures' /
                  'recorded_repetition_source.json').read_text(encoding='utf-8'))}


def interpret(row, source=None, plan=None):
    return interpret_construction_request(source or row['source'], lambda *_: {
        'schema_version': 'cad.construction-interpretation.v1',
        'is_construction_request': True, 'confidence': .99,
        'evidence_text': [row['original']], 'plan': deepcopy(plan or row['plan']),
    })


@pytest.mark.parametrize('case', ['C23', 'C30'])
def test_recorded_repetition_can_deliver_and_persist_full_source_proof(case, tmp_path):
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    row = ROWS[case]
    result = interpret(row)
    assert result['status'] == 'ready', result.get('error')
    assert result['acceptance_summary']['status'] == 'passed'
    store = CreativeProjectStore(tmp_path / 'projects.json')
    saved = commit_construction_interpretation(row['source'], result, store=store)
    proof = store.get(saved['project_id'])['variants'][0]['construction_record']['source_acceptance']['repetition_source_acceptance']
    assert proof['coverage'] == 'complete' and proof['checks']


@pytest.mark.parametrize('case', ['C23', 'C30'])
@pytest.mark.parametrize('extra', ['，另外画一个圆', '，旋转30度', '，标注全部尺寸',
                                  '，整体向右平移1米', '，面积10平方米'])
def test_partial_repetition_measurements_do_not_hide_unconsumed_source(case, extra):
    result = interpret(ROWS[case], ROWS[case]['source'] + extra)
    assert result.get('acceptance_summary', {}).get('status') != 'passed'


@pytest.mark.parametrize('extra', ['，4级', '，每级宽0.5米高0.3米',
                                  '，每级水平0.4米、竖直0.5米', '，坐标单位毫米'])
def test_conflicting_step_restatements_cannot_gain_complete_coverage(extra):
    result = interpret(ROWS['C23'], ROWS['C23']['source'] + extra)
    assert result.get('acceptance_summary', {}).get('status') != 'passed'


@pytest.mark.parametrize('mutation', ['direction', 'origin'])
def test_step_origin_and_direction_are_independent_source_constraints(mutation):
    row = ROWS['C23']
    plan = deepcopy(row['plan'])
    for point in plan['steps'][0]['vertices']:
        if mutation == 'direction': point['y'] *= -1
        else: point['x'] += 1
    result = interpret(row, plan=plan)
    assert result['status'] == 'invalid'


@pytest.mark.parametrize('mutation', ['bowtie', 'bulge'])
def test_strip_bounds_and_dimensions_cannot_prove_valid_rectangles(mutation):
    row = ROWS['C30']
    gs = execute_construction_plan(row['plan'])['geometries']
    if mutation == 'bowtie':
        gs[0]['vertices'][1], gs[0]['vertices'][2] = gs[0]['vertices'][2], gs[0]['vertices'][1]
    else: gs[0]['vertices'][0]['bulge'] = .5
    with pytest.raises(StructureContractError):
        verify_repetition_requirements(row['source'], gs)


def test_step_linework_cannot_be_curved_even_with_correct_vertex_deltas():
    row = ROWS['C23']
    gs = execute_construction_plan(row['plan'])['geometries']
    gs[0]['vertices'][0]['bulge'] = .5
    with pytest.raises(StructureContractError):
        verify_repetition_requirements(row['source'], gs)


def test_closed_step_base_cannot_retrace_the_first_tread():
    row = ROWS['C23']
    gs = execute_construction_plan(row['plan'])['geometries']
    gs[0]['vertices'][-1] = {'x': 2000, 'y': 0}
    with pytest.raises(StructureContractError, match='自交'):
        verify_repetition_requirements(row['source'], gs)


@pytest.mark.parametrize('extra', ['，5条平行横线', '，每条长3米宽0.4米',
                                  '，中心距0.6米', '，间距0.2米'])
def test_strip_count_dimensions_and_spacing_reference_must_all_match(extra):
    result = interpret(ROWS['C30'], ROWS['C30']['source'] + extra)
    assert result.get('acceptance_summary', {}).get('status') != 'passed'
