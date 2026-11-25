"""Offline sensitivity study; analytic curves are test data, not CAD generators."""
import hashlib
import json
import math
from pathlib import Path
from evaluations.lower_taper_relation_v1 import lower_taper_relation


def study():
    rows=[]
    for radius in (100,1000,10000):
        for count in (32,128,512):
            for phase in (0,.25,.5,.75):
                for dx,dy in ((0,0),(1e6,-1e6)):
                    points=[(dx+radius*math.cos(2*math.pi*(i+phase)/count),
                        dy+radius+radius*math.sin(2*math.pi*(i+phase)/count)) for i in range(count)]
                    proof=lower_taper_relation(points)
                    error=radius*(1-math.cos(math.pi/count))
                    rows.append({'case':'sampled_round_bottom','radius_mm':radius,'samples':count,
                        'phase':phase,'translation_mm':[dx,dy],
                        'scope':'lower_relation_only; circle is not a positive full-heart example',
                        'analytic_curve_has_central_taper':True,
                        'chord_error_bound_mm':error,'chord_error_within_tolerance':error<=.5,
                        'proof':proof})
    exact=[]
    for scale in (.1,1,10):
        for dx,dy in ((0,0),(1e6,-1e6)):
            for divisions in (1,5,20):
                for reverse in (False,True):
                    for shift in range(3):
                        vertices=[(0,0),(-2000,4000),(2000,4000)]
                        vertices=vertices[shift:]+vertices[:shift]
                        if reverse:vertices=vertices[::-1]
                        points=[(dx+scale*(a[0]+(b[0]-a[0])*i/divisions),
                            dy+scale*(a[1]+(b[1]-a[1])*i/divisions))
                            for a,b in zip(vertices,vertices[1:]+vertices[:1]) for i in range(divisions)]
                        proof=lower_taper_relation(points)
                        exact.append({'scale':scale,'translation_mm':[dx,dy],'divisions':divisions,
                            'reversed':reverse,'cyclic_shift':shift,'relation_passed':proof['relation_passed']})
    shallow=[]
    for fraction in (.005,.01,.05,.1,.25,.5):
        points=[(0,0),(-2000,4000*fraction),(-2000,4000),(2000,4000),(2000,4000*fraction)]
        shallow.append({'taper_band_height_fraction':fraction,'scope':'local V-bottom only, not a full-heart positive',
            'proof':lower_taper_relation(points)})
    return {'scope':'Lower-relation sensitivity, not fresh model tests or corpus scores',
        'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'rule_sha256':hashlib.sha256(Path(__file__).with_name('lower_taper_relation_v1.py').read_bytes()).hexdigest(),
        'sampled_round_bottom_rows':rows,'exact_polygon_rows':exact,'thin_taper_band_rows':shallow,
        'production_promotion_supported':False,
        'summary':{'round_bottom_count':len(rows),'round_bottom_passed':sum(r['proof']['relation_passed'] for r in rows),
            'rejected_within_chord_tolerance':sum(r['chord_error_within_tolerance'] and not r['proof']['relation_passed'] for r in rows),
            'exact_polygon_count':len(exact),'exact_polygon_passed':sum(r['relation_passed'] for r in exact)}}


if __name__=='__main__':
    import sys
    result=study();Path(sys.argv[1]).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result['summary']))
