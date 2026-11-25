from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_structure_contract import explicit_composition, StructureContractError

RECORDED = json.loads((Path(__file__).parent / 'fixtures' /
                       'recorded_rectangle_handoff.json').read_text(encoding='utf-8'))


def interpret(source, plan):
    return interpret_construction_request(source, lambda *_: {
        'schema_version': 'cad.construction-interpretation.v1',
        'is_construction_request': True, 'confidence': .99,
        'evidence_text': [source], 'plan': plan,
    }, force_structured_model=True)


def test_recorded_rectangle_delivers_measured_evidence_to_saved_candidate(tmp_path):
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    row = RECORDED[0]
    result = interpret(row['source'], row['plan'])
    assert result['status'] == 'ready', result.get('error')
    assert result['acceptance_summary']['status'] == 'passed'
    store = CreativeProjectStore(tmp_path / 'projects.json')
    saved = commit_construction_interpretation(row['source'], result, store=store)
    variant = store.get(saved['project_id'])['variants'][0]
    proof = variant['construction_record']['source_acceptance']['rectangle_acceptance']
    assert proof['coverage'] == 'complete'
    assert {check['field'] for check in proof['checks']} >= {
        'single_rectangle_shape_and_count', 'width', 'height'}
    assert variant['acceptance_summary']['status'] == 'passed'


@pytest.mark.parametrize('source', [
    '画一个圆角矩形，宽3米高2米，圆角半径0.5米',
    RECORDED[1]['source'],
    '画一个矩形，四个角做圆弧过渡，半径0.5米',
    '画一个矩形，四角不要放圆',
    '画一个矩形，四个角不放圆',
    '不要在矩形四角各放一个圆',
    '画矩形，禁止在四个角各画一个圆',
])
def test_rounding_or_negative_instruction_is_not_corner_circle_placement(source):
    contract = explicit_composition(source)
    assert contract is None or contract['kind'] != 'corner_placement'


@pytest.mark.parametrize('source', [
    '画一个矩形，四个角各放一个半径0.5米的圆',
    '矩形四角各绘制一个圆',
    '矩形四个角上分别放置一个圆形',
])
def test_explicit_circle_placement_still_uses_existing_composition_validator(source):
    assert explicit_composition(source)['kind'] == 'corner_placement'


def test_recorded_five_part_rounded_rectangle_is_never_accepted_as_rounding(tmp_path):
    from app.cad_construction_commit import commit_construction_interpretation
    from app.cad_candidate_state import candidate_is_accepted, accepted_project_view
    from app.creative_projects import CreativeProjectStore
    row = RECORDED[1]
    result = interpret(row['source'], row['plan'])
    assert result['status'] == 'ready', result.get('error')
    assert result['acceptance_summary']['status'] == 'review_required'
    assert result['source_acceptance']['coverage'] != 'complete'
    # Existing policy permits a persisted review draft; it must never become
    # an accepted candidate or appear in the accepted project view.
    store = CreativeProjectStore(tmp_path / 'projects.json')
    saved = commit_construction_interpretation(row['source'], result, store=store)
    project = store.get(saved['project_id'])
    variant = project['variants'][0]
    assert variant['acceptance_summary']['status'] == 'review_required'
    assert not candidate_is_accepted(variant)
    assert accepted_project_view(project)['variants'] == []


def rectangle():
    return execute_construction_plan(RECORDED[0]['plan'])['geometries'][0]


@pytest.mark.parametrize('source', [
    RECORDED[0]['original'], RECORDED[0]['source'],
    '请绘制一个长方形，宽500厘米、高3000mm。',
    '创建矩形，宽度5m，高度3m，单位m',
])
def test_single_rectangle_source_is_fully_consumed_and_measured(source):
    from app.cad_rectangle_acceptance import verify_single_rectangle
    proof = verify_single_rectangle(source, [rectangle()])
    assert proof['coverage'] == 'complete'
    assert all(check['status'] == 'passed' for check in proof['checks'])


@pytest.mark.parametrize('extra', [
    '，再画一个圆', '，向右移动1米', '，旋转30度', '，圆角半径0.5米',
    '，中心位于(1,2)', '，不要闭合', '，宽不超过6米', '，标注尺寸',
    '，矩形面积等于15平方米', '，矩形和矩形',
])
def test_additional_unmeasured_requirements_keep_partial_coverage(extra):
    from app.cad_rectangle_acceptance import verify_single_rectangle
    assert verify_single_rectangle(RECORDED[0]['original'] + extra,
                                   [rectangle()])['coverage'] == 'partial'


@pytest.mark.parametrize('source', [
    '画矩形，宽5米高3米，宽4米', '画矩形，宽5米高3米\n宽4米',
    '画矩形，宽0米高3米', '画矩形，宽-5米高3米', '画矩形，宽5米',
])
def test_conflicting_or_incomplete_source_does_not_claim_full_coverage(source):
    from app.cad_rectangle_acceptance import verify_single_rectangle
    assert verify_single_rectangle(source, [rectangle()])['coverage'] == 'partial'


@pytest.mark.parametrize('mutation', [
    'width', 'height', 'extra', 'open', 'bowtie', 'triangle', 'trapezoid',
    'curved', 'degenerate', 'type',
])
def test_same_bounds_and_model_labels_cannot_prove_rectangle_identity(mutation):
    from app.cad_rectangle_acceptance import verify_single_rectangle
    g = rectangle()
    gs = [g]
    if mutation == 'width': g['vertices'][1]['x'] -= 20
    elif mutation == 'height':
        for p in g['vertices']: p['y'] *= .9
    elif mutation == 'extra': gs.append({**deepcopy(g), 'id': 999})
    elif mutation == 'open': g['closed'] = False
    elif mutation == 'bowtie': g['vertices'][1], g['vertices'][2] = g['vertices'][2], g['vertices'][1]
    elif mutation == 'triangle': g['vertices'].pop()
    elif mutation == 'trapezoid': g['vertices'][2]['x'] -= 1000
    elif mutation == 'curved': g['vertices'][0]['bulge'] = .5
    elif mutation == 'degenerate': g['vertices'][1] = deepcopy(g['vertices'][0])
    elif mutation == 'type': g['type'] = 'spline'
    with pytest.raises(StructureContractError):
        verify_single_rectangle(RECORDED[0]['original'], gs)


def test_rectangle_measurement_is_independent_of_order_origin_and_plan_assertions():
    from app.cad_rectangle_acceptance import verify_single_rectangle
    g = rectangle()
    g['vertices'].reverse()
    for point in g['vertices']:
        point['x'] += 124
        point['y'] -= 246
    assert verify_single_rectangle(RECORDED[0]['original'], [g])['coverage'] == 'complete'
    plan = deepcopy(RECORDED[0]['plan'])
    plan['assertions'] = []
    result = interpret(RECORDED[0]['original'], plan)
    assert result['source_acceptance']['rectangle_acceptance']['coverage'] == 'complete'
