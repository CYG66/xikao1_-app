"""Read-only source verifier diagnostics; never change official holdout results."""
import json
from pathlib import Path
import sys
from evaluations import production_contract_pilot as base
from app.cad_circle_group_acceptance import verify_circle_group_source
from app.cad_vertex_acceptance import verify_vertex_path, open_straight_path_requirements
from app.cad_semantic_source_coverage import semicircular_source_requirements


def main(root):
    manifest=json.loads((root/'holdout-manifest.json').read_text(encoding='utf-8'))
    protected=[root/'results.json',root/'holdout-analysis.json',root/'budget.json']
    before={str(p):p.read_bytes() for p in protected}
    records=[]
    for case in manifest['cases']:
        if case['id'] not in {'V1','V2','V4','V6'}: continue
        for repeat in (1,2):
            folder=root/f"{case['id']}-r{repeat}-B"
            store=json.loads((folder/'projects.json').read_text(encoding='utf-8'))
            variants=[v for p in store['projects'] for v in p.get('variants',[])]
            source=case['text']+'只生成预览，不执行小车。'
            if case['id']=='V1': proof=verify_circle_group_source(source,variants[0]['geometries'])
            elif case['id']=='V2': proof=verify_vertex_path(source,variants[0]['geometries'])
            elif case['id']=='V4': proof=open_straight_path_requirements(source)
            else: proof=semicircular_source_requirements(source)
            records.append({'trial':folder.name,'source_parser':proof,'stored_variant_count':len(variants)})
    assert all(p.read_bytes()==before[str(p)] for p in protected)
    base.dump(root/'source-parser-diagnostics.json',{'scope':'Read-only original-source diagnostics; no score or source rewrite.', 'records':records,'official_results_unchanged':True})
    print(json.dumps({'diagnosed_trials':len(records),'all_source_coverage_partial':all(r['source_parser'].get('coverage')=='partial' for r in records),'official_results_unchanged':True}))


if __name__=='__main__': main(Path(sys.argv[1]))
