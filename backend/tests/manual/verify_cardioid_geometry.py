"""Independent read-only cardioid fit on saved geometry, never a generator.

Polar identity r=a*(1+cos(theta-phi)); permits translation/rotation/scale.
Reference: https://mathworld.wolfram.com/Cardioid.html
"""
import json
import sys
from pathlib import Path
from app.cad_curve_fit_acceptance import verify_cardioid


if __name__=='__main__':
    project=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))['projects'][0]
    variant=project['variants'][-1]
    print(json.dumps({'variant_id':variant['id'],
        'checks':[verify_cardioid(g) for g in variant['geometries']]},ensure_ascii=False,indent=2))
