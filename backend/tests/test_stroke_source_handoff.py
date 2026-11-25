from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_stroke_acceptance import verify_stroke_requirements
from app.cad_structure_contract import StructureContractError

ROW = json.loads((Path(__file__).parent / 'fixtures' / 'recorded_stroke_source.json').read_text(encoding='utf-8'))


def interpret(source):
    return interpret_construction_request(source, lambda *_: {
        'schema_version': 'cad.construction-interpretation.v1',
        'is_construction_request': True, 'confidence': .99,
        'evidence_text': [ROW['original']], 'plan': deepcopy(ROW['plan']),
    })


def test_recorded_explicit_strokes_deliver_and_preserve_full_source_proof(tmp_path):
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    result = interpret(ROW['source'])
    assert result['status'] == 'ready', result.get('error')
    assert result['acceptance_summary']['status'] == 'passed'
    store = CreativeProjectStore(tmp_path / 'projects.json')
    saved = commit_construction_interpretation(ROW['source'], result, store=store)
    proof = store.get(saved['project_id'])['variants'][0]['construction_record']['source_acceptance']['stroke_source_acceptance']
    assert proof['coverage'] == 'complete'
    assert proof['checks']


@pytest.mark.parametrize('extra', ['，再画一个圆', '，旋转30度', '，笔画宽度0.1米',
                                  '，标注高度', '，向右移动1米', '，坐标单位厘米'])
def test_explicit_stroke_measurements_cannot_consume_unverified_additional_requests(extra):
    result = interpret(ROW['source'] + extra)
    assert result.get('acceptance_summary', {}).get('status') != 'passed'


@pytest.mark.parametrize('mutation', ['duplicate_entity', 'retraced_polyline', 'bulge'])
def test_union_of_linework_cannot_hide_duplicate_or_curved_strokes(mutation):
    gs = execute_construction_plan(ROW['plan'])['geometries']
    if mutation == 'duplicate_entity': gs.append({**deepcopy(gs[0]), 'id': 99})
    elif mutation == 'retraced_polyline':
        line = gs[0]
        gs[0] = {'id': line['id'], 'type': 'polyline', 'closed': False,
                 'vertices': [line['start'], line['end'], line['start']]}
    else:
        line = gs[0]
        gs[0] = {'id': line['id'], 'type': 'polyline', 'closed': False,
                 'vertices': [{**line['start'], 'bulge': .5}, line['end']]}
    with pytest.raises(StructureContractError):
        verify_stroke_requirements(ROW['source'], gs)


def test_final_scalar_scope_binds_all_parts_of_one_exact_assembly():
    from app.cad_source_acceptance import verify_final_source_contract
    trial = execute_construction_plan(ROW['plan'])
    report = verify_final_source_contract(ROW['source'], trial['geometries'], trial['logical_objects'])
    assert report['checks'] and not report['unknown_requirements']
    assert all(set(c['geometry_ids']) == {1, 2, 3} for c in report['checks'])
    wrong = deepcopy(trial['geometries'])
    wrong[0]['start']['x'] -= 100
    with pytest.raises(StructureContractError):
        verify_final_source_contract(ROW['source'], wrong, trial['logical_objects'])


@pytest.mark.parametrize('mutation', ['ambiguous_assembly', 'missing_member_refs', 'stale_refs'])
def test_assembly_binding_never_discards_ambiguous_or_missing_members(mutation):
    from app.cad_source_acceptance import verify_final_source_contract
    trial = execute_construction_plan(ROW['plan'])
    objects = deepcopy(trial['logical_objects'])
    if mutation == 'ambiguous_assembly':
        objects.append({**deepcopy(objects[0]), 'object_id': 'other', 'assembly_id': 'other'})
    elif mutation == 'missing_member_refs': objects[0]['geometry_refs'] = []
    else: objects[0]['geometry_refs'] = [999]
    report = verify_final_source_contract(ROW['source'], trial['geometries'], objects)
    assert report['review_required'] and report['unknown_requirements']
