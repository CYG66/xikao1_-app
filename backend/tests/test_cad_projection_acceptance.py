import itertools
import math
from copy import deepcopy
import pytest
from app.cad_projection_acceptance import verify_projection_requirements
from app.cad_structure_contract import StructureContractError

SOURCE='画一个立方体的二维等轴投影，各投影棱长2米，包含隐藏的12条棱线'


def edges():
    vectors=[(0,2000),(-math.sqrt(3)*1000,-1000),(math.sqrt(3)*1000,-1000)]
    points={bits:{k:sum(bits[i]*vectors[i][axis] for i in range(3))
                  for axis,k in enumerate(('x','y'))} for bits in itertools.product((0,1),repeat=3)}
    result=[]
    for bits,start in points.items():
        for axis in range(3):
            if bits[axis]:continue
            end=list(bits);end[axis]=1
            result.append({'id':len(result)+1,'type':'line','start':start,'end':points[tuple(end)]})
    return result


def test_coincident_projection_vertices_are_valid():
    assert verify_projection_requirements(SOURCE,edges())['status']=='passed'


@pytest.mark.parametrize('damage',['duplicate','shift','length','direction','missing'])
def test_twelve_edges_alone_cannot_prove_projection(damage):
    lines=deepcopy(edges())
    if damage=='duplicate':lines[-1]={**deepcopy(lines[0]),'id':12}
    elif damage=='shift':
        for point in ('start','end'):lines[-1][point]['x']+=100
    elif damage=='length':lines[-1]['end']['x']+=100
    elif damage=='direction':
        for line in lines:
            for point in ('start','end'):line[point]['x']*=2
    else:lines.pop()
    with pytest.raises(StructureContractError):verify_projection_requirements(SOURCE,lines)


def test_rigid_transform_and_edge_order_do_not_change_acceptance():
    lines=deepcopy(edges());angle=.37
    for line in lines:
        for key in ('start','end'):
            x,y=line[key]['x'],line[key]['y']
            line[key]={'x':x*math.cos(angle)-y*math.sin(angle)+4700,
                       'y':x*math.sin(angle)+y*math.cos(angle)-300}
    assert verify_projection_requirements(SOURCE,list(reversed(lines)))['status']=='passed'


def test_unspecified_projection_is_not_falsely_certified():
    assert verify_projection_requirements('画一个立方体透视图',edges())['status']=='not_checked'
    assert verify_projection_requirements('画一个立方体和一个圆，等轴投影，12条棱线',edges())['status']=='not_checked'
