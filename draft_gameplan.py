import os
import sqlite3
import sys

import gameplan.formation as formation
from gameplan.builder import build_gameplan
from gameplan.constants import DB_PATH
from gameplan.data import load_roles, load_formations, resolve_country_paths


def format_squad(starter_asg, sub_asg, wildcard_asgs, slots):
    lines = []
    lines.append("Starters:")
    for slot, a in zip(slots, starter_asg):
        if a is None:
            lines.append(f"  [{slot}] VACANT")
        else:
            lines.append(
                f"  [{a.slot}] {a.player.name} ({a.player.position}) rating {a.player.rating:.2f} #{a.jersey}"
            )

    lines.append("")
    lines.append("Substitutes:")
    for slot, a in zip(slots, sub_asg):
        if a is None:
            lines.append(f"  [{slot}] VACANT")
        else:
            lines.append(
                f"  [{a.slot}] {a.player.name} ({a.player.position}) rating {a.player.rating:.2f} #{a.jersey}"
            )

    if wildcard_asgs:
        lines.append("")
        lines.append("Wildcard:")
        for a in wildcard_asgs:
            lines.append(
                f"  [{a.slot}] {a.player.name} ({a.player.position}) rating {a.player.rating:.2f} #{a.jersey}"
            )

    return lines


def _squad_card_keys(starter_asg, sub_asg, wildcard_asgs):
    """Identify picked cards as (player_id, main_position).

    Same player may still appear in the other squad on a different-position card.
    """
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


def _is_contender(out_path):
    """True when the country folder lives under contenders/."""
    country_dir = os.path.dirname(os.path.abspath(out_path))
    return os.path.basename(os.path.dirname(country_dir)) == "contenders"


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        country_folder = sys.argv[1] if len(sys.argv) > 1 else "belgium"
        country_name = os.path.basename(os.path.normpath(country_folder.strip()))
        formation_file, out_path = resolve_country_paths(country_folder)

        primary_formation, secondary_formation = load_formations(formation_file)
        formation.FORMATION[:] = primary_formation

        roles_by_pos = load_roles(conn, country_name)
        if not roles_by_pos:
            raise RuntimeError(
                f"No game_data rows found for country '{country_name}'. Run fetch_game_data.py {country_name} first."
            )

        starter_asg, sub_asg, wildcard_asgs = build_gameplan(conn, roles_by_pos)

        if _is_contender(out_path):
            used_cards = _squad_card_keys(starter_asg, sub_asg, wildcard_asgs)
            remaining = _exclude_cards(roles_by_pos, used_cards)

            second_slots = secondary_formation if secondary_formation is not None else primary_formation
            formation.FORMATION[:] = second_slots
            starter_asg2, sub_asg2, wildcard_asgs2 = build_gameplan(conn, remaining)

            lines = ["First Squad", ""]
            lines.extend(format_squad(starter_asg, sub_asg, wildcard_asgs, primary_formation))
            lines.append("")
            lines.append("Second Squad")
            lines.append("")
            lines.extend(format_squad(starter_asg2, sub_asg2, wildcard_asgs2, second_slots))
        else:
            lines = format_squad(starter_asg, sub_asg, wildcard_asgs, primary_formation)

        text = "\n".join(lines) + "\n"
        print(text, end="")

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
