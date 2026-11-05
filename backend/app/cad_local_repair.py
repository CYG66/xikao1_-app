"""Conservative locks for measured failures in independent literal paths."""
import hashlib
import json
import math
from copy import deepcopy


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def coordinate_patch_schema(context):
    scope=context['construction_error']['details']['local_repair_scope']
    point={'type':'object','properties':{'x':{'type':['number','string']},'y':{'type':['number','string']},'z':{'type':['number','string']}},'required':['x','y'],'additionalProperties':False}
    alternatives=[]
    for ref,fields in scope['editable_fields_by_ref'].items():
        values={f:({'type':'array','minItems':2,'maxItems':500,'items':point} if f=='vertices' else point) for f in fields}
        alternatives.append({'type':'object','properties':{'output_ref':{'const':ref},**values},'minProperties':2,'required':['output_ref'],'additionalProperties':False})
        step=next(s for s in (context.get('plan') or context['rejected_plan'])['steps'] if s['output_ref']==ref)
        if fields==['vertices'] and step.get('closed') is True:
            rectangle={'type':'object','properties':{k:{'type':'number'} for k in ('min_x','min_y','max_x','max_y')},
                       'required':['min_x','min_y','max_x','max_y'],'additionalProperties':False}
            alternatives.append({'type':'object','properties':{'output_ref':{'const':ref},'subtract_rectangle':rectangle},
                                 'required':['output_ref','subtract_rectangle'],'additionalProperties':False})
            if ref in scope.get('cut_windows_by_ref',{}):
                fractions={'type':'object','properties':{k:{'type':'number','exclusiveMinimum':0,'exclusiveMaximum':1}
                    for k in ('left_fraction','right_fraction','height_fraction')},
                    'required':['left_fraction','right_fraction','height_fraction'],'additionalProperties':False}
                alternatives.append({'type':'object','properties':{'output_ref':{'const':ref},'subtract_relative_rectangle':fractions},
                    'required':['output_ref','subtract_relative_rectangle'],'additionalProperties':False})
    return {'type':'object','properties':{'schema_version':{'const':'cad.coordinate-patch.v2'},
        'source_plan_sha256':{'const':scope['source_plan_sha256']},'confidence':{'type':'number','minimum':0,'maximum':1},
        'edits':{'type':'array','minItems':1,'maxItems':len(scope['editable_fields_by_ref']),'items':{'oneOf':alternatives}}},
        'required':['schema_version','source_plan_sha256','confidence','edits'],'additionalProperties':False}


def coordinate_patch_example(context):
    """Valid JSON structure using only existing failed coordinates, not a fix."""
    scope=context['construction_error']['details']['local_repair_scope']
    ref=next(iter(scope['editable_fields_by_ref']))
    original=next(s for s in (context.get('plan') or context['rejected_plan'])['steps'] if s['output_ref']==ref)
    return {'schema_version':'cad.coordinate-patch.v2','source_plan_sha256':scope['source_plan_sha256'],
            'confidence':0,'edits':[{'output_ref':ref,**{k:deepcopy(original[k]) for k in scope['editable_fields_by_ref'][ref]}}]}


def apply_coordinate_patch(context, patch):
    scope=context['construction_error']['details']['local_repair_scope'];old=context.get('plan') or context.get('rejected_plan')
    if fingerprint(old)!=scope['source_plan_sha256']:raise ValueError('局部修复源计划已变化')
    if not isinstance(patch,dict) or set(patch)!={'schema_version','source_plan_sha256','confidence','edits'}:
        raise ValueError('局部修复只接受坐标补丁，禁止提交整份计划或额外字段')
    if patch['schema_version']!='cad.coordinate-patch.v2' or patch['source_plan_sha256']!=scope['source_plan_sha256']:
        raise ValueError('坐标补丁未绑定当前失败计划')
    confidence=patch['confidence']
    if isinstance(confidence,bool) or not isinstance(confidence,(int,float)) or not math.isfinite(confidence) or not 0<=confidence<=1:
        raise ValueError('补丁置信度无效')
    edits=patch['edits'];allowed=scope['editable_fields_by_ref']
    if not isinstance(edits,list) or not 1<=len(edits)<=len(allowed):raise ValueError('坐标补丁数量无效')
    merged=deepcopy(old);steps={s['output_ref']:s for s in merged['steps']};seen=set()
    for edit in edits:
        if not isinstance(edit,dict) or 'output_ref' not in edit:raise ValueError('补丁步骤字段无效')
        ref=edit['output_ref'];fields={k:v for k,v in edit.items() if k!='output_ref'}
        if not isinstance(ref,str) or ref not in allowed or ref in seen:raise ValueError('补丁涉及受保护、未知或重复的步骤')
        if 'subtract_relative_rectangle' in fields:
            if set(fields)!={'subtract_relative_rectangle'}:raise ValueError('相对裁剪不能与其他操作混合')
            window=scope.get('cut_windows_by_ref',{}).get(ref)
            ratios=fields['subtract_relative_rectangle'];keys={'left_fraction','right_fraction','height_fraction'}
            if not window or not isinstance(ratios,dict) or set(ratios)!=keys:raise ValueError('没有经验证的相对裁剪窗口')
            if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<v<1 for v in ratios.values()):
                raise ValueError('相对裁剪比例必须严格位于0和1之间')
            if ratios['left_fraction']>=ratios['right_fraction']:raise ValueError('相对裁剪左右比例顺序无效')
            x,y,X,Y=window['bounds_in_plan_units'];width=X-x;height=Y-y
            fields={'subtract_rectangle':{'min_x':x+width*ratios['left_fraction'],'max_x':x+width*ratios['right_fraction'],
                'min_y':y,'max_y':y+height*ratios['height_fraction']}}
        if 'subtract_rectangle' in fields:
            if set(fields)!={'subtract_rectangle'} or allowed[ref]!=['vertices']:
                raise ValueError('布尔裁剪不能混合坐标重写，也不能作用于非边界步骤')
            fields={'vertices':subtract_rectangle_vertices(old,scope,ref,fields['subtract_rectangle'])}
        if not isinstance(fields,dict) or not fields or not set(fields).issubset(allowed[ref]):raise ValueError('补丁包含不允许修改的字段')
        seen.add(ref);steps[ref].update(deepcopy(fields))
    if merged==old:raise ValueError('坐标补丁没有修改失败计划')
    # Full construction schema and deterministic execution still validate all
    # coordinate values; no geometry is generated or committed by this merger.
    return merged


