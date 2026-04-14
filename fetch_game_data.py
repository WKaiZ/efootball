import os
import re
import sqlite3
import sys
import unicodedata

DB_PATH = "pes.db"

MANUAL_ID_OVERRIDES = {
    "argentina": {
        "nico gonzalez": "486031",
    },
    "brazil": {
        "gabriel": "435338",
        "ederson": "607854",
        "vitinho": "468249",
        "pepe": "520662",
        "pedro": "432895",
        "allan": "126422",
        "oscar": "85314",
    },
    "portugal": {
        "pepe": "14132",
    },
    "spain": {
        "pedro": "65278",
    },
    "colombia": {
        "luis suarez": "424784",
        "david silva": "74071",
        "richard rios": "735573",
        "dani torres": "93142",
    },
    "senegal" : {
        'souleymane basse': '1111589',
        'formose mendy': "649023",
    },
    "mexico": {
        "henry martin": "286339",
        "guillermo martinez": "347932",
        "erick sanchez": "370875",
        "osvaldo rodriguez": "295426",
        "johan vasquez": "532937",
        "felipe rodriguez": "102699",
    },
    "uruguay": {
        "luis suarez": "44352",
        "sebastian caceres": "532389",
        "jose luis rodriguez": "430339",
        "emiliano martinez": "707447",
        "agustin alvarez": "812625",
    },
    "switzerland": {
        "dominik schmid": "359409",
    },
    "usa": {
        "patrick agyemang": "1089574",
    },
}


def normalize_name(name):
    nfkd = unicodedata.normalize("NFKD", name)
    no_accents = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", no_accents).strip().lower()


