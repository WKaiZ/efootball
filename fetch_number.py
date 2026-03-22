import asyncio
import os
import re
import shutil
import sqlite3
import sys
import time
import urllib.parse
import unicodedata
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


DB_PATH = "pes.db"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
}

MANUAL_ID_OVERRIDES = {
    "argentina": {
        "nico gonzalez": {"player_id": "486031", "preserve_name": True},
    },
    "brazil": {
        "gabriel": {"player_id": "435338", "preserve_name": True},
        "ederson": {"player_id": "607854", "preserve_name": True},
        "vitinho": {"player_id": "468249", "preserve_name": True},
        "pepe": {"player_id": "520662", "preserve_name": True},
        "pedro": {"player_id": "432895", "preserve_name": True},
        "allan": {"player_id": "126422", "preserve_name": True},
        "oscar": {"player_id": "85314", "preserve_name": True},
    },
    "portugal": {
        "pepe": {"player_id": "14132", "preserve_name": True},
    },
    "spain": {
        "pedro": {"player_id": "65278", "preserve_name": True},
    }
}

def normalize_name(name):
    nfkd = unicodedata.normalize("NFKD", name)
    no_accents = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", no_accents).strip().lower()


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


def get_manual_override(country_name, player_name):
    country_overrides = MANUAL_ID_OVERRIDES.get(normalize_name(country_name), {})
    return country_overrides.get(normalize_name(player_name))


def country_display_name(country_name):
    return country_name.replace("_", " ").strip().title()


def parse_args(argv):
    country_folder = "belgium"
    force_refetch = False
    positional = []
    for arg in argv[1:]:
        if arg in ("--refetch", "--refresh", "--no-cache"):
            force_refetch = True
        else:
            positional.append(arg)
    if len(positional) > 1:
        raise SystemExit("Usage: python fetch_number.py [--refetch] [country_folder]")
    if positional:
        country_folder = positional[0]
    return country_folder, force_refetch


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
    return out, changed


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


def espn_request_json(url, params=None):
    r = requests.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()


def is_womens_espn_competition(text):
    low = (text or "").strip().lower()
    return any(
        marker in low
        for marker in (
            "women",
            "women's",
            "womens",
            "wworld",
            "shebelieves",
            "femen",
            "femin",
        )
    )


def lookup_espn_team(country_label):
    queries = [
        f"{country_label} national team",
        country_label,
    ]
    best = None
    target = normalize_name(country_label)
    for query in queries:
        data = espn_request_json(
            "https://site.api.espn.com/apis/common/v3/search",
            params={"query": query},
        )
        for item in data.get("items", []):
            if item.get("type") != "team" or item.get("sport") != "soccer":
                continue
            name = item.get("displayName", "")
            name_norm = normalize_name(name)
            if name_norm != target:
                continue
            league = (item.get("league") or "").lower()
            if is_womens_espn_competition(league):
                continue
            score = 0
            if league == "fifa.world":
                score += 100
            elif league.startswith("fifa."):
                score += 50
            if normalize_name(query) == target:
                score += 10
            if best is None or score > best[0]:
                best = (score, str(item.get("id")))
        if best is not None and best[0] >= 100:
            break
    return best[1] if best else None


def build_espn_player_aliases(player_entry):
    athlete = player_entry.get("athlete", {})
    aliases = set()
    for raw in (
        athlete.get("fullName"),
        athlete.get("displayName"),
        athlete.get("shortName"),
        athlete.get("lastName"),
    ):
        if raw:
            aliases.add(normalize_name(raw))
    return {alias for alias in aliases if alias}


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


def compatible_name_tokens(local_name, espn_alias):
    local_tokens = [tok for tok in normalize_name(local_name).split() if tok]
    espn_tokens = [tok for tok in normalize_name(espn_alias).split() if tok]
    if not local_tokens or not espn_tokens:
        return False
    if local_tokens == espn_tokens:
        return True
    if len(local_tokens) != len(espn_tokens):
        return False
    if local_tokens[-1] != espn_tokens[-1]:
        return False
    for left, right in zip(local_tokens[:-1], espn_tokens[:-1]):
        if left == right:
            continue
        if left.startswith(right) or right.startswith(left):
            continue
        return False
    return True


def invalid_transfermarkt_title(title_text):
    low = normalize_name(title_text)
    return low in {
        "502 bad gateway",
        "503 service unavailable",
        "504 gateway timeout",
        "403 forbidden",
        "429 too many requests",
        "access denied",
        "just a moment",
        "error",
    }


