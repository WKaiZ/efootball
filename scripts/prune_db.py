import argparse
import sqlite3
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gameplan.constants import DB_PATH


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    try:
        referenced = {str(r[0]) for r in conn.execute("SELECT DISTINCT player_id FROM game_data")}
        if not referenced:
            print(f"  {'db':<10} skipped: game_data is empty, so removals cannot be trusted", file=sys.stderr)
            return
        names = {str(r[0]): r[1] for r in conn.execute("SELECT player_id, name FROM players")}
        known = set(names) | {str(r[0]) for r in conn.execute("SELECT DISTINCT player_id FROM jersey")}
        orphans = sorted(known - referenced)
        if not orphans:
            print(f"  {'db':<10} nothing to remove")
            return
        marks = ",".join("?" for _ in orphans)
        jersey_rows = conn.execute(
            f"SELECT COUNT(*) FROM jersey WHERE player_id IN ({marks})", orphans
        ).fetchone()[0]
        players_rows = sum(1 for pid in orphans if pid in names)
        verb = "would remove" if args.dry_run else "removed"
        print(
            f"  {'db':<10} {verb} {len(orphans)} unreferenced player(s) "
            f"({players_rows} players rows, {jersey_rows} jersey rows)"
        )
        labels = sorted(names.get(pid) or f"[{pid}]" for pid in orphans)
        indent = " " * 13
        print(textwrap.fill(", ".join(labels), width=100, initial_indent=indent, subsequent_indent=indent))
        if args.dry_run:
            return
        with conn:
            conn.execute(f"DELETE FROM jersey WHERE player_id IN ({marks})", orphans)
            conn.execute(f"DELETE FROM players WHERE player_id IN ({marks})", orphans)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
