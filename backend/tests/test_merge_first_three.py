from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.cad_canonical_json import canonical_json_hash
from app.cad_length_units import length_factors
from app.cad_validation_evidence import ConstructionEvidence
from app.cad_structure_contract import StructureContractError

GOLD=json.loads((Path(__file__).parent/'fixtures/merge_first_three_golden.json').read_text(encoding='utf-8'))


def test_all_41_unit_tables_keep_factors_numeric_types_and_aliases():
    assert len(GOLD['unit_tables'])==41
    for row in GOLD['unit_tables']:
        actual=length_factors(row['target_unit'],float_values=row['float_values'],include_gongfen=row['include_gongfen'])
        assert json.dumps(actual,sort_keys=True,ensure_ascii=False)==row['encoded'],row
    changed=length_factors('mm');changed['米']=1
    assert length_factors('mm')['米']==1000
    assert '公分' not in length_factors('mm')
    assert length_factors('mm',include_gongfen=True)['公分']==10
    with pytest.raises(ValueError):length_factors('unknown')


@pytest.mark.parametrize('row',GOLD['fingerprints'])
def test_legacy_fingerprint_bytes_remain_identical(row):
    from app.cad_assertions import _fingerprint as assertion
    from app.cad_edit_preview import _fingerprint as preview
    from app.cad_edit_gate import geometry_fingerprint,geometry_entity_fingerprint
    from app.cad_local_repair import fingerprint
    for fn in (canonical_json_hash,assertion,preview,geometry_fingerprint,geometry_entity_fingerprint,fingerprint):
        assert fn(row['input'])==row['sha256']


@pytest.mark.parametrize('value,encoded',[(float('nan'),b'NaN'),(float('inf'),b'Infinity'),(float('-inf'),b'-Infinity')])
def test_hash_refactor_preserves_legacy_nonfinite_json_encoding(value,encoded):
    assert canonical_json_hash(value)==hashlib.sha256(encoded).hexdigest()


def test_evidence_is_bound_to_complete_inputs_and_returns_independent_reports():
    context=ConstructionEvidence();calls=[]
    def verify(source,geometry):
        calls.append(1)
        return {'checks':[{'source':source,'value':geometry[0]['x']}]}
    geo=[{'x':1}]
    first=context.measure(verify,'original',geo);first['checks'][0]['value']=999
    assert context.measure(verify,'original',geo)['checks'][0]['value']==1
    assert len(calls)==1
    geo[0]['x']=2
    assert context.measure(verify,'original',geo)['checks'][0]['value']==2
    assert context.measure(verify,'corrected',geo)['checks'][0]['source']=='corrected'
    assert len(calls)==3
    ConstructionEvidence().measure(verify,'corrected',geo)
    assert len(calls)==4


def test_failures_propagate_unchanged_and_are_not_cached():
    context=ConstructionEvidence();failure=StructureContractError('wrong radius',{'actual_mm':9});calls=[]
    def verify(source,geometry):
        calls.append(1)
        raise failure
    for _ in range(2):
        with pytest.raises(StructureContractError) as caught:context.measure(verify,'source',[])
        assert caught.value is failure
    assert len(calls)==2


def test_non_json_metadata_preserves_verifier_behavior_without_reuse():
    context=ConstructionEvidence();calls=[]
    def verify(geometry):calls.append(1);return {'x':geometry['x']}
    geometry={'x':1,'metadata':{1:object(),'text':'value'}}
    assert context.measure(verify,geometry)==context.measure(verify,geometry)=={'x':1}
    assert len(calls)==2


def test_parallel_trials_have_separate_evidence():
    def trial(value):
        context=ConstructionEvidence();calls=[]
        def verify(source):calls.append(1);return {'value':source}
        a=context.measure(verify,value);b=context.measure(verify,value)
        return a,b,len(calls)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(trial,['A','B']))
    assert results==[({'value':'A'},{'value':'A'},1),({'value':'B'},{'value':'B'},1)]


@pytest.mark.parametrize('case,module,name',[
    ('C31','cad_symmetric_divider_acceptance','verify_symmetric_divider_source'),
    ('C24','cad_radial_attachment_acceptance','verify_radial_attachment_source'),
    ('C22','cad_repetition_acceptance','verify_repetition_requirements')])
def test_source_binding_and_main_acceptance_share_one_measurement(case,module,name):
    from app.cad_construction_interpreter import interpret_construction_request
    fixtures=Path(__file__).parent/'fixtures'
    if case=='C22':
        row=next(r for r in json.loads((fixtures/'recorded_source_proof_gaps.json').read_text(encoding='utf-8'))['rows'] if r['case']==case)
        source=row['source']
    else:
        filename='recorded_symmetric_divider.json' if case=='C31' else 'recorded_radial_attachments.json'
        row=json.loads((fixtures/filename).read_text(encoding='utf-8'))
        source='\n'.join([row['original'],*row['followups']])
    target=importlib.import_module('app.'+module);verifier=getattr(target,name)
    original_plan=deepcopy(row['plan'])
    with patch.object(target,name,wraps=verifier) as measured:
        result=interpret_construction_request(source,lambda *_:{
            'schema_version':'cad.construction-interpretation.v1','is_construction_request':True,
            'plan':deepcopy(original_plan),'confidence':.99,'evidence_text':[row['original']],'assumptions':[]},force_structured_model=True)
    assert result['status']=='ready',result.get('error')
    assert result['acceptance_summary']['status']=='passed'
    assert measured.call_count==1
    assert row['plan']==original_plan
