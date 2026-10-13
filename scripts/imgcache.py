#!/usr/bin/env python3
"""Transfermarkt photo cache for the eFootball site builder.

Holds the tid -> image-url map plus the null/error backoff counters, keyed by
Transfermarkt player id. The builder's own FotMob mappings live separately in
data/img_cache.json.
"""

import json
import os

KEYS = ("transfermarkt", "tm_null", "tm_err")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SHARED_PATH = os.path.join(ROOT, "data", "tm_img_cache.json")

def load():
    """Return the shared cache with all expected keys present."""
    data = json.load(open(SHARED_PATH)) if os.path.exists(SHARED_PATH) else {}
    for k in KEYS:
        data.setdefault(k, {})
    return data

def merge_legacy(shared, local):
    """Fold Transfermarkt entries that used to live in a per-project cache into
    the shared store, then point the local cache's keys at the shared dicts so
    callers read and write a single source of truth."""
    for k in KEYS:
        for tid, v in (local.get(k) or {}).items():
            if k == "transfermarkt":
                shared[k].setdefault(tid, v)
            else:
                shared[k][tid] = max(shared[k].get(tid, 0), v)
        local[k] = shared[k]
    return shared

def save(shared):
    os.makedirs(os.path.dirname(SHARED_PATH), exist_ok=True)
    out = {k: shared[k] for k in KEYS}
    json.dump(out, open(SHARED_PATH, "w"), ensure_ascii=False, indent=1)
