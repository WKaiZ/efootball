#!/usr/bin/env python3
"""Deep-merge a conflicted JSON file during git rebase/merge.

During a conflict, stage 2 is "ours" and stage 3 is "theirs". In a rebase,
ours is the branch being rebased onto (upstream) and theirs is the commit
being replayed. We keep upstream as the base and overlay the replayed
commit's keys so photo-cache entries from both sides survive.
"""

from __future__ import annotations

import json
import subprocess
import sys


def load_stage(path: str, stage: int):
    try:
        raw = subprocess.check_output(
            ["git", "show", f":{stage}:{path}"], stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        return None
    return json.loads(raw)


def deep_merge(base, overlay):
    if isinstance(base, dict) and isinstance(overlay, dict):
        out = dict(base)
        for key, value in overlay.items():
            out[key] = deep_merge(out[key], value) if key in out else value
        return out
    return overlay


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: merge_json_conflict.py <path>", file=sys.stderr)
        return 2
    path = argv[1]
    ours = load_stage(path, 2)
    theirs = load_stage(path, 3)
    if ours is None and theirs is None:
        print(f"no conflict stages for {path}", file=sys.stderr)
        return 1
    if ours is None:
        merged = theirs
    elif theirs is None:
        merged = ours
    else:
        merged = deep_merge(ours, theirs)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
