import sys,json
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from tests.manual.run_user_cad_corpus import make_creation,make_edit,dump
root=Path(sys.argv[1] if len(sys.argv)>1 else r'D:\xikao\.local-ai-test\unsatisfied-relations-20261105');root.mkdir(parents=True,exist_ok=True)
setups=[('B13','C9','新建CAD图纸。左圆：圆心(0,0)，半径1米；右圆：圆心(3,1)，半径1米；两个独立圆形，坐标单位米。','把两个圆形水平居中对齐','C9'),('B15','A11','新建CAD图纸。圆形：圆心(0,3)，半径1米；矩形：左下角(-1.5,-1)，宽3米高2米；两个独立图形，坐标单位米。','让矩形和圆形一样大','A12')]
reports=[]
for case,base,prompt,edit,oracle in setups:
 report=make_creation(base,prompt,root,oracle)
 result=make_edit(case,edit,root,{base:report},base)
 reports.append(result)
dump(root/'summary.json',{'reports':reports})
