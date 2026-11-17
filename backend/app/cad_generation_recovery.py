"""Bounded CAD recovery evidence; no implicit background jobs."""
from copy import deepcopy
import hashlib
import json
import os


def _env_flag(name, default=True):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "off", "no"}


# Rollback switches. Default ON: the M3 gate only blocks when the stall is
# proven by BOTH an unchanged failure vector AND determined-equivalent
# geometry; every undetermined or missing-evidence path releases. Setting the
# env var to "off" restores the pre-M3 behaviour unchanged.
M3_PROGRESS_GATE_ENABLED = _env_flag("CAD_C1_M3_PROGRESS_GATE", True)
M2_SCOPE_CLASSIFIER_ENABLED = _env_flag("CAD_C1_M2_SCOPE_CLASSIFIER", True)


def recovery_category(result):
    details=(result.get('construction_error') or {}).get('details') or {}
    if details.get('reason')=='unverified_geometry' and details.get('inventory_scope')=='partial':
        return 'requirements_unverified'
    code=str((result.get('construction_error') or {}).get('code') or (result.get('error') or {}).get('code') or '')
    if result.get('clarification') or result.get('status')=='clarification_required':return 'requirements_missing'
    if any(t in code for t in ('budget','too_dense','sampling')):return 'sampling_budget'
    if any(t in code for t in ('constraint','continuity','intersect')):return 'constraint_conflict'
    if any(t in code for t in ('timeout','network','transport','provider','connection')):return 'network_failure'
    if code=='persistence_failed':return 'persistence_failure'
    return 'model_plan_invalid'


def should_repair(result):
    return (result.get('status')=='invalid' and bool(result.get('provider_attempted'))
            and recovery_category(result) in {'model_plan_invalid','constraint_conflict','sampling_budget'})


def bounded_repair_available(attempts, max_repairs=2):
    """Permit a second repair only when the first repair made real progress.

    A compound plan can expose failures sequentially: repairing component A may
    allow independent acceptance to reach component B.  Repeating the same
    failure or returning the same plan is model oscillation, not progress.
    """
    repairs=max(0,len(attempts)-1)
    if repairs>=max_repairs:
        return False
    if len(attempts)<2:
        return True
    previous,current=attempts[-2],attempts[-1]
    current_error=current.get('construction_error') or current.get('error') or {}
    # A repaired plan that still misses the confidence gate has supplied no
    # new geometric failure to act on.  Retrying it would only ask the model
    # to inflate a score, which is explicitly forbidden.
    if str(current_error.get('code') or '') in {'low_confidence','confidence_only_repair'}:
        return False
    def signature(result):
        error=result.get('construction_error') or result.get('error') or {}
        return (recovery_category(result),str(error.get('code') or ''),
                str(error.get('message') or ''),
                json.dumps(error.get('details'),sort_keys=True,ensure_ascii=False,default=str))
    before=previous.get('plan') or previous.get('rejected_plan')
    after=current.get('plan') or current.get('rejected_plan')
    return signature(previous)!=signature(current) and before!=after


def confidence_only_repair(before,after):
    """A confidence number alone is not a plan correction or new user evidence."""
    return (before.get('diagnostic_trial_passed') is True
            and (before.get('error') or {}).get('code')=='low_confidence'
            and after.get('status')=='ready'
            and bool(before.get('rejected_plan'))
            and before['rejected_plan']==after.get('plan'))


# ---------------------------------------------------------------------------
# M3: repair progress judgement (no real model call; deterministic evidence only)
# ---------------------------------------------------------------------------

def _error_bundle(result):
    error = result.get('construction_error') or result.get('error') or {}
    details = error.get('details') or {}
    return error, details


def _feature_vector(result):
    """Comparable failure evidence. Booleans are the only progress signal we
    can prove without executed geometry; plan text is intentionally not used."""
    error, details = _error_bundle(result)
    measured = details.get('measured_features') or {}
    measured_tuple = tuple(sorted(
        (str(k), bool(v)) for k, v in measured.items() if isinstance(v, bool)
    ))
    return {
        'category': recovery_category(result),
        'code': str(error.get('code') or ''),
        'check': str(details.get('check') or ''),
        'failed_features': tuple(sorted(details.get('failed_features') or [])),
        'measured_features': measured_tuple,
    }


