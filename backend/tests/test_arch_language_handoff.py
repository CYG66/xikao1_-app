from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.cad_semantic_source_coverage import semicircular_source_requirements, verify_semicircular_outline_source, source_dimension_relation_guidance
from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import interpret_construction_request

ROWS=json.loads((Path(__file__).parent/'fixtures/recorded_arch_c.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('row',ROWS)
def test_real_arch_plans_keep_geometry_or_original_rejection(row,tmp_path):
    result=interpret_construction_request(row['source'],lambda *_:deepcopy(row['payload']),force_structured_model=True)
    if not row['geometry_proof']['passed']:
        assert result.get('acceptance_summary',{}).get('status')!='passed'
        return
    from app.cad_construction_commit import commit_construction_interpretation
    from app.creative_projects import CreativeProjectStore
    from app.cad_candidate_state import candidate_is_accepted
    assert result.get('acceptance_summary',{}).get('status')=='passed',result
    store=CreativeProjectStore(tmp_path/'projects.json')
    saved=commit_construction_interpretation(row['source'],result,store=store)
    variant=store.get(saved['project_id'])['variants'][0]
    assert candidate_is_accepted(variant)
    assert variant['geometries']==execute_construction_plan(row['payload']['plan'])['geometries']


def source(unit,scale):
    return f'画一个半圆拱门的闭合外轮廓。水平底边左端在({-340/scale},{570/scale})，整体宽{2740/scale}{unit}，从底边到拱顶的整体高{3980/scale}{unit}；左右两段直墙竖直且等高，顶上用直径{2740/scale}{unit}的上半圆连接，整体高度包含这段半圆。不要内部线。坐标单位{unit}。只生成预览，不执行小车。'


@pytest.mark.parametrize('unit,scale',[('米',1000),('厘米',10),('毫米',1)])
@pytest.mark.parametrize('representation',['native','sampled'])
def test_paraphrase_reuses_dimensions_origin_guidance_and_measured_identity(unit,scale,representation):
    from test_arch_source_generalization import plan
    text=source(unit,scale)
    parsed=semicircular_source_requirements(text)
    assert parsed['coverage']=='complete'
    assert next(r['expected_mm'] for r in parsed['requirements'] if r['field']=='bottom_left')==[-340,570]
    assert all(r['source_evidence'] in text for r in parsed['requirements'])
    derived=source_dimension_relation_guidance(text)[0]['derived_relations']
    assert derived['wall_height_mm']==2610 and derived['top_y_mm']==4550
    gs=execute_construction_plan(plan(2740,3980,-340,570,representation))['geometries']
    assert verify_semicircular_outline_source(text,gs)['coverage']=='complete'
    for w,h,x,y in [(2740,3990,-340,570),(2740,3980,-330,570),(2740,3980,-340,580),(2760,3980,-340,570)]:
        bad=execute_construction_plan(plan(w,h,x,y,representation))['geometries']
        assert verify_semicircular_outline_source(text,bad)['coverage']=='partial'


@pytest.mark.parametrize('extra',['整体旋转15度。','左右墙不等高。','再加一条内部线。','执行小车。','总高5000毫米。','圆心(0,0)。'])
def test_new_phrases_do_not_hide_unknown_or_conflicting_source(extra):
    from test_arch_source_generalization import plan
    text=source('毫米',1)+extra
    gs=execute_construction_plan(plan(2740,3980,-340,570,'native'))['geometries']
    assert verify_semicircular_outline_source(text,gs)['coverage']=='partial'
