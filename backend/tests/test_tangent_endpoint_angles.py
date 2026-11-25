from copy import deepcopy
import math
import pytest
from app.cad_connection_direction import resolve_tangent_arc_directions
from app.cad_construction import execute_construction_plan


def fixture(angle,scale):
    def p(x,y):
        a=math.radians(angle)
        return {'x':17+scale*(x*math.cos(a)-y*math.sin(a)),
                'y':-29+scale*(x*math.sin(a)+y*math.cos(a))}
    return {'op':'add_composite_path','step_id':'path','output_ref':'path','semantic':{'label':'边界'},
        'segments':[{'kind':'line','start':p(2,-3),'end':p(0,-3)},
        {'kind':'arc','center':p(0,0),'radius':3*scale,'start_angle':angle,'end_angle':angle+180},
        {'kind':'line','start':p(0,3),'end':p(2,3)}]}


@pytest.mark.parametrize('angle',[-137,-26,0,39,173])
@pytest.mark.parametrize('scale',[1,1000])
def test_unique_tangent_solution_preserves_existing_geometry_inputs(angle,scale):
    step=fixture(angle,scale);before=deepcopy(step)
    changes=resolve_tangent_arc_directions(step,'两条直边与圆弧相切。')
    assert len(changes)==1 and changes[0]['kind']=='resolve_source_tangent_arc_angles'
    assert step['segments'][::2]==before['segments'][::2]
    for key in ('center','radius'):assert step['segments'][1][key]==before['segments'][1][key]
    result=execute_construction_plan({'units':'mm','steps':[step]})
    assert result['geometries']
    assert not resolve_tangent_arc_directions(step,'两条直边与圆弧相切。')


@pytest.mark.parametrize('source',['画一段圆弧','不要相切','圆弧逆时针，相切','起始角0度、终止角180度，相切','从0度到180度，相切'])
def test_source_winding_and_explicit_endpoint_authority_is_preserved(source):
    step=fixture(0,1);before=deepcopy(step)
    assert not resolve_tangent_arc_directions(step,source) and step==before


def test_off_circle_or_wrong_tangent_is_not_repaired():
    for mutation in ('off_circle','wrong_tangent'):
        step=fixture(0,1)
        if mutation=='off_circle':step['segments'][0]['end']['y']+=.01
        else:step['segments'][0]['start']['y']+=1
        before=deepcopy(step)
        assert not resolve_tangent_arc_directions(step,'两条直边与圆弧相切。') and step==before
