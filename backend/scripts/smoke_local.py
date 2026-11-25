"""Offline import and HTTP lifespan smoke check, run via local_dev.py."""
from pathlib import Path

from fastapi.testclient import TestClient

import app.main
from app.agent_service import robot_agent


root = Path(__file__).resolve().parents[1]
assert Path(app.main.__file__).resolve() == root / 'app' / 'main.py'
assert robot_agent.mode == 'local'
assert not robot_agent.api_keys
assert robot_agent.base_model == 'deepseek-flash'
assert robot_agent._cad_planning_model == 'deepseek-flash'
assert robot_agent.config_path.is_relative_to(root / '.local-dev')
with TestClient(app.main.app) as client:
    response = client.get('/health')
    response.raise_for_status()
    payload = response.json()
    assert payload['ok'] is True
    assert payload['status']['runtime_profile'] == 'virtual_sim'
    client.get('/openapi.json').raise_for_status()
print('PASS: local app import, isolated config, virtual runtime, health and OpenAPI.')
