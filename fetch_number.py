import asyncio
import os
import re
import shutil
import sqlite3
import sys
import time
import urllib.parse
import unicodedata

import requests
from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


DB_PATH = "pes.db"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
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


def rewrite_names_in_txt(raw_lines, name_changes):
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
        if key in name_changes:
            new_first = name_changes[key]
            new_line = f"{new_first}{rest}"
            out.append(new_line)
            if new_line != original:
                changed = True
        else:
            out.append(original)
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


def load_cached_numbers_from_db(conn, player_id):
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM players WHERE player_id = ?",
        (str(player_id),),
    )
    name_row = cur.fetchone()
    db_name = name_row[0] if name_row else str(player_id)
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

    print(f"{db_name} {player_id} national jersey numbers (cached):")
    for n in sorted(nums_by_country.keys(), key=int):
        countries = ", ".join(sorted(nums_by_country[n]))
        print(f"  {n}: {countries}")

    return sorted(nums_by_country.keys(), key=int)


async def fetch_numbers_for_player(playwright, name, player_id, conn):
    nums = load_cached_numbers_from_db(conn, player_id)
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
                official_name = parts[0].strip()

        debug_dir = "debug_html"
        os.makedirs(debug_dir, exist_ok=True)
        debug_path = os.path.join(debug_dir, f"debug_playwright_{player_id}.html")
        try:
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"  Wrote Playwright HTML to {debug_path}")
        except Exception as e:
            print(f"  Failed to write Playwright debug HTML for {player_id}: {e}")

        by_number, entries = extract_national_numbers_from_html(html)
        nums = sorted(by_number.keys(), key=int)
        seq = [int(e["number"]) for e in entries]

        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO players (player_id, name) VALUES (?, ?)",
            (str(player_id), official_name),
        )
        cur.execute(
            "DELETE FROM jersey WHERE player_id = ?",
            (str(player_id),),
        )
        for idx, e in enumerate(entries):
            cur.execute(
                "INSERT OR REPLACE INTO jersey (player_id, idx, season, country, number) VALUES (?, ?, ?, ?, ?)",
                (str(player_id), idx, e["season"], e["country"], int(e["number"])),
            )
        conn.commit()

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
        country_folder = sys.argv[1] if len(sys.argv) > 1 else "belgium"
        players_file = resolve_players_file(country_folder)

        if not os.path.exists(players_file):
            print(f"No {players_file} found; nothing to do.")
            return

        with open(players_file, "r", encoding="utf-8") as f:
            raw_lines = [line.rstrip("\n") for line in f]

        players = []
        for line in raw_lines:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if not parts:
                continue
            players.append(parts[0])

        id_map = load_player_id_map(conn)
        had_error = False
        name_changes = {}

        for name in players:
            pid_str = id_map.get(normalize_name(name))
            if not pid_str:
                pid_str = get_transfermarkt_id(name)
                time.sleep(5)
            if not pid_str:
                print(f"Skipping {name}: could not resolve Transfermarkt ID.")
                had_error = True
                continue
            pid = int(pid_str)
            nums, used_cache = await fetch_numbers_for_player(p, name, pid, conn)
            if not nums:
                had_error = True
            official = get_official_name(conn, pid)
            if official and official.strip() != name.strip():
                name_changes[normalize_name(name)] = official
            if not used_cache:
                await asyncio.sleep(5)

        if name_changes:
            new_lines, changed = rewrite_names_in_txt(raw_lines, name_changes)
            if changed:
                with open(players_file, "w", encoding="utf-8") as f:
                    for ln in new_lines:
                        f.write(ln + "\n" if not ln.endswith("\n") else ln)
                print(f"Updated names in {players_file} to match Transfermarkt.")

        if not had_error and os.path.isdir("debug_html"):
            try:
                shutil.rmtree("debug_html")
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())

