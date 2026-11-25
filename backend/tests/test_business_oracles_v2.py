from copy import deepcopy
import itertools
import math

import pytest

from evaluations.business_oracles_v2 import projected_cube_incidence,retained_circle_rotation
from evaluations.business_oracles_v2 import orthographic_cylinder_views


def cube(length=1700,angle=.37,offset=(123,456)):
    axes=[(length*math.cos(angle+i*math.tau/3),length*math.sin(angle+i*math.tau/3)) for i in range(3)]
    vertices={bits:{k:offset[j]+sum(b*axes[i][j] for i,b in enumerate(bits)) for j,k in enumerate(('x','y'))}
              for bits in itertools.product((0,1),repeat=3)}
    lines=[]
    for bits,start in vertices.items():
        for i in range(3):
            if not bits[i]:
                end=list(bits);end[i]=1
                lines.append({'id':len(lines)+1,'type':'line','start':deepcopy(start),'end':deepcopy(vertices[tuple(end)])})
    return lines


@pytest.mark.parametrize('length,angle,offset',[(1700,.37,(123,456)),(500,-.8,(-900,77)),(3200,0,(0,0))])
def test_independent_topology_supports_rigid_transforms_and_collapsed_vertices(length,angle,offset):
    lines=cube(length,angle,offset)
    for g in lines:g['start'],g['end']=g['end'],g['start']
    proof=projected_cube_incidence(list(reversed(lines)),length)
    assert proof['passed'] and proof['collapsed_opposite_vertices_supported']


@pytest.mark.parametrize('damage',['duplicate','missing','shift','wrong_size','nonisometric','nan','rewire'])
def test_independent_topology_rejects_bad_geometry_even_with_twelve_edges(damage):
    lines=cube();length=1700
    if damage=='duplicate':lines[-1]=deepcopy(lines[0])
    elif damage=='missing':lines.pop()
    elif damage=='shift':
        for k in ('start','end'):lines[-1][k]['x']+=100
    elif damage=='wrong_size':length=1800
    elif damage=='nonisometric':
        for g in lines:
            for k in ('start','end'):g[k]['x']*=1.3
    elif damage=='nan':lines[0]['start']['x']=float('nan')
    else:lines[0]['end']=deepcopy(lines[5]['end'])
    assert not projected_cube_incidence(lines,length)['passed']


def noop():
    before={'id':'project','variants':[{'id':'source','acceptance_summary':{'status':'passed'},
            'geometries':[{'id':1,'type':'circle','radius':1500,'center':{'x':200,'y':300}}]}]}
    response={'ok':True,'cad_edit_outcome':'already_satisfied','variant_saved':False,'project_id':'project',
              'source_variant_id':'source','candidate_visibility':{'status':'retained_source'},
              'cad_edit_contract':{'operation':'rotate','parameters':{'angle_degrees':-90,'pivot':'instance_center'}}}
    return before,deepcopy(before),response


def test_verified_noop_is_delivery_without_new_version():
    assert retained_circle_rotation(*noop())['passed']


@pytest.mark.parametrize('damage',['source_changed','wrong_project','unaccepted','wrong_pivot','wrong_operation','no_receipt','extra_version'])
def test_noop_cannot_hide_failed_or_unverified_operations(damage):
    before,after,response=noop()
    if damage=='source_changed':after['variants'][0]['geometries'][0]['radius']+=1
    elif damage=='wrong_project':response['project_id']='other'
    elif damage=='unaccepted':before['variants'][0]['acceptance_summary']['status']='review_required'
    elif damage=='wrong_pivot':response['cad_edit_contract']['parameters']['pivot']='origin'
    elif damage=='wrong_operation':response['cad_edit_contract']['operation']='scale'
    elif damage=='no_receipt':response['ok']=False
    else:after['variants'].append(deepcopy(after['variants'][0]))
    assert not retained_circle_rotation(before,after,response)['passed']


@pytest.mark.parametrize('damage',[None,'overlap','radius','height','width','extra','diagonal','bulge'])
def test_user_confirmed_two_view_oracle_is_independent_and_checks_dimensions(damage):
    gs=[{'id':1,'type':'circle','center':{'x':0,'y':6000},'radius':1000},
        {'id':2,'type':'polyline','closed':True,'vertices':[{'x':x,'y':y} for x,y in [(3000,0),(5000,0),(5000,3000),(3000,3000)]]}]
    if damage=='overlap':gs[0]['center']={'x':4000,'y':1500}
    elif damage=='radius':gs[0]['radius']=500
    elif damage=='height':gs[1]['vertices'][2]['y']+=100
    elif damage=='width':
        for p in gs[1]['vertices']:p['x']*=2
    elif damage=='extra':gs.append(deepcopy(gs[0]))
    elif damage=='diagonal':gs[1]['vertices'][1],gs[1]['vertices'][2]=gs[1]['vertices'][2],gs[1]['vertices'][1]
    elif damage=='bulge':gs[1]['vertices'][0]['bulge']=.1
    assert orthographic_cylinder_views(gs,1000,3000)['passed']==(damage is None)
