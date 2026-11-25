from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.cad_construction_interpreter import interpret_construction_request
from app.cad_construction import execute_construction_plan, ConstructionPlanError
from app.cad_semantic_source_coverage import verify_periodic_outline_source
from app.cad_source_acceptance import verify_final_source_contract
from app.cad_structure_contract import StructureContractError


ROWS = {r['case']: r for r in json.loads((Path(__file__).parent / 'fixtures' /
        'recorded_outline_delivery.json').read_text(encoding='utf-8'))}


def interpret(row, source=None):
    return interpret_construction_request(source or row['source'], lambda *_: {
        'schema_version': 'cad.construction-interpretation.v1', 'is_construction_request': True,
        'confidence': .99, 'evidence_text': [row['original']], 'plan': deepcopy(row['plan']),
    }, force_structured_model=True)


@pytest.mark.parametrize('case', ['C3', 'C6', 'C10'])
def test_recorded_outline_proves_source_and_persists(case, tmp_path):
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    row = ROWS[case]
    result = interpret(row)
    assert result['status'] == 'ready', result.get('error')
    assert result['acceptance_summary']['status'] == 'passed'
    store = CreativeProjectStore(tmp_path / 'projects.json')
    saved = commit_construction_interpretation(row['source'], result, store=store)
    variant = store.get(saved['project_id'])['variants'][0]
    assert variant['acceptance_summary']['status'] == 'passed'
    proof = {'C3': 'arch_source_acceptance', 'C6': 'periodic_source_acceptance',
             'C10': 'composition_acceptance'}[case]
    assert variant['construction_record']['source_acceptance'][proof]['coverage'] == 'complete'


@pytest.mark.parametrize('extra', ['，面积5平方米', '，中心位于(2,3)', '，整体旋转30度',
                                 '，再画一个圆', '，花瓣相同', '，曲线处处相切'])
def test_periodic_measurement_does_not_hide_unmeasured_clauses(extra):
    result = interpret(ROWS['C6'], ROWS['C6']['source'] + extra)
    assert result.get('acceptance_summary', {}).get('status') != 'passed'


@pytest.mark.parametrize('mutation', ['lobes', 'size', 'extra', 'open'])
def test_source_remeasures_periodic_geometry_without_plan_assertions(mutation):
    row = ROWS['C6']
    plan = deepcopy(row['plan']); plan['assertions'] = []
    gs = execute_construction_plan(plan)['geometries']
    source = row['source']
    if mutation == 'lobes': source = source.replace('5片', '6片')
    elif mutation == 'size': gs[0]['vertices'][0]['x'] += 5000
    elif mutation == 'extra': gs.append({**deepcopy(gs[0]), 'id': 2})
    else: gs[0]['closed'] = False
    try:
        result = verify_periodic_outline_source(source, gs)
    except (ConstructionPlanError, StructureContractError):
        return
    assert result['status'] != 'passed'


def test_concave_star_circumradius_binds_to_its_outer_hull():
    row = ROWS['C10']
    result = execute_construction_plan(row['plan'])
    proof = verify_final_source_contract(row['source'], result['geometries'], result['logical_objects'])
    assert not proof['unknown_requirements']
    check = next(c for c in proof['checks'] if c['field'] == 'circumradius')
    assert check['actual_mm'] == pytest.approx(2000)
    assert check['geometry_ids'] == [2]
    result['geometries'][1]['vertices'][0]['y'] += 100
    try:
        proof = verify_final_source_contract(row['source'], result['geometries'], result['logical_objects'])
    except StructureContractError:
        return
    assert proof['unknown_requirements']


@pytest.mark.parametrize('case', ['C3', 'C10'])
@pytest.mark.parametrize('extra', ['，面积5平方米', '，整体旋转30度', '，添加尺寸标注', '，再画一个圆'])
def test_outline_coverage_preserves_unknown_requirements(case, extra):
    result = interpret(ROWS[case], ROWS[case]['source'] + extra)
    assert result.get('acceptance_summary', {}).get('status') != 'passed'


