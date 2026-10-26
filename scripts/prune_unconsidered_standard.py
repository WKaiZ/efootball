import argparse
import math
import os
import sqlite3
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gameplan.formation as formation
from gameplan.builder import build_gameplan
from gameplan.constants import DB_PATH, is_standard
from gameplan.data import load_formations, load_roles, resolve_country_paths
from scripts import fetch_game_data
from scripts.draft_gameplan import compact_backup, _exclude_cards, _squad_card_keys
from scripts.fetch_game_data import (
    get_manual_override,
    jersey_history_matches_country,
    levenshtein,
    load_player_id_map,
    normalize_name,
    parse_line,
    resolve_players_file,
)
from jersey_fetch.players_file import country_display_name


def _resolve_input_player_id(conn, country, data, name_map, ambiguous_names, line_number):
    manual_id = get_manual_override(country, data["name"], position=data["position"])
    if manual_id:
        return str(manual_id)

    normalized_name = normalize_name(data["name"])
    if normalized_name in name_map and normalized_name not in ambiguous_names:
        player_id = name_map[normalized_name]
    else:
        best_key = None
        best_distance = 999
        for key in name_map:
            distance = levenshtein(normalized_name, key)
            if distance < best_distance:
                best_key = key
                best_distance = distance
        if best_key is None or best_distance > 2:
            raise ValueError(
                f"Line {line_number}: no player_id found for '{data['name']}' "
                f"(closest distance {best_distance})"
            )
        player_id = name_map[best_key]

    nation_matches, stored_nations = jersey_history_matches_country(
        conn, player_id, country_display_name(country)
    )
    if not nation_matches:
        raise ValueError(
            f"Line {line_number}: '{data['name']}' maps to jersey history for "
            f"{', '.join(stored_nations)}, not {country_display_name(country)}"
        )
    return str(player_id)


def _input_standard_cards(conn, players_path, country, group):
    name_map, ambiguous_names = load_player_id_map(conn)
    cards_by_key = {}
    with open(players_path, "r", encoding="utf-8") as handle:
        lines = handle.readlines()

    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        ok, data = parse_line(stripped, line_number)
        if not ok:
            raise ValueError(data["error"])
        if data["card_type"].strip().lower() != "standard":
            continue
        player_id = _resolve_input_player_id(
            conn, country, data, name_map, ambiguous_names, line_number
        )
        key = (player_id, data["position"].strip().upper())
        cards_by_key.setdefault(key, []).append(
            {
                "line_number": line_number,
                "recent": bool(data["recent"]),
                "name": data["name"],
                "rating": float(data["rating"]),
            }
        )

    return lines, cards_by_key


def _run_country_selection(conn, country, group, candidate_observer=None, roles_by_pos=None):
    formation_path, _output_path = resolve_country_paths(country)
    first_formation, second_formation = load_formations(formation_path)
    formation.FORMATION[:] = first_formation
    if roles_by_pos is None:
        roles_by_pos = load_roles(conn, country)
    if not roles_by_pos:
        return

    starters, subs, wildcards = build_gameplan(
        conn, roles_by_pos, candidate_observer=candidate_observer
    )
    if group == "contenders":
        used_cards = _squad_card_keys(starters, subs, wildcards)
        remaining = _exclude_cards(roles_by_pos, used_cards)
        formation.FORMATION[:] = second_formation or first_formation
        build_gameplan(conn, remaining, candidate_observer=candidate_observer)
    elif group == "backup":
        compact_backup(conn, roles_by_pos, starters, candidate_observer=candidate_observer)


