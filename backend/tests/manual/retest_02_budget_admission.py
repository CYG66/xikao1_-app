"""Canonical budget admission profile for the RETEST-02 live runner.

The live runner is an evidence-side wrapper: it owns the frozen case order and
the subprocess loop, but it must not carry a second, drifting copy of the
budget boundaries.  This module is the single mapping from the accepted
``eval-config.json`` values to the environment consumed by the ledger and the
P01 admission wrapper.  It performs no I/O and opens no connection.
"""
from __future__ import annotations

from typing import Any

REQUESTS = 36
LOCAL_INPUT_ADMISSION = 600_000
ACTUAL_INPUT_STOP = 450_000
SINGLE_REQUEST_INPUT_CAP = 1_048_576
CUMULATIVE_INPUT_HARD_RISK = 1_498_576
OUTPUT_HARD_RISK = 60_000
COST_CAP_USD = 0.55
INPUT_PRICE_PER_M = 0.30
OUTPUT_PRICE_PER_M = 1.20

_ENV_KEYS = (
    "P12_MAX_REQUESTS",
    "P12_MAX_INPUT_TOKENS",
    "P12_MAX_OUTPUT_TOKENS",
    "P12_MAX_COST_USD",
    "P12_INPUT_PRICE_PER_M",
    "P12_OUTPUT_PRICE_PER_M",
    "P12_BASELINE_ACTUAL_INPUT_STOP",
    "P12_BASELINE_REQUEST_INPUT_CAP",
)


def retest_02_budget_env(
    *,
    requests: int = REQUESTS,
    input_tokens: int = LOCAL_INPUT_ADMISSION,
    output_tokens: int = OUTPUT_HARD_RISK,
    cost_usd: float = COST_CAP_USD,
    input_price_per_m: float = INPUT_PRICE_PER_M,
    output_price_per_m: float = OUTPUT_PRICE_PER_M,
    actual_input_stop: int = ACTUAL_INPUT_STOP,
    request_input_cap: int = SINGLE_REQUEST_INPUT_CAP,
) -> dict[str, str]:
    """Return the exact environment for the live runner's budget boundary.

    Any caller-supplied value that differs from the accepted profile is a
    configuration error, not an invitation to relax the boundary.  This keeps
    ``eval-config.json`` authoritative while preventing a silent widening of
    the local admission, single-request cap or cost cap.
    """

    supplied = {
        "requests": requests,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "input_price_per_m": input_price_per_m,
        "output_price_per_m": output_price_per_m,
        "actual_input_stop": actual_input_stop,
        "request_input_cap": request_input_cap,
    }
    expected = {
        "requests": REQUESTS,
        "input_tokens": LOCAL_INPUT_ADMISSION,
        "output_tokens": OUTPUT_HARD_RISK,
        "cost_usd": COST_CAP_USD,
        "input_price_per_m": INPUT_PRICE_PER_M,
        "output_price_per_m": OUTPUT_PRICE_PER_M,
        "actual_input_stop": ACTUAL_INPUT_STOP,
        "request_input_cap": SINGLE_REQUEST_INPUT_CAP,
    }
    for key, value in supplied.items():
        if value != expected[key]:
            raise ValueError(
                f"retest_02_budget_profile_mismatch:{key}:{value!r}!="
                f"{expected[key]!r}"
            )
    return {
        "P12_MAX_REQUESTS": str(REQUESTS),
        "P12_MAX_INPUT_TOKENS": str(LOCAL_INPUT_ADMISSION),
        "P12_MAX_OUTPUT_TOKENS": str(OUTPUT_HARD_RISK),
        "P12_MAX_COST_USD": str(COST_CAP_USD),
        "P12_INPUT_PRICE_PER_M": str(INPUT_PRICE_PER_M),
        "P12_OUTPUT_PRICE_PER_M": str(OUTPUT_PRICE_PER_M),
        "P12_BASELINE_ACTUAL_INPUT_STOP": str(ACTUAL_INPUT_STOP),
        "P12_BASELINE_REQUEST_INPUT_CAP": str(SINGLE_REQUEST_INPUT_CAP),
    }


def theoretical_worst_case_usd() -> float:
    """Worst-case supplier cost at the accepted cumulative input risk bound."""

    return (
        CUMULATIVE_INPUT_HARD_RISK * INPUT_PRICE_PER_M / 1_000_000
        + OUTPUT_HARD_RISK * OUTPUT_PRICE_PER_M / 1_000_000
    )


def profile_values() -> dict[str, Any]:
    """Return the canonical values for evidence reports and zero-request tests."""

    return {
        "requests": REQUESTS,
        "local_input_admission": LOCAL_INPUT_ADMISSION,
        "actual_input_stop": ACTUAL_INPUT_STOP,
        "single_request_input_cap": SINGLE_REQUEST_INPUT_CAP,
        "cumulative_input_hard_risk": CUMULATIVE_INPUT_HARD_RISK,
        "output_hard_risk": OUTPUT_HARD_RISK,
        "cost_usd": COST_CAP_USD,
        "input_price_per_m": INPUT_PRICE_PER_M,
        "output_price_per_m": OUTPUT_PRICE_PER_M,
        "theoretical_worst_case_usd": theoretical_worst_case_usd(),
    }