def subtract_rectangle_vertices(plan,scope,ref,rectangle):
    """Generic planar CAD difference; never synthesizes a replacement shape."""
    from shapely.geometry import Polygon, LineString, box
    from .cad_construction import ConstructionPoint
    keys=('min_x','min_y','max_x','max_y')
    if not isinstance(rectangle,dict) or set(rectangle)!=set(keys):raise ValueError('裁剪矩形参数不完整')
    values=[rectangle[k] for k in keys]
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>100000 for v in values):
        raise ValueError('裁剪矩形必须使用有限数值，单位与计划一致')
    x,y,X,Y=values
    if x>=X or y>=Y:raise ValueError('裁剪矩形范围无效')
    steps={s['output_ref']:s for s in plan['steps']};step=steps[ref]
    if step.get('op')!='add_polyline' or not step.get('closed'):raise ValueError('布尔裁剪只支持已有闭合多段线')
    def points(s):
        raw=s['vertices'] if s['op']=='add_polyline' else [s['start'],s['end']]
        return [(p.x,p.y) for p in (ConstructionPoint.model_validate(v) for v in raw)]
    polygon=Polygon(points(step));mask=box(x,y,X,Y)
    if not polygon.is_valid or polygon.area<=0:raise ValueError('原边界无效，不能通过裁剪掩盖自相交')
    for protected in scope['protected_geometry_sha256_by_ref']:
        other=steps[protected];xy=points(other)
        if other.get('closed') and xy[0]!=xy[-1]:xy.append(xy[0])
        if mask.intersects(LineString(xy)):raise ValueError('裁剪区域触及受保护路径')
    clipped=polygon.difference(mask)
    if clipped.is_empty or clipped.geom_type!='Polygon' or not clipped.is_valid or clipped.interiors:
        raise ValueError('裁剪会删除、拆分边界或产生内孔，超出单一路径修复范围')
    if clipped.equals(polygon):raise ValueError('裁剪区域没有改变目标边界')
    xy=list(clipped.exterior.coords)[:-1]
    if len(xy)>500:raise ValueError('裁剪结果超过顶点预算')
    return [{'x':float(a),'y':float(b)} for a,b in xy]


