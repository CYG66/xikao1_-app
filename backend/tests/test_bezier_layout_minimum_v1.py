from copy import deepcopy
import pytest
from evaluations.bezier_layout_minimum_v1 import measure


def plan(flat=False,unit='m'):
    k=1 if unit=='m' else 1000
    def segment(points):return {'kind':'bezier','control_points':[{'x':x*k,'y':y*k} for x,y in points]}
    start=(0,2) if flat else (0,2.09);end=(1,2) if flat else (1,2.49)
    return {'units':unit,'steps':[{'step_id':'outline','output_ref':'outline','semantic':{'label':'轮廓'},
        'op':'add_composite_path','closed':True,'continuity':'C0','samples_per_curve':16,
        'segments':[segment([start,(.5,2 if flat else 1.79),end]),
            segment([end,(1,4),(0,4)]),segment([(0,4),(0,3),start])]}],
        'free_outline_layout':[{'target_ref':'outline','width':4*k,'height':3*k,'center':{'x':6*k,'y':7*k}}]}


@pytest.mark.parametrize('unit',['m','mm'])
def test_layout_mapping_keeps_true_isolated_minimum_between_samples(unit):
    source=plan(unit=unit);before=deepcopy(source);result=measure(source)
    assert source==before
    assert result['status']=='mapped_analytic_candidates'
    assert result['minimum_kind']=='isolated_point'
    assert result['source_min_below_sample_mm']>0
    mapping=result['layout_map_mm']
    assert result['minimum_points_mm'][0][0]==pytest.approx(mapping['sx']*300+mapping['tx'])
    assert mapping['residual_mm']<1e-6


@pytest.mark.parametrize('unit',['m','mm'])
def test_real_flat_bezier_segment_remains_an_interval_after_layout(unit):
    result=measure(plan(flat=True,unit=unit))
    assert result['minimum_kind']=='flat_interval'
    assert result['minimum_intervals_mm'][0]['x_interval_mm']==pytest.approx([4000,8000])
    assert result['minimum_y_mm']==pytest.approx(5500)


def test_mixed_or_multi_step_paths_remain_unverified():
    source=plan();source['steps'][0]['segments'][0]={'kind':'line','start':{'x':0,'y':2},'end':{'x':1,'y':2.49}}
    assert measure(source)['status']=='unverified'
    source=plan();source['steps'].append(deepcopy(source['steps'][0]))
    assert measure(source)['status']=='unverified'
