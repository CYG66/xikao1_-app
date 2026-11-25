"""Real model + isolated persistence; replay responses separately in Flutter."""
import argparse
import json
import math
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tests.manual import run_complex_cad_live as probe


def flag_checks(case, variant, paths):
    # Independent from production contract and its matching implementation.
    # Official 30x20 grid, origin at lower left, unit 100mm at chosen 3x2m.
    geometries=variant.get("geometries") or []
    checks=[]
    def check(name,passed,observed=None):
        checks.append({"name":name,"passed":bool(passed),"observed":observed})
    check("one_field_and_five_symbols",len(geometries)==6)
    rectangles=[g for g in geometries if len(g.get("vertices") or [])==4]
    check("one_rectangle",len(rectangles)==1)
    if len(rectangles)!=1:return checks
    points=rectangles[0]["vertices"]
    x0=min(p["x"] for p in points);y0=min(p["y"] for p in points)
    check("field_3000_by_2000mm",abs(max(p["x"] for p in points)-x0-3000)<.1 and abs(max(p["y"] for p in points)-y0-2000)<.1)
    symbols=[g for g in geometries if g is not rectangles[0]]
    grid=[(5,15,3),(10,18,1),(12,16,1),(12,13,1),(10,11,1)]
    used=set()
    for index,(gx,gy,radius) in enumerate(grid):
        cx,cy=x0+100*gx,y0+100*gy
        candidates=[]
        for j,g in enumerate(symbols):
            pts=g.get("vertices") or []
            if j in used or len(pts)!=10:continue
            c=(sum(p["x"] for p in pts)/10,sum(p["y"] for p in pts)/10)
            if math.dist(c,(cx,cy))<.2:candidates.append((j,g,pts))
        check(f"symbol_{index}_center_and_ten_vertices",len(candidates)==1)
        if len(candidates)!=1:continue
        j,g,pts=candidates[0];used.add(j)
        expected_angle=math.pi/2 if index==0 else math.atan2(15-gy,5-gx)
        expected=[]
        for k in range(10):
            r=100*radius*(1 if k%2==0 else math.sin(math.pi/10)/math.sin(3*math.pi/10))
            expected.append((cx+r*math.cos(expected_angle+k*math.pi/5),cy+r*math.sin(expected_angle+k*math.pi/5)))
        check(f"symbol_{index}_radius_shape_orientation",g.get("closed") and all(
            any(math.dist(p,(q["x"],q["y"]))<.2 for q in pts) for p in expected))
    check("preview_available",bool(paths))
    return checks


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",required=True)
    args=parser.parse_args();output=Path(args.output).resolve()
    prompt="生成一个五星红旗，大小按照目前标准的中国红旗"
    followup="实际宽度3米、高度2米，先只生成CAD预览，不执行小车动作。"
    probe.corpus=lambda:{"FLAG":prompt}
    probe.FOLLOWUPS["FLAG"]=followup
    probe.geometry_checks=flag_checks
    probe.run_case("FLAG",output)
    report=json.loads((output/"report.json").read_text(encoding="utf-8"))
    (output/"ui-fixture.json").write_text(json.dumps({"messages":[t["message"] for t in report["turns"]]},ensure_ascii=False),encoding="utf-8")
