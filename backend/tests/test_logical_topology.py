from __future__ import annotations

import unittest

from app.cad_edit_contract import build_cad_edit_contract
from app.logical_topology import (
    evolve_logical_graph_for_edit,
    preserve_logical_graph,
    validate_logical_object_continuity,
    validate_logical_object_graph,
)
from app.incremental_cad import edit_candidate_geometries, parse_incremental_edit
from app.cad_target_resolver import resolve_logical_object_target


def line(geometry_id: int, instance: int, x: float) -> dict:
    return {
        "id": geometry_id,
        "type": "line",
        "template_instance": instance,
        "start": {"x": x, "y": 0.0, "z": 0.0},
        "end": {"x": x + 1000.0, "y": 0.0, "z": 0.0},
    }


class LogicalTopologyTest(unittest.TestCase):
    def test_default_identity_migration_does_not_change_unedited_object(self):
        from app.logical_topology import build_logical_object_diff
        source=[{"object_id":"a","geometry_refs":[1]},{"object_id":"b","geometry_refs":[2]}]
        target,_=preserve_logical_graph(source,{})
        self.assertEqual(build_logical_object_diff(source,target,{},{} )["modified_object_ids"],[])
        target[1]["identity_key"]="changed"
        self.assertEqual(build_logical_object_diff(source,target,{},{} )["modified_object_ids"],["b"])
    def test_assembly_membership_survives_edits_and_cannot_drift(self):
        geometries=[line(1,1,0),line(2,2,3000)]
        objects=[{"object_id":f"part-{i}","geometry_refs":[i],"assembly_id":"whole","assembly_label":"整体"} for i in (1,2)]
        self.assertTrue(validate_logical_object_graph(geometries,objects,{})["verified"])
        copied,topology=preserve_logical_graph(objects,{})
        self.assertEqual(copied[1]["assembly_id"],"whole")
        copied[1]["assembly_id"]="another"
        report=validate_logical_object_continuity(geometries,geometries,objects,copied,{},topology,target_object_ids=["part-2"])
        self.assertFalse(report["verified"])
        self.assertIn("assembly_ownership_drift",[e["code"] for e in report["errors"]])

    def test_same_assembly_cannot_have_conflicting_names(self):
        objects=[{"object_id":"a","geometry_refs":[1],"assembly_id":"whole","assembly_label":"甲"},
                 {"object_id":"b","geometry_refs":[2],"assembly_id":"whole","assembly_label":"乙"}]
        self.assertFalse(validate_logical_object_graph([line(1,1,0),line(2,2,3)],objects,{})["verified"])

    def test_legacy_logical_object_gets_durable_identity_key(self) -> None:
        objects, _ = preserve_logical_graph([
            {"object_id": "court-1", "geometry_refs": [1]},
        ], {})
        self.assertEqual(objects[0]["identity_key"], "court-1")

    def test_split_shared_boundary_moves_only_declared_target_side(self) -> None:
        source = [
            {
                "id": 1, "type": "line", "template_instance": 1,
                "start": {"x": 0.0, "y": 0.0}, "end": {"x": 0.0, "y": 5000.0},
            },
            {
                "id": 2, "type": "line", "template_instance": 1,
                "start": {"x": 2500.0, "y": 0.0}, "end": {"x": 2500.0, "y": 5000.0},
            },
            {
                "id": 3, "type": "line", "template_instance": 2,
                "start": {"x": 5000.0, "y": 0.0}, "end": {"x": 5000.0, "y": 5000.0},
            },
        ]
        edit = {
            "operation": "translate", "geometry_ids": [2],
            "dx_mm": 5000.0, "dy_mm": 0.0,
            "boundary_policy": "split_shared",
            "shared_geometry_ids": [2],
        }
        target, error = edit_candidate_geometries(source, edit)
        self.assertIsNone(error)
        self.assertEqual(edit["created_geometry_ids"], [4])
        self.assertEqual(target[1]["start"]["x"], 2500.0)
        self.assertEqual(target[-1]["id"], 4)
        self.assertEqual(target[-1]["start"]["x"], 7500.0)

    def test_split_shared_boundary_updates_logical_refs_and_passes_validation(self) -> None:
        source = [
            {"id": 1, "type": "line", "template_instance": 1,
             "start": {"x": 0.0, "y": 0.0}, "end": {"x": 0.0, "y": 5000.0}},
            {"id": 2, "type": "line", "template_instance": 1,
             "start": {"x": 2500.0, "y": 0.0}, "end": {"x": 2500.0, "y": 5000.0}},
            {"id": 3, "type": "line", "template_instance": 2,
             "start": {"x": 5000.0, "y": 0.0}, "end": {"x": 5000.0, "y": 5000.0}},
        ]
        target = [dict(item) for item in source]
        target[1] = {**target[1], "start": {"x": 2500.0, "y": 0.0},
                     "end": {"x": 2500.0, "y": 5000.0}}
        target.append({"id": 4, "type": "line", "template_instance": 1,
                       "start": {"x": 7500.0, "y": 0.0},
                       "end": {"x": 7500.0, "y": 5000.0}})
        source_objects = [
            {"object_id": "space-1", "object_type": "space", "label": "左侧",
             "geometry_refs": [1, 2]},
            {"object_id": "space-2", "object_type": "space", "label": "右侧",
             "geometry_refs": [2, 3]},
        ]
        target_objects = [
            {"object_id": "space-1", "object_type": "space", "label": "左侧",
             "geometry_refs": [1, 4]},
            {"object_id": "space-2", "object_type": "space", "label": "右侧",
             "geometry_refs": [2, 3]},
        ]
        topology = {"shared_geometries": [{"geometry_id": 2,
                    "object_ids": ["space-1", "space-2"],
                    "relation": "shared_boundary"}], "relations": []}
        target_topology = {"shared_geometries": [], "relations": []}
        result = validate_logical_object_continuity(
            source, target, source_objects, target_objects,
            topology, target_topology, target_object_ids=["space-1"],
            edit_contract={"operation": "translate", "parameters":
                           {"boundary_policy": "split_shared"}},
        )
        self.assertTrue(result["verified"], result)

    def test_parser_requires_explicit_boundary_split_language(self) -> None:
        ordinary = parse_incremental_edit("把中间两个停车位向前移动5米")
        explicit = parse_incremental_edit("拆分共享边界后，把中间两个停车位向前移动5米")
        self.assertNotEqual(ordinary.get("boundary_policy"), "split_shared")
        self.assertEqual(explicit.get("boundary_policy"), "split_shared")
    def test_rejects_dangling_geometry_reference(self) -> None:
        result = validate_logical_object_graph(
            [line(1, 1, 0.0)],
            [{
                "object_id": "room-1", "object_type": "room",
                "label": "房间 1", "geometry_refs": [9],
            }],
            {},
        )
        self.assertFalse(result["verified"])
        self.assertIn("dangling_geometry_refs", {
            item["code"] for item in result["errors"]
        })

    def test_rejects_missing_shared_geometry_declaration(self) -> None:
        result = validate_logical_object_graph(
            [line(1, 1, 0.0)],
            [
                {"object_id": "room-1", "object_type": "room",
                 "label": "房间 1", "geometry_refs": [1]},
                {"object_id": "room-2", "object_type": "room",
                 "label": "房间 2", "geometry_refs": [1]},
            ],
            {},
        )
        self.assertFalse(result["verified"])
        self.assertIn("missing_shared_declaration", {
            item["code"] for item in result["errors"]
        })

    def test_continuity_rejects_non_target_object_drift(self) -> None:
        source = [line(1, 1, 0.0), line(2, 2, 2000.0)]
        target = [line(1, 1, 500.0), line(2, 2, 2000.0)]
        source_objects = [
            {"object_id": "shape-1", "object_type": "shape",
             "label": "图形 1", "geometry_refs": [1]},
            {"object_id": "shape-2", "object_type": "shape",
             "label": "图形 2", "geometry_refs": [2]},
        ]
        target_objects = [dict(item) for item in source_objects]
        target_objects[1] = {**target_objects[1], "label": "被意外修改"}
        result = validate_logical_object_continuity(
            source, target, source_objects, target_objects, {}, {},
            target_object_ids=["shape-1"],
        )
        self.assertFalse(result["verified"])
        self.assertIn("non_target_object_drift", {
            item["code"] for item in result["errors"]
        })

    def test_duplicate_creates_stable_logical_object_for_new_geometry(self) -> None:
        source = [line(1, 1, 0.0)]
        target = source + [line(2, 2, 2000.0)]
        objects = [{
            "object_id": "shape-1", "object_type": "shape",
            "label": "图形 1", "geometry_refs": [1],
            "assembly_id":"whole","assembly_label":"整体",
        }]
        contract = build_cad_edit_contract({
            "operation": "duplicate", "instance": 1, "new_instance": 2,
            "direction": "右", "distance_mm": 1000.0, "placement": "gap",
        })
        evolved, topology = evolve_logical_graph_for_edit(
            source, target, objects, {}, contract
        )
        self.assertEqual([item["object_id"] for item in evolved], ["shape-1", "shape-2"])
        self.assertEqual(evolved[1]["geometry_refs"], [2])
        self.assertNotEqual(evolved[0]["assembly_id"],evolved[1]["assembly_id"])
        self.assertTrue(validate_logical_object_graph(target, evolved, topology)["verified"])

    def test_added_geometry_without_object_owner_fails_continuity(self) -> None:
        source = [line(1, 1, 0.0)]
        target = source + [line(2, 2, 2000.0)]
        objects = [{
            "object_id": "shape-1", "object_type": "shape",
            "label": "图形 1", "geometry_refs": [1],
        }]
        result = validate_logical_object_continuity(
            source, target, objects, objects, {}, {}, target_object_ids=["shape-1"]
        )
        self.assertFalse(result["verified"])
        self.assertIn("unowned_added_geometry", {
            item["code"] for item in result["errors"]
        })

    def test_translation_refreshes_bounds_for_next_spatial_target(self) -> None:
        source = [line(1, 1, 0.0), line(2, 2, 2000.0)]
        target = [line(1, 1, 4000.0), line(2, 2, 2000.0)]
        objects = [
            {"object_id": "shape-1", "object_type": "shape", "label": "图形 1",
             "geometry_refs": [1],
             "bounds": {"min_x": 0, "min_y": 0, "max_x": 1000, "max_y": 0}},
            {"object_id": "shape-2", "object_type": "shape", "label": "图形 2",
             "geometry_refs": [2],
             "bounds": {"min_x": 2000, "min_y": 0, "max_x": 3000, "max_y": 0}},
        ]
        contract = build_cad_edit_contract({
            "operation": "translate", "instance": 1,
            "dx_mm": 4000.0, "dy_mm": 0.0,
        })
        evolved, _ = evolve_logical_graph_for_edit(
            source, target, objects, {}, contract
        )
        resolved = resolve_logical_object_target(
            {"object_type": "shape", "position": "right"}, evolved
        )
        self.assertEqual(evolved[0]["bounds"]["min_x"], 4000.0)
        self.assertEqual(resolved["object_id"], "shape-1")

    def test_circle_radius_change_refreshes_full_object_bounds(self) -> None:
        source = [{
            "id": 1, "type": "circle", "template_instance": 1,
            "center": {"x": 1000.0, "y": 2000.0, "z": 0.0}, "radius": 500.0,
        }]
        target = [{**source[0], "radius": 1000.0}]
        objects = [{
            "object_id": "circle-1", "object_type": "circle", "label": "圆 1",
            "geometry_refs": [1],
            "bounds": {"min_x": 500, "min_y": 1500, "max_x": 1500, "max_y": 2500},
        }]
        contract = build_cad_edit_contract({
            "operation": "resize", "geometry_ids": [1],
            "dimension": "半径", "value_mm": 1000.0,
        })
        evolved, _ = evolve_logical_graph_for_edit(
            source, target, objects, {}, contract
        )
        self.assertEqual(evolved[0]["bounds"], {
            "min_x": 0.0, "min_y": 1000.0, "max_x": 2000.0, "max_y": 3000.0,
        })

    def test_shared_boundary_does_not_replace_area_bounds_with_line_bounds(self) -> None:
        source = [line(1, 1, 1000.0)]
        target = [line(1, 1, 1500.0)]
        objects = [{
            "object_id": "room-1", "object_type": "room", "label": "房间 1",
            "geometry_refs": [1],
            "bounds": {"min_x": 0, "min_y": 0, "max_x": 4000, "max_y": 3000},
        }]
        evolved, _ = evolve_logical_graph_for_edit(source, target, objects, {}, None)
        self.assertEqual(evolved[0]["bounds"], objects[0]["bounds"])

    def test_valid_left_and_adjacent_relations_pass(self) -> None:
        geometries = [line(1, 1, 0.0), line(2, 2, 1000.0)]
        objects = [
            {"object_id": "space-1", "object_type": "space", "label": "左侧",
             "geometry_refs": [1],
             "bounds": {"min_x": 0, "min_y": 0, "max_x": 1000, "max_y": 1000}},
            {"object_id": "space-2", "object_type": "space", "label": "右侧",
             "geometry_refs": [2],
             "bounds": {"min_x": 1000, "min_y": 0, "max_x": 2000, "max_y": 1000}},
        ]
        topology = {"relations": [
            {"source_object_id": "space-1", "target_object_id": "space-2",
             "relation": "left_of"},
            {"source_object_id": "space-1", "target_object_id": "space-2",
             "relation": "adjacent"},
        ]}
        result = validate_logical_object_graph(geometries, objects, topology)
        self.assertTrue(result["verified"], result)
        self.assertEqual(result["relation_count"], 2)

    def test_stale_spatial_relation_is_rejected(self) -> None:
        geometries = [line(1, 1, 3000.0), line(2, 2, 1000.0)]
        objects = [
            {"object_id": "space-1", "object_type": "space", "label": "已移动",
             "geometry_refs": [1],
             "bounds": {"min_x": 3000, "min_y": 0, "max_x": 4000, "max_y": 1000}},
            {"object_id": "space-2", "object_type": "space", "label": "原位置",
             "geometry_refs": [2],
             "bounds": {"min_x": 1000, "min_y": 0, "max_x": 2000, "max_y": 1000}},
        ]
        topology = {"relations": [{
            "source_object_id": "space-1", "target_object_id": "space-2",
            "relation": "left_of",
        }]}
        result = validate_logical_object_graph(geometries, objects, topology)
        self.assertFalse(result["verified"])
        self.assertIn("topology_relation_mismatch", {
            item["code"] for item in result["errors"]
        })

    def test_continuity_rejects_silent_relation_removal(self) -> None:
        geometries = [line(1, 1, 0.0), line(2, 2, 1000.0)]
        objects = [
            {"object_id": "space-1", "object_type": "space", "label": "左侧",
             "geometry_refs": [1],
             "bounds": {"min_x": 0, "min_y": 0, "max_x": 1000, "max_y": 1000}},
            {"object_id": "space-2", "object_type": "space", "label": "右侧",
             "geometry_refs": [2],
             "bounds": {"min_x": 1000, "min_y": 0, "max_x": 2000, "max_y": 1000}},
        ]
        source_topology = {"relations": [{
            "source_object_id": "space-1", "target_object_id": "space-2",
            "relation": "left_of",
        }]}
        result = validate_logical_object_continuity(
            geometries, geometries, objects, objects,
            source_topology, {}, target_object_ids=[],
        )
        self.assertFalse(result["verified"])
        self.assertIn("topology_relation_drift", {
            item["code"] for item in result["errors"]
        })


if __name__ == "__main__":
    unittest.main()
