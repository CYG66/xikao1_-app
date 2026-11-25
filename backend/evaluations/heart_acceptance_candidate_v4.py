"""Offline v4 expands only the supported source-minimum evidence provider."""
from evaluations.heart_acceptance_candidate_v3 import compare as compare_v3
from evaluations.bezier_layout_minimum_v1 import measure as bezier_minimum
from evaluations.trig_layout_minimum_v1 import measure as trig_minimum

VERSION='cad.heart-acceptance-candidate.v4'


def source_minimum(plan):
    steps=plan.get('steps',[])
    return (trig_minimum if len(steps)==1 and steps[0].get('op')=='add_parametric_curve' else bezier_minimum)(plan)


def compare(source,payload):
    result=compare_v3(source,payload,_minimum_measure=source_minimum)
    return {**result,'version':VERSION,'minimum_policy':'bounded_harmonic_or_bezier_source'}
