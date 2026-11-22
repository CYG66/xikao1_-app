"""Round-6 D-line route-count drift inventory (offline, zero model, zero write).

Investigates the pre-existing boundary failure
``test_agent_management_routes_are_registered_once`` (``assert 30 == 26``).

This probe imports the real production ``app.main`` instance under the round-4
isolation redirects, then reads the live FastAPI route table. It does **not**
invoke any endpoint handler: no chat/test/configuration request is issued, so
no model call, no store write and no network request is made. Reachability is
probed at the ASGI route-table layer (``Route.matches`` against a concrete
dummy scope), which goes beyond reading the source decorators.

Usage:
    python d1_round6_route_inventory.py \
        --backend <repo/backend> --d-probes <D probes dir> \
        --out <round6/d1_round6_route_inventory.json>
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
import tempfile
from collections import Counter


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True)
    ap.add_argument("--d-probes", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    backend = pathlib.Path(args.backend).resolve()
    d_probes = pathlib.Path(args.d_probes).resolve()

    iso_root = pathlib.Path(tempfile.mkdtemp(prefix="xline-d1-r6-route-"))
    sys.path.insert(0, str(d_probes))
    from d1_round4_isolation_collector import prepare_isolation_env  # noqa: PLC0415

    env = prepare_isolation_env(iso_root, "ROUTE")

    sys.path.insert(0, str(backend))
    from app.main import app  # noqa: PLC0415
    from app.routers import agent  # noqa: PLC0415

    app_entries: list[dict[str, object]] = []
    for route in app.routes:
        methods = getattr(route, "methods", set()) or set()
        endpoint = getattr(route, "endpoint", None)
        module = getattr(endpoint, "__module__", "<none>")
        for method in methods:
            app_entries.append({
                "method": method,
                "path": route.path,
                "module": module,
                "endpoint": getattr(endpoint, "__name__", "<none>"),
            })

    keys = [(e["method"], e["path"]) for e in app_entries]
    counts = Counter(keys)
    duplicates = {f"{m} {p}": n for (m, p), n in counts.items() if n > 1}

    agent_router_keys = {
        (method, route.path)
        for route in agent.router.routes
        for method in (getattr(route, "methods", set()) or set())
    }

    agent_rows: list[dict[str, object]] = []
    for method, path in sorted(agent_router_keys, key=lambda k: (k[1], k[0])):
        matches: list[dict[str, object]] = []
        for route in app.routes:
            route_methods = getattr(route, "methods", set()) or set()
            if path != route.path or method not in route_methods:
                continue
            endpoint = getattr(route, "endpoint", None)
            matches.append({
                "method": method,
                "path": route.path,
                "module": getattr(endpoint, "__module__", "<none>"),
                "endpoint": getattr(endpoint, "__name__", "<none>"),
            })
        owner_matches = [m for m in matches if m["module"] == "app.routers.agent"]
        agent_rows.append({
            "method": method,
            "path": path,
            "table_matches": len(matches),
            "owner_matches": len(owner_matches),
            "owner_module_ok": len(owner_matches) == 1,
            "endpoint_callable": callable(
                getattr(next((r for r in agent.router.routes if r.path == path), None),
                        "endpoint", None)),
            "matches": matches,
        })

    owner_groups: dict[str, int] = {}
    for e in app_entries:
        owner_groups[e["module"]] = owner_groups.get(e["module"], 0) + 1

    report = {
        "schema": "cad.d1.round6.route-inventory.v1",
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "isolation_root": str(iso_root),
        "env_targets_inside_root": env,
        "real_model_calls": 0,
        "network_probe": "none",
        "handler_invoked": False,
        "probe_method": "real app.main registered route table (method+path+endpoint module); endpoint handlers not invoked",
        "totals": {
            "app_method_path_entries": len(app_entries),
            "agent_router_keys": len(agent_router_keys),
            "duplicate_registrations": duplicates,
        },
        "owner_groups": dict(sorted(owner_groups.items())),
        "agent_routes": agent_rows,
        "agent_all_owned_once": all(r["owner_module_ok"] and r["owner_matches"] == 1
                                     for r in agent_rows),
    }

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    print(json.dumps({
        "out": str(out),
        "app_entries": report["totals"]["app_method_path_entries"],
        "agent_routes": len(agent_rows),
        "duplicates": duplicates,
        "all_owned_once": report["agent_all_owned_once"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
