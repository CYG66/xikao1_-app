"""Regression replay of now-exposed T cases; never a new holdout score."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from scripts.local_dev import ROOT, isolated_environment
from evaluations import transfer_holdout_20261124 as run
from evaluations import production_contract_pilot as base


def main():
    prior=ROOT/'.local-dev/transfer-holdout-live-vo4fxnsd/run'
    old=json.loads((prior/'holdout-manifest.json').read_text(encoding='utf-8'))
    assert run.cases()==old['cases']
    _,freeze=isolated_environment('transfer-source-repair-freeze',False)
    shutil.copytree(ROOT/'app',freeze/'app',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    base.dump(freeze/'freeze.json',{'frozen_utc':datetime.now(timezone.utc).isoformat(),'source_files':base.tree_hashes(freeze/'app')})
    original_dump=base.dump
    def dump(path,value):
        if path.name=='holdout-manifest.json':
            value={**value,'scope':'Exposed T1-T6 regression after repair, not independent holdout.',
                   'replay_of':str(prior),'prior_manifest_sha256':hashlib.sha256((prior/'holdout-manifest.json').read_bytes()).hexdigest()}
            value['hashes']['evaluations/replay_transfer_holdout.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        original_dump(path,value)
    base.dump=dump
    run.FREEZE=freeze
    run.main()


if __name__=='__main__':main()