@pytest.mark.parametrize('mutation', ['radius', 'leg', 'bottom', 'curve', 'sparse', 'open', 'bulge', 'extra'])
def test_arch_measurement_rejects_wrong_outline_without_model_assertions(mutation):
    from app.cad_semantic_source_coverage import verify_semicircular_outline_source
    row=ROWS['C3'];plan=deepcopy(row['plan']);plan['assertions']=[]
    gs=execute_construction_plan(plan)['geometries'];source=row['source']
    if mutation=='radius':source=source.replace('半径1米','半径0.8米')
    elif mutation=='leg':source=source.replace('各长2米','各长1米')
    elif mutation=='bottom':gs[0]['vertices'][0]['y']+=200
    elif mutation=='curve':gs[0]['vertices'][8]['y']+=100
    elif mutation=='sparse':gs[0]['vertices']=gs[0]['vertices'][::8]
    elif mutation=='open':gs[0]['closed']=False
    elif mutation=='bulge':gs[0]['vertices'][0]['bulge']=.1
    else:gs.append({**deepcopy(gs[0]),'id':2})
    if mutation in {'bottom','curve','sparse'}:
        with pytest.raises(StructureContractError) as caught:
            verify_semicircular_outline_source(source,gs)
        assert caught.value.details['reason']=='non_semicircular_boundary_edge'
        assert caught.value.details['measurements']['passed'] is False
    else:
        assert verify_semicircular_outline_source(source,gs)['status']!='passed'


@pytest.mark.parametrize('mutation', ['scale', 'direction', 'vertical', 'wrong_lobes'])
def test_named_component_proof_rejects_bad_geometry_or_constraints(mutation):
    from app.cad_composition_coverage import verify_composition_coverage
    row=ROWS['C10'];gs=execute_construction_plan(row['plan'])['geometries'];source=row['source']
    if mutation=='scale':
        for p in gs[1]['vertices']:p['x']*=1.1
    elif mutation=='direction':
        cy=(max(p['y'] for p in gs[1]['vertices'])+min(p['y'] for p in gs[1]['vertices']))/2
        for p in gs[1]['vertices']:p['y']=2*cy-p['y']
    elif mutation=='vertical':
        for p in gs[1]['vertices']:p['y']+=100
    else:source=source.replace('5个尖角','6个尖角').replace('5个外尖角','6个外尖角')
    try:result=verify_composition_coverage(source,gs)
    except StructureContractError:return
    assert result['status']!='passed'


@pytest.mark.parametrize('width,leg,dx,dy', [(2, 2, 4, -3), (4, 1, -10, 7), (.8, .5, 0, 0)])
def test_arch_measurement_is_independent_of_case_dimensions_and_translation(width,leg,dx,dy):
    from app.cad_semantic_source_coverage import verify_semicircular_outline_source
    import math
    radius=width/2
    # Test geometry only. Production never constructs from this verifier.
    # Keep this positive fixture within the production 0.2mm sampling budget;
    # fixed 64 segments exceed 0.5mm for the 2m radius case.
    count=2*math.ceil(math.pi/(2*math.acos(1-.0002/radius))/2)
    points=[(-radius,0),(-radius,leg),*[(radius*math.cos(math.pi-i*math.pi/count),
            leg+radius*math.sin(math.pi-i*math.pi/count)) for i in range(1,count+1)],(radius,0)]
    gs=[{'id':1,'type':'polyline','closed':True,'vertices':[
        {'x':(x+dx)*1000,'y':(y+dy)*1000} for x,y in points]}]
    source=(f'画一个半圆拱门轮廓：顶部为半径{radius}米的上半圆；两侧直墙各长{leg}米；'
            f'底边闭合。整体宽度{width}米，整体高度{leg+radius}米，坐标单位米。')
    assert verify_semicircular_outline_source(source,gs)['status']=='passed'


@pytest.mark.parametrize('lobes', [3,4,6,7])
def test_periodic_source_reuses_existing_parametric_tool_for_other_counts(lobes):
    row=deepcopy(ROWS['C6'])
    row['source']=row['source'].replace('5片花瓣',f'{lobes}片花瓣')
    row['original']=row['original'].replace('5片花瓣',f'{lobes}片花瓣')
    step=row['plan']['steps'][0]
    for key in ('x_expression','y_expression'):step[key]=step[key].replace('cos(5*t)',f'cos({lobes}*t)')
    row['plan']['assertions']=[]
    result=interpret(row)
    assert result['status']=='ready',result.get('error')
    assert result['acceptance_summary']['status']=='passed'
