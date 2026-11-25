"""Recognize explicit preview-only intent, preserving every other source clause."""
import re


def partition_preview_intent(source):
    evidence=[]
    # Restrict to a complete sentence, never consume geometric suffixes.
    pattern=r'(?P<boundary>^|[。；;\n])(?P<intent>\s*只生成预览[，,]不执行小车)(?=[。；;\n]|$)'
    def consume(match):
        evidence.append({'kind':'preview_only','start':match.start('intent'),'end':match.end('intent'),
                         'text':match['intent'],'scope':'delivery_intent_only'})
        return match['boundary']
    return re.sub(pattern,consume,source),evidence
def partition_outline_scope(text, nouns, *, source=None):
    """Extract only measurable output restrictions for an explicit noun set."""
    import re
    evidence=[];source=text if source is None else source;cursor=0
    pattern=(r'(?:只要|只保留|仅保留|只画)(?P<subject>'+ '|'.join(re.escape(n) for n in nouns)
             +r')(?:的)?(?:轮廓|外边界)|(?:不要|不加)(?:任何|尺寸)?标注|不标尺寸')
    for m in re.finditer(pattern,text):
        start=source.find(m[0],cursor)
        if start<0:raise ValueError('output restriction lost original source')
        cursor=start+len(m[0])
        evidence.append({'kind':'outline_only' if m['subject'] else 'no_annotations','subject':m['subject'],
                         'text':m[0],'start':start,'end':cursor,'source_text':source})
    return re.sub(pattern,' ',text),evidence


def verify_output_restrictions(geometries, intents):
    """No annotation may be hidden by the geometry-only measurement filter."""
    from .cad_structure_contract import StructureContractError
    if not intents:return []
    annotations=[g.get('id') for g in geometries if g.get('selected') is not False and
                 (g.get('role')=='annotation' or g.get('type') in {'text','mtext','dimension','leader'})]
    if annotations:raise StructureContractError('原文要求仅轮廓或无标注，但存在标注图元',{'geometry_ids':annotations})
    return [{'field':'no_visible_annotations','status':'passed','source_evidence':intents}]



