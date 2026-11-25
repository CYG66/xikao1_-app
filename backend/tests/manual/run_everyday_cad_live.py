"""Real DeepSeek through the production chat HTTP handler, isolated per case.

Artifacts retain every request/response. No shape generator or model mock.
"""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys


def load_local_deepseek_key():
    if os.environ.get('DEEPSEEK_API_KEY'):
        return
    credential=Path(__file__).resolve().parents[2] / '.local-ai-test' / 'deepseek-api-key.clixml'
    if not credential.exists():
        return
    command=("$s=Import-Clixml -LiteralPath '" + str(credential).replace("'", "''") + "'; "
             "[Console]::Write(([System.Net.NetworkCredential]::new('', $s)).Password)")
    try:
        value=subprocess.check_output(['powershell','-NoProfile','-NonInteractive','-Command',command], text=True).strip()
    except Exception:
        return
    if value and value != 'System.Security.SecureString':
        os.environ['DEEPSEEK_API_KEY']=value


load_local_deepseek_key()

CASES = {
    "heart_star": ["生成一个爱心和一个五角星，爱心在左，五角星在右，它们的长宽均为5米，间距为8m"],
    "traffic_light": [
        "新建CAD图纸，画一个交通信号灯的正视轮廓：一个竖直矩形灯箱，内部从上到下排列三个等大的圆，三个圆心在灯箱竖直中线上。只画轮廓，不要文字和颜色。",
        "灯箱宽1米、高3米，左下角为(0,0)；三个圆半径均为0.35米，圆心从上到下分别为(0.5,2.4)、(0.5,1.5)、(0.5,0.6)，坐标单位米。",
        "确认需求并生成CAD候选，只预览，不执行小车。",
    ],
    "clock": [
        "新建CAD图纸，画一个简化时钟：圆形表盘，十二根均匀分布的短刻度线，以及表示三点整的时针和分针。不画数字，不画秒针。",
        "表盘圆心(0,0)，半径1米；12根刻度线沿径向从半径0.9米到1米，间隔30度。时针从圆心向右长0.5米，分针从圆心向上长0.75米。",
        "确认需求并生成CAD候选，只预览，不执行小车。",
    ],
    "house": [
        "新建CAD图纸，画一个简笔房屋正视图：矩形墙体、上方三角形屋顶、一个矩形门和左右各一个矩形窗。所有部件都要画出来，不画文字。",
        "单位米：墙体左下角(0,0)，宽6高4；屋顶三个顶点(0,4)、(3,6)、(6,4)；门左下角(2.5,0)，宽1高2；左窗左下角(0.75,2)，右窗左下角(4.25,2)，两个窗均宽1高1。",
        "确认需求并生成CAD候选，只预览，不执行小车。",
    ],
}


def verify(case, geometries):
    """Source-derived numeric oracles; no model labels/assertions used."""
    def xy(p): return (p["x"], p["y"])
    if case == "heart_star":
        checks=[{"name":"two_closed_outlines","passed":len(geometries)==2 and all(g.get("closed") for g in geometries)}]
        if len(geometries)!=2:return checks
        ordered=sorted(geometries,key=lambda g:min(p["x"] for p in g["vertices"]))
        bounds=[]
        for i,g in enumerate(ordered):
            xs=[p["x"] for p in g["vertices"]];ys=[p["y"] for p in g["vertices"]]
            bounds.append((min(xs),max(xs),min(ys),max(ys)))
            checks.append({"name":f"outline_{i}_5000_by_5000mm","passed":abs(max(xs)-min(xs)-5000)<.5 and abs(max(ys)-min(ys)-5000)<.5})
        checks.append({"name":"edge_gap_8000mm","passed":abs(bounds[1][0]-bounds[0][1]-8000)<.5})
        star=ordered[1]["vertices"]
        cx=sum(p["x"] for p in star)/len(star);cy=sum(p["y"] for p in star)/len(star)
        radii=[math.hypot(p["x"]-cx,p["y"]-cy) for p in star]
        peaks=sum(r>radii[i-1] and r>radii[(i+1)%len(radii)] for i,r in enumerate(radii))
        checks.append({"name":"five_star_tips","passed":len(star)==10 and peaks==5})
        heart=ordered[0]["vertices"];b=bounds[0];mx=(b[0]+b[1])/2
        upper=[p for p in heart if p["y"]>b[2]+.65*(b[3]-b[2])]
        checks.append({"name":"heart_two_upper_lobes","passed":any(p["x"]<mx-500 for p in upper) and any(p["x"]>mx+500 for p in upper) and len(heart)>20})
        return checks
    def polygon(points):
        return lambda g: g.get("type") == "polyline" and g.get("closed") and len(g.get("vertices", [])) == len(points) and all(
            any(math.dist(p, xy(q)) < .5 for q in g["vertices"]) for p in points)
    def rect(x,y,w,h): return polygon([(x,y),(x+w,y),(x+w,y+h),(x,y+h)])
    def circle(x,y,r):
        return lambda g: g.get("type") == "circle" and math.dist(xy(g["center"]),(x,y)) < .5 and abs(g["radius"]-r) < .5
    def line(a,b):
        def matches(g):
            pts = [g["start"],g["end"]] if g.get("type") == "line" else g.get("vertices", []) if not g.get("closed") else []
            return len(pts)==2 and any(math.dist(xy(pts[0]),p)<.5 and math.dist(xy(pts[1]),q)<.5 for p,q in [(a,b),(b,a)])
        return matches
    expected = []
    if case == "traffic_light":
        expected = [rect(0,0,1000,3000)] + [circle(500,y,350) for y in (2400,1500,600)]
    elif case == "house":
        expected = [rect(0,0,6000,4000),polygon([(0,4000),(3000,6000),(6000,4000)]),rect(2500,0,1000,2000),rect(750,2000,1000,1000),rect(4250,2000,1000,1000)]
    elif case == "clock":
        expected = [circle(0,0,1000),line((0,0),(500,0)),line((0,0),(0,750))]
        for i in range(12):
            a=i*math.tau/12
            expected.append(line((900*math.cos(a),900*math.sin(a)),(1000*math.cos(a),1000*math.sin(a))))
    remaining = list(geometries)
    checks = [{"name":"exact_component_count", "passed":len(remaining)==len(expected),"actual":len(remaining),"expected":len(expected)}]
    for i, predicate in enumerate(expected):
        match = next((j for j,g in enumerate(remaining) if predicate(g)),None)
        checks.append({"name":f"measured_component_{i}","passed":match is not None})
        if match is not None: remaining.pop(match)
    return checks


