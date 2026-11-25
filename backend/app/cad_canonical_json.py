"""Existing canonical JSON/SHA256 protocol; keep historical bytes stable.

This deliberately preserves json.dumps' existing NaN and integer/float
behavior. Version evidence, semantic hashes and geometry-diff protocols have
different contracts and must not be redirected here implicitly.
"""
import hashlib
import json


def canonical_json_hash(value):
    payload=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()
