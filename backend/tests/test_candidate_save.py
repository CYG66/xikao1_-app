from pathlib import Path
from unittest.mock import patch

from app.routers.projects import save_candidate_drawing
from app.creative_projects import CreativeProjectStore
from app.drawing_versions import DrawingVersionStore
from app.schemas import CreativeProjectSaveDrawingRequest


def test_saved_candidate_is_independent_and_idempotent(tmp_path):
    store = CreativeProjectStore(tmp_path / "projects.json")
    project = store.create("project", "draw", {}, {}, [])
    geometry = [{"id": 1, "type": "line", "layer_id": 1,
                 "start": {"x": 0, "y": 0, "z": 0}, "end": {"x": 1000, "y": 0, "z": 0}}]
    variant = store.add_variant(
        project["id"], "candidate", geometry, "", {}, [],
        acceptance_summary={"status": "passed", "review_required": False},
    )
    versions = DrawingVersionStore(tmp_path / "versions.json")
    with patch("app.routers.projects.get_creative_project_store", return_value=store), patch("app.routers.projects.drawing_versions", versions), patch("app.routers.projects._cad_directory", return_value=tmp_path / "cad"):
        first = save_candidate_drawing(project["id"], variant["id"], CreativeProjectSaveDrawingRequest(name="drawing"))
        second = save_candidate_drawing(project["id"], variant["id"], CreativeProjectSaveDrawingRequest(name="renamed"))
    assert first["ok"], first
    assert first["file_name"] == second["file_name"]
    assert len(versions.list()) == 1
    assert store.delete(project["id"])
    assert Path(tmp_path / "cad" / first["file_name"]).is_file()
    assert versions.payload(first["file_name"])["lines"]
