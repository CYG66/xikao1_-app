from copy import deepcopy
import pytest
from evaluations.frozen_release_validation import holdouts,holdout_oracle
from evaluations.relation_pilot.cases import expected_entities


def golden(row):
    if 'expected' in row:return deepcopy(row['expected'])
    if row['family']=='circle_control':
        factor={'米':1000,'厘米':10,'毫米':1}[row['unit']]
        return [{'type':'circle','center':dict(zip(('x','y'),[v*factor for v in row['origin']])),'radius':row['radius']*factor}]
    if row['family']=='rectangle_control':
        x,y=[v*1000 for v in row['origin']];w=row['width']*1000;h=row['height']*1000
        return [{'type':'polyline','closed':True,'vertices':[{'x':a,'y':b} for a,b in [(x,y),(x+w,y),(x+w,y+h),(x,y+h)]]}]
    return expected_entities(row)


@pytest.mark.parametrize('row',holdouts(),ids=lambda r:r['id'])
def test_frozen_holdout_oracle_accepts_golden_and_rejects_translation(row):
    gs=golden(row);assert holdout_oracle(row,gs)['passed']
    wrong=deepcopy(gs)
    for g in wrong:
        for k in ('start','end','center'):
            if k in g:g[k]['x']+=20
        for p in g.get('vertices',[]):p['x']+=20
    assert not holdout_oracle(row,wrong)['passed']