def _atomic_write(path, content):
    mode = stat.S_IMODE(os.stat(path).st_mode)
    fd, temporary_path = tempfile.mkstemp(prefix=f".{Path(path).name}.", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise


def prune_country(country_arg, dry_run=False):
    players_path = resolve_players_file(country_arg)
    if not os.path.isfile(players_path):
        raise FileNotFoundError(f"Players file not found: {players_path}")

    country = os.path.basename(os.path.dirname(players_path))
    group = os.path.basename(os.path.dirname(os.path.dirname(players_path)))
    conn = sqlite3.connect(DB_PATH)
    original_content = Path(players_path).read_text(encoding="utf-8")
    try:
        lines, file_cards = _input_standard_cards(conn, players_path, country, group)
        baseline_considered = set()

        def collect(role, _slot, stage):
            if group in {"backup", "reserve"}:
                starter_stage = stage.startswith(
                    ("starter_", "starter_replacement_", "starter_vacancy_")
                )
                backup_stage = group == "backup" and stage == "backup_selection"
                if not starter_stage and not backup_stage:
                    return
            if is_standard(role):
                baseline_considered.add((str(role.player_id), role.position))

        _run_country_selection(conn, country, group, candidate_observer=collect)
        roles_by_pos = load_roles(conn, country)
        standard_roles = [
            role
            for roles in roles_by_pos.values()
            for role in roles
            if is_standard(role)
            and not (group == "contenders" and role.recent)
            and (str(role.player_id), role.position) in file_cards
        ]

        candidates_to_probe = {}
        for role in standard_roles:
            key = (str(role.player_id), role.position)
            if key not in baseline_considered:
                candidates_to_probe.setdefault(key, role)

        remove_keys = set()
        for key, baseline_role in candidates_to_probe.items():
            source_rows = file_cards.get(key, [])
            if not source_rows:
                continue
            if group == "contenders" and any(row["recent"] for row in source_rows):
                continue

            probe_roles = load_roles(conn, country)
            probe_role = next(
                (
                    role
                    for role in probe_roles.get(baseline_role.position, [])
                    if str(role.player_id) == key[0]
                    and role.position == baseline_role.position
                    and is_standard(role)
                ),
                None,
            )
            if probe_role is None:
                continue

            original_rating = probe_role.rating
            if not math.isfinite(original_rating):
                raise ValueError(
                    f"Non-finite rating for {probe_role.name} ({probe_role.position}); "
                    "refusing to prune from an invalid probe."
                )
            probe_rating = float(math.floor(original_rating) + 1)
            probe_role.rating = probe_rating
            probe_considered = set()

            def collect_probe(role, _slot, stage):
                if group in {"backup", "reserve"}:
                    starter_stage = stage.startswith(
                        ("starter_", "starter_replacement_", "starter_vacancy_")
                    )
                    backup_stage = group == "backup" and stage == "backup_selection"
                    if not starter_stage and not backup_stage:
                        return
                if is_standard(role):
                    probe_considered.add((str(role.player_id), role.position))

            _run_country_selection(
                conn,
                country,
                group,
                candidate_observer=collect_probe,
                roles_by_pos=probe_roles,
            )
            probe_role.rating = original_rating
            if key not in probe_considered:
                remove_keys.add(key)
                verb = "Would remove" if dry_run else "Removing"
                print(
                    f"{verb} {baseline_role.name} ({baseline_role.position}, "
                    f"{original_rating:.2f} -> {probe_rating:.2f} probe): "
                    "not evaluated by any position or wildcard selector."
                )

        if not remove_keys:
            print(f"No Standard player cards to remove for {country}.")
            return 0

        line_numbers_to_remove = {
            row["line_number"]
            for key in remove_keys
            for row in file_cards.get(key, [])
        }
        updated_content = "".join(
            line for line_number, line in enumerate(lines, start=1)
            if line_number not in line_numbers_to_remove
        )
        print(f"{len(line_numbers_to_remove)} Standard row(s) will be removed from {players_path}.")
        if dry_run:
            return len(line_numbers_to_remove)

        _atomic_write(players_path, updated_content)
        old_argv = sys.argv[:]
        try:
            conn.commit()
            sys.argv[:] = [str(ROOT / "scripts" / "fetch_game_data.py"), country]
            fetch_game_data.main()
        except BaseException:
            _atomic_write(players_path, original_content)
            raise
        finally:
            sys.argv[:] = old_argv
        return len(line_numbers_to_remove)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("country", help="country slug or country directory")
    parser.add_argument("--dry-run", action="store_true", help="report rows without removing them")
    args = parser.parse_args()
    try:
        prune_country(args.country, dry_run=args.dry_run)
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        print(f"Selection cleanup failed; no roster rows were intentionally removed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