def espn_lineup_role(position_abbreviation):
    abbr = (position_abbreviation or "").strip().upper()
    if not abbr or abbr == "SUB":
        return None
    if abbr in {"G", "GK"}:
        return "G"
    if abbr in {"D", "CB", "LB", "RB", "CD-L", "CD-R", "SW"}:
        return "D"
    if abbr in {"M", "DM", "CM", "CM-L", "CM-R", "AM", "AM-L", "AM-R", "LM", "RM"}:
        return "M"
    if abbr in {"F", "FW", "CF", "CF-L", "CF-R", "LW", "RW", "ST", "SS"}:
        return "F"
    return None


def fetch_espn_athlete_role(athlete_id):
    if not athlete_id:
        return None
    try:
        data = espn_request_json(
            f"https://site.web.api.espn.com/apis/common/v3/sports/soccer/athletes/{athlete_id}"
        )
    except requests.RequestException:
        return None
    athlete = data.get("athlete", {})
    position = athlete.get("position", {}) or {}
    abbr = position.get("abbreviation")
    if abbr in {"G", "D", "M", "F"}:
        return abbr
    return None


def season_label_for_match_date(match_dt):
    start_year = match_dt.year if match_dt.month >= 7 else match_dt.year - 1
    end_year = start_year + 1
    return f"{start_year % 100:02d}/{end_year % 100:02d}"


