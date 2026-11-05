"""Conservative, source-bound scalar requirements; never infer missing scope.

This is a partial executable view over the immutable source ledger. Unknown
phrasing remains unresolved rather than becoming a whole-drawing dimension.
"""
import math
import hashlib
import json
import re

from .cad_creation_intent import local_creation_objects


def project_requirement_state(project):
    """Derive the persisted construction gate from committed requirement data."""
    requirements = project.get('requirements') or {}
    missing = list(dict.fromkeys(str(v).strip() for v in
        project.get('missing_parameters') or [] if str(v).strip()))
    contract = requirements.get('requirement_contract') or {}
    conflicts = contract.get('conflicts') or []
    snapshot = {'requirements': requirements, 'constraints': project.get('constraints') or {},
                'missing': missing, 'conflicts': conflicts}
    return {'schema': 'cad.requirement-state.v1',
            'status': 'conflicted' if conflicts else 'clarifying' if missing else 'ready',
            'missing': missing, 'conflicts': conflicts,
            'revision': hashlib.sha256(json.dumps(snapshot, sort_keys=True,
                ensure_ascii=False).encode('utf-8')).hexdigest()}

FIELDS={'宽':'width','宽度':'width','高':'height','高度':'height','半径':'radius',
        '外接圆半径':'circumradius','外径':'diameter','直径':'diameter','边长':'side_length',
        '宽高':'width_height','长宽':'width_height'}
PATTERN=re.compile(r'(?P<qualifier>最大|最小|整体|总)?(?P<field>外接圆半径|宽度|高度|宽高|长宽|外径|直径|半径|边长|宽|高)'
    r'\s*(?P<relation>改为|改成|调整为|变为|均为|都为|均|都|为|是|不超过|至多|至少|不小于|=|：|:)?'
    r'\s*(?P<value>[-+]?\d+(?:\.\d+)?)\s*(?P<unit>毫米|厘米|米|mm|cm|m)(?![a-zA-Z])',re.I)


