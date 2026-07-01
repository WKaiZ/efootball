"""Locate a nation's folder regardless of how the repo groups them.

Nation folders are grouped one level deep under the group directories listed in
``GROUP_DIRS`` (e.g. ``contenders/france``, ``challengers/wales``). This module
lets every stage keep accepting a bare country name ("france") on the command
line: the name is searched for under the repo root and the group directories.
Group-qualified paths ("contenders/france") and explicit paths still work too.

The DB ``country`` column stays the folder *basename*, so grouping folders does
not change any stored keys.
"""

import glob
import os

# Group folders that hold nation subfolders. A country may also live directly at
# the repo root (checked first) so a flat layout still resolves.
GROUP_DIRS = ("contenders", "challengers")


def _repo_root():
    return os.path.dirname(os.path.abspath(__file__))


def resolve_country_dir(country_folder):
    """Return the directory holding a country's ``<name>_*`` files.

    Accepts a bare name ("france"), a group-qualified path ("contenders/france"),
    or any explicit path. Falls back to the given value when nothing matches so
    callers surface a clear not-found error against the original input.
    """
    raw = (country_folder or "").strip()
    if not raw:
        return raw
    name = os.path.basename(os.path.normpath(raw))
    has_sep = os.sep in raw or (os.altsep is not None and os.altsep in raw)
    # An explicit path that already points at a real directory wins outright.
    if has_sep and os.path.isdir(raw):
        return raw
    root = _repo_root()
    candidates = [os.path.join(root, name)]
    for group in GROUP_DIRS:
        candidates.append(os.path.join(root, group, name))
    # Fallback: any single level of grouping under the repo root.
    candidates.extend(sorted(glob.glob(os.path.join(root, "*", name))))
    for cand in candidates:
        if os.path.isdir(cand):
            return cand
    return raw
