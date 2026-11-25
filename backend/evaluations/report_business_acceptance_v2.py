"""Add versioned business scores without overwriting legacy or production scores."""
import argparse
import hashlib
import json
import re
from pathlib import Path

from evaluations.business_oracles_v2 import VERSION,retained_circle_rotation,projected_cube_incidence


def report(root):
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    summary=read(root/'summary.json');manifest=read(root/'manifest.json')
    aligned=read(root/'final-results.json') if (root/'final-results.json').exists() else None
    aligned_rows={r['case']:r for r in aligned['reports']} if aligned else {}
    if not (root/'completed.json').exists():raise ValueError('Run has not completed')
    rows=[]
    for raw in summary['reports']:
        baseline=bool(aligned_rows.get(raw['case'],{}).get('corpus_aligned_passed',raw['formal_passed']))
        row={'case':raw['case'],'legacy_passed':bool(raw['legacy_passed']),
             'runner_formal_passed':bool(raw['formal_passed']),
             'production_formal_passed':baseline,
             'v2_passed':baseline,'rule_change':None}
        case=raw['case'];final=read(Path(raw['last_response'])) if raw.get('last_response') else {}
        if case=='B5' and case in manifest['edit_bases']:
            base=manifest['edit_bases'][case]
            before=read(root/base/'projects.json')['projects'][0]
            after=read(root/case/'projects.json')['projects'][0]
            proof=retained_circle_rotation(before,after,final)
            others=[c for c in raw.get('checks',[]) if c['name']!='new_saved_version']
            if proof['passed'] and others and all(c['passed'] for c in others):
                row.update(v2_passed=True,rule_change='verified_retained_noop_is_valid_delivery')
            row['v2_proof']=proof
        elif case=='C27':
            project=read(root/case/'projects.json')['projects'][0]
            variant=next((v for v in project['variants'] if v['id']==(final.get('variant') or {}).get('id')),None)
            if variant is None and raw.get('accepted_candidate'):
                variant=next((v for v in reversed(project['variants']) if v.get('acceptance_summary',{}).get('status')=='passed'),None)
            supplement=manifest['supplements'].get(case,[])
            if isinstance(supplement,str):supplement=[supplement]
            text='\n'.join([manifest['prompts'][case],*supplement])
            sizes=re.findall(r'投影棱长\s*(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)',text,re.I)
            proof={'version':VERSION,'passed':False,'reason':'missing_accepted_variant_or_explicit_projected_length'}
            if variant and sizes:
                value,unit=sizes[-1];scale={'毫米':1,'厘米':10,'米':1000,'mm':1,'cm':10,'m':1000}[unit.lower()]
                proof=projected_cube_incidence(variant['geometries'],float(value)*scale)
            others=[c for c in raw.get('checks',[]) if c['name']!='projection_topology_review']
            if (proof['passed'] and raw.get('accepted_candidate') and final.get('ok') is True
                    and others and all(c['passed'] for c in others)):
                row.update(v2_passed=True,rule_change='independent_endpoint_adjacency_replaces_manual_marker')
            row['v2_proof']=proof
        rows.append(row)
    result={'schema':VERSION,'scope':'Separate evaluation rule version; not a production capability improvement',
            'oracle_source_sha256':hashlib.sha256(Path(__file__).with_name('business_oracles_v2.py').read_bytes()).hexdigest(),
            'reporter_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'run_manifest_sha256':hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest(),
            'source_run':str(root.resolve()),'source_summary_sha256':hashlib.sha256((root/'summary.json').read_bytes()).hexdigest(),
            'total':len(rows),'legacy_passed':sum(r['legacy_passed'] for r in rows),
            'production_formal_passed':sum(r['production_formal_passed'] for r in rows),
            'v2_passed':sum(r['v2_passed'] for r in rows),'rows':rows}
    if aligned:
        result['original_expectation_v1']=aligned['original_expectation_passed']
        result['original_expectation_v2']=aligned['original_expectation_passed']+sum(r['v2_passed']-r['production_formal_passed'] for r in rows)
        result['inherited_alignment_source_sha256']=hashlib.sha256((root/'final-results.json').read_bytes()).hexdigest()
    (root/'business-results-v2.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,required=True)
    r=report(parser.parse_args().run)
    print(json.dumps({k:v for k,v in r.items() if k!='rows'},ensure_ascii=False,indent=2))
