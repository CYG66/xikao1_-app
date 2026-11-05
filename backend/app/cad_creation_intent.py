"""Sentence-local creation scope, independent of supported geometry names."""
import re


def has_compound_primitives(message: str) -> bool:
    """Decline partial primitive parsers for explicitly composite drawings.

    This recognizes geometry vocabulary, not everyday object names, and
    never constructs geometry or infers an unstated component count.
    """
    if len(local_creation_objects(message)) >= 2:
        return True
    if re.search(r"墙体|屋顶|房屋|门窗|灯箱|表盘|刻度|眼睛|嘴巴|灯珠", message):
        return True
    kinds = sum(bool(re.search(pattern, message)) for pattern in (
        r"矩形|长方形|正方形", r"圆(?!弧)|圆形", r"圆弧", r"三角形",
        r"线段|刻度线|时针|分针", r"五角星|多边形",
    ))
    repeated=bool(re.search(r'(?:两|[二三四五六七八九十]|[2-9])(?:条|个|块|组)?[^，。；;]{0,12}(?:矩形|圆形|圆|线段|多边形)',message)
        and re.search(r'交叉|相交|叠加|组合|拼接|阵列|各|并排',message))
    return kinds >= 2 or repeated


def local_creation_objects(message: str) -> list[str]:
    source = re.sub(r"^\s*新建\s*CAD\s*图纸[：:]\s*", "", message.strip(), flags=re.I)
    # Do not split a creation sentence at the comma inside a coordinate pair,
    # e.g. ``画一条线段从(0,0)到(5,3)``.  The old first-comma split reduced the
    # head to ``画一条线段从(0`` and made the deterministic route believe that
    # no local creation object had been requested.  Split only at top-level
    # clause punctuation; commas inside (), [], or Chinese brackets belong to
    # the geometry expression.
    depth = 0
    cut = len(source)
    opening = "([{（【"
    closing = ")] }）】".replace(" ", "")
    for index, char in enumerate(source):
        if char in opening:
            depth += 1
        elif char in closing:
            depth = max(0, depth - 1)
        elif depth == 0 and char in "，,。；;\n":
            cut = index
            break
    head = source[:cut]
    if not re.match(r"^(?:请|帮我|请帮我|给我|麻烦)?\s*(?:生成|创建|新建|绘制|画出|画|设计)", head):
        return []
    if re.search(r"它|这个|那个|刚才|之前|上一|当前|已有|原有|再|相同|一样", head):
        return []
    body = re.sub(r"^(?:请|帮我|请帮我|给我|麻烦)?\s*(?:生成|创建|新建|绘制|画出|画|设计)\s*", "", head)
    return [name for part in re.split(r"和|与|及", body)
            if (name := re.sub(r"^[一二两三四五六七八九十\d]+\s*(?:个|条|朵|张|颗|幅|块)\s*", "", part.strip()))]


def has_local_plural_reference(message: str) -> bool:
    objects = local_creation_objects(message)
    # Only discharge plural references whose antecedents are explicitly in
    # this sentence. Mixed old/new targets still need historical resolution.
    return (len(objects) >= 2 and "它们" in message
            and not re.search(r"刚才|之前|上一|这个|那个|已有|原有|当前的", message))