def _geometry_evidence(result):
    """Executed-geometry snapshot carried by an interpretation.

    The failure path currently attaches no geometries (interpreter invalid
    shape), so most attempts report ``available=False``. The M3 gate must
    NOT block on a missing snapshot; it releases and records the gap.
    """
    trial = result.get('trial_result') if isinstance(result.get('trial_result'), dict) else {}
    geometries = trial.get('geometries')
    if isinstance(geometries, list) and geometries:
        from .cad_candidate_state import geometry_evidence_hash
        return {'available': True, 'source': 'trial_result',
                'fingerprint': geometry_evidence_hash(geometries),
                'geometries': geometries}
    return {'available': False, 'source': 'missing'}


# ---------------------------------------------------------------------------
# Narrow adapter for B's geometry judge (probes/b_round5_geometry_contract).
# The evaluator is injected; this branch must NOT copy B's implementation or
# invent a second equivalence judge. Until the A+B+C combo tree merges B's
# module, the default evaluator is absent and every geometry verdict is
# ``undetermined`` (fail-closed: released and recorded, never blocked).
# ---------------------------------------------------------------------------

_GEOMETRY_EVALUATOR = None

# Equivalence vocabulary accepted from B's ``trajectory_equivalent`` result.
# Contract source: B probes/b_round5_geometry_contract.py. A proven
# same-trajectory match may be labelled either ``identical`` or ``equivalent``
# by the B version in use; both mean determined-equivalent and are the only
# relations that can feed a stall block.
EQUIVALENT_RELATIONS = {'identical', 'equivalent'}
# Non-equivalent relations: these are deliberate geometry changes or a
# non-progress orientation reversal; they must release, never block.
_NON_EQUIVALENT_RELATIONS = {
    'same_trajectory_reversed', 'similar_transform', 'compliant_other', 'different',
}


def set_geometry_evaluator(fn):
    """Inject the B-compatible evaluator. ``fn`` mirrors ``trajectory_equivalent``:
    ``fn(spec_a, spec_b, tolerance) -> EquivalenceResult`` with
    ``equivalent / undetermined / relation / reversed / checks / fail_reasons``.
    """
    global _GEOMETRY_EVALUATOR
    _GEOMETRY_EVALUATOR = fn


def _geometry_spec(result, evidence):
    return {'geometries': evidence.get('geometries'),
            'plan': result.get('plan') or result.get('rejected_plan')}


