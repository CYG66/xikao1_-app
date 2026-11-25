import itertools
import math
from copy import deepcopy
import pytest
from app.cad_projection_acceptance import verify_projection_requirements, projection_requirements
from app.cad_structure_contract import StructureContractError

SOURCE='画一个立方体的二维等轴投影，各投影棱长2米，包含隐藏的12条棱线'


@pytest.mark.parametrize('size,unit,expected',[(1.7,'米',1700),(43,'厘米',430),(950,'毫米',950)])
def test_planning_constraints_and_measurement_share_source_lengths(size,unit,expected):
    source=SOURCE.replace('2米',f'{size}{unit}')
    constraints=projection_requirements(source)
    assert constraints['projected_edge_length_mm']==expected
    lines=edges()
    for line in lines:
        for endpoint in ('start','end'):
            line[endpoint]={key:value*expected/2000 for key,value in line[endpoint].items()}
    measured=verify_projection_requirements(source,lines)
    assert measured['status']=='passed'
    assert measured['projected_edge_length_mm']==pytest.approx(expected)


@pytest.mark.parametrize('source',['画一个立方体透视图','画一个立方体和一个圆，等轴投影，12条棱线'])
def test_planner_does_not_add_unconfirmed_projection_constraints(source):
    assert projection_requirements(source) is None


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


def test_topology_failure_retains_best_existing_incidence_match_without_replacement_coordinates():
    lines=deepcopy(edges())
    lines[-1]={**lines[-1],**{endpoint:{'x':lines[-1][endpoint]['x']+101,'y':lines[-1][endpoint]['y']+233} for endpoint in ('start','end')}}
    before=deepcopy(lines)
    with pytest.raises(StructureContractError) as caught:verify_projection_requirements(SOURCE,lines)
    diagnostic=caught.value.details['incidence_diagnostic']
    assert diagnostic['matched_geometry_ids']==list(range(1,12))
    assert diagnostic['unmatched_geometry_ids']==[12]
    assert diagnostic['missing_edge_count']==1
    assert diagnostic['diagnostic_only'] and not diagnostic['candidate_accepted']
    assert lines==before


@pytest.mark.parametrize('damaged',[True,False])
def test_failed_model_assertion_diagnoses_projection_before_bounded_repair(damaged):
    from app.cad_construction_interpreter import interpret_construction_request
    lines=deepcopy(edges())
    if damaged:lines[-1]['end']['x']+=100
    plan={'units':'mm','steps':[{'op':'add_line','step_id':str(i),'output_ref':'edge'+str(i),
        'semantic':{'label':'棱线'+str(i)},'start':g['start'],'end':g['end']} for i,g in enumerate(lines)],
        'assertions':[{'kind':'entity_count','assertion_id':'wrong-count','equals':13}]}
    original=deepcopy(plan)
    result=interpret_construction_request(SOURCE,lambda *_:{'schema_version':'cad.construction-interpretation.v1',
        'is_construction_request':True,'confidence':.99,'evidence_text':[SOURCE],'plan':plan},force_structured_model=True)
    assert result['status']=='invalid'
    assert result['construction_error']['code']=='assertion_failed'
    details=result['construction_error']['details']
    assert plan==original
    if damaged:
        proof=details['independent_source_failure']
        assert proof['diagnostic_only'] and not proof['candidate_accepted']
        assert details['requires_structural_replan'] is True
        assert set(details['affected_output_refs'])=={'edge'+str(i) for i in range(12)}
        diagnostic=proof['details']
        assert len(diagnostic['measured_edges'])==12
        assert {i for family in diagnostic['measured_axis_families'] for i in family['geometry_ids']}==set(diagnostic['geometry_ids'])
    else:
        assert not details.get('requires_structural_replan')
        assert 'independent_source_failure' not in details


