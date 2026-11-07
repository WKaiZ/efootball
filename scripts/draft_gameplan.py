import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gameplan.formation as formation
from gameplan.builder import build_gameplan
from gameplan.constants import DB_PATH
from gameplan.models import Assignment
from gameplan.jerseys import jersey_prefs_for_player
from gameplan.candidates import report_candidates
from gameplan.data import load_roles, resolve_country_paths
from gameplan.formation_selection import choose_formation


BENCH_GROUPS = (
    ("FW", frozenset({"LWF", "RWF", "CF", "SS"})),
    ("MF", frozenset({"AMF", "CMF", "DMF", "LMF", "RMF"})),
    ("DF", frozenset({"LB", "CB", "RB"})),
    ("GK", frozenset({"GK"})),
)


def compact_backup(conn, roles_by_pos, starter_asg, candidate_observer=None):
    starters = [a for a in starter_asg if a is not None]
    used_ids = {a.player.player_id for a in starters}
    used_numbers = {a.jersey for a in starters}
    cards = sorted(
        (r for roles in roles_by_pos.values() for r in roles),
        key=lambda r: r.rating, reverse=True,
    )

    def pick(slot_for, tiers):
        for eligible in tiers:
            for r in cards:
                if r.player_id in used_ids:
                    continue
                matched = eligible(r)
                if not matched:
                    continue
                slot = matched if isinstance(matched, str) else "WILD"
                report_candidates(candidate_observer, [r], slot, "backup_selection")
                most_recent, prefs = jersey_prefs_for_player(conn, r)
                num = most_recent if r.recent and most_recent not in used_numbers else None
                if num is None:
                    num = next((n for n in prefs if n not in used_numbers), None)
                if num is None:
                    continue
                used_ids.add(r.player_id)
                used_numbers.add(num)
                return Assignment(slot=slot_for(r, matched), player=r, jersey=num)
        return None

    def tier(group, attr):
        def eligible(r):
            if attr is None:
                return r.position if r.position in group else None
            return next((p for p in getattr(r, attr) or [] if p in group), None)
        return eligible

    bench = [None] * len(BENCH_GROUPS)
    for attr in (None, "proficient_positions", "semiproficient_positions"):
        for i, (label, group) in enumerate(BENCH_GROUPS):
            if bench[i] is None:
                bench[i] = pick(lambda r, m, label=label: label, [tier(group, attr)])
    vacant = sum(1 for a in starter_asg + bench if a is None)
    wildcards = []
    for _ in range(1 + vacant):
        wildcard = pick(lambda r, m: "WILD", [lambda r: True])
        if wildcard is None:
            break
        wildcards.append(wildcard)
    return bench, wildcards


def format_squad(starter_asg, sub_asg, wildcard_asgs, slots, *, starters_only=False, omit_vacant_starters=False, max_starters=None, compact_bench=False):
    lines = []
    lines.append("Starters:")
    starter_pairs = list(zip(slots, starter_asg))
    if max_starters is not None:
        starter_pairs = [(slot, assignment) for slot, assignment in starter_pairs if assignment]
        starter_pairs.sort(key=lambda pair: pair[1].player.rating, reverse=True)
        starter_pairs = starter_pairs[:max_starters]
    for slot, a in starter_pairs:
        if a is None:
            if not omit_vacant_starters:
                lines.append(f"  [{slot}] VACANT")
        else:
            lines.append(
                f"  [{a.slot}] {a.player.name} ({a.player.position}) rating {a.player.rating:.2f} #{a.jersey}"
            )

    if starters_only:
        return lines

    if compact_bench:
        lines.append("")
        lines.append("Substitutes:")
        for label, group in BENCH_GROUPS:
            a = sub_asg[BENCH_GROUPS.index((label, group))]
            if a is None:
                lines.append(f"  [{label}] VACANT")
                continue
            lines.append(
                f"  [{a.slot}] {a.player.name} ({a.player.position}) rating {a.player.rating:.2f} #{a.jersey}"
            )
        sub_asg = []
        slots = []

    if not compact_bench:
        lines.append("")
        lines.append("Substitutes:")
    for slot, a in zip(slots, sub_asg):
        if a is None:
            lines.append(f"  [{slot}] VACANT")
        else:
            lines.append(
                f"  [{a.slot}] {a.player.name} ({a.player.position}) rating {a.player.rating:.2f} #{a.jersey}"
            )

    lines.append("")
    lines.append("Wildcard:")
    if not wildcard_asgs:
        lines.append("  [WILD] VACANT")
    else:
        for a in wildcard_asgs:
            lines.append(
                f"  [{a.slot}] {a.player.name} ({a.player.position}) rating {a.player.rating:.2f} #{a.jersey}"
            )

    return lines


