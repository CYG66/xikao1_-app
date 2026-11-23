"""Static lint for the RELEASE-TEST-01 GitHub Actions workflow.

A plain YAML loader only proves the file parses; it cannot check GitHub
Actions context-scope rules or job/dependency pairing. This lint complements
it with the rules that already broke the real CI runs (CI-R4, CI-R5). It runs
locally and is **not** invoked by the gate jobs, to avoid the workflow linting
itself under test.

Checks
------
1. Top-level ``env`` values must not reference restricted contexts
   (``runner``, ``secrets``, ``needs``, ``steps``, ``job``, ``strategy``,
   ``matrix``). Workflow-scope env may only use ``github`` / ``inputs`` /
   ``vars``; runner-derived paths must be exported per job from the shell.
2. Every ``uses:`` action pins a valid ``owner/repo@vX`` ref (or a local /
   Docker reference).
3. Every job declares ``runs-on``.
4. Every ``needs:`` reference resolves to an existing job in this workflow.
5. No ``continue-on-error: true`` and no bare ``|| true`` in run commands.
6. A job that invokes pytest directly (``python -m pytest`` / ``pytest``) or
   via ``check_manual_collection.py`` (which shells out to pytest) must install
   ``requirements-dev.txt`` (or pytest directly), and must export
   ``XLINE_DATABASE_PATH``; conftest aborts collection without the latter.
7. Every ``upload-artifact`` step that publishes a JUnit ``.xml`` report must
   run with ``if: always()`` so an upstream-red job still uploads whatever
   evidence exists; otherwise a skipped report vanishes before the diff job
   can classify it.
8. Every ``download-artifact`` step's ``pattern`` must be a single glob. The
   action accepts one glob expression; a multi-line block scalar is parsed as
   one pattern containing newlines and matches nothing, so the diff job never
   receives the reports it expects.
9. Upload/download artifact names must pair up: a downloaded ``name`` must be
   published by an upload step, and every uploaded artifact that a downstream
   job consumes must be downloaded by name. Final/local-only artifacts
   (``diff-report``, ``manual-inventory``) are explicitly exempt.

Usage
-----
    python scripts/ci/lint_workflow.py --workflow ../../.github/workflows/release-test-01-regression.yml

Exit codes
----------
0  All checks passed.
1  At least one error-level finding.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a local validation dependency
    print("ERROR: PyYAML is required to run lint_workflow.py.")
    raise SystemExit(2)


# Contexts forbidden inside the workflow-level env block.
_RESTRICTED_TOP_ENV_CONTEXTS = re.compile(
    r"\b(runner|secrets|needs|steps|job|strategy|matrix)\."
)
_ALLOWED_TOP_ENV_CONTEXTS = ("github.", "inputs.", "vars.")

# owner/repo@vX  (major version pin); also allow docker:// and ./ local refs.
_USES_REF_RE = re.compile(
    r"^(?:[\w.-]+/[\w.-]+@v\d+|docker://\S+|\./\S+)$"
)

_BARE_TRUE_RE = re.compile(r"\|\|\s*true\b")

# pytest invocation, direct or through the manual-inventory helper.
_PYTEST_DIRECT_RE = re.compile(r"(?:python\s+-m\s+pytest|(?:^|\s)pytest\s)")
_MANUAL_HELPER_RE = re.compile(r"check_manual_collection\.py")
_DEV_INSTALL_RE = re.compile(r"requirements-dev\.txt|pip\s+install[^\n]*\bpytest\b")
_DB_PATH_RE = re.compile(r"XLINE_DATABASE_PATH")
_UPLOAD_ARTIFACT_RE = re.compile(r"upload-artifact", re.I)
_DOWNLOAD_ARTIFACT_RE = re.compile(r"download-artifact", re.I)

# Artifacts that are never downloaded by a downstream step: ``diff-report`` is
# the final gate conclusion (no consumer in this workflow), ``manual-inventory``
# is written locally by check_manual_collection.py and not read back.
_NON_DOWNLOADED_UPLOADS = {"diff-report", "manual-inventory"}


def _iter_dicts(node):
    """Yield every dict node in a nested YAML structure."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_dicts(item)


def _job_steps_text(job: dict) -> str:
    """Concatenate run commands and step names for one job."""
    parts: list[str] = []
    for step in job.get("steps", []) or []:
        if isinstance(step, dict):
            if isinstance(step.get("run"), str):
                parts.append(step["run"])
            if isinstance(step.get("name"), str):
                parts.append(step["name"])
    return "\n".join(parts)


def check_top_level_env(workflow: dict, findings: list[tuple[str, str]]) -> None:
    top_env = workflow.get("env")
    if not isinstance(top_env, dict):
        return
    for key, value in top_env.items():
        text = str(value)
        match = _RESTRICTED_TOP_ENV_CONTEXTS.search(text)
        if match:
            findings.append(
                ("ERROR",
                 f"top-level env '{key}' references restricted context "
                 f"'{match.group(0)}'; workflow-scope env may only use "
                 f"{', '.join(_ALLOWED_TOP_ENV_CONTEXTS)}.")
            )


def check_uses_refs(workflow: dict, findings: list[tuple[str, str]]) -> None:
    for node in _iter_dicts(workflow):
        if "uses" in node:
            ref = str(node["uses"]).strip()
            if not _USES_REF_RE.match(ref):
                findings.append(
                    ("ERROR", f"uses action '{ref}' is not pinned to a valid @vX ref.")
                )


