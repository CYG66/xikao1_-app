"""Re-run the frozen full-production protocol against the last paired B baseline."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from scripts.local_dev import ROOT,isolated_environment
from evaluations.production_contract_pilot import prepare,tree_hashes,dump


def main():
    from evaluations.run_live_user_corpus import load_key
    load_key()
    env,state=isolated_environment('source-delivery-live-retest',True)
    output=prepare(state)
    prior=ROOT/'.local-dev/full-production-pilot-vsdbrrk8/run'
    old=json.loads((prior/'manifest.json').read_text(encoding='utf-8'))
    assert tree_hashes(prior/'versions/B')==old['versions']['B']
    target=output/'versions/A/app'
    # Overlay files only; baseline has no added modules from the new source
    # coverage work. Remove those copied-current .py files explicitly, confined
    # to the newly created isolated A/app tree.
    allowed=(output/'versions/A/app').resolve()
    for p in target.rglob('*.py'):
        if not (prior/'versions/B/app'/p.relative_to(target)).exists():
            assert p.resolve().is_relative_to(allowed)
            p.unlink()
    shutil.copytree(prior/'versions/B/app',target,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    manifest=json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    manifest['versions']['A']=tree_hashes(output/'versions/A')
    manifest['historical_archive_sha256']=manifest.pop('baseline_archive_sha256')
    manifest['baseline_origin']=str(prior/'versions/B')
    manifest['comparison']='A: prior full-production B (tool contracts); B: current source coverage and precision repairs'
    protocol=ROOT/'docs/SOURCE_DELIVERY_LIVE_RETEST_PROTOCOL_20261124.md'
    manifest['retest_protocol_sha256']=hashlib.sha256(protocol.read_bytes()).hexdigest()
    manifest['retest_runner_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    manifest['limitations'].append('Same eight visible cases used for development; regression retest, not unseen generalization evidence')
    dump(output/'manifest.json',manifest)
    shutil.copy2(protocol,output/'retest-protocol.md')
    print('FROZEN RETEST '+str(output),flush=True)
    return subprocess.call([sys.executable,'-m','evaluations.production_contract_pilot','--output',str(output)],env=env,cwd=ROOT)


if __name__=='__main__':raise SystemExit(main())
