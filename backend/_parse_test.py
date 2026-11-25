import sys, json
sys.path.insert(0, r"D:\xikao\xikao1_-app\backend")
from app.incremental_cad import parse_incremental_edit

OUT = r"C:\Users\kira-\AppData\Local\Temp\xline_parse_test.log"
def out(s):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(str(s) + "\n")

messages = [
    "在爱心中心右侧6m处规划一个同样的爱心 图形",
    "在当前爱心中心右侧6米处再画一个相同的爱心",
    "把这个爱心向右移动6米",
    "复制爱心到右侧6米处",
    "在右侧6m处添加一个同样的爱心",
    "画一个同样的爱心放在右侧6m处",
]
for m in messages:
    try:
        edit = parse_incremental_edit(m)
        out("msg=%s\n => %s" % (m, json.dumps(edit, ensure_ascii=False, default=str)))
    except Exception as e:
        out("msg=%s\n => ERROR %r" % (m, e))
out("done")
