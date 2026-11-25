from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import interpret_construction_request, construction_acceptance_summary
from app.cad_semantic_acceptance import verify_semantic_requirements
from app.cad_structure_contract import StructureContractError

ROWS = {row['case']: row for row in json.loads((Path(__file__).parent / 'fixtures' /
                 'recorded_measured_semantics.json').read_text(encoding='utf-8'))}


def interpret(row, source=None):
    return interpret_construction_request(source or row['source'], lambda *_: {
        'schema_version': 'cad.construction-interpretation.v1',
        'is_construction_request': True, 'confidence': .99,
        'evidence_text': [row['original']], 'plan': deepcopy(row['plan']),
    })


@pytest.mark.parametrize('case', ['C5', 'C29', 'C32'])
def test_existing_measurements_prove_fully_consumed_sources_and_persist(case, tmp_path):
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    row = ROWS[case]
    result = interpret(row)
    assert result['status'] == 'ready', result.get('error')
    assert result['acceptance_summary']['status'] == 'passed'
    store = CreativeProjectStore(tmp_path / 'projects.json')
    saved = commit_construction_interpretation(row['source'], result, store=store)
    variant = store.get(saved['project_id'])['variants'][0]
    proof = variant['construction_record']['source_acceptance']['semantic_source_acceptance']
    assert proof['coverage'] == 'complete' and proof['checks']


def test_historical_half_size_hexagon_is_rejected_by_actual_side_length():
    result = interpret(ROWS['C13'])
    assert result['status'] == 'invalid'
    from app.cad_source_acceptance import verify_final_source_contract
    gs = execute_construction_plan(ROWS['C13']['plan'])['geometries']
    with pytest.raises(StructureContractError) as caught:
        verify_final_source_contract(ROWS['C13']['source'], gs)
    check = next(c for c in caught.value.details['failures'] if c['field'] == 'side_length')
    assert check['expected_mm'] == 1000
    assert check['actual_mm'] == pytest.approx(500)


@pytest.mark.parametrize('case', ['C5', 'C29', 'C32'])
@pytest.mark.parametrize('extra', ['，再画一个圆', '，旋转30度', '，整体向右平移1米',
                                  '，面积等于5平方米', '，添加尺寸标注'])
def test_local_semantic_success_never_consumes_unknown_extra_clauses(case, extra):
    result = interpret(ROWS[case], ROWS[case]['source'] + extra)
    assert result.get('acceptance_summary', {}).get('status') != 'passed'


@pytest.mark.parametrize('extra', ['，外接圆半径2米', '，边长2米', '，中心圆孔半径0.2米'])
def test_conflicting_or_unmeasured_polygon_dimensions_do_not_gain_complete_coverage(extra):
    result = interpret(ROWS['C32'], ROWS['C32']['source'] + extra)
    assert result.get('acceptance_summary', {}).get('status') != 'passed'


@pytest.mark.parametrize('mutation', ['extra', 'bulge', 'hole_outside'])
def test_regular_polygon_measurement_requires_exact_inventory_and_straight_containment(mutation):
    row = ROWS['C32' if mutation == 'hole_outside' else 'C5']
    gs = execute_construction_plan(row['plan'])['geometries']
    source = row['source']
    if mutation == 'extra':
        gs.append({'id': 99, 'type': 'circle', 'center': {'x': 0, 'y': 0}, 'radius': 100})
    elif mutation == 'bulge': gs[0]['vertices'][0]['bulge'] = .3
    else:
        source = source.replace('0.8米', '1.4米')
        gs[1]['radius'] = 1400
    with pytest.raises(StructureContractError):
        verify_semantic_requirements(source, gs)


def test_nested_square_measurement_does_not_accept_a_curved_boundary():
    gs = execute_construction_plan(ROWS['C29']['plan'])['geometries']
    gs[1]['vertices'][0]['bulge'] = .5
    with pytest.raises(StructureContractError):
        verify_semantic_requirements(ROWS['C29']['source'], gs)


@pytest.mark.parametrize('n', [3, 4, 5, 6, 8])
def test_regular_polygon_side_relation_is_generic_and_measured(n):
    radius = 1000 / (2 * math.sin(math.pi / n))
    geometry = {'id': 1, 'type': 'polyline', 'closed': True, 'vertices': [
        {'x': radius * math.cos(i * math.tau / n), 'y': radius * math.sin(i * math.tau / n)}
        for i in range(n)]}
    source = f'画一个正{n}边形，边长1米'
    assert verify_semantic_requirements(source, [geometry])['status'] == 'passed'
    geometry['vertices'][0]['x'] += 10
    with pytest.raises(StructureContractError):
        verify_semantic_requirements(source, [geometry])


@pytest.mark.parametrize('nested', [False, True])
def test_a_failed_independent_check_cannot_hide_behind_another_passed_check(nested):
    report = {'coverage': 'complete', 'checks': [{'status': 'passed'}, {'status': 'failed'}]}
    if nested:
        report = {'coverage': 'complete', 'checks': [{'status': 'passed'}], 'semantic_acceptance': report}
    summary = construction_acceptance_summary(preflight_structure=None, structure_contract=None,
        structure_validation=None, composition_contract=None, composition_validation=None,
        source_acceptance=report, trial_result={'feasibility': {'ok': True}})
    assert summary['status'] == 'review_required'
    assert summary['failed_checks']
