from copy import deepcopy
from app.cad_candidate_state import bind_version_symbols,resolve_version_symbols,geometry_evidence_hash


def test_mapping_is_project_version_and_geometry_bound():
    variant={'id':'v','geometries':[{'id':1},{'id':2}]}
    record={'symbol_table':{'roof':[1],'outline':[1,2]},'geometry_hash':geometry_evidence_hash(variant['geometries'])}
    before=deepcopy(record)
    variant['construction_record']={**record,'version_symbols':bind_version_symbols(record,variant,'p')}
    assert resolve_version_symbols(variant,'p')==record['symbol_table']
    assert resolve_version_symbols(variant,'other') is None
    variant['id']='v2'
    assert resolve_version_symbols(variant,'p') is None
    assert record==before


def test_missing_deleted_or_stale_mapping_is_unknown():
    variant={'id':'v','geometries':[{'id':1}]}
    assert bind_version_symbols({},variant,'p')['status']=='unknown'
    record={'symbol_table':{'roof':[1,2]},'geometry_hash':geometry_evidence_hash(variant['geometries'])}
    assert bind_version_symbols(record,variant,'p')['status']=='unknown'
    record['symbol_table']={'roof':[1]};record['geometry_hash']='old'
    assert bind_version_symbols(record,variant,'p')['status']=='unknown'


def test_multiturn_transform_and_delete_preserve_only_proven_identity():
    from app.cad_candidate_state import transformed_version_symbols
    first={'id':'v1','geometries':[{'id':1,'x':0},{'id':2,'x':2}]}
    record={'symbol_table':{'inner':[1],'outer':[2]},'geometry_hash':geometry_evidence_hash(first['geometries'])}
    first['construction_record']={'version_symbols':bind_version_symbols(record,first,'p')}
    moved={'id':'v2','geometries':[{'id':1,'x':3},{'id':2,'x':5}]}
    moved['reference_mapping']=transformed_version_symbols(first,moved,'p','translate')
    assert resolve_version_symbols(moved,'p')=={'inner':[1],'outer':[2]}
    deleted={'id':'v3','geometries':[{'id':2,'x':5}]}
    deleted['reference_mapping']=transformed_version_symbols(moved,deleted,'p','delete')
    assert resolve_version_symbols(deleted,'p')=={'outer':[2]}
    copied={'id':'v4','geometries':[{'id':2},{'id':3}]}
    assert transformed_version_symbols(deleted,copied,'p','copy')['status']=='unknown'
