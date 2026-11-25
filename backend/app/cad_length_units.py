"""Shared length factors with explicit output units and legacy table types.

Parsing, missing-unit policy and source conflicts belong to callers. A fresh
table prevents one caller from changing another caller's unit definitions.
"""

_TO_MM={'毫米':1,'厘米':10,'米':1000,'mm':1,'cm':10,'m':1000}
_TO_M={'毫米':.001,'厘米':.01,'米':1,'mm':.001,'cm':.01,'m':1}


def length_factors(target_unit, *, float_values=False, include_gongfen=False):
    if target_unit=='mm':factors=dict(_TO_MM)
    elif target_unit=='m':factors=dict(_TO_M)
    else:raise ValueError('目标长度单位必须显式为mm或m')
    if float_values:factors={key:float(value) for key,value in factors.items()}
    if include_gongfen:factors['公分']=factors['厘米']
    return factors


def planning_unit_contract(text):
    """Source-local values for either supported plan unit; never rescale CAD."""
    import re
    from .cad_source_acceptance import source_texts, P
    from .cad_requirement_contract import requirement_contract
    sources=[{'source_id':f'user:{i}','text':s} for i,s in enumerate(source_texts(text))]
    contract=requirement_contract(sources)
    result={'schema':'cad.planning-unit-contract.v1','plan_units':['m','mm'],
            'consistent':contract['consistent'],'conflicts':contract['conflicts'],
            'scalars':[],'points':[],'unresolved_coordinate_sources':[]}
    from .cad_vertex_acceptance import open_straight_path_requirements
    path=open_straight_path_requirements(text)
    if path.get('coverage')=='complete':
        result['ordered_path']={'source_text':path['original_text'],'segment_count':path['count'],
            'start_plan_values':{'mm':path['start_mm'],'m':[v/1000 for v in path['start_mm']]},
            'segments':[{'length_plan_values':{'mm':r['length_mm'],'m':r['length_mm']/1000},
                'angle_deg':r['angle_deg'],'angle_reference':'world_x' if i==0 else 'previous_segment'}
                for i,r in enumerate(path['requirements'])]}
    for fact in contract['facts']:
        if fact['status']!='effective':continue
        value=fact['value_mm']
        result['scalars'].append({'source_id':fact['source_id'],'evidence':fact['evidence'],
            'subject':fact['subject'],'field':fact['field'],'operator':fact['operator'],
            'binding':fact['binding'],'plan_values':{'m':value/1000,'mm':value}})
    for source in sources:
        units=re.findall(r'坐标单位(?:为|是|[:：])?\s*(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])',source['text'],re.I)
        pattern=r'(圆心|中心|左下角|底边左端|底边从|起点|终点)(?:位于|在|为|是)?\s*'+P
        matches=list(re.finditer(pattern,source['text']))
        if not matches:continue
        scales={length_factors('mm')[u.lower()] for u in units}
        if len(scales)!=1:
            result['unresolved_coordinate_sources'].append(source['source_id']);continue
        scale=scales.pop()
        for match in matches:
            values=[float(match[i])*scale for i in (2,3)]
            result['points'].append({'source_id':source['source_id'],'role':match[1],
                'evidence':{'start':match.start(),'end':match.end(),'text':match[0]},
                'plan_values':{'m':[v/1000 for v in values],'mm':values}})
    return result
