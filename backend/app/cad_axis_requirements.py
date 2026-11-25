"""Source principal-axis dimensions; no geometry generation or model claims."""
from .cad_length_units import length_factors
import math
import re

N = r'[-+]?\d+(?:\.\d+)?'
U = r'(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])'
P = rf'[（(]\s*({N})\s*[,，]\s*({N})\s*[）)]'
FACTORS = length_factors('m')


def ellipse_axes(source):
    from .cad_source_acceptance import source_texts
    text = '\n'.join(source_texts(source))
    from .cad_creation_intent import local_creation_objects
    if len(local_creation_objects(text)) > 1:
        return {'status':'partial','dimensions':{},'evidence':[],'full_source':False}
    values = {}; evidence = []; center = None; rotation = None; consumed = True
    for clause in text.splitlines():
        local = {}; rest = clause
        pattern = r'(长|短)(半轴|轴)(全长|长度)?(?:为|是|改为|=|[:：])?\s*('+N+r')\s*'+U
        for match in re.finditer(pattern, clause, re.I):
            value = float(match[4])*FACTORS[match[5].lower()] / (1 if match[2]=='半轴' else 2)
            key = 'major_radius_m' if match[1]=='长' else 'minor_radius_m'
            if (not math.isfinite(value) or value<=0 or (match[2]=='半轴' and match[3]=='全长')
                    or key in local and not math.isclose(local[key],value,abs_tol=1e-12)):
                return {'status':'conflict','evidence':evidence+[match[0]],'full_source':False}
            local[key] = value; evidence.append(match[0])
        values.update(local)
        rest = re.sub(pattern,' ',rest,flags=re.I)
        units = re.findall(r'坐标单位(?:为|是|[:：])?\s*'+U,clause,re.I)
        if not units:
            units = re.findall(N+r'\s*'+U,clause,re.I)
        centers = list(re.finditer(r'(?:中心|圆心)(?:位于|在|为|是|=|[:：])?\s*'+P,rest))
        if centers:
            if not units or len(set(u.lower() for u in units))!=1:
                consumed = False
            else:
                m = centers[-1]; factor = FACTORS[units[-1].lower()]
                center = [float(m[1])*factor,float(m[2])*factor]
                rest = re.sub(r'(?:中心|圆心)(?:位于|在|为|是|=|[:：])?\s*'+P,' ',rest)
        rotations = list(re.finditer(r'(顺时针|逆时针)?旋转\s*('+N+r')\s*度',rest))
        if rotations:
            m=rotations[-1];rotation=float(m[2])*(-1 if m[1]=='顺时针' else 1)
            rest=re.sub(r'(顺时针|逆时针)?旋转\s*('+N+r')\s*度',' ',rest)
        rest = re.sub(r'坐标单位(?:为|是|[:：])?\s*'+U,' ',rest,flags=re.I)
        rest = re.sub(r'新建图纸|生成|创建|绘制|画出|画|请|一个|椭圆|的|闭合',' ',rest)
        if rest.strip(' \t\r\n，,。；;'):
            consumed = False
    if len(values)!=2:
        return {'status':'partial','dimensions':values,'evidence':evidence,'full_source':False}
    if values['major_radius_m']<values['minor_radius_m']:
        return {'status':'conflict','evidence':evidence,'full_source':False}
    return {'status':'complete','dimensions':values,'center_m':center,
            'rotation_deg':rotation,'evidence':evidence,
            'full_source':consumed and '椭圆' in text}


def verify_ellipse_axes(source, geometries):
    from .cad_structure_contract import StructureContractError
    requirement=ellipse_axes(source)
    if requirement['status']!='complete' or not requirement['full_source']:
        return {'status':'not_checked','coverage':'partial','checks':[]}
    gs=[g for g in geometries if g.get('selected') is not False and g.get('role') not in {'annotation','reference','ignored'}]
    checks=[{'field':'single_ellipse_type_and_count',
             'status':'passed' if len(gs)==1 and gs[0].get('type')=='ellipse' else 'failed'}]
    if checks[0]['status']=='passed':
        g=gs[0];axis=g.get('major_axis') or {};actual=math.hypot(axis.get('x',0),axis.get('y',0))
        expected=requirement['dimensions']
        for field,value in [('major_radius_m',actual),('minor_radius_m',actual*g.get('ratio',0))]:
            checks.append({'field':field,'actual_mm':value,'expected_mm':expected[field]*1000,
                'status':'passed' if abs(value-expected[field]*1000)<=.5 else 'failed'})
        span=g.get('end_angle',360)-g.get('start_angle',0)
        checks.append({'field':'full_planar_ellipse', 'status':'passed' if abs(span-360)<=.001 and abs(axis.get('z',0))<=.5 else 'failed'})
        if requirement['center_m'] is not None:
            actual_center=[g['center']['x'],g['center']['y']]
            checks.append({'field':'center','status':'passed' if math.dist(actual_center,
                [v*1000 for v in requirement['center_m']])<=.5 else 'failed'})
        if requirement['rotation_deg'] is not None:
            angle=math.degrees(math.atan2(axis.get('y',0),axis.get('x',0)))
            error=abs((angle-requirement['rotation_deg']+90)%180-90)
            checks.append({'field':'principal_axis_orientation','status':'passed' if error<=.001 else 'failed'})
    if any(c['status']=='failed' for c in checks):
        raise StructureContractError('椭圆实际主轴不符合原始全轴/半轴要求',
            {'geometry_ids':[g['id'] for g in gs],'checks':checks,'source_evidence':requirement['evidence']})
    return {'status':'passed','coverage':'complete','checks':checks,
            'source_evidence':requirement['evidence'],'authority':'backend_measured_geometry'}
