from __future__ import annotations

import ast
import json
from pathlib import Path

root = Path(r"C:\Users\29924\AppData\Local\Temp\xikao-github-sync\backend")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


base = load_json(root / "evaluations" / "cad_construction_model_benchmark.json")
ext = load_json(root / "evaluations" / "cad_construction_model_benchmark_extended.json")
frozen = load_json(root / "evaluations" / "p1.3e_dual_case_frozen.json")

result = {
    "benchmarks": {
        "base_schema": base.get("schema"),
        "base_case_count": len(base.get("cases", [])),
        "base_case_ids": [c.get("case_id") for c in base.get("cases", [])],
        "extended_schema": ext.get("schema"),
        "extended_case_count": len(ext.get("cases", [])),
        "extended_first_ids": [c.get("case_id") for c in ext.get("cases", [])[:12]],
        "extended_contains_A9_S1_M1": [
            c.get("case_id") for c in ext.get("cases", [])
            if c.get("case_id") in {"A9", "S1", "M1"}
        ],
    },
    "frozen": {
        "schema": frozen.get("schema"),
        "status": frozen.get("status"),
        "case_ids": sorted((frozen.get("cases") or {}).keys()),
        "a9_prompt": (frozen.get("cases") or {}).get("A9", {}).get("prompt"),
        "s1_prompt": (frozen.get("cases") or {}).get("S1", {}).get("prompt"),
        "historical_plan": (frozen.get("cases") or {}).get("A9", {}).get("historical_plan"),
    },
}

app_files = sorted(p for p in (root / "app").rglob("*.py") if p.is_file())
tests = sorted(p for p in (root / "tests").rglob("test_*.py") if p.is_file())

app_summary = []
for p in app_files:
    text = p.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        continue
    funcs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
    app_summary.append({
        "path": str(p.relative_to(root)).replace("\\", "/"),
        "lines": text.count("\n") + 1,
        "functions": len(funcs),
        "classes": len(classes),
        "function_names": funcs,
        "class_names": classes,
    })

test_summary = []
for p in tests:
    text = p.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        continue
    funcs = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test")]
    imports = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imports.append(n.module)
    test_summary.append({
        "path": str(p.relative_to(root)).replace("\\", "/"),
        "test_functions": len(funcs),
        "app_imports": sorted({m for m in imports if m.startswith("app.")}),
    })

result["counts"] = {
    "app_py_files": len(app_files),
    "app_py_lines": sum(x["lines"] for x in app_summary),
    "test_files": len(tests),
    "test_functions": sum(x["test_functions"] for x in test_summary),
    "eval_files": len(list((root / "evaluations").rglob("*"))),
}
result["app_summary"] = app_summary
result["test_summary"] = test_summary

out = Path(r"C:\Users\29924\AppData\Local\Temp\d0_audit_probe.json")
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(out)
print(json.dumps(result["counts"], ensure_ascii=False))
print(json.dumps(result["benchmarks"], ensure_ascii=False))
print(json.dumps(result["frozen"], ensure_ascii=False))
