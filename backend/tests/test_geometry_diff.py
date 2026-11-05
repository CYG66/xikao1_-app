import unittest

from app.geometry_diff import (
    build_diff_preview_paths,
    build_drawing_change_review,
    build_geometry_diff,
    build_path_impact,
)


class GeometryDiffTest(unittest.TestCase):
    def test_diff_preview_distinguishes_before_after_and_unchanged(self) -> None:
        source = [
            {"id": 1, "type": "line", "start": {"x": 0, "y": 0}, "end": {"x": 1000, "y": 0}},
            {"id": 2, "type": "line", "start": {"x": 0, "y": 1000}, "end": {"x": 1000, "y": 1000}},
            {"id": 3, "type": "line", "start": {"x": 0, "y": 2000}, "end": {"x": 1000, "y": 2000}},
        ]
        target = [
            {"id": 1, "type": "line", "start": {"x": 0, "y": 0}, "end": {"x": 2000, "y": 0}},
            source[1],
            {"id": 4, "type": "line", "start": {"x": 0, "y": 3000}, "end": {"x": 1000, "y": 3000}},
        ]

        paths = build_diff_preview_paths(build_geometry_diff(source, target))

        kinds = {item["diff_kind"] for item in paths}
        self.assertEqual(
            kinds,
            {"added", "removed", "modified", "modified_before", "unchanged"},
        )
        self.assertTrue(all(item["route_type"] == "drawing" for item in paths))
    def test_id_aware_diff_reports_added_removed_modified_and_unchanged(self) -> None:
        source = [
            {"id": 1, "type": "line", "start": {"x": 0}, "end": {"x": 1}},
            {"id": 2, "type": "line", "start": {"x": 0}, "end": {"x": 2}},
            {"id": 3, "type": "line", "start": {"x": 0}, "end": {"x": 3}},
        ]
        target = [
            source[0],
            {"id": 2, "type": "line", "start": {"x": 0}, "end": {"x": 20}},
            {"id": 4, "type": "line", "start": {"x": 0}, "end": {"x": 4}},
        ]
        result = build_geometry_diff(source, target)
        self.assertEqual(result["counts"], {"added": 1, "removed": 1, "modified": 1, "unchanged": 1})
        self.assertEqual(result["modified"][0]["before"]["id"], 2)

    def test_path_impact_reports_replan_for_changed_geometry(self) -> None:
        source = [{
            "id": 1, "type": "line",
            "start": {"x": 0, "y": 0}, "end": {"x": 1000, "y": 0},
        }]
        target = [{
            "id": 1, "type": "line",
            "start": {"x": 0, "y": 0}, "end": {"x": 2000, "y": 0},
        }]
        result = build_path_impact(source, target)
        self.assertTrue(result["requires_replan"])
        self.assertEqual(result["affected_path_count"], 1)
        self.assertEqual(result["affected_paths"][0]["change"], "modified")
        self.assertEqual(result["affected_paths"][0]["before"]["length_m"], 1.0)
        self.assertEqual(result["affected_paths"][0]["after"]["length_m"], 2.0)
        self.assertEqual(result["affected_paths"][0]["delta"]["length_m"], 1.0)
        self.assertEqual(result["risk_level"], "medium")

    def test_path_impact_marks_removed_printing_path_high_risk(self) -> None:
        source = [{
            "id": 1, "type": "line",
            "start": {"x": 0, "y": 0}, "end": {"x": 1000, "y": 0},
        }]
        result = build_path_impact(source, [])
        self.assertEqual(result["risk_level"], "high")
        self.assertTrue(result["affected_paths"][0]["requires_replan"])

    def test_review_contract_separates_review_from_execution(self) -> None:
        diff = {"counts": {"added": 0, "removed": 0, "modified": 1, "unchanged": 2}}
        impact = {
            "before_path_count": 3, "after_path_count": 3,
            "affected_path_count": 1, "requires_replan": True,
            "risk_level": "medium", "affected_paths": [],
        }
        review = build_drawing_change_review(
            "source.json", "source_v001.json", diff, impact,
            {"ok": True, "warnings": []}, source_version=1,
        )
        self.assertEqual(review["contract_version"], "1.0")
        self.assertTrue(review["review_only"])
        self.assertTrue(review["execution"]["requires_user_confirmation"])
        self.assertFalse(review["execution"]["execution_allowed"])
        self.assertEqual(review["summary"]["paths_affected"], 1)
