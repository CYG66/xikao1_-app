import math

import pytest

from app.agent_skills import drawing_template_geometries, DRAWING_TEMPLATE_SKILLS
from app.cad_construction import execute_construction_plan
from app.cad_template_plan import template_plan_for_project


def geometry(name, **values):
    return drawing_template_geometries({'template':name, **DRAWING_TEMPLATE_SKILLS[name], **values})


def test_basketball_main_components_and_arc_joins():
    items = geometry('basketball')
    assert len(items) == 19
    assert sum(g['type']=='arc' for g in items) == 6
    triples = [g for g in items if g['type']=='arc' and g['radius']==6750]
    assert len(triples)==2
    for arc in triples:
        for angle in (arc['start_angle'],arc['end_angle']):
            x=arc['center']['x']+6750*math.cos(math.radians(angle))
            y=arc['center']['y']+6750*math.sin(math.radians(angle))
            assert abs(y)==pytest.approx(6600)
            assert any(math.hypot(g['end']['x']-x,g['end']['y']-y)<1e-6
                       for g in items if g['type']=='line')
    keys=[g for g in items if g['type']=='polyline' and not g['closed']]
    assert len(keys)==2
    assert all(abs(g['vertices'][1]['x'])==pytest.approx(8200) for g in keys)
    assert all(abs(g['vertices'][1]['y'])==pytest.approx(2450) for g in keys)
    assert len([g for g in items if g['type']=='arc' and g['radius']==1300])==2


def test_badminton_singles_doubles_service_lines_and_no_painted_net():
    items=geometry('badminton')
    assert len(items)==9
    lines=[g for g in items if g['type']=='line']
    vertical={g['start']['x'] for g in lines if g['start']['x']==g['end']['x']}
    assert vertical=={-5940, -1980, 1980, 5940}
    horizontal={g['start']['y'] for g in lines if g['start']['y']==g['end']['y']}
    assert horizontal=={-2590,0,2590}
    assert 0 not in vertical


def test_grid_obeys_custom_extents_without_overlapping_perimeter():
    items=geometry('grid', width_m=12,height_m=8)
    assert len(items)==10
    segments={tuple(sorted(((g['start']['x'],g['start']['y']),
                            (g['end']['x'],g['end']['y'])))) for g in items}
    assert len(segments)==10
    assert all(-6000<=p['x']<=6000 and -4000<=p['y']<=4000
               for g in items for p in (g['start'],g['end']))
    assert len({g['start']['x'] for g in items if g['start']['x']==g['end']['x']})==5


def test_parking_shared_boundaries_are_printed_once():
    items=geometry('parking', quantity=4)
    segments={tuple(sorted(((g['start']['x'],g['start']['y']),
                            (g['end']['x'],g['end']['y'])))) for g in items}
    assert len(items)==len(segments)==13
    plan=template_plan_for_project({'name':'四个标准车位','original_prompt':'四个标准车位',
        'requirements':{'quantity':4}}, {})
    trial=execute_construction_plan(plan)
    assert len(trial['topology']['shared_geometries'])==3


@pytest.mark.parametrize('name',['basketball','badminton','parking','grid'])
def test_complete_template_survives_production_execution(name):
    label=DRAWING_TEMPLATE_SKILLS[name]['label']
    plan=template_plan_for_project({'name':label,'original_prompt':label,'requirements':{}}, {})
    trial=execute_construction_plan(plan)
    assert trial['graph_validation']['verified']
    assert trial['feasibility']['ok']
    assert len(trial['geometries'])==len(geometry(name))


def test_custom_court_affine_fit_keeps_curves_connected():
    plan=template_plan_for_project({'name':'篮球场','original_prompt':'篮球场',
        'requirements':{'dimensions':{'width_m':20,'height_m':10},'rotation_deg':90}}, {})
    result=execute_construction_plan(plan)
    assert any(g['type']=='ellipse' for g in result['geometries'])
    assert result['graph_validation']['verified']


def test_grid_counts_are_parameters_in_production_plan():
    plan=template_plan_for_project({'name':'施工轴网','original_prompt':'施工轴网',
        'requirements':{'grid_columns':3,'grid_rows':2,'dimensions':{'width_m':12,'height_m':8}}}, {})
    trial=execute_construction_plan(plan)
    assert len(trial['geometries'])==7


def test_saved_candidate_records_template_scope_and_nonstandard_size(tmp_path):
    from app.cad_template_plan import interpret_template_project
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    interpretation=interpret_template_project({'name':'篮球场','original_prompt':'篮球场',
        'requirements':{'dimensions':{'width_m':20,'height_m':10}}}, {})
    store=CreativeProjectStore(tmp_path/'projects.json')
    committed=commit_construction_interpretation('篮球场',interpretation,store=store)
    spec=committed['recommended_variant']['construction_record']['template_specifications'][0]
    assert spec['standard_dimensions'] is False
    assert spec['paint_edge_compensation'] is False
    assert 'rebound_place_ticks' in spec['excluded']


def test_legacy_simplified_court_is_replaced_without_overwriting_history(tmp_path):
    from unittest.mock import patch
    from app.creative_projects import CreativeProjectStore
    from app.agent_service import robot_agent
    store=CreativeProjectStore(tmp_path/'projects.json')
    project=store.create('篮球场','标准篮球场',{'shape':'basketball',
        'dimensions':{'width_m':28,'height_m':15}}, {}, [])
    old=store.add_variant(project['id'],'旧简化球场',geometry('basketball')[:3],'',{},[])
    with patch('app.agent_service.get_creative_project_store',return_value=store):
        result=robot_agent.generate_project_candidate(project['id'])
    assert result['ok']
    variants=store.get(project['id'])['variants']
    assert len(variants)==2
    assert variants[0]['id']==old['id'] and len(variants[0]['geometries'])==3
    assert len(variants[1]['geometries'])==19
