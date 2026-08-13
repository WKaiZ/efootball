import glob
import os

GROUP_DIRS = ("contenders", "challengers")


def _repo_root():
    return os.path.dirname(os.path.abspath(__file__))


def resolve_country_dir(country_folder):
    raw = (country_folder or "").strip()
    if not raw:
        return raw
    name = os.path.basename(os.path.normpath(raw))
    has_sep = os.sep in raw or (os.altsep is not None and os.altsep in raw)
    if has_sep and os.path.isdir(raw):
        return raw
    root = _repo_root()
    candidates = [os.path.join(root, name)]
    for group in GROUP_DIRS:
        candidates.append(os.path.join(root, group, name))
    candidates.extend(sorted(glob.glob(os.path.join(root, "*", name))))
    for cand in candidates:
        if os.path.isdir(cand):
            return cand
    return raw
