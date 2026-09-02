import asyncio
import os
import shutil
import sys
from collections import Counter

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from jersey_fetch.constants import DEBUG_HTML_DIR
from jersey_fetch.discovery import get_transfermarkt_id
from jersey_fetch.espn import fetch_latest_espn_roster, map_recent_players_to_roster
from jersey_fetch.names import invalid_transfermarkt_title, normalize_name, nation_country_names_for_filter
from jersey_fetch.players_file import (
    build_local_player_profiles,
    build_local_player_search_hints,
    build_player_position_rows,
    country_display_name,
    parse_args,
    position_search_phrase,
    resolve_players_file,
    rewrite_players_txt,
)
from jersey_fetch.storage import (
    get_manual_override,
    get_official_name,
    init_db,
    load_cached_numbers_from_db,
    load_game_data_player_map,
    load_jersey_entries_for_player,
    load_player_id_map,
    merge_jersey_entries,
    shared_player_id_for_name,
    store_jersey_entries,
    warn_cached_jersey_nation_mismatch,
    warn_jersey_entries_nation_mismatch,
)
from jersey_fetch.transfermarkt import (
    PROFILE_FALLBACK_SEASON,
    extract_national_numbers_from_html,
    extract_senior_profile_shirt_number,
    fetch_transfermarkt_rueckennummern_html,
    html_looks_like_waf_challenge,
    launch_chromium,
    maybe_note_transfermarkt_waf_once,
    shirt_history_grid_present,
)

async def _profile_shirt_fallback(player_id, expected_nation_label):
    if not expected_nation_label:
        return None
    print(f"  No senior shirt history; checking national team career for {player_id}")
    await asyncio.sleep(5)
    number = await asyncio.to_thread(
        extract_senior_profile_shirt_number, player_id, expected_nation_label
    )
    if number is None:
        print("  National team career has no senior shirt number.")
        return None
    print(
        f"  Using profile #{number} as {PROFILE_FALLBACK_SEASON} {expected_nation_label}."
    )
    return {
        "season": PROFILE_FALLBACK_SEASON,
        "country": expected_nation_label,
        "number": str(number),
    }


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
    _, senior_entries = extract_national_numbers_from_html(html)
    if shirt_history_grid_present(html) and not senior_entries:
        profile_entry = await _profile_shirt_fallback(player_id, expected_nation_label)
        if profile_entry:
            senior_entries = [profile_entry]
    if not senior_entries:
        os.makedirs(DEBUG_HTML_DIR, exist_ok=True)
        debug_path = os.path.join(DEBUG_HTML_DIR, f"debug_playwright_{player_id}.html")
        try:
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"  Wrote debug HTML to {debug_path}")
        except Exception as e:
            print(f"  Failed to write debug HTML for {player_id}: {e}")
    entries = senior_entries
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

def seed_recent_numbers_into_db(conn, country_name, country_label, player_rows, recent_numbers):
    if not recent_numbers:
        return
    id_map = load_player_id_map(conn)
    game_data_map = load_game_data_player_map(conn, country_name)
    ambiguous_names = {
        name for name, count in Counter(normalize_name(row["name"]) for row in player_rows).items() if count > 1
    }
    updated = 0
    for row in player_rows:
        name = row["name"]
        player_position = row["position"]
        key = normalize_name(name)
        seed_entry = recent_numbers.get(key)
        if not seed_entry:
            continue
        override = get_manual_override(country_name, name, position=player_position)
        pid_str = override["player_id"] if override else None
        if not pid_str:
            pid_str = game_data_map.get((key, player_position.strip().upper()))
        if not pid_str and key not in ambiguous_names:
            pid_str = id_map.get(key)
        if not pid_str and key in ambiguous_names:
            pid_str = shared_player_id_for_name(game_data_map, player_rows, key)
        if not pid_str:
            print(f"  Skipping DB number seed for {name} ({player_position}): no cached Transfermarkt ID (run --refetch first).")
            continue
        existing = load_jersey_entries_for_player(conn, pid_str)
        merged = merge_jersey_entries(seed_entry, existing)
        if len(merged) == len(existing):
            continue
        official = get_official_name(conn, pid_str) or name
        store_jersey_entries(conn, pid_str, official, merged)
        print(f"  Seeded latest squad #{seed_entry['number']} at row 0 for {official} ({pid_str}).")
        updated += 1
    if updated:
        print(f"Seeded latest squad numbers into DB for {updated} player(s).")


