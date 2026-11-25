"""Opt-in shadow wrapper. Official interpretation always runs legacy rules."""
from copy import deepcopy
from app.cad_construction_interpreter import interpret_construction_request, _coerce_model_payload


def interpret_with_shadow(source,model_callback,*,enabled=False,rule_version='v5'):
    captured=[]
    def callback(*args):
        payload=model_callback(*args)
        captured.append(deepcopy(payload))
        return payload
    formal=interpret_construction_request(source,callback if model_callback else None)
    if not enabled:return formal
    report={'version':'cad.heart-shadow-entry.v1','requested_rule':rule_version,
        'affects_formal_acceptance':False,'formal_candidate_accepted_by_shadow':False}
    if rule_version!='v5':
        return {**formal,'shadow_acceptance':{**report,'status':'unsupported_rule'}}
    if not captured:
        return {**formal,'shadow_acceptance':{**report,'status':'not_applicable','reason':'no_model_payload'}}
    try:
        payload=_coerce_model_payload(deepcopy(captured[-1]))
        if not isinstance(payload,dict) or not isinstance(payload.get('plan'),dict):
            return {**formal,'shadow_acceptance':{**report,'status':'not_applicable','reason':'no_recorded_plan'}}
        from evaluations.heart_acceptance_candidate_v5 import compare
        result=compare(source,payload)
        report.update(status='completed',comparison=result)
    except Exception as error:
        report.update(status='audit_error',reason=str(error))
    return {**formal,'shadow_acceptance':report}
