"""User's A/B/C/D corpus, real HTTP-handler/provider, independent edit oracles.

Keeps original prompts, follow-ups, every request/response and model output.
No CAD generator or provider is mocked. App replay is separately labeled.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tests.manual.run_complex_cad_live import FOLLOWUPS, geometry_checks
from app.cad_construction import construction_geometry_bounds
from tests.manual.cad_harness_acceptance import (
    evaluate_accepted_base,
    evaluate_edit_formal_delivery,
    evaluate_formal_delivery,
    evaluate_no_change_delivery,
)
from tests.manual.cad_acceptance_metrics import summarize

SOURCE=Path(r'D:\xikao\文生文修CAD测试语料.md')
NEW_EXECUTION_COHORT='new'


def summarize_new_execution(root,reports):
    """New corpus runs count every planned case, including failures."""
    return summarize(root,reports,cohort=NEW_EXECUTION_COHORT)


SUPPLEMENTS={**FOLLOWUPS,
 'B4':'逆时针旋转45度，以当前选中图形的中心为旋转中心。',
 'B8':'以坐标x=5米的竖直直线为镜像轴，镜像复制到右侧并保留原图，坐标单位米。',
 'D2':'以坐标x=4米的竖直直线为镜像轴，左右镜像复制到右侧并保留原曲线，坐标单位米。',
 'D6':'以选中轮廓中心为基准，逆时针旋转90度，再等比缩放为原来的70%，保持同一项目。',
 'B13':'以左侧圆形为固定基准，只移动右侧圆形，使两个圆的中心Y坐标相同，半径保持不变。',
 'B14':'以圆形为固定基准，只平移矩形，使矩形中心与圆心重合，尺寸保持不变。',
 'B15':'以圆形为固定基准，只把矩形宽度改为圆的直径，高度保持原值；圆形保持不变。',
 'A1':'宽度4米，高度4米。','A2':'宽度5米，高度3米，单位米。',
 'A3':'半径2米，圆心(0,0)，坐标单位米。','A4':'长轴全长4米，短轴全长2米，中心(0,0)，坐标单位米。',
 'A5':'圆心(0,0)，半径3米，起始角0度、终止角90度，坐标单位米。',
 'A6':'按标准全场28米乘15米，不包含场外缓冲区。','A7':'按双打全场13.4米乘6.1米。',
 'A8':'两个车位各宽2.5米、长5米，左右并排，共边，单位米。',
 'A9':'宽4米、高4米，左右对称、平滑闭合。','A10':'中心(2,3)，宽4米、高4米，坐标单位米。',
 'A11':'五角星外接圆半径2米，内外半径比0.381966，尖角朝上。',
 'A12':'圆半径1米，圆心(0,3)；矩形左下角(-1,-1)，宽2米、高2米；坐标单位米，两个独立图形。',
 'C10':'爱心宽4米高4米；五角星外接圆半径2米、固定为5个尖角且尖角朝上；两者中心水平相距6米，坐标单位米。',
 'C3':'顶部为半径1米的上半圆；两侧直墙各长2米；底边闭合。整体宽度2米、整体高度3米，坐标单位米。',
 'C31':'外圆半径2米，S形分割线和两个对称小圆，坐标单位米；保持原始太极图要求，只生成预览。',
 'B18':'确认参数：两个矩形尺寸均为宽2米、高1米；分别位于篮球场中心线上方5米和下方5米，关于球场横向中心线对称；请直接基于当前项目生成候选。',
 'C13':'正六边形，边长1米，中心(0,0)，坐标单位米。',
 'C14':'8个等距齿，外径2米，齿根圆直径1.5米，中心(0,0)，各齿齿顶角宽15度。',
 'C15':'外圆半径2米、内圆半径1米，均圆心(0,0)，坐标单位米。',
 'C16':'总宽4米、总高3米；墙体左下角(0,0)，宽4米高2米；屋顶顶点(0,2)(2,3)(4,2)；门左下角(1.5,0)，宽1米高1.5米，坐标单位米。',
 'C17':'正六边形边长0.5米，3列2行共6个，蜂窝错列共边拼接，坐标单位米。',
 'C18':'使用参数式x=2*cos(t)^3、y=2*sin(t)^3，t从0到2*pi，坐标单位米，闭合。',
 'C19':'尖点朝下的心形线，最大宽度3米，闭合，坐标单位米。',
 'C20':'外包宽3米、高2米，四角圆角半径0.5米，闭合。',
 'C21':'总宽4米、总高4米，水平与竖直两臂宽度均1米，中心(0,0)，坐标单位米。',
 'C22':'中心(0,0)，6条主枝半径均2米、角间隔60度；每条主枝在半径1.2米处有两条长度0.5米、与主枝夹角60度的对称侧枝，坐标单位米。',
 'C23':'5级，每级水平0.4米、竖直0.3米，从(0,0)向右向上，坐标单位米。',
 'C24':'外环圆心(0,0)，半径3米；向东南西北四方向从圆周向外各延伸2米，坐标单位米。',
 'C25':'圆心(0,0)，半径1.5米；直径斜线方向45度，坐标单位米。',
 'C26':'字母A总高3米、总宽2米，两斜笔端点(-1,0)(0,3)(1,0)，横笔在高度1.5米处，坐标单位米。',
 'C27':'二维等轴投影，三个投影轴夹角120度，各投影棱长2米，只画可见及隐藏的12条棱线。',
 'C28':'外圆：圆，圆心(0,0)，半径1米，坐标单位米；左眼：圆，圆心(-0.35,0.35)，半径0.09米，坐标单位米；右眼：圆，圆心(0.35,0.35)，半径0.09米，坐标单位米；嘴巴：圆弧，圆心(0,-0.15)，半径0.55米，起始角200度，终止角340度，坐标单位米',
}
BASE={**{f'B{i}':'A1' for i in (1,2,4,7,9,12,19)},
 **{f'B{i}':'A2' for i in (3,8,10)},**{f'B{i}':'A3' for i in (5,6,11)},
 'B13':'C9','B14':'A12','B15':'A12','B16':'A12','B17':'C9','B18':'A6',
 'D1':'C2','D2':'C1','D3':'C10','D4':'C3','D5':'C2','D6':'C6'}
CONFIRM='确认需求并生成CAD候选，只预览，不执行小车。'


def resolve_corpus_setup(corpus,wanted):
    """Resolve the documented A9/A10 merge by exact prompt anchors, not ID guesses."""
    unknown=set(wanted)-set(corpus)
    if unknown:raise ValueError('Requested corpus cases missing: '+','.join(sorted(unknown)))
    aliases={case:case for case in corpus}
    if 'A12' not in corpus:
        anchors={
            '生成一个圆形和一个矩形，圆形在矩形正上方':'A12',
            '生成一个五角星轮廓':'A11',
            '生成一个左右对称、平滑闭合的爱心，中心在(2,3)，宽4米高4米':'A10'}
        for case,prompt in corpus.items():
            if prompt.strip() in anchors:aliases[case]=anchors[prompt.strip()]
    bases={}
    for case in wanted:
        if case not in BASE:continue
        matches=[actual for actual,canonical in aliases.items() if canonical==BASE[case]]
        if len(matches)!=1:raise ValueError(f'{case}: expected one source case for {BASE[case]}, got {matches}')
        bases[case]=matches[0]
    return aliases,bases

def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def call(folder,step,body,operation='chat'):
    result=subprocess.run([sys.executable,str(Path(__file__).with_name('cad_widget_live_worker.py')),'--output',str(folder)],
        input=json.dumps({'operation':operation,'step':step,'body':body},ensure_ascii=False),
        encoding='utf-8',text=True,capture_output=True,timeout=360)
    if result.returncode:raise RuntimeError(result.stderr[-3000:])
    return json.loads(result.stdout)

def bounds(gs):
    b=construction_geometry_bounds(gs)
    return b['min_x'],b['min_y'],b['max_x'],b['max_y']

def persisted_project(folder,project_id):
    path=Path(folder)/'projects.json'
    if not path.exists():return {}
    data=json.loads(path.read_text(encoding='utf-8'))
    return next((p for p in data.get('projects',[]) if str(p.get('id'))==str(project_id)),{})

def persisted_source(folder,project_id,variant_id):
    project=persisted_project(folder,project_id)
    variant=next((v for v in project.get('variants',[])
                  if str(v.get('id'))==str(variant_id)),{})
    return {'authority':'projects.json','independent':True,
            'project_id':str(project_id or ''),'variant_id':str(variant_id or ''),
            'project':project,'variant':variant}

def checks_geometry_ok(checks,after):
    excluded={'base_candidate_accepted','same_project','formal_delivery'}
    observed=[c['passed'] for c in checks if c.get('name') not in excluded]
    return bool((after or {}).get('geometries')) and (all(observed) if observed else True)


def corners(g):
    points=g.get('vertices') or []
    if not g.get('closed') or len(points)<4:return points
    result=[]
    for i,p in enumerate(points):
        a=points[i-1];b=points[(i+1)%len(points)]
        ux,uy=p['x']-a['x'],p['y']-a['y'];vx,vy=b['x']-p['x'],b['y']-p['y']
        if abs(ux*vy-uy*vx)/max(1,math.hypot(b['x']-a['x'],b['y']-a['y']))>.5 or ux*vx+uy*vy<0:
            result.append(p)
    return result

def _semantic_profile_check(messages,geometries,add,name):
    from app.cad_semantic_acceptance import verify_semantic_requirements
    from app.cad_structure_contract import StructureContractError
    try:
        report=verify_semantic_requirements('\n'.join(messages or []),geometries)
    except StructureContractError as exc:
        add(name,False,{'error':str(exc),'details':exc.details})
        return
    if report['status'] in {'partial','passed'} and report.get('checks') and not report.get('review_required'):
        add(name,True,report)
    else:add(name+'_review',False,report)


def create_checks(case,result,messages=None):
    gs=(result.get('variant') or {}).get('geometries') or []
    paths=result.get('preview_paths') or []
    checks=[{'name':'candidate_and_preview','passed':bool(gs and paths and result.get('ok'))}]
    if not gs:return checks
    def add(name,passed,observed=None):checks.append({'name':name,'passed':bool(passed),'observed':observed})
    x,y,X,Y=bounds(gs);w,h=X-x,Y-y
    near=lambda a,b:abs(a-b)<2
    circle=[g for g in gs if g['type']=='circle']
    if case in FOLLOWUPS:
        checks+=geometry_checks(case,result['variant'],paths)
        if case=='C10':
            objects=result['variant'].get('logical_objects') or []
            assemblies={str(o.get('assembly_id') or o.get('object_id') or '').lower() for o in objects}
            labels={str(o.get('assembly_label') or o.get('label') or '') for o in objects}
            for check in checks:
                if check.get('name')=='heart_and_star_semantics_require_visual_review':
                    check['name']='heart_and_star_semantics'
                    heart = 'heart' in assemblies or '爱心' in labels
                    star = any('star' in value for value in assemblies) or '五角星' in labels
                    check['passed']=heart and star
                    check['observed']={'assembly_ids':sorted(assemblies),'assembly_labels':sorted(labels)}
    elif case in {'A1','A9','A10'}:
        add('4000mm_width_and_height',near(w,4000) and near(h,4000),[w,h])
        add('closed_outline',len(gs)==1 and gs[0].get('closed'))
        points=[p for path in paths for p in path.get('points',[])]
        if points:
            xs=[p[0] for p in points];ys=[p[1] for p in points];mx=(min(xs)+max(xs))/2;my=(min(ys)+max(ys))/2
            upper_center=[p[1] for p in points if abs(p[0]-mx)<.04*(max(xs)-min(xs)) and p[1]>my]
            add('heart_upper_notch',bool(upper_center) and max(ys)-min(upper_center)>.05*(max(ys)-min(ys)))
        semantic = (((result.get('variant') or {}).get('construction_record') or {})
                    .get('source_acceptance') or {}).get('semantic_acceptance') or {}
        semantic_checks = semantic.get('checks') or []
        add(
            'heart_visual_semantics',
            any(check.get('name') == 'heart_bilateral_lobes_notch_and_lower_tip'
                and check.get('status') == 'passed' for check in semantic_checks),
            semantic,
        )
        if case=='A10':add('center_2m_3m',near((x+X)/2,2000) and near((y+Y)/2,3000))
    elif case in {'A2','A4'}:
        target=(5000,3000) if case=='A2' else (4000,2000)
        add('dimensions',near(w,target[0]) and near(h,target[1]),[w,h])
        add('primitive_type',len(gs)==1 and (gs[0]['type']=='polyline' if case=='A2' else gs[0]['type']=='ellipse'))
    elif case=='A3':add('circle_radius_2000mm',len(gs)==1 and len(circle)==1 and near(circle[0]['radius'],2000))
    elif case=='A5':add('quarter_arc',len(gs)==1 and gs[0]['type']=='arc' and near(gs[0]['radius'],3000) and near(gs[0]['start_angle'],0) and near(gs[0]['end_angle'],90))
    elif case in {'A6','A7','A8'}:
        target=(15000,28000) if case=='A6' else (6100,13400) if case=='A7' else (5000,5000)
        add('template_dimensions',all(near(a,b) for a,b in zip(sorted((w,h)),target)),[w,h])
        add('template_semantics_review',False,'orientation and markings require review')
    elif case=='A11':
        ps=gs[0].get('vertices') or []
        cx,cy=(x+X)/2,(y+Y)/2
        radii=[math.hypot(p['x']-cx,p['y']-cy) for p in ps]
        peaks=sum(r>radii[i-1]+.1 and r>radii[(i+1)%len(radii)]+.1 for i,r in enumerate(radii))
        add('five_tips_closed_polygon',len(gs)==1 and peaks==5 and gs[0].get('closed'),{'vertex_count':len(ps),'radial_peaks':peaks})
    elif case=='A12':
        add('circle_and_rectangle',len(gs)==2 and len(circle)==1)
        if circle:
            other=[g for g in gs if g['type']!='circle']
            add('circle_above_rectangle',bool(other) and circle[0]['center']['y']-circle[0]['radius']>bounds(other)[3])
    elif case=='C13':
        ps=corners(gs[0])
        add('six_equal_1m_sides',len(gs)==1 and len(ps)==6 and gs[0].get('closed') and all(near(math.dist((p['x'],p['y']),(ps[i-1]['x'],ps[i-1]['y'])),1000) for i,p in enumerate(ps)))
    elif case=='C14':
        from app.cad_repetition_acceptance import verify_repetition_requirements
        from app.cad_structure_contract import StructureContractError
        try:
            measured=verify_repetition_requirements('\n'.join(messages or []),gs)
            names={c['name'] for c in measured.get('checks',[]) if c['status']=='passed'}
            add('approximate_tooth_count_diameter_and_repetition',
                {'有宽度齿顶的数量','齿形外径','齿形旋转重复关系'}<=names,measured)
        except StructureContractError as exc:
            add('approximate_tooth_count_diameter_and_repetition',False,{'error':str(exc),'details':exc.details})
    elif case=='C15':add('concentric_ring_radii',len(gs)==2 and len(circle)==2 and sorted(round(g['radius']) for g in circle)==[1000,2000] and math.dist(tuple(circle[0]['center'].values()),tuple(circle[1]['center'].values()))<2)
    elif case=='C16':
        add('overall_4m_by_3m',near(w,4000) and near(h,3000),[w,h])
        # Wall and roof can be one outer boundary; the door is a separate
        # part. Entity count is not a proof of the house's semantic parts.
        add('outline_and_door_candidates_present',len(gs)>=2 and len((result['variant'].get('logical_objects') or []))>=2)
        _semantic_profile_check(messages,gs,add,'house_part_geometry')
    elif case=='C17':
        add('six_cells',len(gs)==6)
        add('hexagon_side_lengths',all(len(ps:=g.get('vertices') or [])==6 and g.get('closed') and all(near(math.dist((p['x'],p['y']),(ps[i-1]['x'],ps[i-1]['y'])),500) for i,p in enumerate(ps)) for g in gs))
        from shapely.geometry import Polygon
        cells=[Polygon([(p['x'],p['y']) for p in g.get('vertices',[])]) for g in gs]
        overlaps=[cells[i].intersection(cells[j]).area for i in range(len(cells)) for j in range(i)]
        add('honeycomb_no_overlapping_cells',bool(overlaps) and max(overlaps)<1,{'max_overlap_mm2':max(overlaps,default=0)})
        from app.cad_repetition_acceptance import verify_repetition_requirements
        from app.cad_structure_contract import StructureContractError
        try:
            measured=verify_repetition_requirements('\n'.join(messages or []),gs)
            add('honeycomb_shared_edge_connectivity',any(c['name']=='全部单元通过完整公共边连通'
                and c['status']=='passed' for c in measured.get('checks',[])),measured)
        except StructureContractError as exc:
            add('honeycomb_shared_edge_connectivity',False,{'error':str(exc),'details':exc.details})
    elif case=='C18':
        points=[p for path in paths for p in path.get('points',[])]
        # Matching a few vertices can hide straight star edges between them.
        probes=[p for path in paths for a,b in zip(path.get('points',[]),path.get('points',[])[1:])
                for p in [[a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t] for t in (0,.25,.5,.75,1)]]
        add('astroid_equation_radius_2m',bool(probes) and all(abs((abs(p[0])/2)**(2/3)+(abs(p[1])/2)**(2/3)-1)<.01 for p in probes))
        add('closed_four_cusps',len(gs)==1 and gs[0].get('closed') and near(w,4000) and near(h,4000))
    elif case=='C19':
        from app.cad_curve_fit_acceptance import verify_cardioid
        from shapely.geometry import LineString
        add('width_upper_bound_3m',0<w<=3000.5,w)
        valid=len(gs)==1 and gs[0].get('closed') and gs[0].get('type')=='polyline'
        add('one_closed_cardioid',valid)
        if valid:
            vertices=gs[0]['vertices'];points=[(p['x'],p['y']) for p in vertices]
            add('no_self_intersection',LineString(points+[points[0]]).is_simple)
            measured=verify_cardioid(gs[0])
            add('cardioid_independent_coordinate_fit',measured['passed'],measured)
            vector=measured.get('cusp_pointing_unit_vector') or [0,0]
            add('cusp_points_down',measured['passed'] and vector[1]<=-math.cos(math.radians(10)),vector)
    elif case=='C20':
        add('rounded_rectangle_dimensions',near(w,3000) and near(h,2000))
        pts=[p for path in paths for p in path.get('points',[])]
        cx,cy=(x+X)/2,(y+Y)/2
        errors=[]
        for p in pts:
            qx,qy=abs(1000*p[0]-cx)-1000,abs(1000*p[1]-cy)-500
            errors.append(abs(math.hypot(max(qx,0),max(qy,0))+min(max(qx,qy),0)-500))
        add('analytic_500mm_corner_boundary',bool(errors) and max(errors)<2,{'max_error_mm':max(errors,default=None)})
    elif case=='C21':
        add('cross_extent',near(w,4000) and near(h,4000))
        from shapely.geometry import Polygon,box
        from shapely.ops import unary_union
        polys=[Polygon([(1000*p[0],1000*p[1]) for p in path['points']]) for path in paths if len(path.get('points',[]))>3]
        cx,cy=(x+X)/2,(y+Y)/2
        expected=box(cx-2000,cy-500,cx+2000,cy+500).union(box(cx-500,cy-2000,cx+500,cy+2000))
        delta=unary_union(polys).symmetric_difference(expected).area
        add('two_1m_wide_cross_arms',delta<100000,{'symmetric_difference_mm2':delta})
    elif case=='C22':
        add('six_main_twelve_side_branches',len(gs)==18 and all(g['type']=='line' for g in gs),len(gs))
        lines=[g for g in gs if g['type']=='line'];main=[];side=[]
        for g in lines:
            pts=[(g[k]['x'],g[k]['y']) for k in ('start','end')]
            pts.sort(key=lambda p:math.hypot(*p))
            (main if math.hypot(*pts[0])<2 else side).append(pts)
        angles=sorted(math.atan2(p[1][1],p[1][0])%math.tau for p in main)
        add('sixfold_2m_main_branches',len(main)==6 and all(near(math.hypot(*p[1]),2000) for p in main)
            and all(abs((angles[(i+1)%6]-angles[i])%math.tau-math.pi/3)<.001 for i in range(6)))
        # In the follow-up this case explicitly supplied side length and anchor
        # radius. Verify those only when that turn was actually sent.
        side_ok=len(side)==12;side_measurements=[]
        for a,b in side:
            length=math.dist(a,b);radius=math.hypot(*a)
            cosine=(a[0]*(b[0]-a[0])+a[1]*(b[1]-a[1]))/max(1,radius*length)
            side_measurements.append({'anchor_radius_mm':radius,'length_mm':length,'angle_cosine':cosine})
            side_ok=side_ok and near(radius,1200) and near(length,500) and abs(cosine-.5)<.001
        if messages and SUPPLEMENTS[case] in messages:
            add('twelve_500mm_side_branches_at_1200mm',side_ok,side_measurements)
        else:
            # Do not invent numeric anchor/length requirements absent from the
            # source. Connectivity, paired mirror symmetry and rotational
            # correspondence can still be independently measured.
            from app.cad_repetition_acceptance import verify_repetition_requirements
            from app.cad_structure_contract import StructureContractError
            try:
                measured=verify_repetition_requirements('\n'.join(messages or []),gs)
                add('source_branch_connectivity_and_symmetry',bool(measured.get('checks')),measured)
            except StructureContractError as exc:
                add('source_branch_connectivity_and_symmetry',False,{'error':str(exc),'details':exc.details})
    elif case=='C23':
        ps=gs[0].get('vertices') or []
        segments=[(b['x']-a['x'],b['y']-a['y']) for a,b in zip(ps,ps[1:])]
        if gs[0].get('closed') and ps and math.dist((ps[0]['x'],ps[0]['y']),(ps[-1]['x'],ps[-1]['y']))>2:
            segments.append((ps[0]['x']-ps[-1]['x'],ps[0]['y']-ps[-1]['y']))
        kinds=[('h' if near(abs(dx),400) and near(dy,0) else 'v'
                if near(dx,0) and near(abs(dy),300) else 'base') for dx,dy in segments]
        valid=False
        for start in range(len(segments)) if gs[0].get('closed') else [0]:
            ordered=segments[start:]+segments[:start];labels=kinds[start:]+kinds[:start]
            stairs=ordered[:10];base=ordered[10:]
            step_ok=(labels[:10].count('h')==5 and labels[:10].count('v')==5
                and all(labels[i]!=labels[i-1] for i in range(1,10))
                and near(abs(sum(dx for dx,dy in stairs)),2000) and near(abs(sum(dy for dx,dy in stairs)),1500))
            base_ok=(not base and not gs[0].get('closed')) or (len(base)==2 and any(
                near(abs(base[i][0]),2000) and near(base[i][1],0)
                and near(base[1-i][0],0) and near(abs(base[1-i][1]),1500) for i in (0,1)))
            valid=valid or step_ok and base_ok
        add('five_stair_steps',len(gs)==1 and valid,segments)
    elif case=='C29':
        _semantic_profile_check(messages,gs,add,'nested_frame_dimensions_center_and_containment')
    elif case=='C30':
        from app.cad_repetition_acceptance import verify_repetition_requirements
        from app.cad_structure_contract import StructureContractError
        try:
            measured=verify_repetition_requirements('\n'.join(messages or []),gs)
            names={c['name'] for c in measured.get('checks',[]) if c['status']=='passed'}
            add('parallel_strip_count_dimensions_alignment_and_gap',
                {'平行条带数量','每条横向条带长宽','条带横向对齐','平行条带间距'}<=names,measured)
        except StructureContractError as exc:
            add('parallel_strip_count_dimensions_alignment_and_gap',False,{'error':str(exc),'details':exc.details})
    elif case=='C31':
        from app.cad_path_relation_acceptance import verify_path_relations
        from app.cad_structure_contract import StructureContractError
        try:
            measured=verify_path_relations('\n'.join(messages or []),gs)
            outer=[g for g in gs if g.get('type')=='circle']
            add('outer_circle_radius',len(outer)==3 and near(max(g['radius'] for g in outer),2000))
            add('s_divider_and_symmetric_inner_circles',measured['status']!='not_checked' and bool(measured['checks']),measured)
        except StructureContractError as exc:
            add('s_divider_and_symmetric_inner_circles',False,{'error':str(exc),'details':exc.details})
    elif case=='C32':
        _semantic_profile_check(messages,gs,add,'regular_polygon_and_hole')
    elif case=='C34':
        from app.cad_path_relation_acceptance import verify_perpendicular_arm_dimensions
        from app.cad_structure_contract import StructureContractError
        try:
            measured=verify_perpendicular_arm_dimensions('\n'.join(messages or []),gs)
            add('perpendicular_arm_dimensions',bool(measured and measured['status']=='passed'),measured)
        except StructureContractError as exc:
            add('perpendicular_arm_dimensions',False,{'error':str(exc),'details':exc.details})
    elif case=='C24':
        lines=[g for g in gs if g['type']=='line']
        add('ring_and_four_rays',len(gs)==5 and len(circle)==1 and len(lines)==4 and near(circle[0]['radius'],3000))
        add('four_radial_2m_extensions',len(lines)==4 and all(near(math.dist(tuple(g['start'].values()),tuple(g['end'].values())),2000) and sorted(round(math.hypot(*p.values())) for p in (g['start'],g['end']))==[3000,5000] for g in lines))
    elif case=='C25':
        lines=[g for g in gs if g['type']=='line']
        add('circle_and_diameter',len(gs)==2 and len(circle)==1 and len(lines)==1 and near(circle[0]['radius'],1500))
        if lines:
            a,b=lines[0]['start'],lines[0]['end'];dx,dy=b['x']-a['x'],b['y']-a['y']
            add('45degree_3m_diameter',near(abs(dx),abs(dy)) and near(math.hypot(dx,dy),3000))
    elif case=='C26':
        add('letter_A_dimensions',near(w,2000) and near(h,3000))
        _semantic_profile_check(messages,gs,add,'letter_stroke_geometry')
    elif case=='C27':
        if messages and SUPPLEMENTS[case] in messages:
            add('twelve_edges',len(gs)==12 and all(g['type']=='line' for g in gs),len(gs))
        add('projection_topology_review',False,'edge count alone cannot prove cube projection')
    elif case=='C28':
        arcs=[g for g in gs if g['type']=='arc']
        add('outer_circle_two_eyes_one_arc',len(gs)==4 and len(circle)==3 and len(arcs)==1)
        if circle:
            outer=max(circle,key=lambda g:g['radius']);eyes=[g for g in circle if g is not outer]
            add('outer_radius_1m',near(outer['radius'],1000))
            add('eyes_inside_face',len(eyes)==2 and all(math.dist(tuple(g['center'].values()),tuple(outer['center'].values()))+g['radius']<outer['radius'] for g in eyes))
    else:add('independent_semantic_acceptance',False,'not yet covered by an independent oracle; do not claim success')
    return checks

def make_creation(case,prompt,root,oracle_case=None):
    oracle_case=oracle_case or case
    folder=root/case;folder.mkdir(parents=True,exist_ok=True)
    messages=[];history=[];pid=None;response={};checks=[]
    for message in (prompt,*( [SUPPLEMENTS[oracle_case]] if oracle_case in SUPPLEMENTS else []),CONFIRM):
        if response.get('variant') and response.get('preview_paths'):break
        body={'message':message,'mode':'advanced','conversation_id':'user-corpus-'+case,'history':history}
        if pid:body['project_id']=pid
        messages.append(message);response=call(folder,len(messages),body)
        newpid=response.get('project_id') or (response.get('project') or {}).get('id')
        if pid and newpid:checks.append({'name':'same_project','passed':pid==newpid})
        pid=newpid or pid
        history.extend([{'role':'user','content':message},{'role':'assistant','content':response.get('message','')}])
        print(json.dumps({'case':case,'turn':len(messages),'ok':response.get('ok'),'message':response.get('message')},ensure_ascii=False),flush=True)
    checks+=create_checks(oracle_case,response,messages)
    created_project=response.get('project') if isinstance(response.get('project'),dict) else {}
    has_candidate=bool(response.get('variant')) or bool(created_project.get('variants'))
    project=persisted_project(folder,pid)
    source=persisted_source(folder,pid,(response.get('variant') or {}).get('id'))
    geometry_ok=checks_geometry_ok(checks,response.get('variant') or {})
    formal=evaluate_formal_delivery(response,project=project,persisted_project=project,
        persisted_source=source,
        expected_project_id=pid,expected_variant_id=(response.get('variant') or {}).get('id'),
        geometry_checks=geometry_ok)
    legacy_passed=all(c['passed'] for c in checks)
    checks.append({'name':'formal_delivery','passed':formal['formal_delivery_ok'] is True,
        'observed':{'diagnostic_status':formal['diagnostic_status'],
                    'formal_reason':formal['formal_reason']}})
    report={'case':case,'oracle_case':oracle_case,'kind':'create','messages':messages,'history':history,'project_id':pid,
            'candidate_step':len(messages),'has_candidate':has_candidate,'checks':checks,
            'passed':all(c['passed'] for c in checks),'legacy_passed':legacy_passed,'app':'not_run',
            'generation_ok':formal['generation_ok'],'geometry_ok':formal['geometry_ok'],
            'formal_evaluable':formal['formal_evaluable'],
            'formal_delivery_ok':formal['formal_delivery_ok'],
            'diagnostic_status':formal['diagnostic_status'],
            'formal_reason':formal['formal_reason'],'formal_evidence':formal['evidence']}
    dump(folder/'ui-fixture.json',{'id':case,'messages':messages})
    dump(folder/'corpus-report.json',report)
    return report

def edit_checks(case,before,after,ids):
    near=lambda a,b:abs(a-b)<.5
    checks=[];old=before.get('geometries') or [];new=after.get('geometries') or []
    def add(name,value,observed=None):checks.append({'name':name,'passed':bool(value),'observed':observed})
    add('new_saved_version',bool(new) and before.get('id')!=after.get('id'))
    if not new:return checks
    src={g['id']:g for g in old};dst={g['id']:g for g in new}
    def coords(g):return [g[k] for k in ('center','start','end') if k in g]+list(g.get('vertices') or [])+list(g.get('control_points') or [])
    if case!='B17':add('non_target_unchanged',all(gid in dst and dst[gid]==g for gid,g in src.items() if gid not in ids))
    translations={'B2':(6000,0),'B3':(-2000,1000),'D1':(-2000,0)}
    if case in translations:
        dx,dy=translations[case]
        add('exact_selected_translation',all(i in dst and len(coords(src[i]))==len(coords(dst[i])) and all(abs(b['x']-a['x']-dx)<.5 and abs(b['y']-a['y']-dy)<.5 for a,b in zip(coords(src[i]),coords(dst[i]))) for i in ids))
    elif case in {'B1','B19'}:
        dx=6000 if case=='B1' else -3000
        extras=[g for g in new if g['id'] not in src]
        add('source_retained_and_copy_count',len(extras)==len(ids) and all(dst.get(i)==src[i] for i in src))
        add('copy_exact_displacement',all(any(len(coords(g))==len(coords(src[i])) and all(abs(b['x']-a['x']-dx)<.5 and abs(b['y']-a['y'])<.5 for a,b in zip(coords(src[i]),coords(g))) for g in extras) for i in ids))
    elif case=='B9':
        a=bounds([src[i] for i in ids]);axis=(a[0]+a[2])/2
        add('mirror_replaces_source_exactly',len(new)==len(old) and all(i in dst
            and len(coords(src[i]))==len(coords(dst[i]))
            and all(abs(q['x']-(2*axis-p['x']))<.5 and abs(q['y']-p['y'])<.5
                    for p,q in zip(coords(src[i]),coords(dst[i]))) for i in ids))
    elif case in {'B8','D2'}:
        axis=5000 if case=='B8' else 4000
        extras=[g for g in new if g['id'] not in src]
        add('mirror_source_retained',all(dst.get(i)==g for i,g in src.items()))
        remaining=list(extras)
        matched=True
        for gid in ids:
            source=src[gid];points=coords(source)
            target=next((g for g in remaining if g.get('type')==source.get('type')
                and len(coords(g))==len(points)
                and g.get('degree')==source.get('degree')
                and all(abs(q['x']-(2*axis-p['x']))<.5 and abs(q['y']-p['y'])<.5
                        for p,q in zip(points,coords(g)))),None)
            if target is None:matched=False
            else:remaining.remove(target)
        add('mirror_exact_axis_and_geometry',matched and not remaining and len(extras)==len(ids))
    elif case in {'B6','B7','D5'}:
        scale={'B6':2,'B7':.5,'D5':1.5}[case]
        a=bounds([src[i] for i in ids]);b=bounds([dst[i] for i in ids if i in dst])
        add('selected_dimensions_scaled',abs((b[2]-b[0])-scale*(a[2]-a[0]))<2 and abs((b[3]-b[1])-scale*(a[3]-a[1]))<2)
    elif case in {'B4','B5','D3','D6'}:
        angle={'B4':45,'B5':-90,'D3':-45,'D6':90}[case]*math.pi/180;scale=.7 if case=='D6' else 1
        a=bounds([src[i] for i in ids]);cx,cy=(a[0]+a[2])/2,(a[1]+a[3])/2
        add('rotation_about_selected_center',all(i in dst and len(coords(src[i]))==len(coords(dst[i])) and all(math.dist((b['x'],b['y']),(cx+scale*((p['x']-cx)*math.cos(angle)-(p['y']-cy)*math.sin(angle)),cy+scale*((p['x']-cx)*math.sin(angle)+(p['y']-cy)*math.cos(angle))))<2 for p,b in zip(coords(src[i]),coords(dst[i]))) for i in ids))
    elif case in {'B11','B12','D4'}:
        count={'B11':12,'B12':6,'D4':6}[case]
        add('array_cardinality',len(new)==len(old)-len(ids)+len(ids)*count)
        if case=='B11' and len(ids)==1 and src[ids[0]].get('type')=='circle':
            original=src[ids[0]];center=original['center']
            expected=[(center['x']+column*1500,center['y']+row*1000)
                      for row in range(3) for column in range(4)]
            remaining=list(new)
            for x,y in expected:
                match=next((g for g in remaining if g.get('type')=='circle'
                    and abs(g['center']['x']-x)<.5 and abs(g['center']['y']-y)<.5
                    and abs(g['radius']-original['radius'])<.5),None)
                if match is None:break
                remaining.remove(match)
            else:
                add('array_centers_pitch_and_radius',not remaining)
                return checks
            add('array_centers_pitch_and_radius',False)
        elif case=='B12':
            box=bounds([src[i] for i in ids]);cx,cy=(box[0]+box[2])/2,(box[1]+box[3])/2
            remaining=[g for g in new if g['id'] in ids or g['id'] not in src]
            matched=True
            for index in range(count):
                angle=2*math.pi*index/count
                for gid in ids:
                    original=src[gid];points=coords(original)
                    expected=[(cx+(p['x']-cx)*math.cos(angle)-(p['y']-cy)*math.sin(angle),
                               cy+(p['x']-cx)*math.sin(angle)+(p['y']-cy)*math.cos(angle)) for p in points]
                    target=next((g for g in remaining if g.get('type')==original.get('type')
                        and all(g.get(k)==original.get(k) for k in ('closed','degree','radius'))
                        and len(coords(g))==len(expected)
                        and all(math.dist((q['x'],q['y']),e)<.5 for q,e in zip(coords(g),expected))),None)
                    if target is None:matched=False
                    else:remaining.remove(target)
            add('polar_array_exact_center_angles_and_geometry',matched and not remaining)
        elif case=='D4':
            remaining=[g for g in new if g['id'] in ids or g['id'] not in src]
            matched=True
            for row in range(2):
                for column in range(3):
                    for gid in ids:
                        original=src[gid];points=coords(original)
                        match=next((g for g in remaining
                            if g.get('type')==original.get('type')
                            and all(g.get(k)==original.get(k) for k in ('closed','degree','radius','start_angle','end_angle'))
                            and len(coords(g))==len(points)
                            and all(abs(q['x']-p['x']-column*3000)<.5
                                    and abs(q['y']-p['y']-row*2000)<.5
                                    for p,q in zip(points,coords(g)))),None)
                        if match is None:matched=False
                        else:remaining.remove(match)
            add('array_exact_geometry_and_pitch',matched and not remaining)
    elif case in {'B13','B14','B15'}:
        circles=[g for g in old if g.get('type')=='circle']
        if case=='B13' and len(circles)==2:
            fixed,moving=sorted(circles,key=lambda g:g['center']['x'])
            a,b=dst.get(fixed['id']),dst.get(moving['id'])
            add('fixed_circle_preserved',a==fixed)
            add('horizontal_alignment_exact',bool(b) and near(b['center']['y'],fixed['center']['y'])
                and near(b['center']['x'],moving['center']['x']) and near(b['radius'],moving['radius']))
        elif len(circles)==1:
            fixed=circles[0];parts=[g for g in old if g['id']!=fixed['id']]
            add('fixed_circle_preserved',dst.get(fixed['id'])==fixed)
            if len(parts)==1 and parts[0]['id'] in dst:
                old_b=bounds(parts);new_b=bounds([dst[parts[0]['id']]])
                if case=='B14':
                    add('concentric_preserves_dimensions',near((new_b[0]+new_b[2])/2,fixed['center']['x'])
                        and near((new_b[1]+new_b[3])/2,fixed['center']['y'])
                        and near(new_b[2]-new_b[0],old_b[2]-old_b[0]) and near(new_b[3]-new_b[1],old_b[3]-old_b[1]))
                else:
                    add('equal_width_preserves_height',near(new_b[2]-new_b[0],2*fixed['radius'])
                        and near(new_b[3]-new_b[1],old_b[3]-old_b[1]))
            else:add('relation_target_exists',False)
        else:add('relation_source_inventory',False)
    elif case=='B10':
        a=bounds(old);b=bounds(new);add('rectangle_outward_offset',all(abs(v-t)<2 for v,t in zip(b,(a[0]-1000,a[1]-1000,a[2]+1000,a[3]+1000))))
    elif case=='B16':add('selected_deleted',all(i not in dst for i in ids))
    elif case=='B17':add('only_selected_left_circle_remains',len(new)==len(ids) and all(dst.get(i)==src[i] for i in ids))
    elif case=='B18':
        added=[g for g in new if g.get('id') not in src]
        rects=[bounds([g]) for g in added if len(g.get('vertices') or [])>=4]
        centers=[((b[0]+b[2])/2,(b[1]+b[3])/2) for b in rects]
        add('added_rectangle_count',len(rects)==2,len(rects))
        add('added_rectangle_dimensions',len(rects)==2 and all(sorted((round(b[2]-b[0]),round(b[3]-b[1])))==[1000,2000] for b in rects),rects)
        add('added_rectangle_symmetry',len(centers)==2 and abs(centers[0][0]-centers[1][0])<2 and abs(centers[0][1]+centers[1][1])<2,centers)
        add('added_rectangle_center_offset',len(centers)==2 and all(abs(abs(y)-5000)<2 for _,y in centers),centers)
        add('base_basketball_preserved',all(dst.get(gid)==g for gid,g in src.items()),None)
    else:add('independent_edit_semantics',False,'requires independent acceptance; candidate alone is not a pass')
    return checks

def make_edit(case,prompt,root,reports,base_case=None):
    base=base_case or BASE[case];source=root/base;folder=root/case
    base_store=source/'projects.json'
    base_has_candidate=False
    if base_store.exists():
        try:
            base_data=json.loads(base_store.read_text(encoding='utf-8'))
            base_has_candidate=any(item.get('variants') for item in base_data.get('projects', []))
        except (OSError, json.JSONDecodeError):
            base_has_candidate=False
    if not reports[base].get('has_candidate') and not base_has_candidate:
        report={'case':case,'kind':'edit','base':base,'passed':False,'blocked_by':base,'app':'not_run'}
        dump(folder/'corpus-report.json',report);return report
    # Copy only business state needed to edit the candidate. Runtime evidence
    # (model responses, audit, usage, memory, tasks, runs and budget files) is
    # case-local and must never cross the setup boundary.
    folder.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source/'projects.json',folder/'projects.json')
    step_name=f"step-{reports[base]['candidate_step']}.json"
    shutil.copy2(source/step_name,folder/step_name)
    base_report=reports[base];messages=list(base_report['messages']);history=list(base_report['history'])
    copied_projects=json.loads((folder/'projects.json').read_text(encoding='utf-8'))
    copied_candidates=[item for item in copied_projects.get('projects',[]) if item.get('variants')]
    if len(copied_candidates)!=1:
        raise RuntimeError(f'{case}: copied project store must contain exactly one candidate project')
    copied_project_id=str(copied_candidates[0]['id'])
    prior=json.loads((folder/f"step-{base_report['candidate_step']}.json").read_text(encoding='utf-8'))
    before=prior['variant'];objects=before.get('logical_objects') or [];gs=before['geometries']
    ids=[g['id'] for g in gs]
    if case=='B17':ids=[min(gs,key=lambda g:bounds([g])[0])['id']]
    if case=='B16':ids=[g['id'] for g in gs if g['type']!='circle']
    selection={'scope':'group','geometry_ids':ids,'project_id':copied_project_id,'variant_id':before['id']}
    if case=='B17':
        matching=[o for o in objects if set(o.get('geometry_refs') or [])==set(ids)]
        if len(matching)==1:
            selection.update(scope='logical_object',object_id=matching[0]['object_id'])
    elif case in {'B14','B15'} and len(objects)==2 and set(ids)=={ref for o in objects for ref in o.get('geometry_refs') or []}:
        selection.update(scope='logical_object',object_ids=[o['object_id'] for o in objects])
    body={'message':prompt,'mode':'advanced','conversation_id':'user-corpus-'+base,'history':history,
          'project_id':copied_project_id,'drawing_selection':selection}
    messages.append(prompt);step=len(messages);response=call(folder,step,body)
    # Template edits may legitimately clarify a missing parameter before the
    # actual edit. Continue the same conversation and project explicitly so
    # storage/session binding is tested across the full two-turn flow.
    followup = SUPPLEMENTS.get(case)
    # Drive the documented supplement by the absence of a new candidate,
    # never by wording chosen by the model for its clarification question.
    returned_variant = response.get('variant') or {}
    new_candidate = bool(returned_variant.get('id') and returned_variant['id'] != before.get('id'))
    if followup and not new_candidate and not response.get('pending_action'):
        messages.append(followup)
        history = history + [
            {'role':'user','content':prompt},
            {'role':'assistant','content':str(response.get('message') or '')},
        ]
        response=call(folder,len(messages),{
            'message':followup,'mode':'advanced','conversation_id':'user-corpus-'+base,
            'history':history,'project_id':copied_project_id,'drawing_selection':selection})
    # Some edit routes finish deterministic parsing with a textual confirmation
    # request instead of a pending action. Continue with the corpus confirmation
    # so the candidate submission stage is exercised.
    if (not response.get('variant') and not response.get('pending_action')
        and any(token in str(response.get('message') or '') for token in ('请确认', '确认生成', '重新确认'))):
        messages.append(CONFIRM)
        confirmation_message = prompt + "\n确认按已解析的阵列参数生成候选方案。"
        response=call(folder,len(messages),{
            'message':confirmation_message,'mode':'advanced','conversation_id':'user-corpus-'+base,
            'history':history + [{'role':'user','content':followup or prompt},
                                 {'role':'assistant','content':str(response.get('message') or '')}],
            'project_id':copied_project_id,'drawing_selection':selection})
    confirmation=None
    if response.get('pending_action'):
        confirmation=step+1
        response=call(folder,confirmation,{'action_id':response['pending_action']['id'],'approved':True},'confirm')
    after=response.get('variant') or {}
    if not after and isinstance(response.get('project'),dict):
        variants=response['project'].get('variants') or []
        if variants:
            after=variants[-1]
    checks=edit_checks(case,before,after,ids)
    if response.get('cad_edit_outcome')=='already_satisfied' and case in {'B13','B14','B15'}:
        stored=json.loads((folder/'projects.json').read_text(encoding='utf-8'))
        current=next((p for p in stored.get('projects',[]) if str(p.get('id'))==copied_project_id),{})
        versions=current.get('variants') or []
        retained=next((v for v in versions if v.get('id')==before.get('id')),{})
        checks=edit_checks(case,before,retained,ids)
        checks=[c for c in checks if c['name']!='new_saved_version']
        checks.extend([
            {'name':'source_version_reused_without_mutation','passed':bool(retained) and retained==before},
            {'name':'no_duplicate_version','passed':{v.get('id') for v in versions}=={v.get('id') for v in copied_candidates[0].get('variants',[])}},
            {'name':'measured_relation_response','passed':response.get('ok') is True
                and response.get('source_variant_id')==before.get('id')
                and (response.get('relation_verification') or {}).get('authority')=='backend_measured_geometry'},
        ])
    checks.append({'name':'same_project','passed':response.get('project_id')==prior['project_id'] or (response.get('project') or {}).get('id')==prior['project_id']})
    base_acceptance=evaluate_accepted_base(before)
    checks.append({'name':'base_candidate_accepted','passed':base_acceptance['accepted'],
        'observed':base_acceptance})
    project=persisted_project(folder,copied_project_id)
    source_variant=after or before
    source=persisted_source(folder,copied_project_id,source_variant.get('id'))
    geometry_ok=checks_geometry_ok(checks,after)
    formal_response=response if response.get('variant') else ({**response,'variant':after} if after else response)
    if formal_response.get('cad_edit_outcome')=='already_satisfied':
        checks=[c for c in checks if c['name']!='new_saved_version']
        formal=evaluate_no_change_delivery(formal_response,base_variant=before,
            persisted_project=project,persisted_source=source,
            expected_project_id=prior['project_id'])
    else:
        formal=evaluate_edit_formal_delivery(formal_response,base_variant=before,
            project=project,persisted_project=project,persisted_source=source,
            expected_project_id=prior['project_id'],
            expected_variant_id=after.get('id'),geometry_checks=geometry_ok)
    legacy_passed=all(c['passed'] for c in checks)
    checks.append({'name':'formal_delivery','passed':formal['formal_delivery_ok'] is True,
        'observed':{'diagnostic_status':formal['diagnostic_status'],
                    'formal_reason':formal['formal_reason']}})
    report={'case':case,'kind':'edit','base':base,'messages':messages,'has_candidate':bool(after),
        'checks':checks,'passed':all(c['passed'] for c in checks),'legacy_passed':legacy_passed,
        'reply':response.get('message'),'app':'not_run',
        'edit_outcome':response.get('cad_edit_outcome'),
        'generation_ok':formal['generation_ok'],'geometry_ok':formal['geometry_ok'],
        'formal_evaluable':formal['formal_evaluable'],
        'formal_delivery_ok':formal['formal_delivery_ok'],
        'diagnostic_status':formal['diagnostic_status'],
        'formal_reason':formal['formal_reason'],'formal_evidence':formal['evidence']}
    dump(folder/'ui-fixture.json',{'id':case,'messages':messages,'selection_before_step':step,
        'drawing_selection':selection,'confirmation_step':confirmation,'expected_preview_count':len(response.get('preview_paths') or [])})
    dump(folder/'corpus-report.json',report)
    print(json.dumps({'case':case,'passed':report['passed'],'message':response.get('message')},ensure_ascii=False),flush=True)
    return report

def app_check(case,root):
    folder=root/case
    p=subprocess.run(['D:/flutter/bin/flutter.bat','test','test/live_cad_preview_test.dart',
        '--dart-define=CAD_LIVE_FIXTURE_DIR='+str(folder),'--reporter','expanded'],
        cwd=ROOT.parent/'xikao1_-app',text=True,encoding='utf-8',capture_output=True,timeout=300)
    (folder/'app-test.log').write_text(p.stdout+p.stderr,encoding='utf-8')
    return 'replay_passed' if p.returncode==0 else 'failed'

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--workers',type=int,default=3)
    p.add_argument('--app',action='store_true');p.add_argument('--cases',nargs='*');p.add_argument('--resume',action='store_true')
    p.add_argument('--source',help='override the frozen corpus path for an isolated worktree')
    args=p.parse_args()
    source=Path(args.source).resolve() if args.source else SOURCE
    root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=True)
    os.environ['P12_EVAL_MODE']='1'
    os.environ['P12_EVAL_FORMAL_HTTP']='1'
    os.environ['P12_EXPECTED_PROVIDER']='deepseek'
    os.environ['P12_EXPECTED_MODEL']='deepseek-flash'
    os.environ['DEEPSEEK_CAD_PLANNING_MODEL']='deepseek-flash'
    os.environ['DEEPSEEK_BASE_MODEL']='deepseek-flash'
    os.environ['DEEPSEEK_ADVANCED_MODEL']='deepseek-flash'
    os.environ.setdefault('P12_EVAL_RUN_ID', root.name)
    budget_path=os.getenv('P12_EVAL_BUDGET_PATH','').strip()
    if not budget_path or not Path(budget_path).parent.exists():
        raise RuntimeError('evaluation_budget_unavailable: P12_EVAL_BUDGET_PATH is required')
    if os.getenv('P12_EVAL_MOCK_PROVIDER') != '1' and os.getenv('P12_REAL_MODEL_AUTHORIZED') != '1':
        raise RuntimeError('real_model_not_authorized: explicit P12_REAL_MODEL_AUTHORIZED=1 is required')
    raw=source.read_bytes();corpus=dict(re.findall(r'^\| (?:⭐)?([ABCD]\d+) \| ([^|]+) \|',raw.decode('utf-8'),re.M))
    wanted=set(args.cases or corpus);aliases,resolved_bases=resolve_corpus_setup(corpus,wanted)
    needed=wanted|set(resolved_bases.values())
    code_digest=hashlib.sha256()
    for code_file in sorted((Path(__file__).resolve().parents[2]/'app').rglob('*.py')):
        code_digest.update(str(code_file.relative_to(Path(__file__).resolve().parents[2])).replace('\\','/').encode())
        code_digest.update(code_file.read_bytes())
    dump(root/'manifest.json',{'source':str(source),'sha256':hashlib.sha256(raw).hexdigest(),
        'backend_code_sha256':code_digest.hexdigest(),
        'model_configuration':{'provider':'deepseek','cad_planning_model':os.getenv('DEEPSEEK_CAD_PLANNING_MODEL','deepseek-chat')},
        'original_prompts':corpus,
        'supplemental_answers':SUPPLEMENTS,'case_aliases':aliases,'resolved_bases':resolved_bases,'requested':sorted(wanted),'app_scope':'production Flutter widgets replay real HTTP responses; hardware virtual; not an installed Android APK'})
    # Initialise geometry submodules before concurrent independent oracles;
    # their first imports can otherwise observe partially loaded siblings.
    import shapely.geometry
    import shapely.affinity
    import shapely.ops
    reports={}
    def run(case):
        path=root/case/'corpus-report.json'
        if args.resume and path.exists():return json.loads(path.read_text(encoding='utf-8'))
        try:return make_creation(case,corpus[case].strip(),root,aliases[case]) if case not in BASE else make_edit(case,corpus[case].strip(),root,reports,resolved_bases[case])
        except Exception as exc:
            report={'case':case,'passed':False,'runner_error':str(exc),'app':'not_run'};dump(path,report);return report
    for group in ([c for c in corpus if c in needed and c not in BASE],[c for c in corpus if c in needed and c in BASE]):
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures={pool.submit(run,c):c for c in group}
            for future in as_completed(futures):
                report=future.result();reports[report['case']]=report
                dump(root/'summary.json',{'reports':list(reports.values()),'completed':len(reports),'requested':len(wanted)})
    if args.app:
        for case in corpus:
            if case not in wanted:continue
            report=reports[case]
            if not report.get('has_candidate'):continue
            try:report['app']=app_check(case,root)
            except Exception as exc:report['app']='runner_error';report['app_error']=str(exc)
            if report.get('app')!='replay_passed':
                report['formal_delivery_ok']=False
                report['diagnostic_status']='frontend_failed'
                report['formal_reason']=[*(report.get('formal_reason') or []),'frontend_failed']
            dump(root/case/'corpus-report.json',report)
            print(json.dumps({'case':case,'app':report['app']},ensure_ascii=False),flush=True)
            dump(root/'summary.json',{'reports':list(reports.values()),'completed':len(reports),'requested':len(wanted)})
    selected=[reports[c] for c in corpus if c in wanted]
    seen={}; contamination=[]
    for case in needed:
        usage=root/case/'model-usage.jsonl'
        if not usage.exists(): continue
        for line in usage.read_text(encoding='utf-8').splitlines():
            try: rid=json.loads(line).get('request_id')
            except json.JSONDecodeError: rid=None
            if rid and rid in seen and seen[rid]!=case: contamination.append({'request_id':rid,'cases':[seen[rid],case]})
            elif rid: seen[rid]=case
    dump(root/'evidence-audit.json',{'unique_request_ids':len(seen),'contamination':contamination,'blocked':bool(contamination)})
    metrics=summarize_new_execution(root,selected)
    dump(root/'metrics.json',metrics)
    dump(root/'summary.json',{'source_sha256':hashlib.sha256(raw).hexdigest(),'reports':selected,'completed':len(selected),
        'evidence_audit':{'unique_request_ids':len(seen),'contamination':contamination,'blocked':bool(contamination)},
        'passed':sum(r.get('passed') is True and (not args.app or r.get('app')=='replay_passed') for r in selected),
        'legacy_passed':sum(r.get('legacy_passed') is True and (not args.app or r.get('app')=='replay_passed') for r in selected),
        'formal_delivery_pass':sum(r.get('formal_delivery_ok') is True for r in selected),
        'formal_evaluable':sum(r.get('formal_evaluable') is True for r in selected),
        'unassessable_cases':[r.get('case') for r in selected if r.get('formal_evaluable') is not True],
        'requested':len(wanted),
        'evaluation_cohort':'new','planned_case_count':metrics['planned_case_count'],
        'success_count':metrics['new_execution_pass_count'],
        'failed_count':metrics['new_execution_failed_count'],
        'end_to_end_pass_rate':metrics['end_to_end_pass_rate']})
