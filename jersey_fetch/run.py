import asyncio
import os
import shutil
import sys

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from jersey_fetch.constants import DEBUG_HTML_DIR
from jersey_fetch.discovery import get_transfermarkt_id
from jersey_fetch.espn import fetch_latest_espn_roster, map_recent_players_to_roster
from jersey_fetch.names import invalid_transfermarkt_title, normalize_name
from jersey_fetch.players_file import (
    build_local_player_profiles,
    build_local_player_search_hints,
    country_display_name,
    parse_args,
    resolve_players_file,
    rewrite_players_txt,
)
from jersey_fetch.storage import (
    get_manual_override,
    get_official_name,
    init_db,
    load_cached_numbers_from_db,
    load_player_id_map,
    merge_jersey_entries,
    store_jersey_entries,
    warn_cached_jersey_nation_mismatch,
    warn_jersey_entries_nation_mismatch,
)
from jersey_fetch.transfermarkt import (
    extract_national_numbers_from_html,
    fetch_transfermarkt_rueckennummern_html,
    html_looks_like_waf_challenge,
    launch_chromium,
    maybe_note_transfermarkt_waf_once,
)


async def fetch_numbers_for_player(
    playwright,
    name,
    player_id,
    conn,
    db_name_override=None,
    cache_country_filter=None,
    espn_seed_entry=None,
    expected_nation_label=None,
):
    nums = load_cached_numbers_from_db(
        conn, player_id, country_filter=cache_country_filter, display_name=name
    )
    if nums:
        warn_cached_jersey_nation_mismatch(conn, player_id, expected_nation_label)
        return (nums, True)
    url = f"https://www.transfermarkt.com/-/rueckennummern/spieler/{player_id}"
    try:
        html = await fetch_transfermarkt_rueckennummern_html(playwright, url)
    except PlaywrightTimeoutError:
        print(f"  Timeout loading {url}. Skipping for now.")
        if espn_seed_entry:
            official_name = db_name_override or name
            warn_jersey_entries_nation_mismatch(
                [espn_seed_entry], expected_nation_label, official_name, player_id
            )
            nums, by_number = store_jersey_entries(
                conn, player_id, official_name, [espn_seed_entry], cache_country_filter=cache_country_filter
            )
            print(f"{official_name} {player_id} national jersey numbers (ESPN fallback):")
            for n in nums:
                countries = ", ".join(sorted(by_number[n]))
                print(f"  {n}: {countries}")
            return (nums, False)
        return ([], False)
    maybe_note_transfermarkt_waf_once(html)
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
    _, tm_only_entries = extract_national_numbers_from_html(html)
    if html_looks_like_waf_challenge(html) or not tm_only_entries:
        os.makedirs(DEBUG_HTML_DIR, exist_ok=True)
        debug_path = os.path.join(DEBUG_HTML_DIR, f"debug_playwright_{player_id}.html")
        try:
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"  Wrote debug HTML to {debug_path}")
        except Exception as e:
            print(f"  Failed to write debug HTML for {player_id}: {e}")
    entries = tm_only_entries
    entries = merge_jersey_entries(espn_seed_entry, entries)
    warn_jersey_entries_nation_mismatch(entries, expected_nation_label, official_name, player_id)
    nums, by_number = store_jersey_entries(
        conn, player_id, official_name, entries, cache_country_filter=cache_country_filter
    )
    if by_number:
        print(f"{official_name} {player_id} national jersey numbers:")
        for n in nums:
            countries = ", ".join(sorted(by_number[n]))
            print(f"  {n}: {countries}")
    else:
        print(f"{name} {player_id} national jersey numbers: NONE FOUND")
    return (nums, False)


async def main():
    country_folder, force_refetch, game_id, lineup_only = parse_args(sys.argv)
    players_file = resolve_players_file(country_folder)
    if not os.path.exists(players_file):
        print(f"No {players_file} found; nothing to do.")
        return
    with open(players_file, "r", encoding="utf-8") as f:
        raw_lines = [line.rstrip("\n") for line in f]
    country_name = os.path.basename(os.path.normpath(country_folder.strip()))
    country_label = country_display_name(country_name)
    players = []
    seen_names = set()
    player_positions = {}
    for line in raw_lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if not parts:
            continue
        nk = normalize_name(parts[0])
        if nk not in player_positions and len(parts) >= 2:
            player_positions[nk] = parts[1]
        if nk in seen_names:
            continue
        seen_names.add(nk)
        players.append(parts[0])
    player_profiles = build_local_player_profiles(raw_lines)
    player_search_hints = build_local_player_search_hints(raw_lines)
    latest_match = None
    recent_flags = {}
    recent_numbers = {}
    if lineup_only or force_refetch:
        latest_match = fetch_latest_espn_roster(country_label, game_id)
        recent_flags, recent_numbers = map_recent_players_to_roster(player_profiles, latest_match)
        if recent_flags:
            raw_lines, changed = rewrite_players_txt(raw_lines, recent_flags=recent_flags)
            if changed:
                with open(players_file, "w", encoding="utf-8") as f:
                    for ln in raw_lines:
                        f.write(ln + "\n")
                print(f"Updated recent flags in {players_file} from ESPN latest match.")
    if lineup_only:
        print("Skipping Transfermarkt jersey fetch (--lineup-only).")
        return
    conn = init_db()
    async with async_playwright() as p:
        id_map = load_player_id_map(conn)
        had_error = False
        name_changes = {}
        refreshed_player_ids = set()
        browser = await launch_chromium(p)
        page = await browser.new_page()
        for name in players:
            player_position = player_positions.get(normalize_name(name))
            override = get_manual_override(country_name, name, position=player_position)
            pid_str = id_map.get(normalize_name(name))
            if override:
                pid_str = override["player_id"]
            if not pid_str:
                pid_str = await get_transfermarkt_id(
                    name,
                    page,
                    country_label=country_label,
                    position_hint=player_search_hints.get(normalize_name(name)),
                )
                await asyncio.sleep(5)
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
                expected_nation_label=country_label,
            )
            if not nums:
                had_error = True
            refreshed_player_ids.add(pid)
            official = get_official_name(conn, pid)
            if not override and official and (official.strip() != name.strip()):
                name_changes[normalize_name(name)] = official
            if not used_cache:
                await asyncio.sleep(5)
        await browser.close()
        if name_changes:
            new_lines, changed = rewrite_players_txt(raw_lines, name_changes=name_changes)
            if changed:
                with open(players_file, "w", encoding="utf-8") as f:
                    for ln in new_lines:
                        f.write(ln + "\n")
                print(f"Updated names in {players_file} to match Transfermarkt.")
        if not had_error and os.path.isdir(DEBUG_HTML_DIR):
            try:
                shutil.rmtree(DEBUG_HTML_DIR)
            except Exception:
                pass
