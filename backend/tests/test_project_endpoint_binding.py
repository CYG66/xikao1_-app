from copy import deepcopy
from unittest.mock import patch

import pytest

from app.routers.projects import _guard_project_endpoint_binding
from app.cad_edit_session import selection_binding


@pytest.mark.parametrize('drift', ['project', 'variant', 'selection', 'command', None])
def test_project_action_checks_pending_binding(drift):
    selection = {'project_id': 'p', 'variant_id': 'v', 'scope': 'entity', 'geometry_ids': [1]}
    binding = selection_binding(selection)
    pending = {'project_id': 'p', 'variant_id': 'v', 'binding': binding,
               'command': {'project_id': 'p', 'variant_id': 'v', 'operation': 'translate', 'binding': binding}}
    request_selection = deepcopy(selection)
    project_id, variant_id = 'p', 'v'
    if drift == 'project': project_id = 'other'
    if drift == 'variant': variant_id = 'other'
    if drift == 'selection': request_selection['geometry_ids'] = [2]
    if drift == 'command': pending['command']['variant_id'] = 'other'
    with patch('app.routers.projects.conversation_memory') as memory:
        memory.context.return_value = {'pending_cad_edit': pending}
        result = _guard_project_endpoint_binding(
            project_id=project_id, variant_id=variant_id,
            conversation_id='chat', drawing_selection=request_selection)
        if drift:
            assert result['error_code'] == 'cad_context_binding_mismatch'
            memory.clear_pending_cad_edit.assert_called_once()
        else:
            assert result is None
            memory.clear_pending_cad_edit.assert_not_called()