def create_game_data_table(conn):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS game_data (
            country TEXT NOT NULL,
            player_id TEXT NOT NULL,
            position TEXT NOT NULL,
            rating REAL,
            recent INTEGER,
            card_type TEXT,
            proficient_positions TEXT,
            semiproficient_positions TEXT,
            PRIMARY KEY (country, player_id, position)
        )
        """
    )
    conn.commit()


def init_db(conn):
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'game_data'"
    )
    has_table = cur.fetchone() is not None
    if not has_table:
        create_game_data_table(conn)
        return

    cur.execute("PRAGMA table_info(game_data)")
    columns = [row[1] for row in cur.fetchall()]
    if "country" in columns:
        return

    cur.execute("ALTER TABLE game_data RENAME TO game_data_legacy")
    create_game_data_table(conn)
    cur.execute(
        """
        INSERT INTO game_data (
            country, player_id, position, rating, recent, card_type,
            proficient_positions, semiproficient_positions
        )
        SELECT
            '__legacy__', player_id, position, rating, recent, card_type,
            proficient_positions, semiproficient_positions
        FROM game_data_legacy
        """
    )
    cur.execute("DROP TABLE game_data_legacy")
    conn.commit()


def load_player_id_map(conn):
    cur = conn.cursor()
    cur.execute("SELECT player_id, name FROM players")
    mapping = {}
    for pid, name in cur.fetchall():
        key = normalize_name(name)
        mapping[key] = pid
    return mapping


def get_manual_override(country_name, player_name):
    country_overrides = MANUAL_ID_OVERRIDES.get(normalize_name(country_name), {})
    return country_overrides.get(normalize_name(player_name))


def levenshtein(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr.append(
                min(
                    prev[j] + 1,
                    curr[j - 1] + 1,
                    prev[j - 1] + cost,
                )
            )
        prev = curr
    return prev[-1]


def parse_positions_list(raw):
    m = re.search(r"\[(.*)\]", raw)
    if not m:
        return ""
    inside = m.group(1).strip()
    if not inside:
        return ""
    parts = [p.strip() for p in inside.split(",") if p.strip()]
    return ",".join(parts)


def parse_line(line, line_no):
    original = line
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 5:
        return False, {"error": f"Line {line_no}: too few comma-separated fields ({len(parts)}): {original}"}

    name = parts[0]
    main_pos = parts[1]

    try:
        rating = float(parts[2])
    except ValueError:
        return False, {"error": f"Line {line_no}: invalid rating '{parts[2]}': {original}"}

    tail = ",".join(parts[3:]).strip()

    bracket_matches = list(re.finditer(r"\[[^\]]*\]", tail))
    if len(bracket_matches) != 2:
        return False, {"error": f"Line {line_no}: expected two bracketed position lists: {original}"}

    prof_span = bracket_matches[0].span()
    semi_span = bracket_matches[1].span()

    flags_part = tail[: prof_span[0]].strip().strip(",")
    prof_raw = tail[prof_span[0] : prof_span[1]]
    semi_raw = tail[semi_span[0] : semi_span[1]]

    prof_positions = parse_positions_list(prof_raw)
    semi_positions = parse_positions_list(semi_raw)

    flag_tokens = [t.strip() for t in flags_part.split(",") if t.strip()]
    recent = None
    card_type = ""
    for tok in flag_tokens:
        low = tok.lower()
        if low == "true":
            recent = True
        elif low == "false":
            recent = False
        else:
            if not card_type:
                card_type = tok

    if recent is None:
        return False, {"error": f"Line {line_no}: could not determine recent flag (True/False): {original}"}
    if not card_type:
        card_type = "Unknown"

    return True, {
        "name": name,
        "position": main_pos,
        "rating": rating,
        "recent": recent,
        "card_type": card_type,
        "proficient_positions": prof_positions,
        "semiproficient_positions": semi_positions,
    }


def resolve_players_file(country_folder):
    folder = country_folder.strip()
    country_name = os.path.basename(os.path.normpath(folder))
    return os.path.join(folder, f"{country_name}_players.txt")


def main():
    country_folder = sys.argv[1] if len(sys.argv) > 1 else "belgium"
    txt_path = resolve_players_file(country_folder)
    country_name = os.path.basename(os.path.normpath(country_folder.strip()))
    if not os.path.exists(txt_path):
        print(f"Players file not found: {txt_path}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    try:
        init_db(conn)
        name_map = load_player_id_map(conn)
        if not name_map:
            print("Warning: 'players' table is empty; cannot map names to player_ids.")

        weird_lines = []
        inserted = 0
        updated = 0
        skipped_no_id = 0

        with open(txt_path, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f]

        cur = conn.cursor()
        cur.execute("DELETE FROM game_data WHERE country = ?", (country_name,))

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            ok, data = parse_line(stripped, idx)
            if not ok:
                weird_lines.append(data["error"])
                continue

            norm_name = normalize_name(data["name"])
            manual_player_id = get_manual_override(country_name, data["name"])
            if manual_player_id:
                player_id = manual_player_id
            elif norm_name in name_map:
                player_id = name_map[norm_name]
            else:
                best_key = None
                best_dist = 999
                for key in name_map.keys():
                    d = levenshtein(norm_name, key)
                    if d < best_dist:
                        best_dist = d
                        best_key = key

                if best_key is None or best_dist > 2:
                    skipped_no_id += 1
                    weird_lines.append(
                        f"Line {idx}: no player_id found in DB for name '{data['name']}' (closest distance {best_dist})"
                    )
                    continue

                player_id = name_map[best_key]

            cur.execute(
                """
                INSERT OR REPLACE INTO game_data
                    (country, player_id, position, rating, recent, card_type,
                     proficient_positions, semiproficient_positions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    country_name,
                    player_id,
                    data["position"],
                    data["rating"],
                    1 if data["recent"] else 0,
                    data["card_type"],
                    data["proficient_positions"],
                    data["semiproficient_positions"],
                ),
            )
            if cur.rowcount == 1:
                inserted += 1
            else:
                updated += 1

        conn.commit()

        print(f"Done processing {txt_path}.")
        print(f"  Rows inserted/updated into game_data: {inserted}")
        if skipped_no_id:
            print(f"  Rows skipped due to missing player_id: {skipped_no_id}")

        if weird_lines:
            print("\nPotentially weird lines or issues detected:")
            for msg in weird_lines:
                print(" -", msg)
        else:
            print("\nNo obvious issues detected in the txt file.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()

