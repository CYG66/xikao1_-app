import json
import sqlite3
from unittest.mock import patch

import pytest

from app.creative_projects import CreativeProjectStore
from app.database import XLineDatabase
from app.drawing_versions import DrawingVersionStore
from app.creative_workflow import prepare_project_plan
from app.state import robot_state


ACCEPTED = {"status": "passed", "review_required": False}


def _project_with_selected_variant(tmp_path):
    store = CreativeProjectStore(tmp_path / "projects.json")
    project = store.create("project", "draw", {}, {}, [])
    geometry = [{
        "id": 1, "type": "line", "layer_id": 1,
        "start": {"x": 0, "y": 0, "z": 0},
        "end": {"x": 1000, "y": 0, "z": 0},
    }]
    variant = store.add_variant(
        project["id"], "candidate", geometry, "",
        {"feasibility": {"ok": True, "errors": []}}, [],
        acceptance_summary=ACCEPTED,
    )
    assert store.select_variant(project["id"], variant["id"])
    return store, project["id"], variant["id"]


def test_planning_drawing_and_project_snapshot_commit_together(tmp_path):
    project_store, project_id, variant_id = _project_with_selected_variant(tmp_path)
    versions = DrawingVersionStore(tmp_path / "versions.json")
    result = versions.save_project_planning(
        tmp_path / "cad", "plan.json",
        {"creative_project_id": project_id, "lines": []},
        "creative_project", "planning",
        project_store=project_store,
        project_id=project_id,
        planning_factory=lambda version: {
            "variant_id": variant_id,
            "file_name": version["file_name"],
            "drawing_version": version,
            "stage": "planning_preview",
            "submitted": True,
            "validation": {},
        },
    )
    assert result["planning"]["file_name"] == result["drawing_version"]["file_name"]
    assert project_store.get(project_id)["planning"] == result["planning"]
    assert versions.find_by_file(result["drawing_version"]["file_name"])
    assert (tmp_path / "cad" / result["drawing_version"]["file_name"]).is_file()


def test_planning_transaction_rolls_back_file_indexes_and_project_memory(tmp_path, monkeypatch):
    project_store, project_id, variant_id = _project_with_selected_variant(tmp_path)
    versions = DrawingVersionStore(tmp_path / "versions.json")
    before = project_store.get(project_id)
    monkeypatch.setattr(project_store, "_apply_planning", lambda *_args, **_kwargs: False)
    with pytest.raises(RuntimeError, match="planning transition"):
        versions.save_project_planning(
            tmp_path / "cad", "plan.json",
            {"creative_project_id": project_id, "lines": []},
            "creative_project", "planning",
            project_store=project_store,
            project_id=project_id,
            planning_factory=lambda version: {
                "variant_id": variant_id,
                "file_name": version["file_name"],
                "drawing_version": version,
                "stage": "planning_preview",
                "validation": {},
            },
        )
    assert project_store.get(project_id) == before
    assert versions.list() == []
    assert list((tmp_path / "cad").glob("*.json")) == []


def test_prepare_project_plan_uses_atomic_drawing_and_planning_unit(tmp_path):
    project_store, project_id, _variant_id = _project_with_selected_variant(tmp_path)
    versions = DrawingVersionStore(tmp_path / "versions.json")
    with (
        patch("app.creative_workflow.get_creative_project_store", return_value=project_store),
        patch("app.creative_workflow.drawing_versions", versions),
        patch("app.creative_workflow.cad_directory", return_value=tmp_path / "cad"),
        patch("app.creative_workflow.resolve_drawing", return_value=None),
        patch("app.creative_workflow.ros_adapter.prepare_mission", return_value=True),
        patch.object(robot_state, "mission_stage", "planning_preview"),
    ):
        result = prepare_project_plan(project_id)
    assert result["ok"] is True
    assert len(versions.list()) == 1
    persisted = project_store.get(project_id)
    assert persisted["planning"]["file_name"] == result["planning"]["file_name"]
    assert persisted["planning"]["drawing_version"] == versions.list()[0]


def test_sqlite_project_bundle_rolls_back_all_rows_on_version_failure(tmp_path):
    database = XLineDatabase(tmp_path / "xline.db")
    original = {"id": "p1", "status": "ready_for_design", "updated_at": "1"}
    database.save_project_bundle([original])
    changed = {"id": "p1", "status": "planning", "updated_at": "2",
               "planning": {"stage": "planning_preview"}}
    with pytest.raises(KeyError):
        database.save_project_bundle(
            [changed], [{"item": {}, "payload": {}}]
        )
    with sqlite3.connect(database.path) as connection:
        project_payload = json.loads(
            connection.execute(
                "SELECT payload_json FROM projects WHERE project_id='p1'"
            ).fetchone()[0]
        )
        planning_count = connection.execute(
            "SELECT COUNT(*) FROM planning_tasks WHERE project_id='p1'"
        ).fetchone()[0]
        version_count = connection.execute(
            "SELECT COUNT(*) FROM design_versions WHERE project_id='p1'"
        ).fetchone()[0]
    assert project_payload["status"] == "ready_for_design"
    assert planning_count == 0
    assert version_count == 0