async def main():
    country_folder, force_refetch, game_id, game_index, lineup_only = parse_args(sys.argv)
    players_file = resolve_players_file(country_folder)
    if not os.path.exists(players_file):
        print(f"No {players_file} found; nothing to do.")
        return
    with open(players_file, "r", encoding="utf-8") as f:
        raw_lines = [line.rstrip("\n") for line in f]
    country_name = os.path.basename(os.path.normpath(country_folder.strip()))
    country_label = country_display_name(country_name)
    player_rows = build_player_position_rows(raw_lines)
    players = []
    seen_names = set()
    player_positions = {}
    for row in player_rows:
        name = row["name"]
        nk = normalize_name(name)
        if nk not in player_positions:
            player_positions[nk] = row["position"]
        if nk in seen_names:
            continue
        seen_names.add(nk)
        players.append(name)
    player_profiles = build_local_player_profiles(raw_lines)
    player_search_hints = build_local_player_search_hints(raw_lines)
    latest_match = None
    recent_flags = {}
    recent_numbers = {}
    if lineup_only or force_refetch:
        latest_match = fetch_latest_espn_roster(country_label, game_id, game_index=game_index)
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
        conn = init_db()
        try:
            seed_recent_numbers_into_db(
                conn, country_name, country_label, player_rows, recent_numbers
            )
        finally:
            conn.close()
        return
    conn = init_db()
    async with async_playwright() as p:
        id_map = load_player_id_map(conn)
        game_data_map = load_game_data_player_map(conn, country_name)
        had_error = False
        name_changes = {}
        refreshed_player_ids = set()
        fetched_player_ids = set()
        resolved_row_ids = {}
        browser = await launch_chromium(p)
        page = await browser.new_page()
        ambiguous_names = {
            name for name, count in Counter(normalize_name(row["name"]) for row in player_rows).items() if count > 1
        }
        for row in player_rows:
            name = row["name"]
            player_position = row["position"]
            norm_name = normalize_name(name)
            row_key = (norm_name, player_position.strip().upper())
            override = get_manual_override(country_name, name, position=player_position)
            pid_str = override["player_id"] if override else None
            if not pid_str:
                pid_str = resolved_row_ids.get(row_key)
            if not pid_str:
                pid_str = game_data_map.get(row_key)
            if not pid_str and norm_name not in ambiguous_names:
                pid_str = id_map.get(norm_name)
            if not pid_str and norm_name in ambiguous_names:
                pid_str = shared_player_id_for_name(game_data_map, player_rows, norm_name)
            if not pid_str:
                position_hint = position_search_phrase(player_position) or player_search_hints.get(norm_name)
                pid_str = await get_transfermarkt_id(
                    name,
                    page,
                    country_label=country_label,
                    position_hint=position_hint,
                )
                await asyncio.sleep(5)
            if not pid_str:
                print(f"Skipping {name} ({player_position}): could not resolve Transfermarkt ID.")
                had_error = True
                continue
            resolved_row_ids[row_key] = str(pid_str)
            if norm_name not in ambiguous_names:
                id_map[norm_name] = str(pid_str)
            pid = int(pid_str)
            if pid in fetched_player_ids and not force_refetch:
                load_cached_numbers_from_db(conn, pid, display_name=name)
                official = get_official_name(conn, pid)
                if not override and official and (official.strip() != name.strip()):
                    name_changes[norm_name] = official
                continue
            should_clear_country_cache = force_refetch and pid not in refreshed_player_ids
            if should_clear_country_cache:
                cur = conn.cursor()
                country_names = nation_country_names_for_filter(country_label)
                placeholders = ", ".join("?" * len(country_names))
                cur.execute(
                    f"""
                    DELETE FROM jersey
                    WHERE player_id = ? AND country IN ({placeholders})
                    """,
                    [str(pid), *country_names],
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
            fetched_player_ids.add(pid)
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
