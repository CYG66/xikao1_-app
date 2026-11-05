from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from io import BytesIO
import subprocess
from pathlib import Path
from unittest.mock import patch

import ezdxf
from fastapi import UploadFile

from app.agent_skills import analyze_geometry_topology, calculate_geometry_bounds
from app.cad_import import (
    classify_layer_semantic,
    convert_dxf_to_dwg,
    convert_dwg_to_dxf,
    dwg_converter_status,
    export_dxf,
    parse_dxf,
)
from app.drawing_store import preview_paths
from app.routers.drawings import (
    cad_file_capabilities,
    export_drawing_dwg,
    export_drawing_dxf,
    import_cad_drawing,
)


class CadImportSampleTest(unittest.TestCase):
    def test_dwg_upload_uses_converter_and_enters_existing_cad_chain(self):
        def convert(_source, target):
            document = ezdxf.new("R2018")
            document.layers.add("PRINT")
            document.modelspace().add_line(
                (0, 0), (1000, 0), dxfattribs={"layer": "PRINT"}
            )
            document.saveas(target)
            return {"engine": "LibreDWG dwg2dxf", "return_code": 0}

        upload = UploadFile(filename="site.dwg", file=BytesIO(b"AC1032-test-dwg"))
        with tempfile.TemporaryDirectory() as directory, patch(
            "app.routers.drawings.convert_dwg_to_dxf", side_effect=convert
        ), patch(
            "app.routers.drawings._cad_directory", return_value=Path(directory)
        ), patch(
            "app.routers.drawings.drawing_versions.save",
            return_value={"file_name": "site_v001.json"},
        ):
            result = asyncio.run(import_cad_drawing(upload, "mm"))

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["source_format"], "dwg")
        self.assertEqual(result["dwg_conversion"]["engine"], "LibreDWG dwg2dxf")
        self.assertGreater(result["paths"], 0)

    def test_dwg_upload_rejects_a_renamed_non_dwg_file(self):
        upload = UploadFile(filename="fake.dwg", file=BytesIO(b"not-a-dwg"))

        result = asyncio.run(import_cad_drawing(upload, "mm"))

        self.assertFalse(result["ok"])
        self.assertIn("不是有效的 DWG", result["message"])

    def test_cad_capabilities_reflect_converter_runtime(self):
        with patch("app.routers.drawings.dwg_converter_status", return_value={
            "available": True, "engine": "LibreDWG dwg2dxf",
            "executable": "/usr/bin/dwg2dxf", "installation_hint": None,
            "import_available": True, "export_available": True,
        }):
            result = cad_file_capabilities()

        self.assertTrue(result["dxf_import"])
        self.assertTrue(result["dxf_export"])
        self.assertTrue(result["dwg_import"])
        self.assertTrue(result["dwg_export"])

    def test_dwg_converter_reports_missing_runtime(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("app.cad_import.shutil.which", return_value=None),
        ):
            status = dwg_converter_status()
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(RuntimeError, "LibreDWG"):
                    convert_dwg_to_dxf(
                        Path(directory) / "source.dwg",
                        Path(directory) / "target.dxf",
                    )

        self.assertFalse(status["available"])
        self.assertIn("DWG2DXF_BIN", status["installation_hint"])

    def test_invalid_configured_converter_is_not_reported_available(self):
        with patch.dict(
            "os.environ",
            {"DWG2DXF_BIN": "/missing/dwg2dxf", "DXF2DWG_BIN": "/missing/dxf2dwg"},
        ), patch("app.cad_import.shutil.which", return_value=None):
            status = dwg_converter_status()

        self.assertFalse(status["import_available"])
        self.assertFalse(status["export_available"])

    def test_dwg_converter_requires_a_real_output_file(self):
        def run(command, **kwargs):
            source = Path(command[-1])
            generated = Path(kwargs["cwd"]) / source.with_suffix(".dxf").name
            generated.write_text("0\nEOF\n", encoding="ascii")
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"DWG2DXF_BIN": "dwg2dxf-test"}
        ), patch(
            "app.cad_import.shutil.which", side_effect=lambda name: name
        ), patch("app.cad_import.subprocess.run", side_effect=run) as execute:
            result = convert_dwg_to_dxf(
                Path(directory) / "source.dwg",
                Path(directory) / "target.dxf",
            )

        self.assertEqual(result["engine"], "LibreDWG dwg2dxf")
        self.assertEqual(execute.call_count, 1)
        self.assertNotIn("-o", execute.call_args.args[0])

    def test_dwg_export_converter_requires_a_real_output_file(self):
        def run(command, **_kwargs):
            target = Path(command[command.index("-o") + 1])
            target.write_bytes(b"AC1032-test-dwg")
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"DXF2DWG_BIN": "dxf2dwg-test"}
        ), patch(
            "app.cad_import.shutil.which", side_effect=lambda name: name
        ), patch("app.cad_import.subprocess.run", side_effect=run) as execute:
            result = convert_dxf_to_dwg(
                Path(directory) / "source.dxf",
                Path(directory) / "target.dwg",
            )

        self.assertEqual(result["engine"], "LibreDWG dxf2dwg")
        self.assertEqual(execute.call_count, 1)

    def test_internal_geometry_exports_to_readable_dxf(self):
        payload = {
            "unit": "mm",
            "layers": [{"id": 1, "name": "DRAW_MAIN"}],
            "lines": [
                {"id": 1, "type": "line", "layer_id": 1,
                 "start": {"x": 0, "y": 0, "z": 0},
                 "end": {"x": 1000, "y": 0, "z": 0}},
                {"id": 2, "type": "circle", "layer_id": 1,
                 "center": {"x": 500, "y": 500, "z": 0}, "radius": 250},
                {"id": 3, "type": "polyline", "layer_id": 1, "closed": True,
                 "vertices": [
                     {"x": 0, "y": 0, "z": 0},
                     {"x": 1000, "y": 0, "z": 0},
                     {"x": 1000, "y": 1000, "z": 0},
                 ]},
            ],
        }

        content, warnings = export_dxf(payload)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "exported.dxf"
            path.write_bytes(content)
            document = ezdxf.readfile(path)

        self.assertEqual(warnings, [])
        self.assertEqual(document.header["$INSUNITS"], 4)
        self.assertEqual(
            [entity.dxftype() for entity in document.modelspace()],
            ["LINE", "CIRCLE", "POLYLINE"],
        )

    def test_export_endpoint_returns_real_dxf_bytes(self):
        payload = {
            "unit": "mm",
            "lines": [{
                "id": 1, "type": "line", "layer_id": 1,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 1000, "y": 0, "z": 0},
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            drawing = Path(directory) / "current.json"
            drawing.write_text(json.dumps(payload), encoding="utf-8")
            with patch("app.routers.drawings.resolve_drawing", return_value=drawing):
                response = export_drawing_dxf("current.json")
            dxf_path = Path(directory) / "current.dxf"
            dxf_path.write_bytes(response.body)
            document = ezdxf.readfile(dxf_path)

        self.assertEqual(response.media_type, "application/dxf")
        self.assertEqual(response.headers["content-disposition"], 'attachment; filename="drawing.dxf"')
        self.assertEqual(len(document.modelspace()), 1)

    def test_export_download_errors_use_non_success_http_status(self):
        with patch("app.routers.drawings.resolve_drawing", return_value=None):
            dxf = export_drawing_dxf("missing.json")
            dwg = export_drawing_dwg("missing.json")

        self.assertEqual(dxf.status_code, 404)
        self.assertEqual(dwg.status_code, 404)
        self.assertIn("不存在", json.loads(dxf.body)["message"])

    def test_dwg_export_endpoint_returns_converter_bytes(self):
        payload = {
            "unit": "mm",
            "lines": [{
                "id": 1, "type": "line", "layer_id": 1,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 1000, "y": 0, "z": 0},
            }],
        }

        def convert(_source, target):
            target.write_bytes(b"AC1032-test-dwg")
            return {"engine": "LibreDWG dxf2dwg", "return_code": 0}

        with tempfile.TemporaryDirectory() as directory:
            drawing = Path(directory) / "current.json"
            drawing.write_text(json.dumps(payload), encoding="utf-8")
            with patch("app.routers.drawings.resolve_drawing", return_value=drawing), patch(
                "app.routers.drawings.convert_dxf_to_dwg", side_effect=convert
            ):
                response = export_drawing_dwg("current.json")

        self.assertEqual(response.media_type, "application/acad")
        self.assertEqual(response.body, b"AC1032-test-dwg")
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="drawing.dwg"',
        )

    def test_layer_semantics_are_conservative_and_unambiguous(self):
        self.assertEqual(classify_layer_semantic("DRAW_MAIN"), "DRAW")
        self.assertEqual(classify_layer_semantic("TRAVEL_PATH"), "TRAVEL")
        self.assertEqual(classify_layer_semantic("SKIP_HIDDEN"), "SKIP")
        self.assertEqual(classify_layer_semantic("DIMENSIONS"), "AUXILIARY")
        self.assertEqual(classify_layer_semantic("Layer 0"), "AUXILIARY")

    def test_polyline_ellipse_and_semantics_are_preserved(self):
        def build(document):
            for layer in ("DRAW_MAIN", "TRAVEL_PATH", "SKIP_GUIDE", "MISC"):
                document.layers.new(layer)
            space = document.modelspace()
            space.add_lwpolyline(
                [(0, 0), (1000, 0), (1000, 500)],
                dxfattribs={"layer": "DRAW_MAIN", "elevation": 25},
            )
            space.add_polyline2d(
                [(0, 0), (0, 500), (500, 500)],
                dxfattribs={"layer": "TRAVEL_PATH"},
            )
            space.add_ellipse(
                (500, 500), major_axis=(300, 0), ratio=0.5,
                dxfattribs={"layer": "DRAW_MAIN"},
            )
            space.add_line((0, 0), (1, 1), dxfattribs={"layer": "SKIP_GUIDE"})
            space.add_line((0, 0), (2, 2), dxfattribs={"layer": "MISC"})

        payload, warnings = self._parse(build)
        types = [item["type"] for item in payload["lines"]]
        self.assertIn("polyline", types)
        self.assertIn("ellipse", types)
        self.assertEqual(
            {layer["name"]: layer["path_semantic"] for layer in payload["layers"]},
            {
                "DRAW_MAIN": "DRAW",
                "TRAVEL_PATH": "TRAVEL",
                "SKIP_GUIDE": "SKIP",
                "MISC": "AUXILIARY",
            },
        )
        lwpolyline = next(
            item for item in payload["lines"]
            if item["type"] == "polyline" and item["path_semantic"] == "DRAW"
        )
        self.assertEqual(lwpolyline["vertices"][0]["z"], 25.0)
        travel = next(
            item for item in payload["lines"]
            if item["type"] == "polyline" and item["path_semantic"] == "TRAVEL"
        )
        self.assertEqual(travel["role"], "reference")
        self.assertEqual(len(preview_paths(payload)), 2)
        self.assertTrue(any("AUXILIARY" in warning for warning in warnings))
    def _parse(self, build):
        document = ezdxf.new("R2018")
        build(document)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.dxf"
            document.saveas(path)
            return parse_dxf(path)

    def test_real_ezdxf_sample_preserves_layers_and_complex_entities(self):
        def build(document):
            document.layers.new("PRINT_MAIN")
            document.layers.new("DIMENSIONS")
            document.layers.new("REFERENCE")
            space = document.modelspace()
            space.add_line((0, 0), (1000, 0), dxfattribs={"layer": "PRINT_MAIN"})
            space.add_lwpolyline([(0, 0, 0, 0, 0.41421356), (1000, 0)], dxfattribs={"layer": "PRINT_MAIN"})
            space.add_spline([(0, 0), (200, 500), (600, 300), (1000, 0)], dxfattribs={"layer": "PRINT_MAIN"})
            space.add_text("A-01", dxfattribs={"insert": (10, 10), "height": 20, "layer": "DIMENSIONS"})
            space.add_mtext("说明", dxfattribs={"insert": (20, 20), "char_height": 20, "layer": "REFERENCE"})

        payload, warnings = self._parse(build)
        types = {item["type"] for item in payload["lines"]}
        roles = {item["role"] for item in payload["lines"]}
        self.assertIn("spline", types)
        self.assertIn("arc", types)
        self.assertIn("text", types)
        self.assertIn("annotation", roles)
        self.assertIn("reference", roles)
        self.assertGreaterEqual(payload["cad_analysis"]["printing_geometry_count"], 3)
        self.assertIsInstance(warnings, list)
        self.assertGreaterEqual(len(preview_paths(payload)), 3)

    def test_blocks_are_expanded_and_unsupported_entities_are_reported(self):
        def build(document):
            document.layers.new("PRINT")
            block = document.blocks.new("MARK")
            block.add_line((0, 0), (100, 0), dxfattribs={"layer": "PRINT"})
            space = document.modelspace()
            space.add_blockref("MARK", (500, 500), dxfattribs={"layer": "PRINT"})
            space.add_3dface([(0, 0), (1, 0), (1, 1), (0, 1)], dxfattribs={"layer": "PRINT"})

        payload, warnings = self._parse(build)
        self.assertTrue(any(item.get("source_block") == "MARK" for item in payload["lines"]))
        self.assertEqual(payload["cad_analysis"]["expanded_blocks"], 1)
        self.assertTrue(any("3DFACE" in warning for warning in warnings))

    def test_bulged_polyline_is_converted_to_arc_without_printing_its_chord(self):
        def build(document):
            document.layers.new("PRINT")
            document.modelspace().add_lwpolyline(
                [(0, 0, 0, 0, 1.0), (1000, 0)],
                dxfattribs={"layer": "PRINT"},
            )

        payload, _ = self._parse(build)
        self.assertEqual([item["type"] for item in payload["lines"]], ["arc"])
        self.assertEqual(payload["cad_analysis"]["printing_geometry_count"], 1)

    def test_auto_unit_uses_dxf_header_and_reports_conversion(self):
        def build(document):
            document.header["$INSUNITS"] = 5  # centimetres
            document.layers.new("PRINT")
            document.modelspace().add_line(
                (1, 0), (2, 0), dxfattribs={"layer": "PRINT"}
            )

        with tempfile.TemporaryDirectory() as directory:
            document = ezdxf.new("R2018")
            build(document)
            path = Path(directory) / "centimetres.dxf"
            document.saveas(path)
            payload, _ = parse_dxf(path, "auto")
        line = payload["lines"][0]
        self.assertEqual(payload["cad_analysis"]["source_unit"], "cm")
        self.assertEqual(payload["cad_analysis"]["unit_factor_to_mm"], 10.0)
        self.assertEqual(line["start"]["x"], 10.0)
        self.assertEqual(line["end"]["x"], 20.0)

    def test_topology_detects_crossing_and_duplicate_paths(self):
        line = lambda identifier, start, end: {
            "id": identifier, "type": "line", "layer_id": 1,
            "start": {"x": start[0], "y": start[1], "z": 0},
            "end": {"x": end[0], "y": end[1], "z": 0},
        }
        result = analyze_geometry_topology([
            line(1, (0, 0), (1000, 1000)),
            line(2, (0, 1000), (1000, 0)),
            line(3, (0, 0), (1000, 1000)),
        ])
        self.assertEqual(result["self_intersection_count"], 1)
        self.assertEqual(result["duplicate_geometry_count"], 1)
        self.assertFalse(result["ok"])

    def test_bounds_use_configured_work_area(self):
        geometry = [{
            "id": 1, "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 2000, "y": 500, "z": 0},
        }]
        with patch.dict("os.environ", {
            "XLINE_WORKSPACE_MIN_X_MM": "0",
            "XLINE_WORKSPACE_MAX_X_MM": "1000",
            "XLINE_WORKSPACE_MIN_Y_MM": "0",
            "XLINE_WORKSPACE_MAX_Y_MM": "1000",
        }, clear=False):
            result = calculate_geometry_bounds(geometry)
        self.assertFalse(result["ok"])
        self.assertEqual(result["bounds"]["width_mm"], 2000.0)
        self.assertTrue(result["errors"])

    def test_batch_of_real_cad_samples_parses_without_losing_executable_paths(self):
        # These are real ezdxf files generated on disk, not parser mocks.  The
        # loop approximates the variety seen in field exports: changing units,
        # layer names, curve types and open/closed geometry.
        with tempfile.TemporaryDirectory() as directory:
            for sample_index in range(20):
                document = ezdxf.new("R2018")
                layer = "PLOT" if sample_index % 2 else "喷墨层"
                document.layers.new(layer)
                space = document.modelspace()
                scale = sample_index + 1
                space.add_line((0, 0), (100 * scale, 0), dxfattribs={"layer": layer})
                space.add_circle((50 * scale, 50), 10 + scale, dxfattribs={"layer": layer})
                space.add_arc((50 * scale, 50), 20 + scale, 0, 180, dxfattribs={"layer": layer})
                space.add_ellipse((0, 0), major_axis=(30 * scale, 10), ratio=0.5, dxfattribs={"layer": layer})
                path = Path(directory) / f"sample_{sample_index}.dxf"
                document.saveas(path)
                payload, _ = parse_dxf(path, "cm" if sample_index % 3 == 0 else "mm")
                self.assertGreaterEqual(len(preview_paths(payload)), 4, path.name)
                self.assertEqual(payload["source_format"], "dxf")


if __name__ == "__main__":
    unittest.main()
