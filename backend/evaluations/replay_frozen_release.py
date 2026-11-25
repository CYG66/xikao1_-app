"""Replay exposed cases after repair, preserving the original frozen results.

Reuses the original protocol/runner verbatim. These are regression cases now,
not a second independent holdout or a paired causal experiment.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from evaluations import frozen_release_validation as release
from evaluations import production_contract_pilot as base
from scripts.local_dev import ROOT, isolated_environment


def main():
    previous=ROOT/'.local-dev/frozen-release-live-h84i_x2a/run'
    prior= json.loads((previous/'release-manifest.json').read_text(encoding='utf-8'))
    assert base.cases()==prior['datasets']['regression']
    assert release.holdouts()==prior['datasets']['holdout']
    _,snapshot=isolated_environment('handoff-repair-freeze',False)
    shutil.copytree(ROOT/'app',snapshot/'app',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    base.dump(snapshot/'freeze.json',{'frozen_utc':datetime.now(timezone.utc).isoformat(),
                                    'app_files':base.tree_hashes(snapshot/'app')})
    context={'previous_run':str(previous),'previous_manifest_sha256':hashlib.sha256((previous/'release-manifest.json').read_bytes()).hexdigest(),
             'scope':'Both stages are exposed regression cases after repair, not new holdout. Same messages, repeats, budgets and independent geometry gates.',
             'replay_runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    original_prepare=base.prepare
    def prepare(state):
        output=original_prepare(state)
        base.dump(output/'retest-context.json',context)
        return output
    base.prepare=prepare
    release.FREEZE=snapshot
    return release.main()


if __name__=='__main__':
    raise SystemExit(main())