def fetch_latest_espn_roster(country_label):
    team_id = lookup_espn_team(country_label)
    if not team_id:
        print(f"Could not resolve ESPN team ID for {country_label}.")
        return None

    schedule = espn_request_json(
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{team_id}/schedule",
        params={"limit": 100},
    )
    completed = []
    now = datetime.now(timezone.utc)
    for event in schedule.get("events", []):
        competition = (event.get("competitions") or [{}])[0]
        status = competition.get("status", {}).get("type", {})
        event_date_raw = event.get("date")
        if not status.get("completed") or not event_date_raw:
            continue
        try:
            event_dt = datetime.fromisoformat(event_date_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if event_dt > now:
            continue
        completed.append((event_dt, event))
    if not completed:
        print(f"No completed ESPN matches found for {country_label}.")
        return None

    completed.sort(key=lambda item: item[0], reverse=True)
    latest_dt, latest_event = completed[0]
    event_id = latest_event.get("id")
    summary = espn_request_json(
        "https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary",
        params={"event": event_id},
    )

    roster_payload = None
    for roster in summary.get("rosters", []):
        if str(roster.get("team", {}).get("id")) == str(team_id):
            roster_payload = roster
            break
    if roster_payload is None:
        print(f"ESPN summary for {country_label} did not include a matching roster.")
        return None

    athlete_role_cache = {}
    roster = []
    for player in roster_payload.get("roster", []):
        jersey = player.get("jersey")
        if not jersey or not str(jersey).isdigit():
            continue
        aliases = build_espn_player_aliases(player)
        if not aliases:
            continue
        athlete_id = str(player.get("athlete", {}).get("id") or "")
        role = espn_lineup_role(player.get("position", {}).get("abbreviation"))
        if role is None and athlete_id:
            if athlete_id not in athlete_role_cache:
                athlete_role_cache[athlete_id] = fetch_espn_athlete_role(athlete_id)
            role = athlete_role_cache[athlete_id]
        roster.append(
            {
                "aliases": aliases,
                "jersey": int(jersey),
                "role": role,
            }
        )

    lineup_url = f"https://www.espn.com/soccer/lineups/_/gameId/{event_id}"
    print(
        f"Latest ESPN match for {country_label}: {latest_event.get('name')} "
        f"({latest_dt.date()}) [{lineup_url}]"
    )
    return {
        "event_id": str(event_id),
        "date": latest_dt.date().isoformat(),
        "season": season_label_for_match_date(latest_dt),
        "country": country_label,
        "lineup_url": lineup_url,
        "roster": roster,
    }


def map_recent_players_to_roster(player_profiles, latest_match):
    if not latest_match:
        return {}, {}

    roster_names = list(player_profiles.items())
    recent_flags = {key: False for key in player_profiles.keys()}
    recent_numbers = {}
    taken = set()

    for espn_player in latest_match["roster"]:
        matched_key = None
        espn_role = espn_player.get("role")
        for key, profile in roster_names:
            if key in taken:
                continue
            if espn_role and profile["roles"] and espn_role not in profile["roles"]:
                continue
            if any(compatible_name_tokens(key, alias) for alias in espn_player["aliases"]):
                matched_key = key
                break
        if matched_key is None:
            for key, profile in roster_names:
                if key in taken:
                    continue
                if espn_role and profile["roles"] and espn_role not in profile["roles"]:
                    continue
                roster_tokens = [tok for tok in key.split() if tok]
                if len(roster_tokens) == 1:
                    if any(roster_tokens[0] in alias.split() for alias in espn_player["aliases"]):
                        matched_key = key
                        break
                else:
                    if any(
                        alias.startswith(key + " ") or key.startswith(alias + " ")
                        for alias in espn_player["aliases"]
                    ):
                        matched_key = key
                        break
        if matched_key is None:
            continue
        taken.add(matched_key)
        recent_flags[matched_key] = True
        recent_numbers[matched_key] = {
            "season": latest_match["season"],
            "match_date": latest_match["date"],
            "country": latest_match["country"],
            "number": espn_player["jersey"],
            "source": "espn",
        }
    return recent_flags, recent_numbers


def season_matches_year(season_text, year):
    if not season_text:
        return False
    nums = re.findall(r"\d{2,4}", season_text)
    if not nums:
        return False
    target_short = year % 100
    for raw in nums:
        val = int(raw)
        if len(raw) == 4 and val == year:
            return True
        if len(raw) == 2 and val == target_short:
            return True
    return False


def merge_jersey_entries(espn_entry, transfermarkt_entries):
    entries = list(transfermarkt_entries)
    if not espn_entry:
        return entries
    espn_season = (espn_entry.get("season") or "").strip()
    for entry in entries:
        if int(entry["number"]) != int(espn_entry["number"]):
            continue
        if normalize_name(entry["country"]) != normalize_name(espn_entry["country"]):
            continue
        if (entry.get("season") or "").strip() == espn_season:
            return entries
    return [espn_entry] + entries


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
        cur.execute(
            "DELETE FROM jersey WHERE player_id = ?",
            (str(player_id),),
        )
    for idx, entry in enumerate(entries):
        cur.execute(
            "INSERT OR REPLACE INTO jersey (player_id, idx, season, country, number) VALUES (?, ?, ?, ?, ?)",
            (str(player_id), idx, entry["season"], entry["country"], int(entry["number"])),
        )
    conn.commit()
    return nums, by_number


def extract_national_numbers_from_html(html):
    by_number = {}
    entries = []

    section_match = re.search(
        r'<div id="yw2" class="grid-view">(.+?)</table>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not section_match:
        return by_number, entries

    section_html = section_match.group(1)

    for row in re.findall(r"<tr[^>]*>(.+?)</tr>", section_html, flags=re.DOTALL | re.IGNORECASE):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.DOTALL | re.IGNORECASE)
        if len(cells) < 3:
            continue

        season_cell = cells[0]
        if len(cells) >= 4:
            raw_club = cells[2]
            raw_num = cells[3]
        else:
            raw_club = cells[1]
            raw_num = cells[2]

        season = re.sub(r"<.*?>", "", season_cell).strip()
        club_cell = re.sub(r"<.*?>", "", raw_club).strip()
        num_cell = re.sub(r"<.*?>", "", raw_num).strip()

        if not club_cell or not num_cell or not season:
            continue

        m = re.search(r"\b(\d{1,2})\b", num_cell)
        if not m:
            continue
        num = m.group(1)

        club_low = club_cell.strip().lower()
        if re.search(r"\s+b$", club_low):
            continue

        if any(
            u in club_cell
            for u in (
                "U15",
                "U16",
                "U17",
                "U18",
                "U19",
                "U20",
                "U21",
                "U23",
                "Olympic",
            )
        ):
            continue

        by_number.setdefault(num, set()).add(club_cell)
        entries.append({"season": season, "country": club_cell, "number": num})

    return by_number, entries


def get_transfermarkt_id(player):
    def unwrap_duckduckgo_link(link):
        if not link:
            return None
        if link.startswith("/l/") or "duckduckgo.com/l/?" in link:
            if link.startswith("//"):
                link_to_parse = "https:" + link
            elif link.startswith("/"):
                link_to_parse = "https://duckduckgo.com" + link
            else:
                link_to_parse = link
            parsed = urllib.parse.urlparse(link_to_parse)
            qs = urllib.parse.parse_qs(parsed.query)
            if "uddg" in qs and qs["uddg"]:
                return qs["uddg"][0]
        return link

    def score_candidate(player_name, link, text):
        if not link or "transfermarkt." not in link or "/spieler/" not in link:
            return None
        m = re.search(r"/spieler/(\d+)", link)
        if not m:
            return None
        pid = m.group(1)
        parsed = urllib.parse.urlparse(link)
        path = parsed.path.lower()
        slug = ""
        parts = [p for p in path.split("/") if p]
        if parts:
            slug = parts[0].replace("-", " ")
        player_norm = normalize_name(player_name)
        text_norm = normalize_name(text)
        slug_norm = normalize_name(slug)
        player_tokens = [tok for tok in player_norm.split() if tok]

        score = 0
        if slug_norm == player_norm:
            score += 100
        elif player_norm and player_norm in slug_norm:
            score += 80

        if text_norm.startswith(player_norm):
            score += 60
        elif player_norm and player_norm in text_norm:
            score += 40

        token_matches = sum(1 for tok in player_tokens if tok in slug_norm or tok in text_norm)
        score += token_matches * 10

        if token_matches == 0:
            return None
        return score, pid

    queries = [
        f"{player} transfermarkt",
        f"\"{player}\" transfermarkt",
        f"{player} transfermarkt player",
        f"{player} transfermarkt spieler",
    ]

    print(f"Searching ID for {player} via DuckDuckGo...")
    best = None
    seen_pids = set()

    for raw_query in queries:
        query = urllib.parse.quote(raw_query)
        url = f"https://duckduckgo.com/html/?q={query}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
        except requests.RequestException as e:
            print(f"  Request failed while searching ID for {player}: {e}")
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            link = unwrap_duckduckgo_link(a.get("href"))
            text = " ".join(a.get_text(" ", strip=True).split())
            scored = score_candidate(player, link, text)
            if not scored:
                continue
            score, pid = scored
            if pid in seen_pids:
                continue
            seen_pids.add(pid)
            if best is None or score > best[0]:
                best = (score, pid)
                if score >= 100:
                    break
        if best is not None and best[0] >= 100:
            break

    if best is not None:
        print(f"  Found ID for {player}: {best[1]}")
        return best[1]

    print(f"  ID not found in search results for {player}")
    return None


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


def load_cached_numbers_from_db(conn, player_id, country_filter=None):
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM players WHERE player_id = ?",
        (str(player_id),),
    )
    name_row = cur.fetchone()
    db_name = name_row[0] if name_row else str(player_id)
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
        print(f"{db_name} {player_id} national jersey numbers (cached for {country_filter}):")
    else:
        print(f"{db_name} {player_id} national jersey numbers (cached):")
    for n in sorted(nums_by_country.keys(), key=int):
        countries = ", ".join(sorted(nums_by_country[n]))
        print(f"  {n}: {countries}")

    return sorted(nums_by_country.keys(), key=int)


