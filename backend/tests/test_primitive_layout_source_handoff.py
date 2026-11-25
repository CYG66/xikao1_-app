from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_structure_contract import StructureContractError, _frame

ROWS={row['case']:row for row in json.loads((Path(__file__).parent/'fixtures'/
                'recorded_primitive_layout.json').read_text(encoding='utf-8'))}


def interpret(case,extra=''):
    row=ROWS[case]
    return interpret_construction_request(row['source']+extra,lambda *_:{
        'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
        'confidence':.99,'evidence_text':[row['original']],'plan':deepcopy(row['plan']),
    })


@pytest.mark.parametrize('case',['A11','C15'])
def test_recorded_layout_passes_and_retains_actual_geometry_proof(case,tmp_path):
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    row=ROWS[case];result=interpret(case)
    assert result['status']=='ready',result.get('error')
    assert result['acceptance_summary']['status']=='passed'
    store=CreativeProjectStore(tmp_path/'projects.json')
    saved=commit_construction_interpretation(row['source'],result,store=store)
    proof=store.get(saved['project_id'])['variants'][0]['construction_record']['source_acceptance']['primitive_layout_acceptance']
    assert proof['coverage']=='complete' and proof['checks']


@pytest.mark.parametrize('case',['A11','C15'])
@pytest.mark.parametrize('extra',['，再画一个三角形','，整体旋转30度','，标注全部尺寸','，面积10平方米'])
def test_unconsumed_extra_requirements_never_gain_complete_layout_coverage(case,extra):
    assert interpret(case,extra).get('acceptance_summary',{}).get('status')!='passed'


def test_direct_above_relation_uses_exact_type_binding_and_alignment():
    from app.cad_relation_acceptance import verify_named_relations
    row=ROWS['A11'];gs=execute_construction_plan(row['plan'])['geometries']
    bindings=[{'subject':'圆','geometry_ids':[gs[0]['id']]},
              {'subject':'矩形','geometry_ids':[gs[1]['id']]}]
    report=verify_named_relations('圆形在矩形正上方',gs,bindings)
    assert report['checks'] and report['checks'][0]['status']=='passed'
    gs[0]['center']['x']+=100
    with pytest.raises(StructureContractError):
        verify_named_relations('圆形在矩形正上方',gs,bindings)


@pytest.mark.parametrize('mutation',['bowtie','bulge'])
def test_common_rectangle_frame_does_not_accept_invalid_or_curved_edges(mutation):
    g=execute_construction_plan(ROWS['A11']['plan'])['geometries'][1]
    if mutation=='bowtie':g['vertices'][1],g['vertices'][2]=g['vertices'][2],g['vertices'][1]
    else:g['vertices'][0]['bulge']=.5
    assert _frame(g) is None


@pytest.mark.parametrize('case,mutation',[
    ('A11','circle_center'),('A11','rectangle_origin'),('A11','rectangle_width'),
    ('A11','extra'),('C15','outer_radius'),('C15','inner_radius'),
    ('C15','inner_center'),('C15','both_centers'),('C15','extra'),
])
def test_layout_source_checks_actual_coordinates_dimensions_and_inventory(case,mutation):
    from app.cad_primitive_layout_acceptance import verify_primitive_layout
    gs=execute_construction_plan(ROWS[case]['plan'])['geometries']
    if mutation=='circle_center':gs[0]['center']['x']+=10
    elif mutation=='rectangle_origin':
        for p in gs[1]['vertices']:p['x']+=10
    elif mutation=='rectangle_width':
        for p in gs[1]['vertices']:p['x']*=1.1
    elif mutation=='outer_radius':gs[0]['radius']+=10
    elif mutation=='inner_radius':gs[1]['radius']+=10
    elif mutation=='inner_center':gs[1]['center']['x']+=10
    elif mutation=='both_centers':
        for g in gs:g['center']['x']+=10
    else:gs.append({**deepcopy(gs[0]),'id':99})
    with pytest.raises(StructureContractError):
        verify_primitive_layout(ROWS[case]['source'],gs)


def test_nested_circle_scope_binds_by_containment_not_labels_or_radius_value_matching():
    from app.cad_source_acceptance import verify_final_source_contract
    gs=execute_construction_plan(ROWS['C15']['plan'])['geometries']
    report=verify_final_source_contract(ROWS['C15']['source'],list(reversed(gs)))
    assert report['checks'] and not report['unknown_requirements']
    gs[1]['radius']+=100
    with pytest.raises(StructureContractError):
        verify_final_source_contract(ROWS['C15']['source'],gs)


def test_ambiguous_extra_circles_do_not_receive_inner_outer_scalar_bindings():
    from app.cad_source_acceptance import verify_final_source_contract
    gs=execute_construction_plan(ROWS['C15']['plan'])['geometries']
    gs.append({**deepcopy(gs[1]),'id':99})
    report=verify_final_source_contract(ROWS['C15']['source'],gs)
    assert report['unknown_requirements'] and report['review_required']


def test_model_labels_cannot_override_measured_inner_outer_roles():
    from app.cad_source_acceptance import verify_final_source_contract
    gs=execute_construction_plan(ROWS['C15']['plan'])['geometries']
    labels=[{'label':'内圆','geometry_refs':[gs[0]['id']]},
            {'label':'外圆','geometry_refs':[gs[1]['id']]}]
    report=verify_final_source_contract(ROWS['C15']['source'],gs,labels)
    assert report['checks'] and not report['unknown_requirements']
    assert {tuple(c['geometry_ids']) for c in report['checks'] if c['expected_mm']==2000}=={(gs[0]['id'],)}


@pytest.mark.parametrize('declaration',['一个矩形和一个圆形','一个圆形与一个长方形'])
def test_inventory_order_and_primitive_aliases_do_not_change_layout_proof(declaration):
    from app.cad_primitive_layout_acceptance import verify_primitive_layout
    row=ROWS['A11'];gs=execute_construction_plan(row['plan'])['geometries']
    source=row['source'].replace('一个圆形和一个矩形',declaration)
    assert verify_primitive_layout(source,gs)['coverage']=='complete'


@pytest.mark.parametrize('phrase,center',[
    ('正上方',(0,3000)),('正下方',(0,-3000)),('正左方',(-3000,0)),('正右方',(3000,0)),
])
def test_direct_relations_measure_all_four_axes(phrase,center):
    from app.cad_relation_acceptance import verify_named_relations
    gs=execute_construction_plan(ROWS['A11']['plan'])['geometries']
    gs[0]['center'].update(x=center[0],y=center[1])
    bindings=[{'subject':'圆','geometry_ids':[gs[0]['id']]},
              {'subject':'矩形','geometry_ids':[gs[1]['id']]}]
    report=verify_named_relations('圆形在矩形'+phrase,gs,bindings)
    assert report['checks'][0]['status']=='passed'


@pytest.mark.parametrize('case,extra',[
    ('A11','，坐标单位厘米'),('A11','，再生成一个圆形'),
    ('C15','，内圆半径0.5米'),('C15','，均圆心(1,1)'),
])
def test_additional_counts_units_and_conflicting_role_dimensions_do_not_pass(case,extra):
    assert interpret(case,extra).get('acceptance_summary',{}).get('status')!='passed'
