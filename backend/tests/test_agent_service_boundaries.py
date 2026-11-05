from app.agent_service_config import DEFAULT_MODELS, PROVIDERS
from app.agent_service_policy import SAFE_TOOL_NAMES, SYSTEM_PROMPT
from app.main import app


def test_provider_configuration_covers_every_registered_provider() -> None:
    assert PROVIDERS
    assert set(DEFAULT_MODELS) == set(PROVIDERS)


def test_agent_policy_is_non_empty_and_immutable() -> None:
    assert "Dashes" in SYSTEM_PROMPT
    assert "modify_drawing" in SAFE_TOOL_NAMES
    assert isinstance(SAFE_TOOL_NAMES, frozenset)


def test_legacy_geometry_bypass_routes_are_not_registered() -> None:
    registered = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    assert ("POST", "/api/drawings/generate") not in registered
    assert ("POST", "/api/agent/projects/{project_id}/variants") not in registered
    assert ("POST", "/api/agent/projects/{project_id}/generate-candidate") in registered


def test_system_routes_are_registered_from_system_router() -> None:
    expected = {
        ("GET", "/health"),
        ("GET", "/api/status"),
        ("GET", "/api/telemetry"),
        ("GET", "/api/telemetry/history"),
        ("GET", "/api/network/status"),
        ("GET", "/api/network/wifi"),
        ("POST", "/api/network/wifi"),
        ("POST", "/api/network/wifi/connect-saved"),
        ("GET", "/api/network/wifi/verify"),
        ("POST", "/api/network/wifi/disconnect"),
        ("POST", "/api/network/wifi/forget"),
        ("GET", "/api/database/summary"),
        ("GET", "/api/database/migrations"),
        ("POST", "/api/database/backup"),
        ("GET", "/api/database/integrity"),
        ("POST", "/api/database/cleanup"),
    }
    registered = {
        (method, route.path): route.endpoint.__module__
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    assert all(registered.get(route) == "app.routers.system" for route in expected)


def test_project_routes_are_registered_from_projects_router() -> None:
    expected = {
        ("GET", "/api/agent/projects"),
        ("POST", "/api/agent/projects"),
        ("GET", "/api/agent/projects/{project_id}"),
        ("GET", "/api/agent/projects/{project_id}/timeline"),
        ("POST", "/api/agent/projects/{project_id}/generate-candidate"),
        ("PATCH", "/api/agent/projects/{project_id}"),
        ("DELETE", "/api/agent/projects/{project_id}"),
        ("POST", "/api/agent/projects/{project_id}/variants/{variant_id}/save-drawing"),
        ("POST", "/api/agent/projects/{project_id}/select-variant"),
        ("POST", "/api/agent/projects/{project_id}/start-iteration"),
        ("POST", "/api/agent/projects/{project_id}/confirm-instance-groups"),
        ("POST", "/api/agent/projects/{project_id}/plan"),
        ("GET", "/api/agent/projects/{project_id}/plan"),
        ("POST", "/api/agent/projects/{project_id}/exit-plan"),
        ("POST", "/api/agent/projects/{project_id}/request-execution"),
        ("GET", "/api/agent/projects/{project_id}/execution"),
        ("GET", "/api/agent/projects/{project_id}/recovery"),
        ("POST", "/api/agent/projects/{project_id}/recovery"),
        ("POST", "/api/agent/projects/{project_id}/resume-execution"),
        ("POST", "/api/agent/projects/{project_id}/recovery-inspection"),
        ("POST", "/api/agent/projects/{project_id}/report"),
        ("GET", "/api/agent/projects/{project_id}/report"),
    }
    registered = {
        (method, route.path): route.endpoint.__module__
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    assert all(registered.get(route) == "app.routers.projects" for route in expected)


def test_drawing_routes_are_registered_once_from_drawings_router() -> None:
    from app.routers.drawings import router

    expected = {
        (method, route.path)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }
    assert len(expected) == 17
    for method, path in expected:
        matches = [
            route for route in app.routes
            if route.path == path and method in getattr(route, "methods", set())
        ]
        assert len(matches) == 1, (method, path)
        assert matches[0].endpoint.__module__ == "app.routers.drawings"


def test_agent_management_routes_are_registered_once() -> None:
    from app.routers.agent import router

    expected = {(method, route.path) for route in router.routes
                for method in getattr(route, "methods", set())}
    assert len(expected) == 26
    for method, path in expected:
        matches = [route for route in app.routes if route.path == path
                   and method in getattr(route, "methods", set())]
        assert len(matches) == 1, (method, path)
        assert matches[0].endpoint.__module__ == "app.routers.agent"


def test_application_routes_have_unique_owners_outside_main() -> None:
    from collections import Counter

    routes = [route for route in app.routes
              if getattr(route, "endpoint", None) is not None
              and route.endpoint.__module__ != "fastapi.applications"]
    keys = [(method, route.path) for route in routes
            for method in getattr(route, "methods", {"WEBSOCKET"})]
    assert all(count == 1 for count in Counter(keys).values())
    assert all(route.endpoint.__module__.startswith("app.routers.") for route in routes)
    websocket_paths = {route.path for route in routes if not hasattr(route, "methods")}
    assert websocket_paths == {"/", "/ws/rosbridge", "/ws/status"}