async def fetch_numbers_for_player(
    playwright,
    name,
    player_id,
    conn,
    db_name_override=None,
    cache_country_filter=None,
    espn_seed_entry=None,
):
    nums = load_cached_numbers_from_db(conn, player_id, country_filter=cache_country_filter)
    if nums:
        return nums, True

    url = f"https://www.transfermarkt.com/-/rueckennummern/spieler/{player_id}"

    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()
    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=120000)
        except PlaywrightTimeoutError:
            print(f"  Timeout loading {url}. Skipping for now.")
            if espn_seed_entry:
                official_name = db_name_override or name
                nums, by_number = store_jersey_entries(
                    conn,
                    player_id,
                    official_name,
                    [espn_seed_entry],
                    cache_country_filter=cache_country_filter,
                )
                print(f"{official_name} {player_id} national jersey numbers (ESPN fallback):")
                for n in nums:
                    countries = ", ".join(sorted(by_number[n]))
                    print(f"  {n}: {countries}")
                return nums, False
            return [], False

        for selector in [
            'button[title*="Accept"]',
            'button:has-text("Accept all")',
            'button:has-text("I agree")',
            'button:has-text("Continue")',
        ]:
            try:
                if await page.is_visible(selector, timeout=2000):
                    await page.click(selector)
                    break
            except Exception:
                pass

        await page.wait_for_timeout(2000)

        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        official_name = name
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            title_text = title_tag.string.strip()
            parts = title_text.split(" - ", 1)
            if parts:
                candidate_name = parts[0].strip()
                if not invalid_transfermarkt_title(candidate_name):
                    official_name = candidate_name
        if db_name_override:
            official_name = db_name_override

        debug_dir = "debug_html"
        os.makedirs(debug_dir, exist_ok=True)
        debug_path = os.path.join(debug_dir, f"debug_playwright_{player_id}.html")
        try:
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"  Wrote Playwright HTML to {debug_path}")
        except Exception as e:
            print(f"  Failed to write Playwright debug HTML for {player_id}: {e}")

        _, entries = extract_national_numbers_from_html(html)
        entries = merge_jersey_entries(espn_seed_entry, entries)
        nums, by_number = store_jersey_entries(
            conn,
            player_id,
            official_name,
            entries,
            cache_country_filter=cache_country_filter,
        )

        if by_number:
            print(f"{official_name} {player_id} national jersey numbers:")
            for n in nums:
                countries = ", ".join(sorted(by_number[n]))
                print(f"  {n}: {countries}")
        else:
            print(f"{name} {player_id} national jersey numbers: NONE FOUND")
        return nums, False
    finally:
        await browser.close()