def check_jobs(workflow: dict, findings: list[tuple[str, str]]) -> None:
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        findings.append(("ERROR", "workflow has no 'jobs' mapping."))
        return

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            findings.append(("ERROR", f"job '{job_id}' is not a mapping."))
            continue
        if "runs-on" not in job:
            findings.append(("ERROR", f"job '{job_id}' declares no 'runs-on'."))

        needs = job.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        if isinstance(needs, list):
            for referenced in needs:
                if referenced not in jobs:
                    findings.append(
                        ("ERROR",
                         f"job '{job_id}' needs unknown job '{referenced}'.")
                    )


def check_honest_failure_policy(workflow: dict, findings: list[tuple[str, str]]) -> None:
    for node in _iter_dicts(workflow):
        if node.get("continue-on-error") is True:
            findings.append(
                ("ERROR", "continue-on-error: true would mask a red job; remove it.")
            )
        run = node.get("run")
        if isinstance(run, str) and _BARE_TRUE_RE.search(run):
            findings.append(
                ("ERROR", "run command contains a bare '|| true' that masks failures.")
            )


def check_pytest_pairing(workflow: dict, findings: list[tuple[str, str]]) -> None:
    """Pair pytest-consuming jobs with a dev install step and the DB path."""
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        text = _job_steps_text(job)
        needs_pytest = bool(_PYTEST_DIRECT_RE.search(text)) or bool(
            _MANUAL_HELPER_RE.search(text)
        )
        if not needs_pytest:
            continue

        if not _DEV_INSTALL_RE.search(text):
            findings.append(
                ("ERROR",
                 f"job '{job_id}' invokes pytest but installs neither "
                 "requirements-dev.txt nor pytest directly; add a dev-dependency "
                 "install step.")
            )
        if not _DB_PATH_RE.search(text):
            findings.append(
                ("ERROR",
                 f"job '{job_id}' runs pytest but does not export "
                 "XLINE_DATABASE_PATH; conftest aborts collection without it.")
            )


def check_upload_always(workflow: dict, findings: list[tuple[str, str]]) -> None:
    """JUnit report uploads must run with ``if: always()``."""
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            if not _UPLOAD_ARTIFACT_RE.search(str(step.get("uses", ""))):
                continue
            with_block = step.get("with", {}) or {}
            path_text = str(with_block.get("path", ""))
            if ".xml" not in path_text:
                continue  # non-JUnit artifact (inventory JSON, evidence txt)
            condition = str(step.get("if", ""))
            if "always()" not in condition:
                findings.append(
                    ("ERROR",
                     f"job '{job_id}' uploads a JUnit report but its upload step "
                     "lacks 'if: always()'; an upstream-red job would skip the report.")
                )


def check_download_pattern_single_line(workflow: dict, findings: list[tuple[str, str]]) -> None:
    """``download-artifact`` ``pattern`` must be one glob, not a block scalar."""
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            if not _DOWNLOAD_ARTIFACT_RE.search(str(step.get("uses", ""))):
                continue
            with_block = step.get("with", {}) or {}
            if "pattern" not in with_block:
                continue
            pattern_text = str(with_block["pattern"]).strip()
            if "\n" in pattern_text:
                findings.append(
                    ("ERROR",
                     f"job '{job_id}' download-artifact 'pattern' is a "
                     "multi-line block scalar; the action accepts a single "
                     "glob, so split it into one step per pattern.")
                )


def check_artifact_name_pairing(workflow: dict, findings: list[tuple[str, str]]) -> None:
    """Pair download artifact names with the upload steps that publish them."""
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return

    upload_names: set[str] = set()
    download_names: set[str] = set()
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            with_block = step.get("with", {}) or {}
            name = with_block.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            if _UPLOAD_ARTIFACT_RE.search(str(step.get("uses", ""))):
                upload_names.add(name.strip())
            elif _DOWNLOAD_ARTIFACT_RE.search(str(step.get("uses", ""))):
                download_names.add(name.strip())

    for name in sorted(download_names - upload_names):
        findings.append(
            ("ERROR",
             f"download-artifact fetches '{name}' but no upload step publishes it.")
        )
    for name in sorted(upload_names - download_names - _NON_DOWNLOADED_UPLOADS):
        findings.append(
            ("ERROR",
             f"artifact '{name}' is uploaded but never downloaded by any step; "
             "either it is consumed and needs a by-name download, or it must be "
             "exempted explicitly.")
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint the regression workflow.")
    parser.add_argument("--workflow", type=Path, required=True)
    args = parser.parse_args()

    if not args.workflow.is_file():
        print(f"ERROR: workflow file not found: {args.workflow}")
        return 2

    try:
        workflow = yaml.safe_load(args.workflow.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"ERROR: workflow is not valid YAML: {exc}")
        return 1

    findings: list[tuple[str, str]] = []
    check_top_level_env(workflow, findings)
    check_uses_refs(workflow, findings)
    check_jobs(workflow, findings)
    check_honest_failure_policy(workflow, findings)
    check_pytest_pairing(workflow, findings)
    check_upload_always(workflow, findings)
    check_download_pattern_single_line(workflow, findings)
    check_artifact_name_pairing(workflow, findings)

    errors = [msg for level, msg in findings if level == "ERROR"]
    for level, msg in findings:
        print(f"[{level}] {msg}")

    if errors:
        print(f"LINT FAILED: {len(errors)} error(s).")
        return 1
    print("LINT PASSED: top-level env contexts, action refs, runs-on, needs, "
          "failure policy, pytest/dev-install pairing, JUnit upload "
          "always-conditions, download-artifact single-glob patterns, and "
          "upload/download artifact name pairing are clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