@pytest.mark.parametrize('first_gate',['assertion','identity'])
def test_formal_repair_receives_structure_evidence_and_rechecks_corrected_plan(tmp_path,first_gate):
    from unittest.mock import patch
    from app.agent_service import RobotAgentService
    from app.creative_projects import CreativeProjectStore
    from app.cad_construction_interpreter import interpret_construction_request
    lines=edges()
    plan={'units':'mm','steps':[{'op':'add_line','step_id':str(i),'output_ref':'edge'+str(i),
        'semantic':{'label':'棱线'+str(i)},'start':g['start'],'end':g['end']} for i,g in enumerate(lines)]}
    bad=deepcopy(plan)
    bad['steps'][-1]['end']['x']+=100
    if first_gate=='assertion':
        bad['assertions']=[{'kind':'entity_count','assertion_id':'wrong-count','equals':13}]
    else:
        for step in bad['steps']:step['semantic']['object_id']='same'
    calls=[]
    def interpret(text,**kwargs):
        calls.append((text,kwargs))
        result=interpret_construction_request(SOURCE,lambda *_:{'schema_version':'cad.construction-interpretation.v1',
            'is_construction_request':True,'confidence':.99,'evidence_text':[SOURCE],
            'plan':deepcopy(bad if len(calls)==1 else plan)},force_structured_model=True)
        result['provider_attempted']=True
        return result
    service=RobotAgentService(restore_pending_actions=False)
    store=CreativeProjectStore(tmp_path/'projects.json')
    with patch('app.agent_service.get_creative_project_store',return_value=store),patch.object(service,'_interpret_cad_construction_plan',side_effect=interpret):
        result=service._formal_cad_construction(SOURCE,{'name':'drawing_design','operation':'create'},mode='advanced')
    assert len(calls)==2
    assert ('independent_source_failure' if first_gate=='assertion' else 'source_structure_diagnostic') in calls[1][0]
    assert 'measured_edges' in calls[1][0]
    assert '全部构造步骤均未通过结构验收' in calls[1][0]
    assert 'component_repair_context' not in calls[1][1]
    assert result['ok'] is True
    assert result['variant']['acceptance_summary']['status']=='passed'
    assert len(store.list())==1


@pytest.mark.parametrize('damaged',[True,False])
def test_identity_conflict_does_not_hide_independent_projection_failure(damaged):
    from app.cad_construction_interpreter import interpret_construction_request
    lines=deepcopy(edges())
    if damaged:lines[-1]['end']['x']+=100
    plan={'units':'mm','steps':[{'op':'add_line','step_id':str(i),'output_ref':'edge'+str(i),
        'semantic':{'label':'棱线'+str(i),'object_id':'same'},'start':g['start'],'end':g['end']} for i,g in enumerate(lines)]}
    original=deepcopy(plan)
    result=interpret_construction_request(SOURCE,lambda *_:{'schema_version':'cad.construction-interpretation.v1',
        'is_construction_request':True,'confidence':.99,'evidence_text':[SOURCE],'plan':plan},force_structured_model=True)
    assert result['status']=='invalid'
    assert result['construction_error']['code']=='logical_graph_invalid'
    details=result['construction_error']['details']
    assert details['identity_only_repair'] is True
    assert plan==original
    if damaged:
        assert details['requires_structural_replan'] is True
        assert details['source_structure_diagnostic']['topology_verified'] is False
        assert len(details['affected_output_refs'])==12
    else:
        assert not details.get('requires_structural_replan')
        assert 'source_structure_diagnostic' not in details


def test_backend_enforces_same_explicit_inventory_as_model_schema():
    from app.cad_construction_interpreter import interpret_construction_request
    source='画一个立方体的二维等轴投影，各投影棱长2米，只画12条棱线'
    plan={'units':'m','steps':[{'op':'add_polyline','step_id':'outline','output_ref':'outline',
        'semantic':{'label':'轮廓'},'vertices':[{'x':0,'y':0},{'x':1,'y':1}], 'closed':False}]}
    result=interpret_construction_request(source,lambda *_:{'schema_version':'cad.construction-interpretation.v1',
        'is_construction_request':True,'confidence':.99,'evidence_text':[source],'plan':plan},force_structured_model=True)
    assert result['status']=='invalid'
    assert result['construction_error']['code']=='source_inventory_mismatch'
    assert result['construction_error']['details']['required_line_steps']==12
    assert result['construction_error']['details']['requires_structural_replan'] is True


