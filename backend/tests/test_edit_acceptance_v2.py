from copy import deepcopy
import pytest
from evaluations.edit_acceptance_v2 import assess_clarification,candidate_snapshot


def test_structured_clarification_does_not_require_keyword():
    state=candidate_snapshot([{'id':'p','original_prompt':'source','variants':[{'id':'v','geometries':[{'id':1}]}]}])
    assert assess_clarification({'clarification_required':True,'message':'请在画布点选对象。'},state,deepcopy(state))['passed']
    assert not assess_clarification({'message':'请选择哪个对象。'},state,state)['passed']


@pytest.mark.parametrize('change',['new_project','new_candidate','change_geometry','change_source','delivery','commit','pending'])
def test_v2_refuses_candidate_side_effects_even_with_clarification_flag(change):
    state={'p':{'original_prompt':'source','variants':[{'id':'v','geometries':[{'id':1}]}]}}
    after=deepcopy(state);response={'clarification_required':True}
    if change=='new_project':after['other']={'variants':[]}
    elif change=='new_candidate':after['p']['variants'].append({'id':'new'})
    elif change=='change_geometry':after['p']['variants'][0]['geometries']=[]
    elif change=='change_source':after['p']['original_prompt']='changed'
    elif change=='delivery':response['variant']={'id':'v'}
    elif change=='commit':response['tool_results']=[{'kind':'candidate_commit'}]
    else:response['pending_action']={'id':'pending'}
    assert not assess_clarification(response,state,after)['passed']
