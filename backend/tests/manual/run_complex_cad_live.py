"""Manual production-pipeline corpus probe. Real provider; isolated stores.

No model outputs or generation routes are mocked. Each case runs in its own
process so project selection, user configuration and persistence cannot leak.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
SOURCE = Path(r"D:\xikao\文生文修CAD测试语料.md")
FOLLOWUPS = {
    "C1": "坐标单位为米，使用原文给出的四个控制点。",
    "C2": "坐标单位为米，使用原文给出的五个控制点，要求平滑闭合。",
    "C3": "总宽度2米，总高度3米，两侧竖直段高2米，顶部半圆半径1米，底边闭合。",
    "C4": "坐标单位为米，使用原文给出的三个顶点，闭合。",
    "C5": "正五边形，外接圆半径1.5米。",
    "C6": "宽度5米，高度5米。",
    "C7": "矩形宽4米、高2米，四个圆半径均为0.5米，圆心分别位于矩形四个顶点。",
    "C8": "3行4列，各矩形宽1米、高0.6米；相邻中心行距1.2米、列距1.5米。",
    "C9": "两个圆半径均为1米，两圆心相距1.5米，水平排列，相交。",
    "C10": "爱心宽4米高4米；五角星外接圆半径2米；两者中心水平相距6米。",
    "C11": "总长5米，振幅0.5米，相邻波峰间距1米，共5个周期。",
    "C12": "坐标单位为米，从原点开始，逆时针旋转3圈，半径从0线性增长到2米。",
}


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def corpus():
    return dict(re.findall(r"^\| (C\d+) \| ([^|]+) \|", SOURCE.read_text(encoding="utf-8"), re.M))


def geometry_checks(case, variant, paths):
    """Checks derived from corpus requirements, not the model's assertions."""
    from app.cad_construction import construction_geometry_bounds
    geometries = variant.get("geometries") or []
    checks = []
    def check(name, passed, observed=None):
        checks.append({"name": name, "passed": bool(passed), "observed": observed})
    def near(a, b, tol=2):
        return abs(a-b) <= tol
    def vertices(g):
        points=g.get("vertices") or g.get("control_points") or []
        if g.get('type')=='polyline' and g.get('closed') and len(points)>3:
            # Subdividing a straight edge does not change the polygon. Compare
            # geometric corners rather than the model's tessellation count.
            result=[]
            for i,p in enumerate(points):
                a=points[i-1];b=points[(i+1)%len(points)]
                ux,uy=p['x']-a['x'],p['y']-a['y'];vx,vy=b['x']-p['x'],b['y']-p['y']
                if abs(ux*vy-uy*vx)>1e-6*max(1,math.hypot(ux,uy)*math.hypot(vx,vy)) or ux*vx+uy*vy<0:
                    result.append(p)
            return result
        return points
    def center(g):
        if g.get("center"):
            return g["center"]["x"], g["center"]["y"]
        b = construction_geometry_bounds([g])
        return (b["min_x"]+b["max_x"])/2, (b["min_y"]+b["max_y"])/2
    check("nonempty_geometry_and_preview", bool(geometries and paths))
    if not geometries:
        return checks
    bounds = construction_geometry_bounds(geometries)
    width, height = bounds["max_x"]-bounds["min_x"], bounds["max_y"]-bounds["min_y"]
    circles = [g for g in geometries if g.get("type") == "circle"]
    polylines = [g for g in geometries if g.get("type") == "polyline"]
    if case == "C1":
        expected = [(0,0), (1000,3000), (3000,3000), (4000,0)]
        actual = [(p["x"], p["y"]) for p in vertices(geometries[0])]
        check("cubic_bezier_four_exact_control_points", len(geometries)==1 and geometries[0].get("degree")==3 and len(actual)==4 and all(near(x,a) and near(y,b) for (x,y),(a,b) in zip(actual,expected)), actual)
    elif case == "C2":
        actual = [(p["x"],p["y"]) for p in vertices(geometries[0])]
        expected = [(0,0),(1000,2000),(2000,-1000),(3000,2000),(4000,0)]
        check("closed_cubic_spline_exact_control_points", len(geometries)==1 and geometries[0].get("type")=="spline" and geometries[0].get("closed") is True and geometries[0].get("degree")==3 and len(actual)==5 and all(near(x,a) and near(y,b) for (x,y),(a,b) in zip(actual,expected)), actual)
        sampled = (paths[0].get("points") or []) if paths else []
        sampled = [tuple(p[:2]) for p in sampled if isinstance(p,list) and len(p)>=2]
        if len(sampled)>2 and math.dist(sampled[0],sampled[-1])<1e-8:sampled.pop()
        angle=180.0
        if len(sampled)>2:
            a=(sampled[0][0]-sampled[-1][0],sampled[0][1]-sampled[-1][1])
            b=(sampled[1][0]-sampled[0][0],sampled[1][1]-sampled[0][1])
            denominator=math.hypot(*a)*math.hypot(*b)
            if denominator:angle=math.degrees(math.acos(max(-1,min(1,(a[0]*b[0]+a[1]*b[1])/denominator))))
        check("smooth_closure_preview_tangent", angle<15, {"seam_turn_degrees":angle,"allowed_degrees":15})
    elif case in {"C3", "C6"}:
        target = (2000,3000) if case=="C3" else (5000,5000)
        check("overall_dimensions_mm", near(width,target[0]) and near(height,target[1]), [width,height])
        check("single_closed_boundary", len(geometries)==1 and geometries[0].get("closed") is True)
        if case=="C6":
            from app.cad_construction import RadialPatternAssertion, _run_assertions
            try:
                _run_assertions([RadialPatternAssertion(kind="radial_pattern", assertion_id="corpus-five", target_ref="outline", lobes=5)], geometries, {"outline":[g["id"] for g in geometries]}, 1000)
                check("five_smooth_radial_lobes", True)
            except Exception as exc:
                check("five_smooth_radial_lobes", False, str(exc))
    elif case=="C4":
        actual = [(p["x"],p["y"]) for p in vertices(geometries[0])]
        expected = [(0,0),(3000,0),(1500,2600)]
        check("three_exact_vertices_and_closure", len(geometries)==1 and geometries[0].get("closed") is True and len(actual)==3 and all(any(near(x,a) and near(y,b) for x,y in actual) for a,b in expected), actual)
    elif case=="C5":
        points = vertices(geometries[0]); cx,cy=center(geometries[0])
        # Circumcentre of an odd regular polygon differs from its bbox centre.
        if points: cx=sum(p["x"] for p in points)/len(points); cy=sum(p["y"] for p in points)/len(points)
        radii = [math.hypot(p["x"]-cx,p["y"]-cy) for p in points]
        sides = [math.hypot(p["x"]-points[i-1]["x"],p["y"]-points[i-1]["y"]) for i,p in enumerate(points)]
        check("regular_pentagon_radius_1500mm", len(geometries)==1 and len(points)==5 and geometries[0].get("closed") is True and all(near(r,1500,5) for r in radii) and max(sides)-min(sides)<5, {"radii":radii,"sides":sides})
    elif case=="C7":
        rectangle = next((g for g in polylines if len(vertices(g))==4), None)
        check("one_rectangle_four_circles", len(geometries)==5 and len(circles)==4 and rectangle is not None)
        if rectangle:
            b=construction_geometry_bounds([rectangle]); check("rectangle_4000_by_2000mm", near(b["max_x"]-b["min_x"],4000) and near(b["max_y"]-b["min_y"],2000), b)
            check("four_radius_500mm_circles_at_corners", len(circles)==4 and all(near(c["radius"],500) for c in circles) and all(any(near(center(c)[0],p["x"]) and near(center(c)[1],p["y"]) for c in circles) for p in vertices(rectangle)))
    elif case=="C8":
        centers=[center(g) for g in geometries]
        xs=sorted(set(round(p[0],1) for p in centers)); ys=sorted(set(round(p[1],1) for p in centers))
        check("twelve_rectangles_3rows_4columns", len(geometries)==12 and len(xs)==4 and len(ys)==3, {"x_centers_mm":xs,"y_centers_mm":ys})
        check("center_pitch_1500_by_1200mm", len(xs)==4 and len(ys)==3 and all(near(xs[i]-xs[i-1],1500) for i in range(1,len(xs))) and all(near(ys[i]-ys[i-1],1200) for i in range(1,len(ys))))
        check("each_rectangle_1000_by_600mm", all(near((b:=construction_geometry_bounds([g]))["max_x"]-b["min_x"],1000) and near(b["max_y"]-b["min_y"],600) for g in geometries))
    elif case=="C9":
        check("two_circles", len(geometries)==2 and len(circles)==2)
        if len(circles)==2:
            d=math.dist(center(circles[0]),center(circles[1])); r=[c["radius"] for c in circles]
            check("intersecting_centers_1500mm", near(d,1500) and abs(r[0]-r[1])<d<sum(r), {"distance_mm":d,"radii_mm":r})
    elif case=="C10":
        check("two_separate_closed_shapes", len(geometries)==2 and all(g.get("closed") for g in geometries))
        check("heart_and_star_semantics_require_visual_review", False, "manual shape identification required")
    elif case in {"C11","C12"}:
        points=[]
        for segment in paths:
            for p in segment.get("points") or []:
                if isinstance(p,list) and len(p)>=2: points.append((float(p[0]),float(p[1])))
                elif isinstance(p,dict): points.append((float(p["x"]),float(p["y"])))
        # Preview contract uses metres, independently of mm geometry storage.
        if case=="C11":
            check("wave_extent_5m_and_1m_peak_to_peak", near(width,5000,20) and near(height,1000,20),[width,height])
            peaks=sum(points[i][1]>points[i-1][1] and points[i][1]>=points[i+1][1] for i in range(1,len(points)-1))
            check("five_wave_periods", peaks==5,peaks)
        else:
            radii=[math.hypot(x,y) for x,y in points]
            angles=[]
            for x,y in points:
                if math.hypot(x,y)>1e-5:
                    a=math.atan2(y,x)
                    if angles:
                        while a-angles[-1]>math.pi:a-=math.tau
                        while a-angles[-1]<-math.pi:a+=math.tau
                    angles.append(a)
            turns=abs(angles[-1]-angles[0])/math.tau if len(angles)>1 else 0
            check("spiral_three_turns_max_radius_2m", bool(radii) and abs(turns-3)<.15 and abs(max(radii)-2)<.03, {"turns":turns,"max_radius_m":max(radii,default=0)})
    return checks


