"""Fresh provider creation, then isolated production relation-edit branches."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import sys

from run_user_cad_corpus import call, dump, app_check

sys.stdout.reconfigure(encoding="utf-8")
parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True)
parser.add_argument("--runs", type=int, default=2)
args = parser.parse_args()
root = Path(args.output).resolve()
root.mkdir(parents=True, exist_ok=False)
messages = ["新建CAD图纸，画一个圆形和一个矩形，分别作为两个完整对象，只预览，不执行小车。",
            "圆形半径1米，圆心(0,3)；矩形宽4米、高3米，中心(5,0)，坐标单位米。",
            "确认需求并生成CAD候选，只预览，不执行小车。"]


def run(number):
    folder = root / f"run-{number}"
    folder.mkdir()
    pid = None
    response = {}
    for step, text in enumerate(messages, 1):
        body = {"message": text, "mode": "advanced", "conversation_id": f"live-relations-{number}", "history": []}
        if pid:
            body["project_id"] = pid
        response = call(folder, step, body)
        newpid = response.get("project_id") or (response.get("project") or {}).get("id")
        if newpid and pid and pid != newpid:
            raise AssertionError("Project changed during supplementation")
        pid = newpid or pid
        print(json.dumps({"run": number, "step": step, "ok": response.get("ok"), "message": response.get("message")}, ensure_ascii=False), flush=True)
    variant = response.get("variant") or {}
    gs = variant.get("geometries") or []
    circle = next((g for g in gs if g.get("type") == "circle"), None)
    rect = next((g for g in gs if g.get("type") == "polyline" and g.get("closed")), None)
    assert len(gs) == 2 and circle and rect, "Fresh generation did not produce requested primitives"
    assert abs(circle["radius"]-1000) < .001 and abs(circle["center"]["x"]) < .001 and abs(circle["center"]["y"]-3000) < .001
    xs = [p["x"] for p in rect["vertices"]]; ys = [p["y"] for p in rect["vertices"]]
    assert abs(max(xs)-min(xs)-4000) < .001 and abs(max(ys)-min(ys)-3000) < .001
    assert abs((max(xs)+min(xs))/2-5000) < .001 and abs((max(ys)+min(ys))/2) < .001
    objects = variant.get("logical_objects") or []
    assert len(objects) == 2 and {g["id"] for g in gs} == {i for o in objects for i in o["geometry_refs"]}
    assert (folder/"model-responses.jsonl").exists(), "No fresh provider response recorded"
    branches = []
    for kind, prompt, answer in [
        ("concentric", "让矩形和圆形同心", "以圆形为基准，移动矩形，使两者同心"),
        ("equal", "让矩形和圆形一样大", "宽度相等，以圆形为基准，修改矩形"),
    ]:
        branch = root / f"run-{number}-{kind}"
        shutil.copytree(folder, branch)
        selection = {"scope": "logical_object", "object_ids": [o["object_id"] for o in objects],
                     "geometry_ids": [g["id"] for g in gs], "project_id": pid, "variant_id": variant["id"]}
        body = {"message": prompt, "mode": "advanced", "conversation_id": f"live-relations-{number}",
                "history": [], "project_id": pid, "drawing_selection": selection}
        clarification = call(branch, 4, body)
        body.pop("drawing_selection")
        body["message"] = answer
        final = call(branch, 5, body)
        check = (final.get("cad_preflight") or {}).get("relation_validation") or {}
        checks = {"initial_clarification": clarification.get("clarification_required") is True,
                  "new_saved_variant": bool((final.get("variant") or {}).get("id")) and final["variant"]["id"] != variant["id"],
                  "same_project": final.get("project_id") == pid,
                  "relation_independently_verified": check.get("enforced") is True and check.get("verified") is True,
                  "reference_unchanged": (final.get("cad_preflight") or {}).get("scope_validation", {}).get("non_target_integrity", {}).get("verified") is True,
                  "preview_available": len(final.get("preview_paths") or []) == 2}
        record = {"run": number, "kind": kind, "checks": checks, "passed": all(checks.values()), "message": final.get("message"), "relations": check}
        dump(branch/"acceptance-report.json", record)
        dump(branch/"ui-fixture.json", {"id": branch.name, "messages": messages+[prompt, answer],
            "selection_before_step": 4, "drawing_selection": selection, "expected_preview_count": 2})
        print(json.dumps(record, ensure_ascii=False), flush=True)
        branches.append(record)
    return {"run": number, "fresh_creation_measured": True, "branches": branches}


results = []
with ThreadPoolExecutor(max_workers=min(args.runs, 2)) as pool:
    futures = [pool.submit(run, n) for n in range(1, args.runs+1)]
    for n, future in enumerate(futures, 1):
        try:
            results.append(future.result())
        except Exception as exc:
            results.append({"run": n, "passed": False, "error": str(exc)})
dump(root/"report.json", {"method": "fresh real provider creation, isolated deterministic edit branches; empty history and worker restart every request", "results": results, "app": "pending; response replay is not installed APK"})
