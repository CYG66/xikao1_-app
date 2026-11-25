from copy import deepcopy
import json
from pathlib import Path
import pytest
from evaluations.closed_boundary_oracle_v3 import single_closed_boundary


def native_arch():
    root=Path(__file__).parent/'fixtures/recorded_native_arch_boundary.json'
    return json.loads(root.read_text(encoding='utf-8'))


def test_native_arc_and_lines_are_one_physical_boundary():
    geometries=native_arch();before=deepcopy(geometries)
    assert single_closed_boundary(geometries)['passed']
    assert single_closed_boundary(list(reversed(geometries)))['passed']
    assert geometries==before


@pytest.mark.parametrize('damage',['missing','duplicate','gap','extra_loop','zero_arc'])
def test_invalid_native_boundary_stays_rejected(damage):
    geometries=native_arch()
    if damage=='missing':geometries.pop()
    elif damage=='duplicate':geometries.append(deepcopy(geometries[-1]))
    elif damage=='gap':
        line=next(g for g in geometries if g['type']=='line');line['start']['x']+=5
    elif damage=='zero_arc':
        arc=next(g for g in geometries if g['type']=='arc');arc['end_angle']=arc['start_angle']
    else:geometries.append({'id':99,'type':'polyline','closed':True,'vertices':[{'x':10000,'y':0},{'x':11000,'y':0},{'x':11000,'y':1000}]})
    assert not single_closed_boundary(geometries)['passed']