def run_case(case, output):
    output.mkdir(parents=True,exist_ok=True)
    os.environ.update(XLINE_RUNTIME_PROFILE="virtual_sim",XLINE_AGENT_PROVIDER="deepseek",
                      XLINE_AGENT_TASK_STORE=str(output/"tasks.json"),XLINE_AGENT_AUDIT_STORE=str(output/"audit.jsonl"),
                      XLINE_DATABASE_PATH=str(output/"test.db"))
    from app.agent_service import RobotAgentService
    from app.creative_projects import CreativeProjectStore
    service=RobotAgentService(restore_pending_actions=False)
    store=CreativeProjectStore(output/"projects.json")
    report={"case":case,"prompt":corpus()[case].strip(),"model":service.advanced_model,
            "turns":[],"model_calls":[],"checks":[],"ui":"not_run"}
    original=service._structured_review_text
    def observe(*args,**kwargs):
        t=time.monotonic()
        try:
            raw=original(*args,**kwargs)
            report["model_calls"].append({"seconds":round(time.monotonic()-t,2),"response":raw})
            dump(output/"report.json",report)
            return raw
        except Exception as exc:
            report["model_calls"].append({"seconds":round(time.monotonic()-t,2),"error":str(exc)})
            raise
    service._structured_review_text=observe
    history=[]; project_id=None; candidate_response=None
    with patch("app.agent_service.get_creative_project_store",return_value=store):
        messages=[report["prompt"]]
        for index in range(4):
            message=messages[index]
            route=service.resolve_intent(message,"advanced",history)
            if project_id:route["selected_project_id"]=project_id
            started=time.monotonic()
            try:
                events=list(service.chat_stream(message,history,mode="advanced",route=route))
                result=next(e for e in reversed(events) if e.get("type")=="result")
            except Exception as exc:
                result={"ok":False,"message":str(exc),"exception_type":type(exc).__name__}
            dump(output/f"step-{index+1}.json",result)
            old_id=project_id; project_id=result.get("project_id") or project_id
            if old_id and result.get("project_id"):
                report["checks"].append({"name":f"project_identity_turn_{index+1}","passed":old_id==project_id})
            project=store.get(project_id) if project_id else None
            turn={"message":message,"seconds":round(time.monotonic()-started,2),"ok":result.get("ok"),
                  "reply":result.get("message"),"project_id":project_id,"status":(project or {}).get("status"),
                  "missing":(project or {}).get("missing_parameters"),"preview_count":len(result.get("preview_paths") or [])}
            report["turns"].append(turn)
            print(json.dumps({"case":case,"turn":index+1,**turn},ensure_ascii=False),flush=True)
            dump(output/"report.json",report)
            history.extend([{"role":"user","content":message},{"role":"assistant","content":str(result.get("message") or "")}])
            if result.get("ok") is True and result.get("preview_paths"):
                candidate_response=result
                break
            if index==0:
                # Only send the corpus-specific extra dimensions when needed.
                messages.append(FOLLOWUPS[case] if not project or project.get("missing_parameters") else "确认生成")
            elif index==1:
                messages.append("确认生成")
            else:
                break
        if candidate_response:
            variant=candidate_response.get("variant") or next(iter((project or {}).get("variants") or []),{})
            try: report["checks"].extend(geometry_checks(case,variant,candidate_response["preview_paths"]))
            except Exception as exc: report["checks"].append({"name":"independent_geometry_checks","passed":False,"error":str(exc)})
            report["checks"].append({"name":"project_and_variant_response_contract","passed":bool(candidate_response.get("project") and variant)})
            report["status"]="geometry_checks_pass" if all(c["passed"] for c in report["checks"]) else "geometry_check_failed_or_review_required"
            report["candidate_step"]=len(report["turns"])
        else:
            report["status"]="no_candidate"
        report["provider_call_count"]=len(report["model_calls"])
        report["project_count"]=len(store.list())
        dump(output/"report.json",report)
        print(json.dumps({"case":case,"status":report["status"],"calls":report["provider_call_count"]}),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--case");parser.add_argument("--output",required=True)
    args=parser.parse_args(); output=Path(args.output).resolve()
    if args.case:run_case(args.case,output)
    else:
        output.mkdir(parents=True,exist_ok=True)
        dump(output/"manifest.json",{"source":str(SOURCE),"cases":corpus(),"supplemental_answers":FOLLOWUPS})
        for case in corpus():
            try:subprocess.run([sys.executable,str(Path(__file__).resolve()),"--case",case,"--output",str(output/case)],check=False,timeout=360)
            except subprocess.TimeoutExpired:dump(output/case/"timeout.json",{"timeout_seconds":360})