@pytest.mark.parametrize('damage',['duplicate','zero'])
def test_feasibility_failure_also_returns_existing_source_structure_diagnostic(damage):
    from app.cad_construction_interpreter import interpret_construction_request
    lines=deepcopy(edges())
    if damage=='duplicate':lines[-1]=deepcopy(lines[0])
    else:lines[-1]['end']=deepcopy(lines[-1]['start'])
    plan={'units':'mm','steps':[{'op':'add_line','step_id':str(i),'output_ref':'edge'+str(i),
        'semantic':{'label':'棱线'+str(i)},'start':g['start'],'end':g['end']} for i,g in enumerate(lines)]}
    result=interpret_construction_request(SOURCE,lambda *_:{'schema_version':'cad.construction-interpretation.v1',
        'is_construction_request':True,'confidence':.99,'evidence_text':[SOURCE],'plan':plan},force_structured_model=True)
    assert result['status']=='invalid'
    assert result['construction_error']['code']=='drawing_infeasible'
    details=result['construction_error']['details']
    assert details['requires_structural_replan'] is True
    assert len(details['affected_output_refs'])==12
    assert details['source_structure_diagnostic']['topology_verified'] is False
    assert details['source_structure_diagnostic']['requested_projected_edge_length_mm']==2000


def test_wrong_length_is_reported_after_independent_topology_verification():
    lines=edges()
    for g in lines:
        for key in ('start','end'):
            g[key]={axis:g[key][axis]*.5 for axis in ('x','y')}
    with pytest.raises(StructureContractError) as caught:verify_projection_requirements(SOURCE,lines)
    details=caught.value.details
    assert details['topology_verified'] is True
    assert details['source_length_satisfied'] is False
    assert details['requested_projected_edge_length_mm']==2000
    assert all(abs(v-1000)<1e-6 for v in details['measured_projected_edge_lengths_mm'])


def test_wrong_topology_is_not_hidden_by_a_simultaneous_length_error():
    lines=edges()
    for g in lines:
        for key in ('start','end'):
            g[key]={axis:g[key][axis]*.5 for axis in ('x','y')}
    lines[-1]=deepcopy(lines[0])
    with pytest.raises(StructureContractError) as caught:verify_projection_requirements(SOURCE,lines)
    assert caught.value.details['topology_verified'] is False
    assert caught.value.details['source_length_satisfied'] is False


def test_unrequested_bounds_can_be_replaced_only_after_full_projection_proof():
    from app.cad_construction_interpreter import interpret_construction_request
    from app.cad_construction import execute_construction_plan
    source='画一个立方体的透视轮廓，边长2米\n二维等轴投影，三个投影轴夹角120度，各投影棱长2米，只画可见及隐藏的12条棱线。'
    plan={'units':'mm','steps':[{'op':'add_line','step_id':str(g['id']),'output_ref':'edge'+str(g['id']),
        'semantic':{'label':'棱线'+str(g['id'])},'start':g['start'],'end':g['end']} for g in edges()]}
    baseline=execute_construction_plan(plan)['geometries']
    plan['assertions']=[{'kind':'bounds_size','assertion_id':'wrong','target_ref':'edge1','width':3464,'height':3500}]
    def run(text,p):return interpret_construction_request(text,lambda *_:{
        'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
        'plan':p,'confidence':.99,'evidence_text':[text],'assumptions':[]},force_structured_model=True)
    result=run(source,plan)
    assert result['status']=='ready',result.get('error')
    assert result['acceptance_summary']['status']=='passed',result['source_acceptance']
    assert result['trial_result']['geometries']==baseline
    assert result['deterministic_repairs'][-1]['geometry_unchanged']
    assert run(source+'整体宽4米高4米',plan)['status']=='invalid'
    wrong=deepcopy(plan);wrong['steps'][0]['end']['x']+=100
    assert run(source,wrong)['status']=='invalid'


def test_wrong_axes_report_measured_directions_for_structural_replanning():
    lines=deepcopy(edges())
    for line in lines:
        for key in ('start','end'):line[key]['x']*=2
    with pytest.raises(StructureContractError) as caught:
        verify_projection_requirements(SOURCE,lines)
    details=caught.value.details
    assert details['requires_structural_replan']
    assert details['geometry_ids']==list(range(1,13))
    assert len(details['measured_axis_families'])==3
    assert len(details['measured_undirected_angles_degrees'])==3


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
