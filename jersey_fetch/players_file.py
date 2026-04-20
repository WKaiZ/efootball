import os
import re

from jersey_fetch.constants import POSITION_SEARCH_PHRASES
from jersey_fetch.names import normalize_name


def country_display_name(country_name):
    return country_name.replace("_", " ").replace("-", " ").strip().title()


def parse_args(argv):
    country_folder = "belgium"
    force_refetch = False
    game_id = None
    lineup_only = False
    positional = []
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in ("--refetch", "--refresh", "--no-cache"):
            force_refetch = True
        elif arg in ("--lineup-only", "--espn-lineup"):
            lineup_only = True
        elif arg == "--gameid":
            if i + 1 < len(argv):
                game_id = argv[i + 1]
                i += 1
            else:
                raise SystemExit(
                    "Usage: python fetch_number.py|fetch_numbers.py [--refetch | --lineup-only] [--gameid <id>] [country_folder]"
                )
        else:
            positional.append(arg)
        i += 1
    if len(positional) > 1:
        raise SystemExit(
            "Usage: python fetch_number.py|fetch_numbers.py [--refetch | --lineup-only] [--gameid <id>] [country_folder]"
        )
    if positional:
        country_folder = positional[0]
    if lineup_only and force_refetch:
        raise SystemExit(
            "Cannot combine --lineup-only with --refetch. "
            "Use --lineup-only to refresh ESPN recent flags only (no Transfermarkt). "
            "Use --refetch for a full jersey refetch including ESPN."
        )
    return (country_folder, force_refetch, game_id, lineup_only)


def rewrite_players_txt(raw_lines, name_changes=None, recent_flags=None):
    name_changes = name_changes or {}
    recent_flags = recent_flags or {}
    changed = False
    out = []
    for line in raw_lines:
        original = line
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out.append(original)
            continue
        comma_idx = line.find(",")
        if comma_idx == -1:
            first = line.strip()
            rest = ""
        else:
            first = line[:comma_idx].strip()
            rest = line[comma_idx:]
        if not first:
            out.append(original)
            continue
        key = normalize_name(first)
        new_first = name_changes.get(key, first)
        new_line = f"{new_first}{rest}"
        if key in recent_flags:
            parts = [p.strip() for p in new_line.split(",")]
            for idx in range(3, len(parts)):
                parsed = parse_recent_flag(parts[idx])
                if parsed is None:
                    continue
                parts[idx] = "True" if recent_flags[key] else "False"
                candidate = ", ".join(parts)
                if candidate != original:
                    changed = True
                out.append(candidate)
                break
            else:
                out.append(new_line)
                if new_line != original:
                    changed = True
        else:
            out.append(new_line)
            if new_line != original:
                changed = True
    return (out, changed)


def resolve_players_file(country_folder):
    folder = country_folder.strip()
    country_name = os.path.basename(os.path.normpath(folder))
    return os.path.join(folder, f"{country_name}_players.txt")


def parse_recent_flag(token):
    t = token.strip().lower()
    if t == "true":
        return True
    if t == "false":
        return False
    return None


def local_position_role(position):
    pos = (position or "").strip().upper()
    if pos == "GK":
        return "G"
    if pos in {"CB", "LB", "RB"}:
        return "D"
    if pos in {"DMF", "CMF", "AMF", "LMF", "RMF"}:
        return "M"
    if pos in {"LWF", "RWF", "SS", "CF"}:
        return "F"
    return None


def position_search_phrase(position):
    if not position:
        return ""
    return POSITION_SEARCH_PHRASES.get(position.strip().upper(), "")


def build_local_player_profiles(raw_lines):
    profiles = {}
    for line in raw_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        name = parts[0]
        key = normalize_name(name)
        profile = profiles.setdefault(key, {"name": name, "roles": set()})
        role = local_position_role(parts[1])
        if role:
            profile["roles"].add(role)
        for match in re.findall(r"\[([^\]]*)\]", stripped):
            for token in match.split(","):
                role = local_position_role(token.strip())
                if role:
                    profile["roles"].add(role)
    return profiles


def build_local_player_search_hints(raw_lines):
    hints = {}
    for line in raw_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        name = parts[0]
        main_pos = parts[1]
        phrase = position_search_phrase(main_pos)
        if phrase:
            hints[normalize_name(name)] = phrase
    return hints
