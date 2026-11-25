from copy import deepcopy

import pytest

from evaluations.production_contract_pilot import cases, oracle
from evaluations.relation_pilot.cases import expected_entities


@pytest.mark.parametrize('row', [r for r in cases() if not r['family'].endswith('_control')], ids=lambda r:r['id'])
def test_new_case_oracles_accept_goldens_and_reject_translation(row):
    geometries=expected_entities(row)
    assert oracle(row,geometries)['passed']
    wrong=deepcopy(geometries)
    for g in wrong:
        for k in ('center','start','end'):
            if k in g:g[k]['x']+=10
    assert not oracle(row,wrong)['passed']


def test_controls_reject_wrong_dimensions_and_duplicate_geometry():
    circle=next(r for r in cases() if r['id']=='Q2')
    g={'id':1,'type':'circle','center':{'x':-800,'y':1100},'radius':650}
    assert oracle(circle,[g])['passed']
    assert not oracle(circle,[g,{**g,'id':2}])['passed']
    assert not oracle(circle,[{**g,'radius':660}])['passed']
    rect=next(r for r in cases() if r['id']=='Q1')
    outline={'type':'polyline','closed':True,'vertices':[{'x':x,'y':y} for x,y in [(1200,-700),(4800,-700),(4800,1700),(1200,1700)]]}
    assert oracle(rect,[outline])['passed']
    outline['vertices'][1]['x']+=10
    assert not oracle(rect,[outline])['passed']
