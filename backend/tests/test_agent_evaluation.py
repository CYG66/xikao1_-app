from __future__ import annotations

import json
import unittest

from app.agent_evaluation import (
    DEFAULT_CAD_CORPUS_PATH,
    DEFAULT_CORPUS_PATH,
    _cad_counterfactual_case,
    load_evaluation_corpus,
    run_policy_evaluation,
)
from app.agent_service import RobotAgentService


class AgentPolicyEvaluationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = object.__new__(RobotAgentService)

    def test_real_user_suite_passes_without_api_or_robot_calls(self) -> None:
        result = run_policy_evaluation(
            self.service.route_intent,
            self.service._selected_deepseek_tools,
            self._safe_resolve,
        )

        self.assertTrue(
            result["ok"],
            [item["case_id"] for item in result["results"] if not item["passed"]],
        )
        self.assertGreaterEqual(result["total"], 18)
        self.assertEqual(result["passed"], result["total"])
        self.assertFalse(result["external_api_called"])
        self.assertFalse(result["robot_control_called"])
        self.assertTrue(result["read_only"])

    def test_corpus_is_machine_readable_and_has_unique_ids(self) -> None:
        corpus = load_evaluation_corpus()
        case_ids = [item["id"] for item in corpus["cases"]]

        self.assertEqual(len(case_ids), len(set(case_ids)))
        self.assertTrue(all(item.get("category") for item in corpus["cases"]))
        json.dumps(corpus, ensure_ascii=False)

    def test_corpus_covers_required_acceptance_categories(self) -> None:
        categories = {
            item["category"] for item in load_evaluation_corpus()["cases"]
        }

        self.assertTrue(
            {
                "ordinary_conversation",
                "live_telemetry",
                "degraded_data",
                "cad_creation",
                "cad_modification",
                "reference_resolution",
                "dangerous_operation",
                "adversarial_safety",
                "tool_verification",
                "api_failure_recovery",
                "citation_integrity",
            }.issubset(categories)
        )

    def test_evaluation_does_not_modify_corpus(self) -> None:
        before = DEFAULT_CORPUS_PATH.read_bytes()

        run_policy_evaluation(
            self.service.route_intent,
            self.service._selected_deepseek_tools,
            self._safe_resolve,
        )

        self.assertEqual(DEFAULT_CORPUS_PATH.read_bytes(), before)

    def test_real_chinese_cad_command_suite_passes_deterministically(self) -> None:
        result = run_policy_evaluation(
            self.service.route_intent,
            self.service._selected_deepseek_tools,
            self._safe_resolve,
            DEFAULT_CAD_CORPUS_PATH,
        )

        self.assertTrue(
            result["ok"],
            {
                item["case_id"]: item
                for item in result["results"]
                if not item["passed"]
            },
        )
        self.assertGreaterEqual(result["total"], 10)
        self.assertFalse(result["external_api_called"])
        self.assertFalse(result["robot_control_called"])

    def test_cad_corpus_covers_required_regression_categories(self) -> None:
        corpus = load_evaluation_corpus(DEFAULT_CAD_CORPUS_PATH)
        categories = {item["category"] for item in corpus["cases"]}
        ids = [item["id"] for item in corpus["cases"]]

        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue({
            "common_commands",
            "multiple_instances",
            "unit_conversion",
            "coordinate_frame",
            "dangerous_operation",
            "no_change_operation",
            "intent_boundary",
            "layer_semantics",
            "multi_turn_context",
            "fuzzy_reference",
            "coordinate_conflict",
            "complex_dxf",
            "counterfactual_protection",
        }.issubset(categories))
        self.assertIn("three_instances", corpus.get("fixtures", {}))

    def test_cad_corpus_schema_and_fixtures_are_stable(self) -> None:
        before = DEFAULT_CAD_CORPUS_PATH.read_bytes()
        corpus = load_evaluation_corpus(DEFAULT_CAD_CORPUS_PATH)
        supported = {
            "cad_edit", "cad_counterfactual", "cad_followup", "cad_dxf",
        }

        for case in corpus["cases"]:
            self.assertIsInstance(case.get("id"), str)
            self.assertIn(case.get("kind"), supported)
            self.assertIsInstance(case.get("category"), str)
            self.assertIsInstance(case.get("expected"), dict)
            if case["kind"] in {"cad_edit", "cad_followup"}:
                self.assertIsInstance(case.get("message"), str)
            if case["kind"] == "cad_counterfactual":
                self.assertIsInstance(case.get("base_message"), str)
                self.assertIsInstance(case.get("variant_message"), str)
                self.assertTrue(
                    case["expected"].get("changed_paths")
                    or case["expected"].get("variant_valid") is False
                )
            if case["kind"] == "cad_dxf":
                fixture = (DEFAULT_CAD_CORPUS_PATH.parent / case["file"]).resolve()
                self.assertIn(DEFAULT_CAD_CORPUS_PATH.parent.resolve(), fixture.parents)
                self.assertTrue(fixture.is_file())

        run_policy_evaluation(
            self.service.route_intent,
            self.service._selected_deepseek_tools,
            self._safe_resolve,
            DEFAULT_CAD_CORPUS_PATH,
        )
        self.assertEqual(DEFAULT_CAD_CORPUS_PATH.read_bytes(), before)

    def test_counterfactual_pairs_change_only_declared_contract_fields(self) -> None:
        result = run_policy_evaluation(
            self.service.route_intent,
            self.service._selected_deepseek_tools,
            self._safe_resolve,
            DEFAULT_CAD_CORPUS_PATH,
        )
        pairs = [
            item for item in result["results"]
            if item["category"] == "counterfactual_protection"
        ]

        self.assertGreaterEqual(len(pairs), 6)
        self.assertTrue(
            all(item["passed"] for item in pairs),
            {item["case_id"]: item for item in pairs if not item["passed"]},
        )

    def test_counterfactual_missing_contract_path_fails_closed(self) -> None:
        result = _cad_counterfactual_case({
            "id": "invalid-path",
            "category": "counterfactual_protection",
            "base_message": "把第一个图形向右移动1米",
            "variant_message": "把第二个图形向右移动1米",
            "source_geometry": [
                {
                    "id": 1, "type": "line", "layer_id": 1,
                    "template_instance": 1,
                    "start": {"x": 0, "y": 0, "z": 0},
                    "end": {"x": 1000, "y": 0, "z": 0},
                },
                {
                    "id": 2, "type": "line", "layer_id": 1,
                    "template_instance": 2,
                    "start": {"x": 2000, "y": 0, "z": 0},
                    "end": {"x": 3000, "y": 0, "z": 0},
                },
            ],
            "expected": {
                "changed_paths": ["target.instance_ids"],
                "unchanged_paths": ["parameters.not_a_real_field"],
            },
        })

        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"][
            "unchanged:parameters.not_a_real_field"
        ])

    def _safe_resolve(
        self, message: str, mode: str, history: list[dict[str, str]]
    ) -> dict[str, object]:
        self.service.mode = "local"
        self.service.api_keys = {}
        return self.service.resolve_intent(message, mode, history)


if __name__ == "__main__":
    unittest.main()