def evaluate_geometry_progress(before, after, tolerance=None):
    """B-aligned geometry verdict. Relations (B contract):

      - ``identical`` / ``equivalent``: same trajectory, all dimensions pass
        (both are the B equivalence vocabulary; see EQUIVALENT_RELATIONS).
      - ``same_trajectory_reversed``: same point set, direction reversed; this
        is NOT progress and the orientation dimension fails -> release.
      - ``similar_transform`` / ``compliant_other``: compliant rigid/scale/
        reflection or topology-preserving adjustment -> release, never block.
      - ``different``: geometry changed -> release.
      - any missing snapshot, missing required field, or absent evaluator ->
        ``undetermined``; undetermined is neither equivalent nor a pass, it is
        released and recorded. Symmetry alone is never a blocking basis.
    """
    evidence_before = _geometry_evidence(before)
    evidence_after = _geometry_evidence(after)
    if not evidence_before['available'] or not evidence_after['available']:
        return {'equivalent': None, 'undetermined': True, 'relation': 'unavailable',
                'reversed': False, 'checks': {}, 'fail_reasons': ['geometry snapshot unavailable'],
                'source': 'missing'}
    if _GEOMETRY_EVALUATOR is None:
        return {'equivalent': None, 'undetermined': True, 'relation': 'evaluator_unavailable',
                'reversed': False, 'checks': {},
                'fail_reasons': ['B geometry evaluator not injected in this tree'],
                'source': 'adapter'}
    try:
        verdict = _GEOMETRY_EVALUATOR(
            _geometry_spec(before, evidence_before),
            _geometry_spec(after, evidence_after), tolerance)
    except Exception as exc:  # evaluator failure must fail closed, not block
        return {'equivalent': None, 'undetermined': True, 'relation': 'evaluator_error',
                'reversed': False, 'checks': {},
                'fail_reasons': [f'evaluator raised: {type(exc).__name__}'],
                'source': 'adapter'}

    relation = str(verdict.get('relation') or (
        'equivalent' if verdict.get('equivalent') else 'different'))
    undetermined = bool(verdict.get('undetermined'))
    reversed_flag = bool(verdict.get('reversed'))
    checks = verdict.get('checks') or {}
    fail_reasons = list(verdict.get('fail_reasons') or [])
    # Direction / endpoints / closure / topology are the required coverage
    # dimensions (Hausdorff / bbox / arc-length alone are not enough). If any
    # of those checks reports undetermined, fail closed: release, do not block.
    dimension_checks = ('geometry', 'orientation', 'endpoints', 'closed', 'topology')
    if not undetermined and any(checks.get(k) == 'undetermined' for k in dimension_checks):
        undetermined = True
        fail_reasons.append('one coverage dimension undetermined')
    if undetermined:
        equivalent = None
    elif relation in EQUIVALENT_RELATIONS:
        # Proven same-trajectory match (B vocabulary: identical | equivalent).
        equivalent = bool(verdict.get('equivalent', True))
    elif relation in _NON_EQUIVALENT_RELATIONS:
        # Reversal is not progress; similar_transform / compliant_other /
        # different are geometry changes. All release via geometry_changed.
        equivalent = False
    else:
        # Out-of-contract vocabulary: fail safe. Treat as undetermined, release,
        # and record the unknown relation so a future B vocabulary shift cannot
        # either silently block a real fix or silently pass a stall.
        undetermined = True
        equivalent = None
        fail_reasons.append(f'unknown geometry relation: {relation}')
    # Similarity-transform channel: C does NOT call B's ``similarity_transform``
    # separately. A rigid/scale/reflection or topology-preserving adjustment
    # moves the sampled points beyond the raw equivalence tolerance, so B
    # reports ``similar_transform``/``compliant_other`` rather than an
    # equivalence relation; that non-equivalent verdict is released above and
    # cannot be mistaken for a stall. Only a verdict inside EQUIVALENT_RELATIONS
    # is eligible to block.
    return {'equivalent': equivalent, 'undetermined': undetermined,
            'relation': relation, 'reversed': reversed_flag, 'checks': checks,
            'fail_reasons': fail_reasons, 'source': 'b_evaluator'}


def evaluate_repair_progress(before, after):
    """Decide whether the most recent repair made real progress.

    Stall requires BOTH conditions together (never split):
      1. failure feature set and measured values show no improvement;
      2. before/after geometry are determined equivalent within existing
         tolerances.

    Release whitelist (any one -> allow another repair): an improved failed
    feature, a new failure/part/structure, geometry beyond tolerance,
    undetermined equivalence, or a missing geometry snapshot. The first
    repair is always allowed by the caller (single attempt).
    """
    if before is None:
        return {'decision': 'allow', 'progress': 'first_repair',
                'feature_before': None, 'feature_after': None,
                'geometry': None, 'reasons': ['first repair always allowed']}
    feature_before = _feature_vector(before)
    feature_after = _feature_vector(after)
    geometry = evaluate_geometry_progress(before, after)

    failed_before = set(feature_before['failed_features'])
    failed_after = set(feature_after['failed_features'])
    improved = bool(failed_before - failed_after)
    new_failure = bool(failed_after - failed_before)
    feature_same = (failed_before == failed_after
                    and feature_before['measured_features'] == feature_after['measured_features']
                    and feature_before['check'] == feature_after['check']
                    and feature_before['code'] == feature_after['code'])

    reasons = []
    if improved:
        reasons.append('previously failed feature improved')
        return {'decision': 'allow', 'progress': 'feature_improved',
                'feature_before': feature_before, 'feature_after': feature_after,
                'geometry': geometry, 'reasons': reasons}
    if new_failure:
        reasons.append('new failure feature or part surfaced')
        return {'decision': 'allow', 'progress': 'new_failure',
                'feature_before': feature_before, 'feature_after': feature_after,
                'geometry': geometry, 'reasons': reasons}
    if geometry['equivalent'] is False:
        reasons.append('geometry changed beyond equivalence evidence')
        return {'decision': 'allow', 'progress': 'geometry_changed',
                'feature_before': feature_before, 'feature_after': feature_after,
                'geometry': geometry, 'reasons': reasons}
    if geometry['undetermined']:
        reasons.append('geometry equivalence undetermined; conservative release')
        return {'decision': 'allow', 'progress': 'undetermined',
                'feature_before': feature_before, 'feature_after': feature_after,
                'geometry': geometry, 'reasons': reasons}

    # Geometry determined equivalent: stall only when the failure vector is
    # also unchanged. Any feature movement below keeps the repair allowed.
    if feature_same:
        reasons.append('failure vector unchanged and geometry determined equivalent')
        return {'decision': 'block', 'progress': 'stalled_equivalent',
                'feature_before': feature_before, 'feature_after': feature_after,
                'geometry': geometry, 'reasons': reasons}
    reasons.append('geometry equivalent but failure vector moved')
    return {'decision': 'allow', 'progress': 'feature_moved',
            'feature_before': feature_before, 'feature_after': feature_after,
            'geometry': geometry, 'reasons': reasons}


