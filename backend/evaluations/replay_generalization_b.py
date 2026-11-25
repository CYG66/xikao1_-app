"""Replay now-exposed U cases after output-intent/recovery repair."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from scripts.local_dev import ROOT, isolated_environment
from evaluations import generalization_holdout_b as batch
from evaluations import production_contract_pilot as base


def main():
    prior=ROOT/'.local-dev/transfer-holdout-live-lbndly5w/run'
    old=json.loads((prior/'holdout-manifest.json').read_text(encoding='utf-8'))
    assert batch.cases()==old['cases']
    _,freeze=isolated_environment('output-intent-repair-freeze',False)
    shutil.copytree(ROOT/'app',freeze/'app',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    base.dump(freeze/'freeze.json',{'frozen_utc':datetime.now(timezone.utc).isoformat(),'source_files':base.tree_hashes(freeze/'app')})
    original_dump=base.dump
    def dump(path,value):
        if path.name=='holdout-manifest.json':
            value={**value,'scope':'Exposed U1-U6 regression after repair; not a new holdout.',
                'replay_of':str(prior),'prior_manifest_sha256':hashlib.sha256((prior/'holdout-manifest.json').read_bytes()).hexdigest()}
            value['hashes']['evaluations/replay_generalization_b.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        original_dump(path,value)
    base.dump=dump;batch.FREEZE=freeze
    batch.main()


if __name__=='__main__':main()
