from __future__ import annotations

import unittest

from app.cad_target_resolver import (
    bind_resolved_target,
    logical_object_topology_conflict,
    resolve_cad_target,
    resolve_logical_object_target,
    validate_split_shared_boundary_target,
)
from app.agent_skills import (
    build_template_logical_object_graph,
    drawing_template_geometries,
)
from app.agent_service import robot_agent
from app.cad_edit_contract import build_cad_edit_contract, cad_edit_contract_to_edit
from app.incremental_cad import edit_candidate_geometries, parse_incremental_edit


class CadTargetResolverTests(unittest.TestCase):
    def test_logical_object_contract_keeps_identity_and_exact_refs(self) -> None:
        contract = build_cad_edit_contract({
            "operation": "translate",
            "logical_object_id": "parking-space-2",
            "geometry_ids": [2, 3],
            "dx_mm": 0.0,
            "dy_mm": 5000.0,
        })

        self.assertEqual(contract["target"]["scope"], "logical_object")
        self.assertEqual(contract["target"]["object_id"], "parking-space-2")
        self.assertEqual(contract["target"]["geometry_ids"], [2, 3])
        restored = cad_edit_contract_to_edit(contract)
        self.assertEqual(restored["logical_object_id"], "parking-space-2")
        self.assertEqual(restored["geometry_ids"], [2, 3])

    def test_four_connected_parking_spaces_select_middle_two(self) -> None:
        match = {
            "template": "parking", "width_m": 2.5, "height_m": 5.0,
            "quantity": 4,
        }
        geometries = drawing_template_geometries(match)
        graph = build_template_logical_object_graph(match, geometries)
        edit = parse_incremental_edit("把中间的两个停车位整体向前移动5m")
        resolution = resolve_logical_object_target(
            edit["logical_object_selector"], graph["logical_objects"]
        )

        self.assertEqual(
            resolution["object_ids"], ["parking-space-2", "parking-space-3"]
        )
        self.assertGreaterEqual(len(resolution["geometry_ids"]), 2)
        self.assertTrue(graph["topology"]["shared_geometries"])
        self.assertIsNotNone(
            logical_object_topology_conflict(
                resolution["object_ids"], graph["topology"]
            )
        )

    def test_split_contract_is_rebound_to_current_parent_topology(self) -> None:
        match = {"template": "parking", "width_m": 2.5, "height_m": 5.0,
                 "quantity": 4}
        geometries = drawing_template_geometries(match)
        graph = build_template_logical_object_graph(match, geometries)
        resolution = resolve_logical_object_target(
            {"position": "middle", "count": 2, "object_type": "parking_space"},
            graph["logical_objects"],
        )
        contract = {
            "operation": "translate",
            "target": {"scope": "logical_object",
                       "object_ids": resolution["object_ids"],
                       "geometry_ids": resolution["geometry_ids"]},
            "parameters": {"boundary_policy": "split_shared",
                           "shared_geometry_ids": [2, 4],
                           "created_geometry_ids": [14, 15]},
        }
        valid = validate_split_shared_boundary_target(
            contract, geometries, graph["logical_objects"], graph["topology"]
        )
        self.assertTrue(valid["ok"], valid)

        forged = {**contract, "parameters": {
            **contract["parameters"], "shared_geometry_ids": [2, 3],
        }}
        rejected = validate_split_shared_boundary_target(
            forged, geometries, graph["logical_objects"], graph["topology"]
        )
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["reason"], "split_topology_drift")
    def test_middle_parking_space_resolves_by_bounds_not_geometry_order(self) -> None:
        match = {
            "template": "parking", "width_m": 2.5, "height_m": 5.0,
            "quantity": 3,
        }
        geometries = drawing_template_geometries(match)
        graph = build_template_logical_object_graph(match, geometries)
        edit = parse_incremental_edit("将中间的停车位向上移动2m")

        self.assertEqual(edit["logical_object_selector"], {
            "position": "middle", "object_type": "parking_space",
        })
        resolution = resolve_logical_object_target(
            edit["logical_object_selector"], graph["logical_objects"]
        )
        self.assertEqual(resolution["status"], "resolved")
        self.assertEqual(resolution["object_id"], "parking-space-2")
        self.assertEqual(resolution["geometry_ids"], [2, 3, 7, 8])
        conflict = logical_object_topology_conflict(
            resolution["object_id"], graph["topology"]
        )
        self.assertEqual(conflict["reason"], "shared_topology_conflict")
        self.assertEqual(conflict["shared_geometry_ids"], [2, 3])

    def test_even_middle_logical_objects_require_clarification(self) -> None:
        objects = [
            {"object_id": "left", "object_type": "room", "confirmed": True,
             "bounds": {"min_x": -2, "min_y": 0, "max_x": -1, "max_y": 1}},
            {"object_id": "right", "object_type": "room", "confirmed": True,
             "bounds": {"min_x": 1, "min_y": 0, "max_x": 2, "max_y": 1}},
        ]
        resolution = resolve_logical_object_target(
            {"position": "middle", "object_type": "room"}, objects
        )
        self.assertEqual(resolution["status"], "needs_clarification")
        self.assertEqual(resolution["reason"], "even_middle_objects")

    def test_stable_spatial_identity_wins_after_geometry_order_changes(self) -> None:
        objects = [
            {
                "object_id": "court-1", "object_type": "basketball",
                "label": "下方篮球场", "geometry_refs": [1],
                "bounds": {"min_x": 0, "min_y": 0, "max_x": 10, "max_y": 10},
                "spatial_anchor": {"axis": "y", "rank": 1, "count": 2, "position": "bottom"},
                "confirmed": True,
            },
            {
                "object_id": "court-2", "object_type": "basketball",
                "label": "上方篮球场", "geometry_refs": [2],
                "bounds": {"min_x": 0, "min_y": 20, "max_x": 10, "max_y": 30},
                "spatial_anchor": {"axis": "y", "rank": 2, "count": 2, "position": "top"},
                "confirmed": True,
            },
        ]
        objects[0]["bounds"], objects[1]["bounds"] = objects[1]["bounds"], objects[0]["bounds"]
        resolution = resolve_logical_object_target(
            {"object_type": "basketball", "position": "bottom"}, objects
        )
        self.assertEqual(resolution["status"], "resolved")
        self.assertEqual(resolution["object_id"], "court-1")
        self.assertEqual(resolution["reason"], "stable_spatial_identity")

    @staticmethod
    def source() -> list[dict]:
        return [
            {"id": 1, "type": "line", "template_instance": 1,
             "start": {"x": 0, "y": 0}, "end": {"x": 1000, "y": 0}},
            {"id": 2, "type": "line", "template_instance": 2,
             "start": {"x": 3000, "y": 3000}, "end": {"x": 4000, "y": 3000}},
            {"id": 3, "type": "line", "template_instance": 3,
             "start": {"x": 6000, "y": 6000}, "end": {"x": 7000, "y": 6000}},
            {"id": 4, "type": "line", "template_instance": 4,
             "start": {"x": 9000, "y": 9000}, "end": {"x": 10000, "y": 9000}},
        ]

    def test_extreme_superlatives_resolve_requested_count(self) -> None:
        cases = (
            ("最上方的图形向右移动1米", [4]),
            ("最右边两个车位向上移动1米", [3, 4]),
            ("最左侧三个图形向下移动1米", [1, 2, 3]),
        )
        for message, expected in cases:
            with self.subTest(message=message):
                edit = parse_incremental_edit(message)
                self.assertIsNotNone(edit)
                result, error = edit_candidate_geometries(self.source(), edit)
                self.assertIsNone(error)
                self.assertIsNotNone(result)
                targets = edit.get("instances") or [edit.get("instance")]
                self.assertEqual(targets, expected)

    def test_typed_middle_scene_target_resolves_without_canvas_click(self) -> None:
        edit = parse_incremental_edit("将中间的羽毛球场向上移动5m")
        self.assertIsNotNone(edit)
        self.assertEqual(edit["object_type"], "badminton")
        resolution = resolve_cad_target(edit, [
            {"id": 1, "type": "line", "template_type": "basketball", "template_instance": 1,
             "start": {"x": 0, "y": 0}, "end": {"x": 1000, "y": 0}},
            {"id": 2, "type": "line", "template_type": "badminton", "template_instance": 2,
             "start": {"x": 2000, "y": 0}, "end": {"x": 3000, "y": 0}},
            {"id": 3, "type": "line", "template_type": "basketball", "template_instance": 3,
             "start": {"x": 4000, "y": 0}, "end": {"x": 5000, "y": 0}},
        ])
        self.assertEqual(resolution["status"], "resolved")
        self.assertEqual(resolution["instance_ids"], [2])

    def test_clear_extreme_target_includes_ranked_score_evidence(self) -> None:
        resolution = resolve_cad_target(
            {"selector": {"kind": "extreme", "position": "top", "count": 1}},
            self.source(),
        )

        self.assertEqual(resolution["status"], "resolved")
        self.assertEqual(resolution["instance_ids"], [4])
        scoring = resolution["scoring"]
        self.assertEqual(scoring["schema"], "cad.target-score.v1")
        self.assertEqual(scoring["decision"], "resolved")
        self.assertGreaterEqual(scoring["winner_score"], scoring["minimum_score"])
        self.assertGreaterEqual(scoring["margin"], scoring["minimum_margin"])
        self.assertEqual(
            [item["instance_id"] for item in scoring["candidates"]],
            [4, 3, 2, 1],
        )
        self.assertEqual(
            scoring["candidates"][0]["evidence"][0]["kind"],
            "spatial_position",
        )

    def test_near_tied_extreme_target_requires_clarification(self) -> None:
        source = self.source()
        source[2]["start"]["y"] = 8990
        source[2]["end"]["y"] = 8990

        resolution = resolve_cad_target(
            {"selector": {"kind": "extreme", "position": "top", "count": 1}},
            source,
        )

        self.assertEqual(resolution["status"], "needs_clarification")
        self.assertEqual(resolution["reason"], "target_score_margin_too_small")
        self.assertEqual(resolution["confidence"], 0.0)
        self.assertEqual(resolution["candidate_instance_ids"], [1, 2, 3, 4])
        self.assertEqual(
            [
                item["instance_id"]
                for item in resolution["scoring"]["candidates"][:2]
            ],
            [4, 3],
        )
        self.assertGreater(resolution["scoring"]["margin"], 0.0)
        self.assertLess(
            resolution["scoring"]["margin"],
            resolution["scoring"]["minimum_margin"],
        )
        self.assertEqual(resolution["scoring"]["decision"], "clarify")

    def test_low_absolute_position_score_requires_clarification(self) -> None:
        source = [
            {"id": 1, "type": "line", "template_instance": 1,
             "start": {"x": 0, "y": 0}, "end": {"x": 0, "y": 100000}},
            {"id": 2, "type": "line", "template_instance": 2,
             "start": {"x": 1000, "y": 0}, "end": {"x": 1000, "y": 20000}},
        ]

        resolution = resolve_cad_target(
            {"selector": {"kind": "extreme", "position": "top", "count": 1}},
            source,
        )

        self.assertEqual(resolution["status"], "needs_clarification")
        self.assertEqual(resolution["reason"], "target_score_too_low")
        self.assertLess(
            resolution["scoring"]["winner_score"],
            resolution["scoring"]["minimum_score"],
        )
        self.assertEqual(resolution["confidence"], 0.0)

    def test_extreme_boundary_tie_requires_clarification(self) -> None:
        source = self.source()
        source[2]["start"]["x"] = 9000
        source[2]["end"]["x"] = 10000
        edit = parse_incremental_edit("最右边的图形向上移动1米")
        result, error = edit_candidate_geometries(source, edit)
        self.assertIsNone(result)
        self.assertIn("位置相同", error)

        resolution = resolve_cad_target(edit, source)
        self.assertEqual(resolution["reason"], "equal_extreme_position")
        self.assertEqual(resolution["scoring"]["margin"], 0.0)
        self.assertEqual(len(resolution["scoring"]["candidates"]), 4)

    def test_previous_v2_target_resolves_and_stale_target_rejects(self) -> None:
        previous = {
            "schema": "cad.edit.v2", "operation": "translate",
            "target": {"scope": "instance", "instance_ids": [2], "geometry_ids": []},
            "coordinate_frame": "drawing",
            "parameters": {"dx_mm": 1000, "dy_mm": 0},
        }
        resolution = resolve_cad_target(
            {"target_reference": "previous"}, self.source(), previous,
        )
        self.assertEqual(resolution["status"], "resolved")
        self.assertEqual(resolution["instance_ids"], [2])
        target = {"target_reference": "previous"}
        bind_resolved_target(target, resolution)
        self.assertEqual(target["instance"], 2)

        stale = {**previous, "target": {**previous["target"], "instance_ids": [9]}}
        resolution = resolve_cad_target(
            {"target_reference": "previous"}, self.source(), stale,
        )
        self.assertEqual(resolution["status"], "needs_clarification")
        self.assertEqual(resolution["reason"], "stale_previous_target")

    def test_canvas_selection_has_priority_over_explicit_target(self) -> None:
        resolution = resolve_cad_target(
            {"instance": 1}, self.source(),
            drawing_selection={"scope": "entity", "geometry_ids": [3]},
        )
        self.assertEqual(resolution["scope"], "geometry")
        self.assertEqual(resolution["geometry_ids"], [3])
        self.assertEqual(resolution["reason"], "canvas_selection")
        self.assertEqual(resolution["scoring"]["winner_score"], 1.0)
        self.assertEqual(resolution["scoring"]["decision"], "authoritative")

    def test_explicit_instance_remains_authoritative(self) -> None:
        resolution = resolve_cad_target({"instance": 2}, self.source())

        self.assertEqual(resolution["status"], "resolved")
        self.assertEqual(resolution["instance_ids"], [2])
        self.assertEqual(resolution["confidence"], 1.0)
        self.assertEqual(resolution["scoring"]["winner_score"], 1.0)
        self.assertEqual(
            resolution["scoring"]["candidates"][0]["evidence"][0]["kind"],
            "explicit_id",
        )

    def test_unscoped_command_does_not_inherit_previous_target(self) -> None:
        previous = {
            "schema": "cad.edit.v2", "operation": "translate",
            "target": {"scope": "instance", "instance_ids": [2]},
        }
        resolution = resolve_cad_target({}, self.source(), previous)

        self.assertEqual(resolution["status"], "needs_clarification")
        self.assertEqual(resolution["reason"], "target_ambiguous")
        self.assertNotIn("scoring", resolution)

    def test_near_tied_logical_objects_require_clarification(self) -> None:
        objects = [
            {"object_id": "upper-a", "object_type": "room", "confirmed": True,
             "bounds": {"min_x": 0, "min_y": 9.0, "max_x": 2, "max_y": 11.0},
             "geometry_refs": [1]},
            {"object_id": "upper-b", "object_type": "room", "confirmed": True,
             "bounds": {"min_x": 3, "min_y": 9.1, "max_x": 5, "max_y": 11.1},
             "geometry_refs": [2]},
            {"object_id": "lower", "object_type": "room", "confirmed": True,
             "bounds": {"min_x": 0, "min_y": 0, "max_x": 2, "max_y": 2},
             "geometry_refs": [3]},
        ]

        resolution = resolve_logical_object_target(
            {"position": "top", "object_type": "room"}, objects,
        )

        self.assertEqual(resolution["status"], "needs_clarification")
        self.assertEqual(resolution["reason"], "target_score_margin_too_small")
        self.assertEqual(resolution["candidate_object_ids"][:2], ["upper-b", "upper-a"])
        self.assertLess(
            resolution["scoring"]["margin"],
            resolution["scoring"]["minimum_margin"],
        )

    def test_screen_and_unresolved_object_local_frames_fail_closed(self) -> None:
        edit = parse_incremental_edit("第一个图形在屏幕上向上移动1米")
        self.assertEqual(edit["coordinate_frame"], "screen")
        result, error = edit_candidate_geometries(self.source(), edit)
        self.assertIsNone(result)
        self.assertIn("不能直接作为图纸施工方向", error)

        edit = parse_incremental_edit("第一个图形沿长边正方向移动1米")
        self.assertEqual(edit["coordinate_frame"], "object_local")
        result, error = edit_candidate_geometries(self.source(), edit)
        self.assertIsNone(result)
        self.assertIn("局部坐标轴", error)

    def test_ambiguous_target_returns_semantic_replayable_choices(self) -> None:
        source = self.source()
        edit = parse_incremental_edit("把图形向右移动1米")

        clarification = robot_agent._cad_target_clarification(
            "把图形向右移动1米", edit, source,
        )

        self.assertIsNotNone(clarification)
        self.assertEqual(clarification["schema"], "cad.target-clarification.v1")
        self.assertEqual(len(clarification["options"]), 4)
        option = clarification["options"][1]
        self.assertEqual(option["instance_id"], 2)
        self.assertEqual(option["geometry_ids"], [2])
        self.assertEqual(option["reply"], "第2个图形向右移动1000毫米")
        highlighted = [
            item for item in option["preview_paths"]
            if item["selection_state"] == "candidate"
        ]
        self.assertEqual([item["geometry_id"] for item in highlighted], [2])
        self.assertTrue(all(
            item["selection_state"] == "context"
            for item in option["preview_paths"] if item["geometry_id"] != 2
        ))
        replay = parse_incremental_edit(option["reply"])
        self.assertEqual(replay["instance"], 2)
        self.assertEqual(replay["dx_mm"], 1000)

    def test_scored_clarification_exposes_machine_readable_evidence(self) -> None:
        source = self.source()
        source[2]["start"]["y"] = 8990
        source[2]["end"]["y"] = 8990
        edit = parse_incremental_edit("最上方的图形向右移动1米")

        clarification = robot_agent._cad_target_clarification(
            "最上方的图形向右移动1米", edit, source,
        )

        self.assertIsNotNone(clarification)
        self.assertEqual(clarification["reason"], "target_score_margin_too_small")
        self.assertEqual(clarification["scoring"]["schema"], "cad.target-score.v1")
        self.assertEqual(clarification["scoring"]["decision"], "clarify")

    def test_ambiguous_operation_keeps_structured_target_choices(self) -> None:
        source = self.source()
        edit = parse_incremental_edit("把图形复制到右边，间距1米")

        clarification = robot_agent._cad_target_clarification(
            "把图形复制到右边，间距1米", edit, source,
        )

        self.assertIsNotNone(clarification)
        self.assertEqual(clarification["schema"], "cad.target-clarification.v1")
        self.assertEqual(clarification["selection_mode"], "canvas")
        self.assertEqual(len(clarification["options"]), 4)
        self.assertEqual(
            clarification["options"][1]["target_selection"],
            {"scope": "group", "geometry_ids": [2]},
        )
        self.assertNotIn("reply", clarification["options"][1])
        self.assertEqual(
            {item["geometry_id"] for item in clarification["preview_paths"]},
            {1, 2, 3, 4},
        )
        self.assertTrue(all(
            item["route_type"] == "drawing"
            for item in clarification["preview_paths"]
        ))

    def test_mirror_offset_and_array_ambiguity_are_not_filtered_out(self) -> None:
        source = self.source()
        for message in (
            "把图形左右镜像",
            "把图形向外偏移500毫米",
            "把图形阵列成2行3列，行间距2米，列间距3米",
        ):
            edit = parse_incremental_edit(message)
            clarification = robot_agent._cad_target_clarification(
                message, edit, source,
            )
            self.assertIsNotNone(clarification, message)
            self.assertEqual(len(clarification["options"]), 4, message)
            self.assertTrue(all(
                option["target_selection"]["scope"] == "group"
                for option in clarification["options"]
            ))

    def test_ungrouped_geometry_still_opens_full_canvas_selection(self) -> None:
        source = self.source()
        for item in source:
            item.pop("template_instance", None)
        edit = parse_incremental_edit("把图形向右移动1米")

        clarification = robot_agent._cad_target_clarification(
            "把图形向右移动1米", edit, source,
            failure_message="当前图纸没有已确认的实例分组。",
        )

        self.assertIsNotNone(clarification)
        self.assertEqual(len(clarification["options"]), 4)
        self.assertEqual(
            clarification["options"][0]["target_selection"],
            {"scope": "entity", "geometry_ids": [1]},
        )
        self.assertTrue(all(
            option["scope"] == "geometry"
            for option in clarification["options"]
        ))
        self.assertEqual(clarification["selection_scopes"], ["logical_object", "geometry"])
        self.assertEqual(len(clarification["preview_paths"]), 4)
        self.assertEqual(
            clarification["question"], "当前图纸没有已确认的实例分组。"
        )


if __name__ == "__main__":
    unittest.main()