async def main():
    conn = init_db()
    async with async_playwright() as p:
        country_folder, force_refetch = parse_args(sys.argv)
        players_file = resolve_players_file(country_folder)

        if not os.path.exists(players_file):
            print(f"No {players_file} found; nothing to do.")
            return

        with open(players_file, "r", encoding="utf-8") as f:
            raw_lines = [line.rstrip("\n") for line in f]

        country_name = os.path.basename(os.path.normpath(country_folder.strip()))
        country_label = country_display_name(country_name)

        players = []
        for line in raw_lines:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if not parts:
                continue
            players.append(parts[0])
        player_profiles = build_local_player_profiles(raw_lines)

        latest_match = None
        recent_flags = {}
        recent_numbers = {}
        if force_refetch:
            latest_match = fetch_latest_espn_roster(country_label)
            recent_flags, recent_numbers = map_recent_players_to_roster(player_profiles, latest_match)
            if recent_flags:
                raw_lines, changed = rewrite_players_txt(raw_lines, recent_flags=recent_flags)
                if changed:
                    with open(players_file, "w", encoding="utf-8") as f:
                        for ln in raw_lines:
                            f.write(ln + "\n")
                    print(f"Updated recent flags in {players_file} from ESPN latest match.")

        id_map = load_player_id_map(conn)
        had_error = False
        name_changes = {}
        refreshed_player_ids = set()

        for name in players:
            override = get_manual_override(country_name, name)
            pid_str = id_map.get(normalize_name(name))
            if override:
                pid_str = override["player_id"]
            if not pid_str:
                pid_str = get_transfermarkt_id(name)
                time.sleep(5)
            if not pid_str:
                print(f"Skipping {name}: could not resolve Transfermarkt ID.")
                had_error = True
                continue
            id_map[normalize_name(name)] = str(pid_str)
            pid = int(pid_str)
            should_clear_country_cache = force_refetch and pid not in refreshed_player_ids
            if should_clear_country_cache:
                cur = conn.cursor()
                cur.execute(
                    """
                    DELETE FROM jersey
                    WHERE player_id = ? AND LOWER(country) = LOWER(?)
                    """,
                    (str(pid), country_label),
                )
                conn.commit()
            db_name_override = name if override and override.get("preserve_name") else None
            cache_country_filter = country_label if force_refetch else None
            espn_seed_entry = recent_numbers.get(normalize_name(name)) if force_refetch else None
            nums, used_cache = await fetch_numbers_for_player(
                p,
                name,
                pid,
                conn,
                db_name_override=db_name_override,
                cache_country_filter=cache_country_filter,
                espn_seed_entry=espn_seed_entry,
            )
            if not nums:
                had_error = True
            refreshed_player_ids.add(pid)
            official = get_official_name(conn, pid)
            if not override and official and official.strip() != name.strip():
                name_changes[normalize_name(name)] = official
            if not used_cache:
                await asyncio.sleep(5)

        if name_changes:
            new_lines, changed = rewrite_players_txt(raw_lines, name_changes=name_changes)
            if changed:
                with open(players_file, "w", encoding="utf-8") as f:
                    for ln in new_lines:
                        f.write(ln + "\n")
                print(f"Updated names in {players_file} to match Transfermarkt.")

        if not had_error and os.path.isdir("debug_html"):
            try:
                shutil.rmtree("debug_html")
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())

