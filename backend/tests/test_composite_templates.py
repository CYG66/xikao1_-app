from __future__ import annotations

import unittest

from app.agent_skills import (
    calculate_geometry_bounds,
    check_drawing_feasibility,
    compose_template_geometries,
    compose_template_instance_count,
    build_template_logical_object_graph,
    parameterize_design,
    recognize_drawing_template,
    recognize_drawing_template_set,
)
from app.cad_project_candidates import (
    candidate_generation_context,
    candidate_requirement_readiness,
    design_geometries_for_project,
)


class CompositeTemplateTest(unittest.TestCase):
    """Composite template recognition: '在篮球场的上下方各添加一个羽毛球场'."""

    def test_composite_recognition_keeps_both_templates(self) -> None:
        matches = recognize_drawing_template_set(
            "在篮球场的上下方各添加一个羽毛球场"
        )
        self.assertIsNotNone(matches)
        self.assertEqual(
            [item["template"] for item in matches], ["basketball", "badminton"]
        )
        self.assertEqual(matches[1]["placement"], ["above", "below"])
        self.assertEqual(compose_template_instance_count(matches), 3)

    def test_heart_outline_legacy_project_is_reconciled_before_generation(self) -> None:
        prompt = (
            "新建一个CAD图纸，生成一个左右对称的闭合爱心轮廓，"
            "整体宽度和高度均不超过5米，使用平滑曲线连接，"
            "中心位于坐标原点，不要自相交。"
        )
        project = {
            "id": "legacy-heart",
            "name": "对称爱心轮廓 CAD 图纸",
            "original_prompt": prompt,
            "status": "clarifying",
            "requirements": {"printer": "center"},
            "missing_parameters": ["shape", "dimensions"],
            "variants": [],
        }
        readiness = candidate_requirement_readiness(
            project, {"prompt": prompt}
        )
        self.assertTrue(readiness["ready"])
        self.assertEqual(readiness["missing"], [])
        self.assertEqual(
            readiness["inferred_requirements"]["shape"], "heart_outline"
        )

        context = candidate_generation_context(project, {})
        self.assertEqual(context["expected_template_name"], "heart_outline")
        geometries, missing = design_geometries_for_project(project, {})
        self.assertEqual(missing, [])
        self.assertIsNotNone(geometries)
        self.assertEqual(len(geometries), 1)
        self.assertEqual(geometries[0]["semantic"], "heart_outline")

    def test_heart_outline_parser_preserves_explicit_shape(self) -> None:
        result = parameterize_design(
            "生成一个宽4米高3米的闭合爱心轮廓，中心在原点"
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["shape"], "heart_outline")
        self.assertEqual(result["dimensions"], {"width_m": 4.0, "height_m": 3.0})

    def test_composite_geometries_include_badminton_and_pass_gate(self) -> None:
        matches = recognize_drawing_template_set(
            "在篮球场的上下方各添加一个羽毛球场"
        )
        geometries = compose_template_geometries(matches)
        self.assertIsNotNone(geometries)
        self.assertEqual(len(geometries), 37)
        self.assertEqual(
            sorted({item["template_instance"] for item in geometries}), [1, 2, 3]
        )
        feasibility = check_drawing_feasibility(geometries)
        self.assertTrue(feasibility["ok"], feasibility["errors"])

    def test_standard_basketball_and_badminton_default_to_horizontal_peer_layout(self) -> None:
        prompt = "规划一个标准的篮球场与一个标准的羽毛球场，用于地面划线"
        matches = recognize_drawing_template_set(prompt)

        self.assertIsNotNone(matches)
        self.assertEqual(
            [(item["template"], item["quantity"]) for item in matches],
            [("basketball", 1), ("badminton", 1)],
        )
        self.assertEqual(matches[1]["placement"], ["right"])
        self.assertTrue(matches[1]["placement_inferred"])
        self.assertEqual(compose_template_instance_count(matches), 2)

        geometries = compose_template_geometries(matches)
        self.assertIsNotNone(geometries)
        by_type = {
            template_type: [item for item in geometries if item["template_type"] == template_type]
            for template_type in ("basketball", "badminton")
        }
        self.assertEqual(
            {key: {item["template_instance"] for item in items} for key, items in by_type.items()},
            {"basketball": {1}, "badminton": {2}},
        )
        basketball_bounds = calculate_geometry_bounds(by_type["basketball"])["bounds"]
        badminton_bounds = calculate_geometry_bounds(by_type["badminton"])["bounds"]
        self.assertAlmostEqual(basketball_bounds["max_x_mm"], badminton_bounds["min_x_mm"])
        total_bounds = calculate_geometry_bounds(geometries)["bounds"]
        self.assertAlmostEqual(total_bounds["width_mm"], 41400.0)
        self.assertAlmostEqual(total_bounds["height_mm"], 15000.0)
        self.assertTrue(check_drawing_feasibility(geometries)["ok"])

    def test_repeated_template_names_in_size_explanation_remain_composite(self) -> None:
        prompt = (
            "规划一个标准的篮球场与一个标准的羽毛球场，用于地面喷墨划线。"
            "篮球场按标准尺寸28m×15m，羽毛球场按标准尺寸13.4m×6.1m。"
        )
        matches = recognize_drawing_template_set(prompt)

        self.assertIsNotNone(matches)
        self.assertEqual(
            [(item["template"], item["quantity"]) for item in matches],
            [("basketball", 1), ("badminton", 1)],
        )
        self.assertEqual(matches[1]["placement"], ["right"])
        geometries = compose_template_geometries(matches)
        self.assertEqual(
            {
                (item["template_type"], item["template_instance"])
                for item in geometries
            },
            {("basketball", 1), ("badminton", 2)},
        )

    def test_explicit_long_side_layout_overrides_inferred_peer_direction(self) -> None:
        matches = recognize_drawing_template_set(
            "规划一个标准的篮球场与一个标准的羽毛球场"
        )
        self.assertIsNotNone(matches)
        matches[0]["arrangement"] = "long_side_adjacent"
        matches[0]["spacing_m"] = 2.0

        geometries = compose_template_geometries(matches)
        self.assertIsNotNone(geometries)
        basketball = [
            item for item in geometries
            if item.get("template_type") == "basketball"
        ]
        badminton = [
            item for item in geometries
            if item.get("template_type") == "badminton"
        ]
        basketball_bounds = calculate_geometry_bounds(basketball)["bounds"]
        badminton_bounds = calculate_geometry_bounds(badminton)["bounds"]
        self.assertAlmostEqual(
            badminton_bounds["min_y_mm"] - basketball_bounds["max_y_mm"],
            2000.0,
        )
        self.assertAlmostEqual(
            (basketball_bounds["min_x_mm"] + basketball_bounds["max_x_mm"]) / 2,
            (badminton_bounds["min_x_mm"] + badminton_bounds["max_x_mm"]) / 2,
        )

    def test_recognized_mixed_courts_keep_long_side_layout_and_gap(self) -> None:
        matches = recognize_drawing_template_set(
            "规划一个标准篮球场与一个标准羽毛球场，长边并排，间距为3m"
        )
        self.assertIsNotNone(matches)
        self.assertEqual(matches[0]["arrangement"], "long_side_adjacent")
        self.assertEqual(matches[0]["spacing_m"], 3.0)
        self.assertTrue(matches[0]["layout_override"])

        geometries = compose_template_geometries(matches)
        self.assertIsNotNone(geometries)
        basketball_bounds = calculate_geometry_bounds([
            item for item in geometries
            if item.get("template_type") == "basketball"
        ])["bounds"]
        badminton_bounds = calculate_geometry_bounds([
            item for item in geometries
            if item.get("template_type") == "badminton"
        ])["bounds"]
        self.assertAlmostEqual(
            badminton_bounds["min_y_mm"] - basketball_bounds["max_y_mm"],
            3000.0,
        )
        self.assertAlmostEqual(
            (basketball_bounds["min_x_mm"] + basketball_bounds["max_x_mm"]) / 2,
            (badminton_bounds["min_x_mm"] + badminton_bounds["max_x_mm"]) / 2,
        )

    def test_latest_layout_requirement_overrides_old_explicit_position(self) -> None:
        matches = recognize_drawing_template_set(
            "在篮球场右边放一个羽毛球场"
        )
        self.assertIsNotNone(matches)
        self.assertFalse(matches[1].get("placement_inferred", False))
        matches[0].update({
            "arrangement": "long_side_adjacent",
            "spacing_m": 2.0,
            "layout_override": True,
        })

        geometries = compose_template_geometries(matches)
        basketball = [
            item for item in geometries
            if item.get("template_type") == "basketball"
        ]
        badminton = [
            item for item in geometries
            if item.get("template_type") == "badminton"
        ]
        basketball_bounds = calculate_geometry_bounds(basketball)["bounds"]
        badminton_bounds = calculate_geometry_bounds(badminton)["bounds"]
        self.assertAlmostEqual(
            badminton_bounds["min_y_mm"] - basketball_bounds["max_y_mm"],
            2000.0,
        )

    def test_left_placement_composite(self) -> None:
        matches = recognize_drawing_template_set("在篮球场左边加一个羽毛球场")
        self.assertEqual(matches[1]["placement"], ["left"])
        geometries = compose_template_geometries(matches)
        self.assertEqual(len(geometries), 28)
        self.assertTrue(check_drawing_feasibility(geometries)["ok"])

    def test_right_placement_with_quantity(self) -> None:
        matches = recognize_drawing_template_set("篮球场右边放2个羽毛球场")
        self.assertEqual(matches[1]["quantity"], 2)
        self.assertEqual(matches[1]["placement"], ["right"])
        self.assertEqual(compose_template_instance_count(matches), 3)
        geometries = compose_template_geometries(matches)
        self.assertEqual(
            sorted({item["template_instance"] for item in geometries}), [1, 2, 3]
        )

    def test_middle_template_is_interleaved_on_long_axis_with_exact_spacing(self) -> None:
        prompt = (
            "规划两个标准的篮球场，中间夹着个羽毛球场，"
            "他们3个的间距为2m，长边平行一字排开"
        )
        matches = recognize_drawing_template_set(prompt)

        self.assertIsNotNone(matches)
        self.assertEqual(
            [(item["template"], item["quantity"]) for item in matches],
            [("basketball", 2), ("badminton", 1)],
        )
        self.assertEqual(matches[1]["placement"], ["between"])
        self.assertEqual(matches[1]["sequence_axis"], "long")

        geometries = compose_template_geometries(matches)
        self.assertIsNotNone(geometries)
        by_instance = {
            instance: [
                item for item in geometries
                if item.get("template_instance") == instance
            ]
            for instance in (1, 2, 3)
        }
        self.assertEqual(
            [items[0]["template_type"] for items in by_instance.values()],
            ["basketball", "badminton", "basketball"],
        )
        bounds = {
            instance: calculate_geometry_bounds(items)["bounds"]
            for instance, items in by_instance.items()
        }
        self.assertAlmostEqual(
            bounds[2]["min_y_mm"] - bounds[1]["max_y_mm"], 2000.0
        )
        self.assertAlmostEqual(
            bounds[3]["min_y_mm"] - bounds[2]["max_y_mm"], 2000.0
        )
        total = calculate_geometry_bounds(geometries)["bounds"]
        self.assertAlmostEqual(total["width_mm"], 28000.0)
        self.assertAlmostEqual(total["height_mm"], 40100.0)
        self.assertTrue(check_drawing_feasibility(geometries)["ok"])
        graph = build_template_logical_object_graph(
            {"template": "basketball", "quantity": 3}, geometries
        )
        self.assertEqual(
            [item["object_type"] for item in graph["logical_objects"]],
            ["basketball", "badminton", "basketball"],
        )

    def test_same_scene_repeat_is_not_composite(self) -> None:
        # 停车场 + 8个车位 describe one scene; must not become a composite.
        matches = recognize_drawing_template_set("停车场间距1.5米并排8个车位")
        self.assertIsNone(matches)
        legacy = recognize_drawing_template("停车场间距1.5米并排8个车位")
        self.assertEqual(legacy["template"], "parking")
        self.assertEqual(legacy["quantity"], 8)

    def test_single_template_still_single(self) -> None:
        matches = recognize_drawing_template_set("画一个篮球场")
        self.assertIsNone(matches)
        self.assertEqual(
            recognize_drawing_template("画一个篮球场")["template"], "basketball"
        )


if __name__ == "__main__":
    unittest.main()
