import sqlite3

from jersey_fetch.constants import DB_PATH, MANUAL_ID_OVERRIDES
from jersey_fetch.names import normalize_name


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS players (
            player_id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS jersey (
            player_id TEXT NOT NULL,
            idx INTEGER NOT NULL,
            season TEXT,
            country TEXT,
            number INTEGER,
            PRIMARY KEY (player_id, idx)
        )
        """
    )
    conn.commit()
    return conn


def load_player_id_map(conn):
    cur = conn.cursor()
    cur.execute("SELECT player_id, name FROM players")
    mapping = {}
    for pid, name in cur.fetchall():
        mapping[normalize_name(name)] = str(pid)
    return mapping


def get_official_name(conn, player_id):
    cur = conn.cursor()
    cur.execute("SELECT name FROM players WHERE player_id = ?", (str(player_id),))
    row = cur.fetchone()
    return row[0] if row else None


def get_manual_override(country_name, player_name, position=None):
    country_overrides = MANUAL_ID_OVERRIDES.get(normalize_name(country_name), {})
    override = country_overrides.get(normalize_name(player_name))
    if not override:
        return None
    if "player_id" in override:
        return override
    if position:
        pos_key = position.strip().upper()
        return override.get(pos_key) or override.get("default")
    return None


def merge_jersey_entries(espn_entry, transfermarkt_entries):
    entries = list(transfermarkt_entries)
    if not espn_entry:
        return entries
    espn_season = str(espn_entry.get("season") or "").strip()
    for entry in entries:
        if int(entry["number"]) != int(espn_entry["number"]):
            continue
        if normalize_name(entry["country"]) != normalize_name(espn_entry["country"]):
            continue
        if (entry.get("season") or "").strip() == espn_season:
            return entries
    return [espn_entry] + entries


def _split_jersey_entries_by_nation(entries, expected_nation_label):
    exp = normalize_name(expected_nation_label)
    matching = []
    foreign = []
    for e in entries:
        c = normalize_name((e.get("country") or ""))
        if c == exp:
            matching.append(e)
        else:
            foreign.append(e)
    return (matching, foreign)


def warn_jersey_entries_nation_mismatch(entries, expected_nation_label, player_name, player_id):
    if not expected_nation_label or not entries:
        return
    matching, foreign = _split_jersey_entries_by_nation(entries, expected_nation_label)
    if not matching and foreign:
        foreign_labels = sorted({e["country"] for e in foreign})
        print(
            f"  Warning: No {expected_nation_label} national shirt number for {player_name} ({player_id}); "
            f"Transfermarkt lists only: {', '.join(foreign_labels)}"
        )
    elif matching and foreign:
        foreign_labels = sorted({e["country"] for e in foreign})
        print(
            f"  Warning: {player_name} ({player_id}) has national shirt numbers for other nations too: "
            f"{', '.join(foreign_labels)}"
        )


def warn_cached_jersey_nation_mismatch(conn, player_id, expected_nation_label):
    if not expected_nation_label:
        return
    cur = conn.cursor()
    cur.execute("SELECT name FROM players WHERE player_id = ?", (str(player_id),))
    row = cur.fetchone()
    db_name = row[0] if row else str(player_id)
    cur.execute("SELECT DISTINCT country FROM jersey WHERE player_id = ?", (str(player_id),))
    countries = [r[0] for r in cur.fetchall()]
    if not countries:
        return
    exp = normalize_name(expected_nation_label)
    if any((normalize_name(c) == exp for c in countries)):
        return
    print(
        f"  Warning: Cached jersey rows for {db_name} ({player_id}) include no {expected_nation_label} entry; "
        f"nations present: {', '.join(sorted(countries))}"
    )


def store_jersey_entries(conn, player_id, official_name, entries, cache_country_filter=None):
    by_number = {}
    for entry in entries:
        by_number.setdefault(str(entry["number"]), set()).add(entry["country"])
    nums = sorted(by_number.keys(), key=int)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO players (player_id, name) VALUES (?, ?)",
        (str(player_id), official_name),
    )
    if cache_country_filter:
        cur.execute(
            "DELETE FROM jersey WHERE player_id = ? AND LOWER(country) = LOWER(?)",
            (str(player_id), cache_country_filter),
        )
    else:
        cur.execute("DELETE FROM jersey WHERE player_id = ?", (str(player_id),))
    for idx, entry in enumerate(entries):
        cur.execute(
            "INSERT OR REPLACE INTO jersey (player_id, idx, season, country, number) VALUES (?, ?, ?, ?, ?)",
            (str(player_id), idx, entry["season"], entry["country"], int(entry["number"])),
        )
    conn.commit()
    return (nums, by_number)


def load_cached_numbers_from_db(conn, player_id, country_filter=None, display_name=None):
    cur = conn.cursor()
    cur.execute("SELECT name FROM players WHERE player_id = ?", (str(player_id),))
    name_row = cur.fetchone()
    db_name = name_row[0] if name_row else str(player_id)
    label = display_name if display_name else db_name
    if country_filter:
        cur.execute(
            """
            SELECT number, country
            FROM jersey
            WHERE player_id = ? AND LOWER(country) = LOWER(?)
            ORDER BY idx ASC
            """,
            (str(player_id), country_filter),
        )
    else:
        cur.execute(
            "SELECT number, country FROM jersey WHERE player_id = ? ORDER BY idx ASC",
            (str(player_id),),
        )
    rows = cur.fetchall()
    if not rows:
        return []
    nums_by_country = {}
    for num, country in rows:
        nums_by_country.setdefault(str(num), set()).add(country)
    if country_filter:
        print(f"{label} {player_id} national jersey numbers (cached for {country_filter}):")
    else:
        print(f"{label} {player_id} national jersey numbers (cached):")
    for n in sorted(nums_by_country.keys(), key=int):
        countries = ", ".join(sorted(nums_by_country[n]))
        print(f"  {n}: {countries}")
    return sorted(nums_by_country.keys(), key=int)
