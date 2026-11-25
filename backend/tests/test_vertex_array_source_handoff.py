from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_structure_contract import StructureContractError

ROWS = json.loads((Path(__file__).parent / 'fixtures' /
                   'recorded_vertex_array_handoff.json').read_text(encoding='utf-8'))


def interpret(source, plan):
    return interpret_construction_request(source, lambda *_: {
        'schema_version': 'cad.construction-interpretation.v1',
        'is_construction_request': True, 'confidence': .99,
        'evidence_text': [source], 'plan': plan,
    })


@pytest.mark.parametrize('row', ROWS, ids=lambda row: row['case'])
def test_historical_plan_delivers_source_evidence_and_survives_commit(row, tmp_path):
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    result = interpret(row['source'], row['plan'])
    assert result['status'] == 'ready', result.get('error')
    assert result['acceptance_summary']['status'] == 'passed'
    store = CreativeProjectStore(tmp_path / 'projects.json')
    saved = commit_construction_interpretation(row['source'], result, store=store)
    variant = store.get(saved['project_id'])['variants'][0]
    assert variant['acceptance_summary']['status'] == 'passed'
    assert variant['construction_record']['source_acceptance']['coverage'] == 'complete'


@pytest.mark.parametrize('extra', [
    '，再画一个圆', '，中心在(1,1)', '，旋转30度', '，所有边长相等',
    '，各顶点做圆角', '，面积5平方米', '，宽度为10米',
])
def test_vertex_coordinates_do_not_override_unmeasured_requirements(extra):
    from app.cad_vertex_acceptance import verify_vertex_path
    gs = execute_construction_plan(ROWS[0]['plan'])['geometries']
    assert verify_vertex_path(ROWS[0]['source'] + extra, gs)['coverage'] == 'partial'


@pytest.mark.parametrize('mutation', ['vertex', 'open', 'extra', 'bulge', 'type'])
def test_vertex_path_measures_actual_geometry(mutation):
    from app.cad_vertex_acceptance import verify_vertex_path
    gs = execute_construction_plan(ROWS[0]['plan'])['geometries']
    if mutation == 'vertex': gs[0]['vertices'][0]['x'] += 5
    elif mutation == 'open': gs[0]['closed'] = False
    elif mutation == 'extra': gs.append({**deepcopy(gs[0]), 'id': 99})
    elif mutation == 'bulge': gs[0]['vertices'][0]['bulge'] = .5
    else: gs[0]['type'] = 'spline'
    with pytest.raises(StructureContractError):
        verify_vertex_path(ROWS[0]['source'], gs)


def test_closed_vertex_cycle_can_start_anywhere_and_reverse():
    from app.cad_vertex_acceptance import verify_vertex_path
    gs = execute_construction_plan(ROWS[0]['plan'])['geometries']
    gs[0]['vertices'] = list(reversed(gs[0]['vertices'][1:] + gs[0]['vertices'][:1]))
    assert verify_vertex_path(ROWS[0]['source'], gs)['coverage'] == 'complete'


@pytest.mark.parametrize('source', [
    '画三角形，顶点(0,0)(3,0)(1.5,2.6)，闭合',
    ROWS[0]['source'] + '，坐标单位毫米',
    ROWS[0]['source'] + '，使用四个顶点',
    '画三角形，顶点(0,0)(1,0)(2,0)，坐标单位米，闭合',
    '画多边形，顶点(0,0)(1,1)(0,1)(1,0)，坐标单位米，闭合',
])
def test_ambiguous_units_counts_and_invalid_source_vertices_keep_partial(source):
    from app.cad_vertex_acceptance import verify_vertex_path
    gs = execute_construction_plan(ROWS[0]['plan'])['geometries']
    assert verify_vertex_path(source, gs)['coverage'] == 'partial'


@pytest.mark.parametrize('extra', [
    '，行距1米', '，每个矩形宽2米，然后宽1米', '，整体旋转30度',
    '，净距1.2米', '，2行5列',
])
def test_array_restatement_never_hides_conflicts_or_unknown_relations(extra):
    from app.cad_composition_coverage import verify_composition_coverage
    gs = execute_construction_plan(ROWS[1]['plan'])['geometries']
    assert verify_composition_coverage(ROWS[1]['source'] + extra, gs)['coverage'] == 'partial'


def bezier_plan():
    return {'units': 'm', 'steps': [{
        'op': 'add_composite_path', 'step_id': 'curve', 'output_ref': 'curve',
        'semantic': {'label': '曲线'}, 'closed': False, 'continuity': 'C1',
        'segments': [{'kind': 'bezier', 'control_points': [
            {'x': offset + x, 'y': 0} for x in (0, 1, 2, 3)]}
            for offset in (0, 3)],
    }]}


@pytest.mark.parametrize('extra', ['', '，另画一个圆', '，经过(9,9)', '，曲线下方加矩形'])
def test_bezier_segment_count_cannot_prove_an_entire_unconsumed_request(extra):
    source = '画一条2段三次Bezier组成的开放式曲线，C1连续，不自交，单位米' + extra
    result = interpret(source, bezier_plan())
    assert result['status'] == 'ready', result.get('error')
    # Segment count and continuity are useful measurements, but full source
    # coverage must come from a verifier that actually consumes the source.
    assert result['acceptance_summary']['status'] == 'review_required'
