#!/usr/bin/env python3
import glob
import os

POSITION_ORDER = [
    "CF", "SS", "LWF", "RWF", "AMF", "LMF", "RMF", "CMF", "DMF", "CB", "LB", "RB", "GK",
]
POSITION_RANK = {pos: i for i, pos in enumerate(POSITION_ORDER)}

CANONICAL_TYPES = {
    "standard": "Standard",
    "standrd": "Standard",
    "highlight": "Highlight",
    "epic": "Epic",
    "showtime": "Showtime",
    "bigtime": "BigTime",
}


def canonical_type(raw_type):
    key = raw_type.strip().lower().replace(" ", "")
    return CANONICAL_TYPES.get(key, raw_type.strip())


def parse_line(line):
    parts = line.split(",", 5)
    if len(parts) < 6:
        return None
    name, position, rating, flag, raw_type, rest = parts
    try:
        rating_value = float(rating.strip())
    except ValueError:
        return None
    ctype = canonical_type(raw_type)
    normalized_line = f"{name.strip()}, {position.strip()}, {rating.strip()}, {flag.strip()}, {ctype}, {rest.strip()}"
    return (position.strip().upper(), rating_value, ctype, normalized_line)


def sort_key(player):
    position, rating, _ctype, _line = player
    return (POSITION_RANK.get(position, len(POSITION_ORDER)), -rating)


def sort_file(path):
    with open(path, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    non_standard = []
    standard = []
    skipped = []
    for line in raw_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parsed = parse_line(stripped)
        if parsed is None:
            skipped.append(stripped)
            continue
        if parsed[2] == "Standard":
            standard.append(parsed)
        else:
            non_standard.append(parsed)

    non_standard.sort(key=sort_key)
    standard.sort(key=sort_key)

    out_lines = [p[3] for p in non_standard]
    if non_standard and standard:
        out_lines.append("")
    out_lines.extend(p[3] for p in standard)

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines) + "\n")

    return len(non_standard), len(standard), skipped


def main():
    repo_root = os.path.dirname(os.path.abspath(__file__))
    files = sorted(glob.glob(os.path.join(repo_root, "*", "*_players.txt")))
    if not files:
        print("No *_players.txt files found.")
        return
    for path in files:
        ns, st, skipped = sort_file(path)
        rel = os.path.relpath(path, repo_root)
        msg = f"{rel}: {ns} non-standard + {st} standard"
        if skipped:
            msg += f" ({len(skipped)} unparseable line(s) skipped)"
        print(msg)
        for line in skipped:
            print(f"    skipped: {line}")


if __name__ == "__main__":
    main()