def run(case, root):
    folder = root / case
    folder.mkdir(parents=True, exist_ok=True)
    history, project_id, turns = [], None, []
    worker = Path(__file__).with_name("cad_widget_live_worker.py")
    for index, message in enumerate(CASES[case], 1):
        body = {"message": message, "mode": "advanced", "conversation_id": f"everyday-{case}", "history": history}
        if project_id:
            body["project_id"] = project_id
        completed = subprocess.run([sys.executable, str(worker), "--output", str(folder)],
            input=json.dumps({"operation": "chat", "step": index, "body": body}, ensure_ascii=False),
            capture_output=True, text=True, encoding="utf-8", timeout=480)
        if completed.returncode:
            (folder / f"error-{index}.txt").write_text(completed.stderr, encoding="utf-8")
            raise RuntimeError(f"{case} turn {index}: {completed.stderr[-1200:]}")
        result = json.loads(completed.stdout)
        for tool in result.get("tool_results", []):
            project_id = tool.get("project_id") or (tool.get("project") or {}).get("id") or project_id
        project_id = (result.get("project") or {}).get("id") or project_id
        history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": result.get("message", "")}])
        def has_structured_marker(value):
            if isinstance(value, dict):
                if isinstance(value.get("construction_interpretation"), dict):
                    return True
                if isinstance(value.get("construction_record"), dict):
                    return True
                return any(has_structured_marker(item) for item in value.values())
            if isinstance(value, list):
                return any(has_structured_marker(item) for item in value)
            return False

        structured = has_structured_marker(result)
        turns.append({"message": message, "project_id": project_id, "result": result,
                      "structured_construction_attempted": structured})
        print(json.dumps({"case": case, "turn": index, "ok": result.get("ok"), "message": result.get("message"), "project_id": project_id}, ensure_ascii=False), flush=True)
    (folder / "flow.json").write_text(json.dumps(turns, ensure_ascii=False, indent=2), encoding="utf-8")
    projects_path = folder / "projects.json"
    projects = json.loads(projects_path.read_text(encoding="utf-8"))["projects"] if projects_path.exists() else []
    project = next((p for p in projects if p["id"]==project_id), {})
    variants = project.get("variants") or []
    checks = verify(case, variants[-1].get("geometries",[]) if variants else [])
    non_empty_ids={t["project_id"] for t in turns if t["project_id"]}
    checks.append({"name":"same_project_across_turns","passed":len(non_empty_ids)<=1})
    checks.append({"name":"candidate_and_preview_returned","passed":bool(variants) and bool(result.get("preview_paths"))})
    checks.append({"name":"structured_construction_attempted","passed":any(
        t.get("structured_construction_attempted") for t in turns)})
    validation = {"case":case,"passed":all(c["passed"] for c in checks),"checks":checks,
                  "scope":"production HTTP handler and real DeepSeek; UI and deployment not tested"}
    (folder/"validation.json").write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(validation,ensure_ascii=False),flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    args = parser.parse_args()
    for case in args.cases:
        run(case, Path(args.output).resolve())
