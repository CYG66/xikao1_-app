"""Replay the exposed edit pilot on a new frozen production snapshot."""
from datetime import datetime,timezone
import hashlib
from pathlib import Path
import shutil
from scripts.local_dev import ROOT,isolated_environment
from evaluations import production_contract_pilot as base
from evaluations import edit_transfer_holdout as batch


def main():
    _,freeze=isolated_environment('edit-routing-repair-freeze',False)
    shutil.copytree(ROOT/'app',freeze/'app',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    base.dump(freeze/'freeze.json',{'frozen_utc':datetime.now(timezone.utc).isoformat(),'source_files':base.tree_hashes(freeze/'app')})
    original=base.dump
    def dump(path,value):
        if path.name=='edit-manifest.json':
            value={**value,'scope':'Exposed E1/E2 routing repair regression, not a new holdout.',
                'replay_of':str(ROOT/'.local-dev/edit-transfer-live-l98ton86/run')}
            for name in ['evaluations/replay_edit_transfer.py','docs/EDIT_ROUTING_REPLAY_PROTOCOL_20261125.md']:
                value['hashes'][name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        original(path,value)
    base.dump=dump;batch.FREEZE=freeze;batch.main()


if __name__=='__main__':main()
