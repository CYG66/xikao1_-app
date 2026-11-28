"""P01-only baseline admission checks in front of the evaluation ledger.

This module is test-only.  It is imported by the live evaluation worker, which
is itself a manual test entry, so it cannot affect production imports.
"""
from __future__ import annotations

from typing import Any


def install_baseline_admission(
    budget: Any,
    *,
    actual_input_stop: int,
    request_input_cap: int,
):
    """Install the two P01 pre-send checks without bypassing ``reserve``.

    Returns the wrapper for direct boundary testing.  A zero threshold or cap
    disables that individual check, preserving the earlier behaviour.
    """
    from app.eval_token_bound import input_token_upper_bound
    # Use the exception class from the ledger's own module.  The worker loads
    # ``eval_budget_store`` top-level while pytest loads
    # ``tests.manual.eval_budget_store``; importing a fixed spelling would
    # raise a different class that callers cannot catch.
    import importlib

    stop_cls = importlib.import_module(
        type(budget).__module__
    ).EvaluationBudgetStop

    original_reserve = budget.reserve

    def baseline_reserve(*args, **kwargs):
        snapshot = budget.snapshot()
        used = snapshot.get("used") or {}
        actual_input = int(used.get("input_tokens") or 0)
        if actual_input_stop and actual_input >= actual_input_stop:
            budget.stop_run(
                f"baseline_actual_input_stop_reached:{actual_input}>="
                f"{actual_input_stop}"
            )
            raise stop_cls("baseline_actual_input_stop_reached")
        reserved_input = kwargs.get("input_token_upper_bound")
        if reserved_input is None:
            reserved_input = input_token_upper_bound(
                kwargs.get("payload") or {}
            )["upper_bound"]
        if (request_input_cap
                and int(reserved_input) > request_input_cap):
            budget.stop_run(
                f"baseline_request_input_reservation_exceeds_cap:"
                f"{reserved_input}>{request_input_cap}"
            )
            raise stop_cls(
                "baseline_request_input_reservation_exceeds_cap"
            )
        return original_reserve(*args, **kwargs)

    budget.reserve = baseline_reserve
    return baseline_reserve
