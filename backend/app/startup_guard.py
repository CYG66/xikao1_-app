"""Fail-closed admission for production process startup.

The production preflight is a separate, standard-library-only process.  Only
after it succeeds does the launcher export ``XLINE_STARTUP_PREFLIGHT_OK=1``.
Every module that can create or rewrite persistence calls this guard from its
constructor, so an accidental direct import cannot bypass the preflight.
"""

from __future__ import annotations

import os
from typing import Mapping

PRODUCTION_PROFILE_ENV = "XLINE_DEPLOYMENT_PROFILE"
PREFLIGHT_OK_ENV = "XLINE_STARTUP_PREFLIGHT_OK"
RECOVERY_MODE_ENV = "XLINE_STARTUP_RECOVERY_MODE"


class StartupAdmissionError(RuntimeError):
    """Raised when a production process starts without a passed preflight."""


def _env(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def production_profile(environ: Mapping[str, str] | None = None) -> bool:
    return (
        str(_env(environ).get(PRODUCTION_PROFILE_ENV, "")).strip().lower()
        == "production"
    )


def preflight_passed(environ: Mapping[str, str] | None = None) -> bool:
    return str(_env(environ).get(PREFLIGHT_OK_ENV, "")).strip() == "1"


def assert_startup_admitted(environ: Mapping[str, str] | None = None) -> None:
    """Refuse production imports unless the external preflight succeeded.

    Non-production/test processes keep the historic behaviour.  Production is
    explicit (``XLINE_DEPLOYMENT_PROFILE=production``) and must also carry the
    one-shot admission flag exported by the launcher.
    """

    if production_profile(environ) and not preflight_passed(environ):
        raise StartupAdmissionError(
            "production startup refused: startup preflight has not passed; "
            "run startup_preflight.py before importing app persistence modules"
        )


def startup_recovery_authorized(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether legacy startup recovery may rewrite existing state.

    Production defaults to disabled.  An operator may explicitly set
    ``XLINE_STARTUP_RECOVERY_MODE=authorized`` after reviewing the preflight
    report.  Non-production processes retain the historic recovery behaviour.
    """

    mode = str(_env(environ).get(RECOVERY_MODE_ENV, "")).strip().lower()
    if mode == "authorized":
        return True
    if mode == "disabled":
        return False
    return not production_profile(environ)
