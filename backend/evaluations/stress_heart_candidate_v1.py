"""Synthetic negative fixtures for offline rule testing, never CAD generation."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from shapely.geometry import Polygon, Point
from evaluations.heart_acceptance_candidate_v1 import compare


def scenarios(row):
    def polygon_payload(polygon,count):
        payload=deepcopy(row['payload']);old=payload['plan']['steps'][0]
        ring=polygon.exterior
        samples=[ring.interpolate(ring.length*i/(count//2)) for i in range(count//2)]
        # Preserve exact reflection symmetry rather than testing sampling
        # phase error. Include the central bottom point on flat bottoms.
        samples += [Point(4-p.x,p.y) for p in samples]
        bottom=Point(2,polygon.bounds[1])
        if ring.distance(bottom)<1e-8: samples.append(bottom)
        unique={(round(p.x,12),round(p.y,12)):p for p in samples}
        points=sorted(unique.values(),key=ring.project)
        payload['plan']['steps']=[{'step_id':old['step_id'],'output_ref':old['output_ref'],
            'semantic':old['semantic'],'op':'add_polyline','closed':True,
            'vertices':[{'x':p.x,'y':p.y} for p in points]}]
        payload['plan']['assertions']=[]
        return payload
    u=Polygon([(0,1),(0,5),(1,5),(1,2),(3,2),(3,5),(4,5),(4,1)])
    rounded=u.buffer(.15,resolution=32).buffer(-.3,resolution=32).buffer(.15,resolution=32)
    multi=Polygon([(0,1),(0,4),(.4,5),(.8,4),(1.2,5),(2,3),
        (2.8,5),(3.2,4),(3.6,5),(4,4),(4,1)])
    for name,poly in [('rounded_u',rounded),('multiple_lobes',multi),('circle',Point(2,3).buffer(2,resolution=64))]:
        for count in (160,400):
            yield f'{name}_{count}',polygon_payload(poly,count)
    for name,angle in [('inverted',math.pi),('sideways',math.pi/2)]:
        payload=deepcopy(row['payload'])
        for step in payload['plan']['steps']:
            if step['op']!='add_parametric_curve': raise ValueError('Unsupported fixture transform')
            x,y=step['x_expression'],step['y_expression'];c,s=math.cos(angle),math.sin(angle)
            step['x_expression']=f'2+(({x})-2)*({c})-(({y})-3)*({s})'
            step['y_expression']=f'3+(({x})-2)*({s})+(({y})-3)*({c})'
        yield name,payload
    payload=deepcopy(row['payload'])
    for step in payload['plan']['steps']:
        if step['op']!='add_parametric_curve': raise ValueError('Unsupported fixture transform')
        step['x_expression']=f"({step['x_expression']})+0.15*sin({step['y_expression']})"
    yield 'asymmetric',payload


def run(fixture,output):
    row=next(r for r in json.loads(fixture.read_text(encoding='utf-8')) if r['response_index']==3)
    rows=[]
    for name,payload in scenarios(row):
        result=compare(row['source'],payload)
        rows.append({'case':name,'expected_negative':True,
            'fixture_payload_sha256':hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest(),**result})
        print(name,result['legacy_passed'],result['candidate_passed'],(result.get('candidate_error') or {}).get('message'))
    report={'scope':'Synthetic negative stress tests; not real model or corpus score',
        'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'unexpected_candidate_passes':[r['case'] for r in rows if r['candidate_passed']], 'rows':rows}
    report['promotion_blocked']=bool(report['unexpected_candidate_passes'])
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    import sys
    run(Path(sys.argv[1]),Path(sys.argv[2]))