def build_local_repair_scope(plan, execution, details):
    details=details or {}
    measured=(details or {}).get('measurements') or {}
    contacts=measured.get('affected_geometries') or []
    passed=measured.get('previously_passed_checks') or []
    if (details.get('authority')!='backend_measured_geometry' or not contacts or not passed
            or any(not isinstance(c,dict) or c.get('status')!='passed' for c in passed)):
        return None
    if plan.get('constraints') or plan.get('free_outline_layout'):
        return None
    steps=plan.get('steps') or [];symbols=execution.get('symbol_table') or {}
    geometries=execution.get('geometries') or [];by_id={g.get('id'):g for g in geometries}
    affected={c.get('geometry_id') for c in contacts}
    refs=[s.get('output_ref') for s in steps]
    if (not steps or len(set(refs))!=len(refs) or None in refs or len(by_id)!=len(geometries)
            or not affected.issubset(by_id) or any(not isinstance(i,int) for i in affected)
            or any(s.get('op') not in {'add_line','add_polyline'} for s in steps)):
        return None
    owned=[];editable={};protected={}
    for step in steps:
        ref=step['output_ref'];ids=symbols.get(ref) or []
        if not ids or any(i not in by_id for i in ids):return None
        owned.extend(ids)
        if affected.intersection(ids):
            editable[ref]=['vertices'] if step['op']=='add_polyline' else ['start','end']
        else:
            protected[ref]=fingerprint([by_id[i] for i in ids])
    if len(set(owned))!=len(owned) or set(owned)!=set(by_id) or not editable:return None
    windows={}
    # A single measured boundary contact that must become two contacts admits
    # a bounded cut window below all protected paths. No shape name or fixed
    # coordinates/proportions are used to infer this feasible parameter range.
    if (measured.get('required_bottom_components')==2 and measured.get('actual_bottom_components')==1
            and len(contacts)==1 and protected and measured.get('probe_y_mm') is not None):
        from .cad_construction import ConstructionPoint
        scale=1000 if plan.get('units')=='m' else 1
        low=min(ConstructionPoint.model_validate(p).y for s in steps if s['output_ref'] in protected
                for p in (s.get('vertices') or [s.get('start'),s.get('end')]))
        span=measured.get('bottom_component_bounds_mm') or []
        if len(span)==1 and span[0][2]>span[0][0] and low>measured['probe_y_mm']/scale:
            owner=next((s['output_ref'] for s in steps if affected.issubset(symbols[s['output_ref']])),None)
            if owner in editable and editable[owner]==['vertices']:
                windows[owner]={'bounds_in_plan_units':[span[0][0]/scale,measured['probe_y_mm']/scale,span[0][2]/scale,low],
                    'origin':'measured_contact_span_and_protected_path_clearance','units':plan.get('units')}
    failure_type=str(details.get('code') or details.get('failure_type') or details.get('kind') or 'geometry_validation')
    return {'schema':'cad.local-repair-scope.v1','authority':'backend_measured_geometry',
            'failure_type':failure_type,'retry_limit':1,
            'source_plan_sha256':fingerprint(plan),'step_order':refs,
            'editable_fields_by_ref':editable,'protected_geometry_sha256_by_ref':protected,
            'cut_windows_by_ref':windows,
            'policy':'Only declared coordinate fields may change. Preserve all other steps, identities, order and global fields.'}


def validate_local_repair(before, after):
    scope=(((before.get('construction_error') or {}).get('details') or {}).get('local_repair_scope'))
    if not scope:return {'enforced':False,'verified':True,'reason':'no_verified_local_scope'}
    old=before.get('plan') or before.get('rejected_plan') or {};new=after.get('plan') or {}
    def rejected(reason):return {'enforced':True,'verified':False,'reason':reason,
                                 'failure_type':scope.get('failure_type','geometry_validation'),
                                 'retry_limit':scope.get('retry_limit',1)}
    if fingerprint(old)!=scope['source_plan_sha256']:return rejected('source_plan_changed')
    if {k:v for k,v in old.items() if k!='steps'}!={k:v for k,v in new.items() if k!='steps'}:
        return rejected('global_plan_fields_changed')
    old_steps=old.get('steps') or [];new_steps=new.get('steps') or []
    if [s.get('output_ref') for s in new_steps]!=scope['step_order']:return rejected('step_identity_or_order_changed')
    changed_fields_by_ref={}
    for a,b in zip(old_steps,new_steps):
        editable=set(scope['editable_fields_by_ref'].get(a['output_ref']) or [])
        if {k:v for k,v in a.items() if k not in editable}!={k:v for k,v in b.items() if k not in editable}:
            return rejected('protected_step_fields_changed:'+a['output_ref'])
        changed={k:{'before':a.get(k),'after':b.get(k)} for k in editable
                 if a.get(k)!=b.get(k)}
        if changed:
            changed_fields_by_ref[a['output_ref']]=changed
    if after.get('status')!='ready':
        return {'enforced':True,'verified':False,'reason':'repair_trial_not_ready',
                'plan_fields_preserved':True,'changed_fields_by_ref':changed_fields_by_ref}
    trial=after.get('trial_result') or {};by_id={g.get('id'):g for g in trial.get('geometries') or []}
    for ref,expected in scope['protected_geometry_sha256_by_ref'].items():
        ids=(trial.get('symbol_table') or {}).get(ref) or []
        if not ids or any(i not in by_id for i in ids) or fingerprint([by_id[i] for i in ids])!=expected:
            return rejected('protected_geometry_changed:'+ref)
    return {'enforced':True,'verified':True,'protected_step_refs':sorted(scope['protected_geometry_sha256_by_ref']),
            'editable_step_refs':sorted(scope['editable_fields_by_ref']),
            'changed_fields_by_ref':changed_fields_by_ref,
            'changed_step_refs':sorted(changed_fields_by_ref)}
