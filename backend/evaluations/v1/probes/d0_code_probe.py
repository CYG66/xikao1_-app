from __future__ import annotations

import ast
import json
from pathlib import Path

root = Path(r"C:\Users\29924\AppData\Local\Temp\xikao-github-sync\backend")
envs = {}
routes = []
writes = []
for p in sorted((root / "app").rglob("*.py")):
    text = p.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        continue
    rel = str(p.relative_to(root)).replace("\\", "/")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in {"getenv", "get"} and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                value = node.args[0].value
                if value.startswith(("XLINE", "DEEPSEEK", "OPENAI", "CAD", "MODEL", "AGENT")):
                    envs.setdefault(value, []).append(f"{rel}:{node.lineno}")
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"get", "post", "put", "delete", "patch", "add_api_route"}:
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) and node.args[0].value.startswith("/"):
                    routes.append((rel, node.lineno, node.args[0].value, node.func.attr))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"write_text", "write_bytes"}:
            writes.append((rel, node.lineno, node.func.attr))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str) and "w" in node.args[1].value:
                writes.append((rel, node.lineno, "open-w"))
print("ENV")
for k, v in sorted(envs.items()):
    print(k, "=>", ", ".join(v[:4]))
print("ROUTES", len(routes))
for r in routes[:80]:
    print(r)
print("WRITES", len(writes))
for w in writes[:80]:
    print(w)
