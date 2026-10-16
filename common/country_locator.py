import glob
import os

GROUP_DIRS = ("contenders", "challengers", "backup")


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_country_dir(country_folder):
    raw = (country_folder or "").strip()
    if not raw:
        return raw
    name = os.path.basename(os.path.normpath(raw))
    has_sep = os.sep in raw or (os.altsep is not None and os.altsep in raw)
    root = _repo_root()
    if has_sep:
        direct = raw if os.path.isabs(raw) else os.path.join(root, raw)
        if os.path.isdir(direct):
            return direct
    candidates = [os.path.join(root, "nations", name)]
    for group in GROUP_DIRS:
        candidates.append(os.path.join(root, "nations", group, name))
    candidates.extend(sorted(glob.glob(os.path.join(root, "nations", "*", name))))
    for cand in candidates:
        if os.path.isdir(cand):
            return cand
    return raw
