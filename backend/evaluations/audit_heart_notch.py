"""Read-only replay of recorded plans; topology diagnostic is not a new score."""
import hashlib
import json
from pathlib import Path
import sys

from app.cad_construction import execute_construction_plan
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_structure_contract import _points
from shapely.geometry import Polygon, LineString


def measure_notch_topology(points):
    polygon=Polygon(points)
    if not polygon.is_valid or polygon.area<=0: raise ValueError('invalid polygon')
    xmin,ymin,xmax,ymax=polygon.bounds;cx=(xmin+xmax)/2
    section=polygon.intersection(LineString([(cx,ymin-1),(cx,ymax+1)]))
    center_top=section.bounds[3]
    left=max(y for x,y in points if x<cx)
    right=max(y for x,y in points if x>cx)
    depth=min(left,right)-center_top
    return {'center_upper_boundary_mm':[cx,center_top],
        'left_peak_y_mm':left,'right_peak_y_mm':right,
        'notch_depth_below_both_peaks_mm':depth,
        'center_upper_normalized_height':(center_top-ymin)/(ymax-ymin),
        'center_below_both_side_peaks':depth>0.5,'diagnostic_tolerance_mm':0.5}


def audit(run, relation_v1=False):
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    project=read(run/'A9/projects.json')['projects'][0]
    source='\n'.join([project['original_prompt'],*project['requirements'].get('source_followups',[])])
    rows=[]
    for index,line in enumerate((run/'A9/model-responses.jsonl').read_text(encoding='utf-8').splitlines()):
        raw=json.loads(line)
        try: payload=json.loads(raw['response'])
        except (ValueError,TypeError): continue
        if not isinstance(payload,dict) or not payload.get('plan'): continue
        result=interpret_construction_request(source,lambda *_:payload,force_structured_model=True)
        row={'response_index':index+1,'turn':raw.get('step'),'status':result.get('status'),
            'error':result.get('construction_error') or result.get('error'),
            'input_plan_sha256':hashlib.sha256(json.dumps(payload['plan'],sort_keys=True).encode()).hexdigest()}
        try:
            trial=execute_construction_plan(result['plan'])
            points=_points(trial['geometries'][0])
            row['measured']={**measure_notch_topology(points),
                'geometry_sha256':hashlib.sha256(json.dumps(trial['geometries'],sort_keys=True).encode()).hexdigest()}
            if relation_v1:
                from evaluations.notch_relation_v1 import upper_notch_relation
                row['notch_relation_v1']=upper_notch_relation(points)
        except (ValueError,KeyError,IndexError) as error:
            row['measurement_error']=str(error)
        rows.append(row)
    output={'scope':'Diagnostic audit only; no production rule change and no rescoring',
        'source_run':str(run.resolve()),'source':source,'rows':rows}
    if relation_v1:
        output['oracle_source_sha256']=hashlib.sha256(Path(__file__).with_name('notch_relation_v1.py').read_bytes()).hexdigest()
        output['recorded_responses_sha256']=hashlib.sha256((run/'A9/model-responses.jsonl').read_bytes()).hexdigest()
    name='notch-relation-v1-audit.json' if relation_v1 else 'notch-topology-audit.json'
    (run/'A9'/name).write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    for row in rows: print(json.dumps(row,ensure_ascii=False))


if __name__=='__main__': audit(Path(sys.argv[1]), relation_v1='--relation-v1' in sys.argv[2:])
