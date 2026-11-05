import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.datastructures import UploadFile

from app.routers import drawings as main
from app.image_drawing_import import (
    primitives_to_app_lines,
    resolve_source_image,
    save_source_image,
    suggest_image_instance_groups,
    validate_image_upload,
)


def _primitive(kind: str, **values):
    return SimpleNamespace(
        id=values.pop("id", "p001"),
        type=kind,
        confidence=values.pop("confidence", 0.9),
        **values,
    )


def test_primitives_are_calibrated_to_canonical_millimetres():
    primitives = [
        _primitive("line", start=(10, 20), end=(30, 40)),
        _primitive("circle", id="p002", cx=50, cy=25, radius=10),
        _primitive("polyline", id="p003", points=[(0, 0), (100, 50)], closed=False),
    ]

    lines = primitives_to_app_lines(
        primitives,
        image_width_px=100,
        image_height_px=50,
        physical_width_mm=2000,
    )

    assert [item["id"] for item in lines] == [1, 2, 3]
    assert lines[0]["start"] == {"x": 200.0, "y": 600.0, "z": 0.0}
    assert lines[0]["end"] == {"x": 600.0, "y": 200.0, "z": 0.0}
    assert lines[1]["center"] == {"x": 1000.0, "y": 500.0, "z": 0.0}
    assert lines[1]["radius"] == 200.0
    assert lines[2]["vertices"][-1] == {"x": 2000.0, "y": 0.0, "z": 0.0}
    assert all(item["role"] == "printing" for item in lines)
    assert all(item["path_semantic"] == "DRAW" for item in lines)


def test_arc_direction_is_normalized_for_app_positive_sweep():
    arc = _primitive(
        "arc",
        center=(50, 50),
        radius=25,
        start_angle=10,
        end_angle=100,
        angular_span=90,
        clockwise=True,
    )
    [geometry] = primitives_to_app_lines(
        [arc],
        image_width_px=100,
        image_height_px=100,
        physical_width_mm=1000,
    )
    assert geometry["start_angle"] == pytest.approx(350)
    assert (geometry["end_angle"] - geometry["start_angle"]) % 360 == pytest.approx(90)


def test_image_group_suggestions_keep_separate_drawings_and_absorb_inner_marks():
    def line(identifier, start, end):
        return {
            "id": identifier,
            "type": "line",
            "start": {"x": start[0], "y": start[1]},
            "end": {"x": end[0], "y": end[1]},
            "confidence": 0.9,
        }

    geometries = [
        line(1, (0, 0), (10, 0)),
        line(2, (10, 0), (10, 6)),
        line(3, (10, 6), (0, 6)),
        line(4, (0, 6), (0, 0)),
        {"id": 5, "type": "circle", "center": {"x": 5, "y": 3}, "radius": 1, "confidence": 0.8},
        line(6, (20, 0), (30, 0)),
        line(7, (30, 0), (30, 6)),
        line(8, (30, 6), (20, 6)),
        line(9, (20, 6), (20, 0)),
        {"id": 10, "type": "circle", "center": {"x": 25, "y": 3}, "radius": 1, "confidence": 0.8},
    ]

    groups = suggest_image_instance_groups(geometries, tolerance_mm=0.2)

    assert [group["geometry_ids"] for group in groups] == [
        [1, 2, 3, 4, 5],
        [6, 7, 8, 9, 10],
    ]
    assert all(group["source"] == "image_connectivity" for group in groups)


def test_upload_validation_rejects_extension_content_mismatch():
    with pytest.raises(ValueError, match="扩展名"):
        validate_image_upload("drawing.png", b"not-a-png")

    assert validate_image_upload("drawing.png", b"\x89PNG\r\n\x1a\nrest") == ".png"


def test_image_import_route_saves_canonical_drawing(monkeypatch, tmp_path):
    payload = {
        "units": "mm",
        "lines": [
            {
                "id": 1,
                "type": "line",
                "start": {"x": 0.0, "y": 0.0, "z": 0.0},
                "end": {"x": 1000.0, "y": 0.0, "z": 0.0},
                "role": "printing",
                "path_semantic": "DRAW",
            }
        ],
        "layers": [],
        "cad_analysis": {},
    }
    monkeypatch.setattr(
        main,
        "vectorize_image_to_drawing",
        lambda source, physical_width_mm: (payload, ["请核对"]),
    )
    monkeypatch.setattr(main, "_cad_directory", lambda: tmp_path)
    monkeypatch.setattr(
        main,
        "drawing_versions",
        SimpleNamespace(
            save=lambda directory, name, drawing, source, note: {
                "file_name": "plan_v001.json",
                "source": source,
            }
        ),
    )
    upload = UploadFile(
        filename="plan.png",
        file=__import__("io").BytesIO(b"\x89PNG\r\n\x1a\nrest"),
    )

    result = asyncio.run(main.import_image_drawing(upload, 28000))

    assert result["ok"] is True
    assert result["file_name"] == "plan_v001.json"
    assert result["paths"] == 1
    assert result["source_format"] == "image"
    source_key = payload["cad_analysis"]["source_image_file"]
    assert resolve_source_image(tmp_path, source_key).read_bytes().startswith(b"\x89PNG")
    assert payload["cad_analysis"]["source_image_review_only"] is True


def test_source_image_storage_rejects_path_traversal(tmp_path):
    key = save_source_image(tmp_path, ".png", b"\x89PNG\r\n\x1a\nrest")
    assert resolve_source_image(tmp_path, key) is not None
    assert resolve_source_image(tmp_path, f"../{key}") is None


def test_drawing_preview_exposes_persisted_image_review(monkeypatch, tmp_path):
    drawing = tmp_path / "image_v001.json"
    drawing.write_text(
        __import__("json").dumps(
            {
                "source_format": "image",
                "lines": [],
                "cad_analysis": {
                    "primitive_count": 12,
                    "mean_confidence": 0.82,
                    "requires_user_review": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        main,
        "resolve_drawing",
        lambda file_name: drawing if file_name == drawing.name else None,
    )

    result = main.drawing_preview(drawing.name)

    assert result["ok"] is True
    assert result["source_format"] == "image"
    assert result["cad_analysis"]["primitive_count"] == 12
    assert result["cad_analysis"]["requires_user_review"] is True


def test_source_image_route_returns_review_asset(monkeypatch, tmp_path):
    key = save_source_image(tmp_path, ".png", b"\x89PNG\r\n\x1a\nrest")
    drawing = tmp_path / "image_v001.json"
    drawing.write_text(
        __import__("json").dumps(
            {"source_format": "image", "lines": [], "cad_analysis": {"source_image_file": key}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "_cad_directory", lambda: tmp_path)
    monkeypatch.setattr(main, "resolve_drawing", lambda file_name: drawing)

    response = main.drawing_source_image(drawing.name)

    assert response.media_type == "image/png"
    assert Path(response.path) == resolve_source_image(tmp_path, key)
