from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from pathlib import Path

root = Path(r"C:\Users\29924\AppData\Local\Temp\xikao-github-sync\backend")
stdlib = set(sys.stdlib_module_names)
local_top = {p.stem for p in (root / "app").glob("*.py")}
external = Counter()
files_with_import = {}
errors = []
all_py = sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
for p in all_py:
    rel = str(p.relative_to(root)).replace("\\", "/")
    try:
        source = p.read_text(encoding="utf-8", errors="replace")
        compile(source, str(p), "exec")
        tree = ast.parse(source)
    except SyntaxError as exc:
        errors.append({"path": rel, "error": str(exc)})
        continue
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for name in names:
            top = name.split(".")[0]
            if top in stdlib or top in {"app", "tests"} or top in local_top:
                continue
            external[top] += 1
            files_with_import.setdefault(top, []).append(rel)

manual_refs = []
for p in sorted((root / "tests").rglob("*.py")):
    text = p.read_text(encoding="utf-8", errors="replace")
    if "tests.manual" in text or "from tests import manual" in text:
        manual_refs.append(str(p.relative_to(root)).replace("\\", "/"))

print(json.dumps({
    "python": sys.version.split()[0],
    "py_files_compiled": len(all_py),
    "compile_errors": errors,
    "external_imports": dict(sorted(external.items())),
    "tests_manual_dir_exists": (root / "tests" / "manual").exists(),
    "tests_referencing_tests_manual": manual_refs,
}, ensure_ascii=False, indent=2))