# ---------------------------------------------------------------------------
# M2: generic feature-failure classification.
# Aligned with the A-side contract proposals/feature_contract_fields.v1-draft:
#   classify_feature_failure(details, code) ->
#     {repair_class, requires_structural_replan, reason}
# Inputs are structured fields only (feature_class / failure_subtype /
# measured / geometry_scope / code). No localized text, no feature-name or
# request-string matching. When evidence fields are missing the classifier
# degrades to parameter_repair and must NOT mark a structural replan, so a
# plain parameter fix is never escalated by default.
# ---------------------------------------------------------------------------

_TOPOLOGY_DETAIL_KEYS = {'endpoint_degrees', 'closed_region_count',
                         'self_intersect', 'intersection_groups', 'degree',
                         'connected_components'}
_CONNECTION_KEYS = {'reference_geometry_id', 'adjacency', 'contact', 'junction',
                    'connection', 'distance_to_ref', 'pair_refs'}
_PARAMETER_NUMERIC_KEYS = {'measured_center_mm', 'expected_center_mm', 'error_mm',
                           'measured_direction', 'required_direction',
                           'rotation_degrees_to_required_direction',
                           'actual_side_lengths_mm', 'expected_side_mm',
                           'measured_center', 'tolerance_mm', 'scale', 'offset'}
_TOPOLOGY_CODE_TOKENS = ('constraint', 'continuity', 'intersect', 'closure',
                         'self_cross', 'topology', 'connectivity')
_FEATURE_CLASS_MAP = {
    'parameter': 'parameter_repair',
    'connection': 'connection_repair',
    'feature': 'feature_replan',
    'boundary': 'feature_replan',
    'topology': 'topology_replan',
}
_STRUCTURAL_CLASSES = {'feature_replan', 'topology_replan'}