def requirement_contract(sources):
    subjects=[];declarations=[];normalized_sources=[]
    for source in sources:
        declared=[]
        clauses=[]
        for clause in re.split(r'[，,。；;\n]',source['text']):
            clause=clause.strip()
            if clause:
                clauses.append({'text':clause,'subjects':[]})
            for name in local_creation_objects(clause):
                name = re.sub(r'[（(][A-Za-z][A-Za-z\s-]*[）)]', '', name).strip()
                if (name and len(name)<=32 and not re.search(r'[：:（(]|图纸|方案',name)
                    and name not in declared):declared.append(name)
            heading=re.match(r'\s*([^：:]{1,24})[：:]\s*',clause)
            if heading and (PATTERN.match(clause,heading.end()) or
                            re.match(r'(?:圆弧|圆|矩形|线段)(?:[，,\s]|$)',clause[heading.end():])):
                declared.append(heading[1].strip())
        for clause in clauses:
            if not declared and not PATTERN.search(clause['text']):
                description = re.sub(r'[（(][A-Za-z][A-Za-z\s-]*[）)]', '', clause['text']).strip()
                if (len(description)<=32 and re.search(r'(?:轮廓|曲线|线|图形|图案)$',description)
                        and not re.search(r'[:：\d]|控制点|顶点|端点', description)):
                    declared.append(description)
            clause['subjects']=[name for name in declared if name in clause['text']]
        normalized_sources.append({'source_id':source.get('source_id'),'text':source['text'],
            'subjects':declared,'clauses':clauses})
        declarations.append(declared)
    facts=[];effective={}
    for source,declared in zip(sources,declarations):
        for name in declared:
            if name not in subjects:subjects.append(name)
        text=source['text']
        for index,match in enumerate(PATTERN.finditer(text)):
            left=max(text.rfind(c,0,match.start()) for c in '，,。；;\n')+1
            prefix=text[left:match.start()].strip()
            if re.search(r'例如|示例|比如|假设|如果|或者|还是|不要|不是|不需要|不用',prefix):continue
            targets=[];scope='unresolved'
            normalized_prefix=PATTERN.sub('',prefix).strip(' 、')
            normalized_prefix=re.sub(r'^(?:请把|请将|把|将)','',normalized_prefix).strip()
            named=[]
            for name in subjects:
                alias=re.sub(r'(?:的)?轮廓$','',re.sub(r'^(?:大写|小写)','',name))
                if any(normalized_prefix.startswith(label) and re.fullmatch(
                    r'(?:的|整体|外包|尺寸|调整|设置|改)*',normalized_prefix[len(label):]) for label in {name,alias} if label):
                    named.append(name)
            if len(named)==1:
                targets=named;scope='explicit_subject'
            elif not named and re.fullmatch(r'(?:它们|两者|各自|每个(?:图形|对象)?)(?:的)?',normalized_prefix):
                targets=subjects;scope='explicit_shared'
            elif not named and len(subjects)==1 and re.fullmatch(r'(?:它的|整体|图形的|对象的)?',normalized_prefix):
                targets=subjects;scope='single_subject'
            colon=re.fullmatch(r'([^：:]{1,24})[：:]\s*',prefix)
            if colon:targets=[colon[1].strip()];scope='explicit_subject'
            operator=('lte' if match['qualifier']=='最大' or match['relation'] in {'不超过','至多'} else
                      'gte' if match['qualifier']=='最小' or match['relation'] in {'至少','不小于'} else 'eq')
            value=float(match['value'])*{'毫米':1,'厘米':10,'米':1000,'mm':1,'cm':10,'m':1000}[match['unit'].lower()]
            valid=math.isfinite(value) and value>0
            field=FIELDS[match['field']]
            if (field == 'width' and scope == 'single_subject'
                    and '整体' not in normalized_prefix
                    and re.search(r'(?:两|[二三四五六七八九]|\d+)\s*(?:条|个)?\s*(?:臂|分支|支臂)', text)):
                # The width of an articulated passage/branch is not its
                # overall bounding-box width. Keep the evidence unbound
                # until a component/relationship verifier can measure it.
                targets=[];scope='unresolved'
            fields=['width','height'] if field=='width_height' else [field]
            for axis in fields:
                for target in targets or [None]:
                    fact={'fact_id':f"{source['source_id']}:scalar-{index+1}:{axis}:{target or '?'}",
                        'origin':'user','source_id':source['source_id'],'subject':target,'field':axis,
                        'operator':operator,'value_mm':round(value,9) if valid else None,
                        'evidence':{'start':match.start(),'end':match.end(),'text':text[match.start():match.end()]},
                        'binding':scope,'status':'effective' if target and valid else 'unresolved' if valid else 'invalid'}
                    if target and valid:
                        key=(target,axis,operator)
                        if key in effective:
                            effective[key]['status']='superseded';effective[key]['superseded_by']=fact['fact_id']
                        effective[key]=fact
                    facts.append(fact)
    conflicts=[]
    pairs={(subject,field) for subject,field,_ in effective}
    for subject,field in sorted(pairs):
        values={op:effective.get((subject,field,op)) for op in ('eq','lte','gte')}
        eq,upper,lower=(values[op] for op in ('eq','lte','gte'))
        if ((eq and upper and eq['value_mm']>upper['value_mm']) or
            (eq and lower and eq['value_mm']<lower['value_mm']) or
            (lower and upper and lower['value_mm']>upper['value_mm'])):
            conflicts.append({'subject':subject,'field':field,'fact_ids':[v['fact_id'] for v in values.values() if v],
                'reason':'incompatible_explicit_bounds'})
    unresolved=[f['fact_id'] for f in facts if f['status']=='unresolved']
    return {'schema':'cad.requirement-contract.v1','subjects':subjects,'facts':facts,
        'sources':normalized_sources,'unresolved_fact_ids':unresolved,
        'raw_requirement_text':'\n'.join(s['text'] for s in sources),
        'effective_fact_ids':[f['fact_id'] for f in facts if f['status']=='effective'],
        'conflicts':conflicts,'consistent':not conflicts and not any(f['status']=='invalid' for f in facts),
        'coverage':{'status':'partial','supported_fields':sorted(set(FIELDS.values())-{'width_height'}),
                    'normalized_fields':['objects','raw_text','clauses','scoped_scalar_facts','unresolved_facts'],
                    'note':'未绑定的尺寸不自动归给整体；位置、数量和连接保留原文、分句及证据账本中'}}
