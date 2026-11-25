"""Source-bound harmonic measurement of submitted wave linework; no CAD creation."""
from .cad_length_units import length_factors
import math
import re

import numpy as np

from .cad_source_acceptance import N, source_texts
from .cad_structure_contract import StructureContractError

UNIT=r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'
FACTORS=length_factors('mm')


def wave_requirements(source):
    from .cad_creation_intent import local_creation_objects
    text='\n'.join(source_texts(source))
    if ('正弦' not in text or re.search(r'弧长|路径长度',text)
            or len(local_creation_objects(text))>1):return None
    patterns={'length_mm':r'(?:总长|长)\s*('+N+r')\s*'+UNIT,
              'amplitude_mm':r'(?:振幅|波幅)\s*('+N+r')\s*'+UNIT,
              'wavelength_mm':r'(?:相邻波峰间距|波距)\s*('+N+r')\s*'+UNIT}
    values={}
    for field,pattern in patterns.items():
        matches=list(re.finditer(pattern,text,re.I))
        if not matches:return None
        # Repeated, conflicting source scalars remain unverified; no last-value
        # overwrite may turn a conflicting request into full source coverage.
        numbers=[float(m[1])*FACTORS[m[2].lower()] for m in matches]
        if any(not math.isfinite(v) or v<=0 or abs(v-numbers[0])>1e-6 for v in numbers):return None
        values[field]=numbers[0]
    return {**values,'patterns':patterns}


def verify_wave_requirements(source,geometries):
    partial={'status':'not_checked','coverage':'partial','checks':[]}
    spec=wave_requirements(source)
    if not spec:return partial
    gs=[g for g in geometries if g.get('selected') is not False
        and g.get('role') not in {'annotation','reference','ignored'}]
    def fail(message,**details):
        raise StructureContractError(message,{'geometry_ids':[g['id'] for g in gs],
            'authority':'backend_measured_geometry',**details})
    if (len(gs)!=1 or gs[0].get('type')!='polyline' or gs[0].get('closed')
            or any(p.get('bulge',0)!=0 for p in gs[0].get('vertices',[]))):
        fail('正弦波要求一条开放的直边采样路径')
    points=np.asarray([[p['x'],p['y']] for p in gs[0]['vertices']],dtype=float)
    if len(points)<8 or not np.isfinite(points).all():fail('正弦波缺少可测量的有效采样点')
    from shapely.geometry import LineString
    dx=np.diff(points[:,0])
    if not LineString(points).is_simple or not (np.all(dx>0) or np.all(dx<0)):
        fail('正弦波路径必须沿横向连续前进，不能回叠或自交')
    span=float(np.ptp(points[:,0]))
    if abs(span-spec['length_mm'])>.5:
        fail('正弦波横向总长不符合原文',actual_mm=span,expected_mm=spec['length_mm'])
    k=math.tau/spec['wavelength_mm'];x=points[:,0]-points[0,0]
    design=np.column_stack((np.sin(k*x),np.cos(k*x),np.ones(len(x))))
    coefficients,_,rank,_=np.linalg.lstsq(design,points[:,1],rcond=None)
    if rank!=3:fail('正弦波采样不足以独立测量振幅和相位')
    amplitude=float(np.hypot(*coefficients[:2]))
    if abs(amplitude-spec['amplitude_mm'])>.5:
        fail('正弦波振幅不符合原文：振幅是中线到波峰的距离，峰谷差是其两倍',
             field='amplitude',actual_mm=amplitude,expected_mm=spec['amplitude_mm'])
    following=points[1:];left=points[:-1]
    probes=np.concatenate([points,*[left+(following-left)*f for f in (.25,.5,.75)]])
    px=probes[:,0]-points[0,0]
    predicted=coefficients[0]*np.sin(k*px)+coefficients[1]*np.cos(k*px)+coefficients[2]
    error=float(np.max(np.abs(probes[:,1]-predicted)))
    tolerance=max(.5,spec['amplitude_mm']*.005)
    if error>tolerance:
        fail('实际连接路径不符合原文波距的正弦关系',maximum_error_mm=error,tolerance_mm=tolerance)
    text='\n'.join(source_texts(source));rest=text
    for pattern in spec['patterns'].values():rest=re.sub(pattern,' ',rest,flags=re.I)
    periods=list(re.finditer(r'共\s*('+N+r')\s*个周期',rest))
    consistent=all(abs(float(m[1])-spec['length_mm']/spec['wavelength_mm'])<1e-9 for m in periods)
    if consistent:rest=re.sub(r'共\s*('+N+r')\s*个周期',' ',rest)
    rest=re.sub(r'生成|创建|绘制|画出|画|请|一条|正弦波浪线|正弦曲线',' ',rest)
    complete=consistent and not rest.strip(' \t\r\n，,、。；;')
    return {'status':'passed','coverage':'complete' if complete else 'partial',
            'checks':[{'name':'source_sine_span_amplitude_and_wavelength','status':'passed',
                'length_mm':span,'amplitude_mm':amplitude,'wavelength_mm':spec['wavelength_mm'],
                'maximum_between_vertex_error_mm':error,'tolerance_mm':tolerance}],
            'geometry_ids':[gs[0]['id']],'source_evidence':source_texts(source),
            **({'unconsumed_text':rest.strip()} if not complete else {}),
            'authority':'backend_measured_geometry','measurement_scope':'source_bound_harmonic_fit_and_chord_probes'}