def classify_feature_failure(details, code=''):
    """Map structured failure evidence to a repair channel.

    repair_class:
      - ``parameter_repair``: scalar parameter/range/ratio/offset wrong;
        features and connections are intact.
      - ``connection_repair``: continuity/connection between two segments.
      - ``feature_replan``: extremum/cusp/notch/symmetry missing or misplaced;
        a boundary element must be added, which a parameter tweak cannot do.
      - ``topology_replan``: count/closure/self-cross/containment/connected
        components globally wrong; composition must be rearranged.
    """
    details = details or {}
    code = str(code or '')
    missing = [k for k in ('feature_class', 'failure_subtype', 'measured',
                           'geometry_scope') if k not in details]

    explicit_class = _FEATURE_CLASS_MAP.get(str(details.get('feature_class') or '').lower())
    subtype = str(details.get('failure_subtype') or '').lower()

    expected_count = details.get('expected_count')
    actual_count = details.get('actual_count')
    count_mismatch = (expected_count is not None and actual_count is not None
                      and expected_count != actual_count)
    present_ids = set(details.get('geometry_ids') or [])
    if details.get('geometry_id'):
        present_ids.add(details['geometry_id'])
    missing_ids = set(details.get('expected_geometry_ids') or []) - present_ids

    if explicit_class:
        repair_class = explicit_class
        reason = f"explicit feature_class={details.get('feature_class')}"
    elif subtype in {'connection', 'junction', 'contact', 'adjacency'}:
        repair_class = 'connection_repair'
        reason = f"failure_subtype={details.get('failure_subtype')}"
    elif subtype in {'count', 'closure', 'self_intersection', 'containment',
                     'connectivity', 'topology'}:
        repair_class = 'topology_replan'
        reason = f"failure_subtype={details.get('failure_subtype')}"
    elif subtype in {'cusp', 'notch', 'extremum', 'symmetry', 'boundary_feature'}:
        repair_class = 'feature_replan'
        reason = f"failure_subtype={details.get('failure_subtype')}"
    elif any(k in details for k in _TOPOLOGY_DETAIL_KEYS) or count_mismatch:
        repair_class = 'topology_replan'
        reason = 'topology evidence fields present: ' + ','.join(
            sorted(set(details) & set(_TOPOLOGY_DETAIL_KEYS)) +
            (['count_mismatch'] if count_mismatch else []))
    elif any(k in details for k in _CONNECTION_KEYS):
        repair_class = 'connection_repair'
        reason = 'pairwise connection reference present'
    elif any(k in details for k in _PARAMETER_NUMERIC_KEYS) or 'measurements' in details:
        repair_class = 'parameter_repair'
        reason = 'scalar measured/expected tolerance evidence present'
    elif (bool(details.get('requires_structural_replan')) or missing_ids
          or code == 'structure_requirement_failed' and details.get('failed_features')):
        repair_class = 'feature_replan'
        reason = 'boundary feature missing; parameter tweak cannot add topology'
    elif any(t in code for t in _TOPOLOGY_CODE_TOKENS):
        repair_class = 'topology_replan'
        reason = f"error code token: {code}"
    else:
        # Degraded default: never escalate to structural replan without evidence.
        repair_class = 'parameter_repair'
        reason = 'degraded default: insufficient structured evidence; conservative parameter repair'

    return {
        'repair_class': repair_class,
        'requires_structural_replan': repair_class in _STRUCTURAL_CLASSES,
        'reason': reason,
        'missing_fields': missing,
        'preserve': ['user dimensions', 'source requirement references',
                     'part count', 'non-target components'],
    }


def recovery_record(source,attempts,max_repairs=1):
    records=[]
    for index,result in enumerate(attempts):
        plan=deepcopy(result.get('plan') or result.get('rejected_plan'))
        records.append({'attempt':index+1,'status':result.get('status'),
            'confidence':result.get('confidence'),
            'category':None if result.get('status')=='ready' else recovery_category(result),
            'error':deepcopy(result.get('construction_error') or result.get('error')),
            'plan':plan,'plan_sha256':hashlib.sha256(json.dumps(plan,sort_keys=True,ensure_ascii=False).encode()).hexdigest()})
        if result.get('local_repair_validation'):
            records[-1]['local_repair_validation']=deepcopy(result['local_repair_validation'])
        if result.get('coordinate_patch'):
            records[-1]['coordinate_patch']=deepcopy(result['coordinate_patch'])
        if index:
            before=records[index-1]['plan'] or {}
            after=plan or {}
            records[-1]['changed_plan_fields']=sorted(k for k in set(before)|set(after) if before.get(k)!=after.get(k)) if isinstance(before,dict) and isinstance(after,dict) else ['plan']
            if isinstance(before,dict) and isinstance(after,dict):
                def steps_by_ref(plan):
                    return {str(s.get('output_ref') or s.get('step_id') or i):s
                            for i,s in enumerate(plan.get('steps') or []) if isinstance(s,dict)}
                old,new=steps_by_ref(before),steps_by_ref(after)
                records[-1]['step_diff']={
                    'added_refs':sorted(set(new)-set(old)),
                    'removed_refs':sorted(set(old)-set(new)),
                    'modified_refs':sorted(k for k in set(old)&set(new) if old[k]!=new[k]),
                    'unchanged_refs':sorted(k for k in set(old)&set(new) if old[k]==new[k]),
                    'comparison':'exact_plan_steps_not_geometric_equivalence'}
            progress=evaluate_repair_progress(attempts[index-1], result)
            records[-1]['progress']={k:deepcopy(v) for k,v in progress.items()}
    progress_log=[records[i].get('progress') for i in range(1,len(records)) if records[i].get('progress')]
    return {'schema':'cad.generation-recovery.v1','source_sha256':hashlib.sha256(source.encode('utf-8')).hexdigest(),
            'max_repairs':max_repairs,'repair_count':max(0,len(records)-1),'attempts':records,
            'progress_log':progress_log,
            'background_job':None,'source_preserved':True}
