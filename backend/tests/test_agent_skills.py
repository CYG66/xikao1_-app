from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agent_skills import (
    DRAWING_TEMPLATE_SKILLS,
    _template_layout_requirements,
    check_drawing_feasibility,
    diff_drawings,
    inspect_drawing,
    list_elements,
    clarify_requirements,
    drawing_template_geometries,
    drawing_template_motion_steps,
    compose_template_geometries,
    layer_drawing_paths,
    parameterize_design,
    recommend_recovery,
    recognize_drawing_template,
    score_design_variant,
    snapshot_drawing,
    validate_drawing,
    validate_template_layout,
    normalize_template_layout_for_matches,
    recognize_drawing_template_set,
    apply_drawing_modifications,
    build_template_logical_object_graph,
    heart_outline_geometry,
)
from app.drawing_commands import execute_drawing_commands
from app.state import robot_state


class AgentSkillsTest(unittest.TestCase):
    def test_heart_outline_request_is_complete_and_centered(self) -> None:
        result = parameterize_design(
            "新建一个CAD图纸，生成一个左右对称的闭合爱心轮廓，"
            "整体宽度和高度均不超过5米，使用平滑曲线连接，"
            "中心位于坐标原点，不要自相交。"
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["shape"], "heart_outline")
        self.assertEqual(result["dimensions"], {"width_m": 5.0, "height_m": 5.0})
        self.assertEqual(result["origin"], "drawing_origin")
        self.assertEqual(result["missing"], [])
        self.assertTrue(result["closed"])
        self.assertTrue(result["smooth"])
        self.assertTrue(result["symmetric"])

    def test_heart_outline_geometry_has_exact_bounds(self) -> None:
        geometry = heart_outline_geometry(5.0, 4.0)
        vertices = geometry["vertices"]
        self.assertEqual(geometry["type"], "polyline")
        self.assertTrue(geometry["closed"])
        self.assertEqual(len(vertices), 128)
        self.assertAlmostEqual(min(item["x"] for item in vertices), -2500.0, places=3)
        self.assertAlmostEqual(max(item["x"] for item in vertices), 2500.0, places=3)
        self.assertAlmostEqual(min(item["y"] for item in vertices), -2000.0, places=3)
        self.assertAlmostEqual(max(item["y"] for item in vertices), 2000.0, places=3)

    def test_mixed_court_parameterization_preserves_explicit_layout(self) -> None:
        result = parameterize_design(
            "规划一个标准篮球场与一个标准羽毛球场，长边并排，间距为3m"
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["arrangement"], "long_side_adjacent")
        self.assertEqual(result["spacing_m"], 3.0)
        self.assertTrue(result["layout_override"])
        self.assertNotIn("未指定组合位置时按提及顺序水平并排", result["assumptions"])

    def test_layout_synonyms_keep_direction_and_distance(self) -> None:
        cases = {
            "长边并排，间距为2m": ("long_side_adjacent", 2.0, None),
            "短边并排，间隔2000毫米": ("short_side_adjacent", 2.0, None),
            "长边排列，净距200厘米": ("long_side_adjacent", 2.0, None),
            "长边并排，相隔二米": ("long_side_adjacent", 2.0, None),
            "长边并排，2m间距": ("long_side_adjacent", 2.0, None),
            "左右并排，距离2米": ("long_side_adjacent", 2.0, "right"),
            "上下并排，距离2米": ("long_side_adjacent", 2.0, "above"),
        }
        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                layout = _template_layout_requirements(prompt)
                self.assertEqual(layout.get("arrangement"), expected[0])
                self.assertEqual(layout.get("spacing_m"), expected[1])
                self.assertEqual(layout.get("peer_placement"), expected[2])

    def test_vertical_layout_phrase_and_named_top_court_are_explicit(self) -> None:
        layout = _template_layout_requirements(
            "上下排列，间距为2m，并且羽毛球场在上方"
        )
        self.assertEqual(layout["arrangement"], "long_side_adjacent")
        self.assertEqual(layout["spacing_m"], 2.0)
        self.assertEqual(layout["peer_placement"], "above")

    def test_layout_can_inherit_spacing_from_current_candidate(self) -> None:
        layout = _template_layout_requirements(
            "改成短边并排，间距为不变，篮球场在左侧"
        )
        self.assertEqual(layout["arrangement"], "short_side_adjacent")
        self.assertTrue(layout["preserve_spacing"])
        self.assertEqual(layout["placement_template"], "basketball")
        self.assertEqual(layout["peer_placement"], "left")

    def test_layout_validation_rejects_horizontal_geometry_for_vertical_request(self) -> None:
        source = compose_template_geometries([
            {"template": "basketball", "quantity": 1},
            {"template": "badminton", "quantity": 1, "placement": ["right"]},
        ])
        self.assertIsNotNone(source)
        result = validate_template_layout(
            source or [],
            arrangement="long_side_adjacent",
            spacing_m=2.0,
            peer_placement="above",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("净距" in item for item in result["errors"]))

    def test_named_primary_template_position_is_inverted_for_secondary_translation(self) -> None:
        matches = recognize_drawing_template_set("篮球场与羽毛球场组合")
        layout = _template_layout_requirements("篮球场在上方，间距2米")
        normalized = normalize_template_layout_for_matches(matches, layout)
        self.assertEqual(normalized["placement_template"], "basketball")
        self.assertEqual(normalized["peer_placement"], "below")

    def test_conflicting_layout_direction_is_not_silently_resolved(self) -> None:
        layout = _template_layout_requirements("上下排列又左右并排，间距2米")
        self.assertIn("layout_conflicts", layout)
        self.assertTrue(any("横向" in item and "纵向" in item for item in layout["layout_conflicts"]))

    def test_conflicting_spacing_values_are_not_silently_resolved(self) -> None:
        layout = _template_layout_requirements("上下排列，间距2米，间距改成3米")
        self.assertIn("layout_conflicts", layout)
        self.assertTrue(any("间距" in item for item in layout["layout_conflicts"]))

    def test_list_elements_returns_filtered_stable_catalog(self) -> None:
        source = [
            {"id": 1, "type": "line", "layer_id": 1, "template_instance": 1,
             "template_type": "parking", "start": {"x": 0, "y": 0},
             "end": {"x": 1000, "y": 0}},
            {"id": 2, "type": "circle", "layer_id": 2, "template_instance": 2,
             "template_type": "parking", "center": {"x": 3000, "y": 0},
             "radius": 200},
        ]
        result = list_elements(source, instance_ids=[2])
        self.assertEqual(result["schema"], "cad.element-list.v1")
        self.assertEqual(result["instance_count"], 1)
        self.assertEqual(result["element_count"], 1)
        self.assertEqual(result["instances"][0]["instance_id"], 2)
        self.assertEqual(result["elements"][0]["geometry_id"], 2)
        self.assertFalse(result["execution_allowed"])

    def test_cad_inspection_tools_return_machine_readable_contracts(self) -> None:
        source = [{
            "id": 1, "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        }]
        target = [{
            "id": 1, "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 2000, "y": 0, "z": 0},
        }]

        inspection = inspect_drawing(source)
        self.assertEqual(inspection["contract_version"], "cad-inspect-1.0")
        self.assertEqual(inspection["type_counts"], {"line": 1})
        self.assertEqual(inspection["entity_count"], 1)

        diff = diff_drawings(source, target)
        self.assertEqual(diff["contract_version"], "cad-diff-1.0")
        self.assertTrue(diff["requires_replan"])
        self.assertFalse(diff["execution_allowed"])

        validation = validate_drawing(source)
        self.assertEqual(validation["status"], "valid")
        self.assertFalse(validation["execution_allowed"])

        snapshot = snapshot_drawing(source, "before")
        self.assertEqual(snapshot["contract_version"], "cad-snapshot-1.0")
        self.assertEqual(snapshot["snapshot_id"], snapshot_drawing(source, "after")["snapshot_id"])
        self.assertFalse(snapshot["persisted"])
    def test_drawing_edit_batch_is_atomic_and_returns_commands(self) -> None:
        source = [{
            "id": 1, "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        }]
        result = apply_drawing_modifications(source, [
            {"op": "update", "id": 1, "geometry": {
                "type": "line", "layer_id": 1,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 2000, "y": 0, "z": 0},
            }},
            {"op": "remove", "id": 999},
        ])

        self.assertFalse(result["ok"])
        self.assertTrue(result["rolled_back"])
        self.assertEqual(result["geometries"], source)
        self.assertEqual(result["commands"], [])
        rollback = result["rollback_evidence"]
        self.assertTrue(rollback["triggered"])
        self.assertEqual(rollback["applied_command_count"], 1)
        self.assertEqual(rollback["source_snapshot_id"], rollback["restored_snapshot_id"])
        self.assertTrue(rollback["verified"])
        self.assertFalse(rollback["persisted"])

    def test_drawing_edit_batch_records_before_and_after(self) -> None:
        source = [{
            "id": 1, "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        }]
        result = apply_drawing_modifications(source, [{
            "op": "update", "id": 1, "geometry": {
                "type": "line", "layer_id": 1,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 2000, "y": 0, "z": 0},
            },
        }])

        self.assertTrue(result["ok"])
        self.assertFalse(result["rolled_back"])
        self.assertEqual(result["commands"][0]["command_type"], "UPDATE")
        self.assertEqual(result["commands"][0]["before"]["end"]["x"], 1000)
        self.assertEqual(result["commands"][0]["after"]["end"]["x"], 2000)
        batch = result["command_batch"]
        self.assertEqual(batch["contract_version"], "cad-command-batch-1.0")
        self.assertTrue(batch["verified"])
        self.assertEqual(batch["counts"], {"create": 0, "update": 1, "delete": 0})
        self.assertNotEqual(batch["source_snapshot_id"], batch["target_snapshot_id"])

    def test_drawing_command_rejects_stale_entity_atomically(self) -> None:
        source = [{
            "id": 1, "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        }]
        result = apply_drawing_modifications(source, [{
            "op": "update", "id": 1, "geometry": {
                "type": "line", "layer_id": 1,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 2000, "y": 0, "z": 0},
            },
        }])
        changed_source = [{
            **source[0],
            "end": {"x": 1500, "y": 0, "z": 0},
        }]

        replay = execute_drawing_commands(changed_source, result["commands"])

        self.assertFalse(replay["ok"])
        self.assertEqual(replay["geometries"], changed_source)
        self.assertIn("已发生变化", replay["errors"][0])
        self.assertFalse(replay["rollback_evidence"]["triggered"])
        self.assertEqual(replay["rollback_evidence"]["applied_command_count"], 0)
        self.assertTrue(replay["rollback_evidence"]["verified"])

    def test_drawing_command_proves_partial_batch_was_rolled_back(self) -> None:
        source = [
            {
                "id": 1, "type": "line", "layer_id": 1,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 1000, "y": 0, "z": 0},
            },
            {
                "id": 2, "type": "line", "layer_id": 1,
                "start": {"x": 0, "y": 1000, "z": 0},
                "end": {"x": 1000, "y": 1000, "z": 0},
            },
        ]
        prepared = apply_drawing_modifications(source, [
            {"op": "update", "id": 1, "geometry": {
                **source[0], "end": {"x": 2000, "y": 0, "z": 0},
            }},
            {"op": "update", "id": 2, "geometry": {
                **source[1], "end": {"x": 2000, "y": 1000, "z": 0},
            }},
        ])
        changed_source = [source[0], {
            **source[1], "end": {"x": 1500, "y": 1000, "z": 0},
        }]

        replay = execute_drawing_commands(changed_source, prepared["commands"])

        self.assertFalse(replay["ok"])
        self.assertEqual(replay["geometries"], changed_source)
        rollback = replay["rollback_evidence"]
        self.assertTrue(rollback["triggered"])
        self.assertEqual(rollback["applied_command_count"], 1)
        self.assertEqual(rollback["source_snapshot_id"], rollback["restored_snapshot_id"])
        self.assertTrue(rollback["verified"])

    def test_drawing_command_rejects_tampered_result(self) -> None:
        source = [{
            "id": 1, "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        }]
        result = apply_drawing_modifications(source, [{
            "op": "update", "id": 1, "geometry": {
                "type": "line", "layer_id": 1,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 2000, "y": 0, "z": 0},
            },
        }])
        result["commands"][0]["after"]["end"]["x"] = 9000

        replay = execute_drawing_commands(source, result["commands"])

        self.assertFalse(replay["ok"])
        self.assertEqual(replay["geometries"], source)
        self.assertTrue(any("哈希" in error or "命令 ID" in error for error in replay["errors"]))

    def test_drawing_edit_batch_records_each_repeated_update(self) -> None:
        source = [{
            "id": 1, "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        }]
        result = apply_drawing_modifications(source, [
            {"op": "update", "id": 1, "geometry": {
                "type": "line", "layer_id": 1,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 2000, "y": 0, "z": 0},
            }},
            {"op": "update", "id": 1, "geometry": {
                "type": "line", "layer_id": 1,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 3000, "y": 0, "z": 0},
            }},
        ])

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["commands"]), 2)
        self.assertEqual(result["commands"][0]["before"]["end"]["x"], 1000)
        self.assertEqual(result["commands"][0]["after"]["end"]["x"], 2000)
        self.assertEqual(result["commands"][1]["before"]["end"]["x"], 2000)
        self.assertEqual(result["commands"][1]["after"]["end"]["x"], 3000)
    def test_every_drawing_editor_template_has_local_skill_and_motion_preview(self) -> None:
        for skill in DRAWING_TEMPLATE_SKILLS.values():
            match = recognize_drawing_template(skill["aliases"][0])
            self.assertIsNotNone(match)
            steps = drawing_template_motion_steps(match)
            self.assertGreaterEqual(len(steps), 2, skill["label"])

    def test_parameterization_defaults_to_center_printer_while_offline(self) -> None:
        with patch.object(robot_state, "printer_status", {}):
            result = parameterize_design("画一个 5x3 米矩形")

        self.assertEqual(result["shape"], "rectangle")
        self.assertEqual(result["dimensions"], {"width_m": 5.0, "height_m": 3.0})
        self.assertEqual(result["printer"], "center")
        self.assertNotIn("printer", result["missing"])
        self.assertTrue(result["ok"])

    def test_three_parking_spaces_preserve_quantity_and_generate_three_bays(self) -> None:
        with patch.object(robot_state, "printer_status", {}):
            result = parameterize_design("绘制三个并排标准车位")

        self.assertEqual(result["shape"], "parking")
        self.assertEqual(result["quantity"], 3)
        geometries = drawing_template_geometries(
            recognize_drawing_template("绘制三个并排标准车位")
        )
        self.assertEqual(len(geometries), 10)
        outer_x = [
            point["x"]
            for geometry in geometries
            for point in (geometry.get("start"), geometry.get("end"))
            if isinstance(point, dict)
        ]
        self.assertEqual(max(outer_x) - min(outer_x), 7500.0)
        graph = build_template_logical_object_graph(
            recognize_drawing_template("绘制三个并排标准车位"), geometries
        )
        self.assertEqual(
            [item["object_id"] for item in graph["logical_objects"]],
            ["parking-space-1", "parking-space-2", "parking-space-3"],
        )
        self.assertEqual(
            graph["logical_objects"][1]["geometry_refs"], [2, 3, 7, 8]
        )
        self.assertEqual(
            [item["geometry_id"] for item in graph["topology"]["shared_geometries"]],
            [2, 3],
        )

    def test_parking_quantity_accepts_standard_connected_word_order(self) -> None:
        match = recognize_drawing_template("生成4个标准的相连停车位")
        self.assertIsNotNone(match)
        self.assertEqual(match["template"], "parking")
        self.assertEqual(match["quantity"], 4)
        self.assertEqual(match["arrangement"], "long_side_adjacent")

    def test_composite_requirement_summary_keeps_each_standard_template_size(self) -> None:
        result = parameterize_design(
            "规划一个标准的篮球场与一个标准的羽毛球场，用于地面划线"
        )

        self.assertEqual(result["quantity"], 2)
        self.assertEqual(
            [
                (item["template"], item["quantity"], item["dimensions"])
                for item in result["template_components"]
            ],
            [
                ("basketball", 1, {"width_m": 28.0, "height_m": 15.0}),
                ("badminton", 1, {"width_m": 13.4, "height_m": 6.1}),
            ],
        )
        self.assertTrue(
            any("按提及顺序水平并排" in item for item in result["assumptions"])
        )

    def test_repeated_composite_size_description_parameterizes_both_venues(self) -> None:
        result = parameterize_design(
            "规划一个标准的篮球场与一个标准的羽毛球场，用于地面喷墨划线。"
            "篮球场按标准尺寸28m×15m，羽毛球场按标准尺寸13.4m×6.1m。"
        )

        self.assertEqual(result["quantity"], 2)
        self.assertEqual(
            [item["template"] for item in result["template_components"]],
            ["basketball", "badminton"],
        )
        self.assertEqual(result["spacing_m"], 0.0)

    def test_two_room_template_builds_shared_logical_rooms(self) -> None:
        match = recognize_drawing_template("一个8x6米的两室布局")
        geometries = drawing_template_geometries(match)
        graph = build_template_logical_object_graph(match, geometries)

        self.assertEqual(
            [item["object_id"] for item in graph["logical_objects"]],
            ["room-1", "room-2"],
        )
        self.assertEqual(
            graph["topology"]["shared_geometries"][0]["object_ids"],
            ["room-1", "room-2"],
        )

    def test_all_repeatable_templates_generate_requested_instances(self) -> None:
        prompts = {
            "room": "两个矩形房间并排，间距1m",
            "two_rooms": "两个两室布局并排，间距1m",
            "corridor": "两个长走廊并排，间距1m",
            "parking_lot": "两个停车场并排，间距1m",
            "basketball": "两个篮球场并排，间距1m",
            "badminton": "两个羽毛球场并排，间距1m",
            "warehouse": "两个仓库网格并排，间距1m",
            "grid": "两个施工轴网并排，间距1m",
            "foundation": "两个圆形基础并排，间距1m",
        }

        for template_name, prompt in prompts.items():
            with self.subTest(template=template_name):
                match = recognize_drawing_template(prompt)
                self.assertIsNotNone(match)
                self.assertEqual(match["template"], template_name)
                self.assertEqual(match["quantity"], 2)
                geometries = drawing_template_geometries(match)
                self.assertEqual(
                    {item.get("template_instance") for item in geometries},
                    {1, 2},
                )
                self.assertEqual(
                    {item.get("template_type") for item in geometries},
                    {template_name},
                )

    def test_parameterization_uses_single_online_robot_printer(self) -> None:
        status = {
            "printer_center": {
                "connected": True,
                "is_online": True,
                "enabled": True,
                "device_id": 0,
            }
        }
        with patch.object(robot_state, "printer_status", status):
            result = parameterize_design("画一个半径 0.5 米的圆")

        self.assertEqual(result["printer"], "center")
        self.assertNotIn("printer", result["missing"])
        self.assertTrue(result["ok"])

    def test_clarification_returns_questions_for_missing_parameters(self) -> None:
        result = clarify_requirements("画一个矩形")

        self.assertFalse(result["ready_for_design"])
        self.assertIn("dimensions", result["missing"])
        self.assertTrue(result["questions"])

    def test_feasibility_rejects_degenerate_geometry(self) -> None:
        result = check_drawing_feasibility([
            {
                "id": 1,
                "type": "line",
                "layer_id": 1,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 0, "y": 0, "z": 0},
            }
        ])

        self.assertFalse(result["ok"])
        self.assertTrue(result["errors"])

    def test_feasibility_blocks_crossing_paths(self) -> None:
        result = check_drawing_feasibility([
            {
                "id": 1, "type": "polyline", "layer_id": 1,
                "vertices": [
                    {"x": 0, "y": 0, "z": 0},
                    {"x": 1000, "y": 1000, "z": 0},
                    {"x": 0, "y": 1000, "z": 0},
                    {"x": 1000, "y": 0, "z": 0},
                ],
            },
        ])

        self.assertFalse(result["ok"])
        self.assertIn("自相交", " ".join(result["errors"]))

    def test_feasibility_blocks_duplicate_geometry(self) -> None:
        line = {
            "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        }
        result = check_drawing_feasibility([
            {"id": 1, **line},
            {"id": 2, **line},
        ])

        self.assertFalse(result["ok"])
        self.assertIn("重复几何", " ".join(result["errors"]))

    def test_path_layering_leaves_travel_to_xline_planner(self) -> None:
        result = layer_drawing_paths([
            {
                "id": 1,
                "type": "line",
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 1000, "y": 0, "z": 0},
            }
        ], "center")

        self.assertEqual(result["layers"][0]["route_type"], "printing")
        self.assertEqual(result["layers"][0]["printer"], "center")
        self.assertEqual(result["travel_policy"], "generated_by_xline_ws3_planner")
        self.assertNotIn("travel_paths", result)

    def test_path_layering_preserves_four_cad_semantics(self) -> None:
        geometries = []
        for index, semantic in enumerate(("DRAW", "TRAVEL", "SKIP", "AUXILIARY"), 1):
            geometries.append({
                "id": index, "type": "line", "layer_id": index,
                "path_semantic": semantic,
                "start": {"x": 0, "y": index, "z": 0},
                "end": {"x": 1000, "y": index, "z": 0},
            })

        result = layer_drawing_paths(geometries, "center")

        self.assertEqual(
            {item["path_semantic"] for item in result["lines"]},
            {"DRAW", "TRAVEL", "SKIP", "AUXILIARY"},
        )
        draw = next(item for item in result["lines"] if item["path_semantic"] == "DRAW")
        self.assertEqual(draw["role"], "printing")
        self.assertTrue(all(
            item.get("selected") is False
            for item in result["lines"] if item["path_semantic"] != "DRAW"
        ))

    def test_parameterization_rejects_nonexistent_side_printer(self) -> None:
        status = {
            "printer_center": {"connected": True, "enabled": True},
        }
        with patch.object(robot_state, "printer_status", status):
            result = parameterize_design("用左喷头画一个 5x3 米矩形")

        self.assertFalse(result["ok"])
        self.assertIn(
            "unsupported_printer:xline_ws3_only_has_center",
            result["missing"],
        )

    def test_design_score_is_not_reported_as_ros_planning_score(self) -> None:
        result = score_design_variant([{
            "id": 1, "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        }])

        self.assertEqual(result["score_type"], "design_only")
        self.assertTrue(result["requires_ros_planning_score"])

    def test_recovery_requires_stop_and_never_auto_resumes(self) -> None:
        result = recommend_recovery({
            "mission_running": True,
            "localization_valid": False,
            "control_ready": True,
            "printer_ready": True,
            "mission_required_printers": [],
            "obstacle_distances": {},
            "mission_error": "",
        })

        self.assertTrue(result["stop_required"])
        self.assertFalse(result["auto_resume_allowed"])
        self.assertTrue(result["reasons"])


if __name__ == "__main__":
    unittest.main()
