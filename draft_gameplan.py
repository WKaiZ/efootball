import os
import sqlite3
import sys

import gameplan.formation as formation
from gameplan.builder import build_gameplan
from gameplan.constants import DB_PATH
from gameplan.data import load_roles, load_formation, resolve_country_paths


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        country_folder = sys.argv[1] if len(sys.argv) > 1 else "belgium"
        country_name = os.path.basename(os.path.normpath(country_folder.strip()))
        formation_file, out_path = resolve_country_paths(country_folder)

        formation.FORMATION[:] = load_formation(formation_file)

        roles_by_pos = load_roles(conn, country_name)
        if not roles_by_pos:
            raise RuntimeError(
                f"No game_data rows found for country '{country_name}'. Run fetch_game_data.py {country_name} first."
            )
        starter_asg, sub_asg, wildcard_asg = build_gameplan(conn, roles_by_pos)

        lines = []
        lines.append("Starters:")
        for slot, a in zip(formation.FORMATION, starter_asg):
            if a is None:
                lines.append(f"  [{slot}] VACANT")
            else:
                lines.append(
                    f"  [{a.slot}] {a.player.name} ({a.player.position}) rating {a.player.rating:.2f} #{a.jersey}"
                )

        lines.append("")
        lines.append("Substitutes:")
        for slot, a in zip(formation.FORMATION, sub_asg):
            if a is None:
                lines.append(f"  [{slot}] VACANT")
            else:
                lines.append(
                    f"  [{a.slot}] {a.player.name} ({a.player.position}) rating {a.player.rating:.2f} #{a.jersey}"
                )

        if wildcard_asg is not None:
            lines.append("")
            lines.append("Wildcard:")
            a = wildcard_asg
            lines.append(
                f"  [{a.slot}] {a.player.name} ({a.player.position}) rating {a.player.rating:.2f} #{a.jersey}"
            )

        text = "\n".join(lines) + "\n"
        print(text, end="")

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
