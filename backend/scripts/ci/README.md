# RELEASE-TEST-01 CI scripts

Offline regression gate scripts for the XLine backend. All scripts run against
isolated storage under the runner temp directory; none touches production
data, calls a model provider, or drives real hardware.

## Layout

| Script | Purpose | Failure semantics |
| --- | --- | --- |
| `check_imports.py` | Pure import check over a curated module list. No app start, no I/O. | Exit 1 if any module fails to import. |
| `check_manual_collection.py` | Verifies the `manual_field` marker is registered, collects tagged tests **without executing them**, and cross-checks that no manual test leaked into an offline executed report. | Exit 1 on unknown marker, collection breakage, or executed leak. |
| `extract_collect_errors.py` | Parses a `pytest --collect-only` log and writes the collection-error file list for baseline comparison. | Evidence-only; does not alter pytest exit code. |
| `diff_failures.py` | Compares JUnit failures against `baseline_failures.json`; classifies new / resolved / unchanged. | Exit 1 on a new failure or new collection error (unless `--no-fail-on-new`). |
| `lint_workflow.py` | Static lint for the regression workflow: top-level env contexts, action refs, `runs-on`, `needs` resolution, and honest-failure policy. Local-only; not invoked by the gate jobs. | Exit 1 on any error-level finding. |
| `baseline_failures.json` | Reviewed allowlist of known baseline reds. **Not** a skip list: raw jobs still fail honestly. | — |

## Marker registration

The `manual_field` marker must be declared in `backend/pytest.ini`:

```ini
[pytest]
markers =
    manual_field: Real on-device or live-session action ...
```

A test that drives real rover movement, inkjet/pen output, a live ROS bridge,
or a live model session must be tagged:

```python
@pytest.mark.manual_field
def test_...():
    ...
```

CI collects such tests for inventory only. The offline regression jobs
deselect them with `-m "not manual_field"`.

### Marker scope ruling (do not over-tag)

`manual_field` is reserved for tests that genuinely need real hardware or a
field/live environment. Offline deterministic tests must **not** be tagged,
even when they spawn an isolated subprocess or exercise an HTTP endpoint:

* `test_cad_copy_http_identity.py` (2 cases) — isolated subprocess HTTP trace,
  asserts `provider_calls == 0`; offline deterministic.
* `test_p12_eval_budget.py` (2 worker subprocess cases) — offline budget
  ledger replay; offline deterministic.

The current repository contains no real-device/field test, so the manual
inventory is expected to be empty. An empty inventory is a valid state: the
`manual-collection` job still verifies the marker registers successfully, and
only performs collect-only registration — it never executes a manual test.
Do not backfill `manual_field` onto offline tests just to make the list
non-empty.

## Local equivalent run (Windows PowerShell)

```powershell
$py = "C:\Users\29924\Codes\xikao-recovery\backend\.venv\Scripts\python.exe"
$env:XLINE_DATABASE_PATH = "<unique-temp-dir>\xline-test.db"
$env:XLINE_STATE_DIR     = "<unique-temp-dir>\state"
$env:XLINE_CONFIG_DIR    = "<unique-temp-dir>\config"
$env:XLINE_WS_ROOT        = "<unique-temp-dir>\workspace"

& $py -m pytest tests/test_audit_store.py -q -p no:cacheprovider `
  --junitxml=<artifacts>\security.xml
```

Always pass `-p no:cacheprovider` so a parallel local/audit run cannot share the
pytest cache. Never point `XLINE_DATABASE_PATH` at the production database.

## Reproducibility notes

* Python target: 3.13 (locally validated on 3.13.18, pytest 9.2.0).
* Dependency split:
  * `backend/requirements.txt` — runtime dependencies only.
  * `backend/requirements-dev.txt` — test-only dependencies: `pytest` and
    `httpx` (the TestClient backend used by three HTTP test modules). No pytest
    async plugin is required: async cases use stdlib `asyncio.run` /
    `unittest.IsolatedAsyncioTestCase`.
* The optional native CAD backends (`requirements-native-cad.txt`) are not
  required for this gate; the builtin deterministic backend must work without
  them.
* JUnit paths are assigned to a variable first on PowerShell before being
  passed to `--junitxml`.
