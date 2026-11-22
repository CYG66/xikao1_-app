"""Configuration-level regression for M2/M3 integration defaults.

The capabilities are now opt-in. A subprocess is used so the module-level
flags are evaluated from a clean environment; monkeypatching constants after
import would not prove the default configuration.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
FLAG_SCRIPT = """
import json
from app.cad_generation_recovery import (
    M2_SCOPE_CLASSIFIER_ENABLED,
    M3_PROGRESS_GATE_ENABLED,
)
print(json.dumps({
    "m2": M2_SCOPE_CLASSIFIER_ENABLED,
    "m3": M3_PROGRESS_GATE_ENABLED,
}))
"""


def _read_flags(monkeypatch, *, m2: str | None, m3: str | None) -> dict[str, bool]:
    monkeypatch.delenv("CAD_C1_M2_SCOPE_CLASSIFIER", raising=False)
    monkeypatch.delenv("CAD_C1_M3_PROGRESS_GATE", raising=False)
    if m2 is not None:
        monkeypatch.setenv("CAD_C1_M2_SCOPE_CLASSIFIER", m2)
    if m3 is not None:
        monkeypatch.setenv("CAD_C1_M3_PROGRESS_GATE", m3)
    completed = subprocess.run(
        [sys.executable, "-c", FLAG_SCRIPT],
        cwd=BACKEND_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


@pytest.mark.parametrize("value", ["off", "0", "false", "no"])
def test_explicit_off_disables_both_switches(monkeypatch, value):
    flags = _read_flags(monkeypatch, m2=value, m3=value)
    assert flags == {"m2": False, "m3": False}


@pytest.mark.parametrize("value", ["on", "1", "true", "yes"])
def test_explicit_on_preserves_both_switches(monkeypatch, value):
    flags = _read_flags(monkeypatch, m2=value, m3=value)
    assert flags == {"m2": True, "m3": True}


def test_missing_environment_variables_default_to_off(monkeypatch):
    flags = _read_flags(monkeypatch, m2=None, m3=None)
    assert flags == {"m2": False, "m3": False}


def test_flags_are_independent(monkeypatch):
    flags = _read_flags(monkeypatch, m2="on", m3=None)
    assert flags == {"m2": True, "m3": False}

    flags = _read_flags(monkeypatch, m2=None, m3="on")
    assert flags == {"m2": False, "m3": True}
