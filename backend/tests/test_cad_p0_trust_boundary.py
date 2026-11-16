from copy import deepcopy
import pytest
from app.cad_constraint_solver import ConcentricConstraint, ConstraintSolveError, solve_geometric_constraints
from app.cad_construction_interpreter import construction_acceptance_summary


def test_manual_confirmation_never_promotes_or_transfers_acceptance():
    import threading
    from app.creative_projects import CreativeProjectStore
    from app.cad_candidate_state import candidate_is_accepted,geometry_evidence_hash
    store=CreativeProjectStore.__new__(CreativeProjectStore)
    store._lock=threading.RLock();store._save=lambda:None
    variant={'id':'v1','geometries':[{'id':1}], 'acceptance_summary':{'status':'review_required','review_required':True}}
    store._projects={'p':{'id':'p','variants':[deepcopy(variant),{**deepcopy(variant),'id':'v2','geometries':[{'id':2}]}]}}
    digest=geometry_evidence_hash(variant['geometries'])
    entry=store.record_manual_cad_confirmation('p','v1',digest,'e1')
    assert not entry['construction_authorized']
    assert store._projects['p']['variants'][0]==variant
    assert not candidate_is_accepted(store._projects['p']['variants'][0])
    with pytest.raises(ValueError):store.record_manual_cad_confirmation('p','v2',digest,'e1')
    assert len(store._projects['p']['manual_cad_confirmations'])==1
    store._projects['p']['status']='designing'
    assert store.select_variant('p','v1') is None
    assert store.begin_design_iteration('p','v1') is None
    store._projects['p'].update(status='ready_for_planning',selected_variant_id='v1')
    assert store.set_planning('p',{'stage':'ready','validation':{'ok':True}}) is None


def test_review_draft_is_not_formal_candidate():
    from app.cad_candidate_state import candidate_is_reviewable_draft,candidate_is_accepted,accepted_project_view
    draft={'id':'v','geometries':[{'id':1}],
        'acceptance_summary':{'status':'review_required','review_required':True},
        'construction_record':{'feasibility':{'ok':True},'constraint_solve':{'verified':True}}}
    assert candidate_is_reviewable_draft(draft) and not candidate_is_accepted(draft)
    assert accepted_project_view({'variants':[draft],'selected_variant_id':'v'})['selected_variant_id'] is None
    draft['construction_record']['constraint_solve']['verified']=False
    assert not candidate_is_reviewable_draft(draft)


@pytest.mark.parametrize('reverse',[False,True])
def test_satisfiable_coupled_constraints(reverse):
    from app.cad_constraint_solver import EqualRadiusConstraint
    geometry=[{'id':i+1,'type':'circle','center':{'x':x,'y':0},'radius':i+1} for i,x in enumerate([0,10])]
    constraints=[ConcentricConstraint(kind='concentric',constraint_id='center',target_ref='B',reference_ref='A'),
        EqualRadiusConstraint(kind='equal_radius',constraint_id='radius',target_ref='B',reference_ref='A')]
    if reverse:constraints.reverse()
    solved,report=solve_geometric_constraints(geometry,{'A':[1],'B':[2]},constraints,unit_scale=1,backend='builtin')
    assert report['verified'] and solved[1]['center']==solved[0]['center']
    assert solved[1]['radius']==solved[0]['radius']


def test_satisfiable_chain_is_not_classified_as_conflict():
    geometry=[{'id':i+1,'type':'circle','center':{'x':x,'y':0},'radius':1} for i,x in enumerate([0,10,20])]
    constraints=[ConcentricConstraint(kind='concentric',constraint_id='ab',target_ref='A',reference_ref='B'),
                 ConcentricConstraint(kind='concentric',constraint_id='bc',target_ref='B',reference_ref='C')]
    with pytest.raises(ConstraintSolveError) as failure:
        solve_geometric_constraints(geometry,{'A':[1],'B':[2],'C':[3]},constraints,unit_scale=1,backend='builtin')
    assert failure.value.category=='constraint_unsatisfied'


