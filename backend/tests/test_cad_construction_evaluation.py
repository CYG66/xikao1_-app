from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cad_construction_interpreter import interpret_construction_request


CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "evaluations"
    / "cad_construction_chinese_commands.json"
)
CORPUS = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda case: case["id"])
def test_chinese_construction_command_corpus(case: dict) -> None:
    result = interpret_construction_request(case["command"])

    assert result["status"] == case["expected_status"]
    if result["status"] == "ready":
        assert [
            item["type"] for item in result["trial_result"]["geometries"]
        ] == case["expected_types"]
    else:
        assert "trial_result" not in result