SQUADS_PER_GROUP = {"contenders": 2}
CONTENDER_SQUADS = SQUADS_PER_GROUP["contenders"]
SQUAD_NAMES = ["First", "Second", "Third"]


def _squad_card_keys(starter_asg, sub_asg, wildcard_asgs):
    return {
        (a.player.player_id, a.player.position)
        for a in (starter_asg + sub_asg + wildcard_asgs)
        if a is not None
    }


def _exclude_cards(roles_by_pos, used_cards):
    filtered = {}
    for pos, roles in roles_by_pos.items():
        kept = [r for r in roles if (r.player_id, r.position) not in used_cards]
        if kept:
            filtered[pos] = kept
    return filtered


def _plan(conn, roles_by_pos, slots):
    if not roles_by_pos:
        return [None] * len(slots), [None] * len(slots), []
    return build_gameplan(conn, roles_by_pos)


def _country_group(out_path):
    country_dir = os.path.dirname(os.path.abspath(out_path))
    return os.path.basename(os.path.dirname(country_dir))


def _squad_count(out_path):
    return SQUADS_PER_GROUP.get(_country_group(out_path), 1)


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        country_folder = sys.argv[1] if len(sys.argv) > 1 else "belgium"
        country_name = os.path.basename(os.path.normpath(country_folder.strip()))
        _formation_file, out_path = resolve_country_paths(country_folder)

        roles_by_pos = load_roles(conn, country_name)
        if not roles_by_pos:
            print(
                f"No game_data rows found for country '{country_name}'; every position will be VACANT.",
                file=sys.stderr,
            )

        primary_formation = choose_formation(conn, roles_by_pos)
        formation.FORMATION[:] = primary_formation
        starter_asg, sub_asg, wildcard_asgs = _plan(conn, roles_by_pos, primary_formation)

        if _squad_count(out_path) > 1:
            squads = [(primary_formation, starter_asg, sub_asg, wildcard_asgs)]
            remaining = roles_by_pos
            while len(squads) < _squad_count(out_path):
                _slots, _st, _sb, _wc = squads[-1]
                remaining = _exclude_cards(remaining, _squad_card_keys(_st, _sb, _wc))
                slots = choose_formation(conn, remaining)
                formation.FORMATION[:] = slots
                st, sb, wc = _plan(conn, remaining, slots)
                squads.append((slots, st, sb, wc))

            lines = []
            for i, (slots, st, sb, wc) in enumerate(squads):
                if i:
                    lines.append("")
                lines.extend([f"{SQUAD_NAMES[i]} Squad", ""])
                lines.extend(format_squad(st, sb, wc, slots))
        else:
            if _country_group(out_path) == "backup":
                sub_asg, wildcard_asgs = compact_backup(conn, roles_by_pos, starter_asg)
            lines = format_squad(
                starter_asg, sub_asg, wildcard_asgs, primary_formation,
                starters_only=_country_group(out_path) == "reserve",
                compact_bench=_country_group(out_path) == "backup",
            )

        text = "\n".join(lines) + "\n"
        print(text, end="")

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