@pytest.mark.parametrize('mode',['failed','invalid','wrong','correct'])
def test_native_transport_and_final_readonly_verification(monkeypatch,mode):
    import json
    from types import SimpleNamespace
    import app.cad_constraint_solver as solver
    geometry=[{'id':i+1,'type':'circle','center':{'x':x,'y':0},'radius':1} for i,x in enumerate([0,10])]
    before=deepcopy(geometry)
    monkeypatch.setattr(solver,'available_constraint_backends',lambda:{'builtin':{'available':True},'solvespace':{'available':True,'executable':'fake'}})
    output=deepcopy(geometry)
    if mode=='correct':output[1]['center']={'x':0,'y':0}
    response={'schema':'cad.native-constraint-result.v1','geometries':output}
    monkeypatch.setattr(solver.subprocess,'run',lambda *a,**k:SimpleNamespace(
        returncode=1 if mode=='failed' else 0,stdout='invalid json' if mode=='invalid' else json.dumps(response),stderr='simulated'))
    def forbidden(*args):raise AssertionError('validation must not apply constraints')
    monkeypatch.setattr(solver,'_apply_constraint',forbidden)
    constraints=[ConcentricConstraint(kind='concentric',constraint_id='ab',target_ref='B',reference_ref='A')]
    if mode=='correct':
        solved,report=solver.solve_geometric_constraints(geometry,{'A':[1],'B':[2]},constraints,unit_scale=1,backend='solvespace')
        assert solved==output and report['verified']
    else:
        with pytest.raises(ConstraintSolveError) as failure:
            solver.solve_geometric_constraints(geometry,{'A':[1],'B':[2]},constraints,unit_scale=1,backend='solvespace')
        assert failure.value.category==('constraint_unsatisfied' if mode=='wrong' else 'solver_failed')
    assert geometry==before


@pytest.mark.parametrize('reverse',[False,True])
def test_final_geometry_constraints_are_measured_without_reapplying(monkeypatch,reverse):
    import app.cad_constraint_solver as solver
    geometry=[{'id':i+1,'type':'circle','center':{'x':x,'y':0},'radius':1} for i,x in enumerate([0,10,5])]
    original=deepcopy(geometry)
    constraints=[ConcentricConstraint(kind='concentric',constraint_id=f'c{i}',target_ref='C',reference_ref=ref) for i,ref in enumerate(['A','B'])]
    if reverse:constraints.reverse()
    apply=solver._apply_constraint;calls=[]
    def tracked(*args):calls.append(1);return apply(*args)
    monkeypatch.setattr(solver,'_apply_constraint',tracked)
    residual=solver._constraint_residual
    def readonly(target,reference,*args):
        before=deepcopy((target,reference));result=residual(target,reference,*args)
        assert (target,reference)==before
        return result
    monkeypatch.setattr(solver,'_constraint_residual',readonly)
    with pytest.raises(ConstraintSolveError) as failure:
        solve_geometric_constraints(geometry,{'A':[1],'B':[2],'C':[3]},constraints,unit_scale=1,backend='builtin')
    assert failure.value.category=='constraint_unsatisfied'
    assert len(failure.value.reports)==2 and len(failure.value.failed_constraints)==1
    assert len(calls)==2 and geometry==original


@pytest.mark.parametrize('source', [{}, {'coverage':'partial','checks':[{'status':'passed'}]},
    {'coverage':'complete','checks':[{'status':'passed'}],'unknown_requirements':[{'source':'user:1','text':'外观要求'}]}])
def test_incomplete_source_never_automatically_passes(source):
    result=construction_acceptance_summary(preflight_structure=None,structure_contract=None,
        structure_validation=None,composition_contract=None,composition_validation=None,
        source_acceptance=source,trial_result={'assertions':{'ok':True,'count':0}})
    assert result['status']=='review_required'
    assert result['assertion_status']=='not_checked'
    assert result['unknown_requirements']


def test_upstream_review_survives_passed_structure():
    result=construction_acceptance_summary(preflight_structure={'review_required':True},
        structure_contract={'id':'source'},structure_validation={'status':'passed'},
        composition_contract=None,composition_validation=None,
        source_acceptance={'coverage':'complete','checks':[{'status':'passed'}]})
    assert result['review_required'] and result['status']=='review_required'
