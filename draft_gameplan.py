import os
import sqlite3
import sys

import gameplan.formation as formation
from gameplan.builder import build_gameplan
from gameplan.constants import DB_PATH
from gameplan.data import load_roles, load_formation, resolve_country_paths


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


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        country_folder = sys.argv[1] if len(sys.argv) > 1 else "belgium"
        country_name = os.path.basename(os.path.normpath(country_folder.strip()))
        formation_file, out_path = resolve_country_paths(country_folder)

        slots = load_formation(formation_file)
        if not os.path.exists(formation_file):
            default = ", ".join(slots)
            print(
                f"No {country_name}_formation.txt found; using default formation: {default}",
                file=sys.stderr,
            )
        formation.FORMATION[:] = slots

        roles_by_pos = load_roles(conn, country_name)
        if not roles_by_pos:
            raise RuntimeError(
                f"No game_data rows found for country '{country_name}'. Run fetch_game_data.py {country_name} first."
            )

        starter_asg, sub_asg, wildcard_asgs = build_gameplan(conn, roles_by_pos)
        lines = format_squad(starter_asg, sub_asg, wildcard_asgs, slots)

        text = "\n".join(lines) + "\n"
        print(text, end="")

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
