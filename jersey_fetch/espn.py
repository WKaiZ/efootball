import functools
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

from jersey_fetch.constants import EXCLUDE_FROM_ESPN_RECENT, HEADERS
from jersey_fetch.matching import (
    compatible_name_tokens,
    espn_lineup_role,
    espn_local_matches_full_aliases,
    espn_local_name_match_score,
    espn_local_name_match_tiebreak,
    roster_role_compatible_for_espn_lineup,
)
from jersey_fetch.names import normalize_name


def espn_request_json(url, params=None, timeout=None):
    if timeout is None:
        timeout = float(os.environ.get("ESPN_REQUEST_TIMEOUT", "30"))
    max_retries = max(1, int(os.environ.get("ESPN_REQUEST_RETRIES", "5")))
    base_delay = float(os.environ.get("ESPN_RETRY_BACKOFF_SEC", "1.0"))
    retry_status = {429, 502, 503, 504}
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError):
            if attempt >= max_retries - 1:
                raise
            time.sleep(min(base_delay * (2**attempt), 30.0))
            continue
        if r.status_code in retry_status and attempt < max_retries - 1:
            time.sleep(min(base_delay * (2**attempt), 30.0))
            continue
        r.raise_for_status()
        return r.json()


def is_womens_espn_competition(text):
    low = (text or "").strip().lower()
    if "wworldq" in low:
        return False
    return any(
        (marker in low for marker in ("women", "women's", "womens", "wworld", "shebelieves", "femen", "femin"))
    )


@functools.lru_cache(maxsize=128)
def espn_team_slug(team_id):
    try:
        data = espn_request_json(f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{team_id}")
        return (data.get("team") or {}).get("slug") or ""
    except requests.RequestException:
        return ""


def is_espn_womens_national_team_id(team_id):
    slug = espn_team_slug(str(team_id))
    return bool(slug) and slug.endswith(".w")


def lookup_espn_team(country_label):
    target = normalize_name(country_label)
    queries = [f"{country_label} national team", country_label]
    best = None
    for query in queries:
        data = espn_request_json("https://site.api.espn.com/apis/common/v3/search", params={"query": query})
        for item in data.get("items", []):
            if item.get("type") != "team" or item.get("sport") != "soccer":
                continue
            name = item.get("displayName", "")
            name_norm = normalize_name(name)
            if name_norm != target:
                continue
            tid = str(item.get("id") or "")
            league = (item.get("league") or "").lower()
            if is_womens_espn_competition(league):
                continue
            if tid and is_espn_womens_national_team_id(tid):
                continue
            score = 0
            if league == "fifa.world":
                score += 100
            elif league.startswith("fifa."):
                score += 50
            if normalize_name(query) == target:
                score += 10
            if best is None or score > best[0]:
                best = (score, tid)
        if best is not None and best[0] >= 100:
            break
    return best[1] if best else None


def build_espn_player_aliases(player_entry):
    athlete = player_entry.get("athlete", {}) or {}
    aliases = set()
    for raw in (
        athlete.get("fullName"),
        athlete.get("displayName"),
        athlete.get("shortName"),
        athlete.get("lastName"),
    ):
        if raw:
            aliases.add(normalize_name(raw))
    fn = (athlete.get("firstName") or "").strip()
    ln = (athlete.get("lastName") or "").strip()
    if fn and ln:
        aliases.add(normalize_name(f"{fn} {ln}"))
    return {alias for alias in aliases if alias}


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


def _espn_event_team_lineup_datetime(team_id, event, now_utc):
    comp = (event.get("competitions") or [{}])[0]
    status_type = comp.get("status", {}).get("type", {}) or {}
    completed = bool(status_type.get("completed"))
    state = (status_type.get("state") or "").lower()
    if not completed and state != "in":
        return None
    raw = event.get("date") or comp.get("date")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt > now_utc:
        return None
    for side in comp.get("competitors", []):
        if str((side.get("team") or {}).get("id")) == str(team_id):
            return dt
    return None


def _merge_scoreboard_window(team_id, dates_param, now_utc, event_times, timeout):
    board = espn_request_json(
        "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard",
        params={"dates": dates_param, "limit": 500},
        timeout=timeout,
    )
    for event in board.get("events", []):
        dt = _espn_event_team_lineup_datetime(team_id, event, now_utc)
        if dt is None:
            continue
        eid = str(event.get("id") or "")
        if not eid:
            continue
        prev = event_times.get(eid)
        if prev is None or dt > prev:
            event_times[eid] = dt


def resolve_latest_completed_espn_event_id_for_team(team_id, max_days_back=120, chunk_days=14):
    now = datetime.now(timezone.utc)
    event_times = {}
    latest_sched_dt = None
    schedule_timeout = float(os.environ.get("ESPN_SCHEDULE_TIMEOUT", "30"))
    scoreboard_timeout = float(os.environ.get("ESPN_SCOREBOARD_TIMEOUT", "60"))
    try:
        schedule = espn_request_json(
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{team_id}/schedule",
            params={"limit": 100},
            timeout=schedule_timeout,
        )
        for event in schedule.get("events", []):
            dt = _espn_event_team_lineup_datetime(team_id, event, now)
            if dt is None:
                continue
            eid = event.get("id")
            if not eid:
                continue
            eid = str(eid)
            prev = event_times.get(eid)
            if prev is None or dt > prev:
                event_times[eid] = dt
            if latest_sched_dt is None or dt > latest_sched_dt:
                latest_sched_dt = dt
    except requests.RequestException:
        pass
    end_date = now.date()
    cap_start = end_date - timedelta(days=max_days_back)
    if latest_sched_dt is not None:
        overlap_start = (latest_sched_dt - timedelta(days=3)).date()
        oldest = max(overlap_start, cap_start)
    else:
        oldest = cap_start
    scan_end = end_date
    while scan_end >= oldest:
        start_date = max(oldest, scan_end - timedelta(days=chunk_days - 1))
        dates_param = f"{start_date.strftime('%Y%m%d')}-{scan_end.strftime('%Y%m%d')}"
        for attempt in range(3):
            try:
                _merge_scoreboard_window(team_id, dates_param, now, event_times, scoreboard_timeout)
                break
            except requests.RequestException:
                if attempt == 2:
                    print(
                        f"  Warning: ESPN scoreboard failed for {dates_param} after 3 tries "
                        f"(timeout {scoreboard_timeout}s)."
                    )
                time.sleep(1.0 * (attempt + 1))
        scan_end = start_date - timedelta(days=1)
    if not event_times:
        return None
    _, best_dt = max(event_times.items(), key=lambda kv: kv[1])
    stale_days = (now.date() - best_dt.date()).days
    if stale_days > 21:
        supplemental_start = max(cap_start, (now - timedelta(days=45)).date())
        sup_param = f"{supplemental_start.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}"
        for attempt in range(3):
            try:
                _merge_scoreboard_window(team_id, sup_param, now, event_times, scoreboard_timeout)
                break
            except requests.RequestException:
                time.sleep(1.5 * (attempt + 1))
        else:
            _, best_dt2 = max(event_times.items(), key=lambda kv: kv[1])
            if best_dt2 <= best_dt:
                print(
                    f"  Warning: Latest ESPN lineup source looks stale ({best_dt2.date()}). "
                    "Scoreboard may be failing; try again or pass --gameid <eventId>."
                )
    return max(event_times.items(), key=lambda kv: kv[1])[0]


def fetch_latest_espn_roster(country_label, game_id=None):
    team_id = lookup_espn_team(country_label)
    if not team_id:
        print(f"Could not resolve ESPN team ID for {country_label}.")
        return None
    if game_id:
        event_id = game_id
        print(f"Using provided gameId {event_id} for {country_label}.")
    else:
        event_id = resolve_latest_completed_espn_event_id_for_team(team_id)
        if not event_id:
            print(f"No completed ESPN matches found for {country_label}.")
            return None
    summary = espn_request_json(
        "https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary", params={"event": event_id}
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
        roster.append({"aliases": aliases, "jersey": int(jersey), "role": role})
    lineup_url = f"https://www.espn.com/soccer/lineups/_/gameId/{event_id}"
    match_name = summary.get("header", {}).get("competitions", [{}])[0].get("name") or f"Match {event_id}"
    match_date = summary.get("header", {}).get("competitions", [{}])[0].get("date", "")
    if match_date:
        try:
            dt = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
            date_str = dt.date().isoformat()
        except Exception:
            date_str = match_date[:10]
    else:
        date_str = "Unknown"
    print(f"Latest ESPN match for {country_label}: {match_name} ({date_str}) [{lineup_url}]")
    return {
        "event_id": str(event_id),
        "date": date_str,
        "season": str(summary.get("header", {}).get("season", {}).get("year", "2026")),
        "country": country_label,
        "lineup_url": lineup_url,
        "roster": roster,
    }


def map_recent_players_to_roster(player_profiles, latest_match):
    if not latest_match:
        return ({}, {})
    roster_names = list(player_profiles.items())
    recent_flags = {key: False for key in player_profiles.keys()}
    recent_numbers = {}
    taken = set()
    for espn_player in latest_match["roster"]:
        matched_key = None
        espn_role = espn_player.get("role")
        aliases = espn_player["aliases"]
        candidates = []
        for key, profile in roster_names:
            if key in taken or key in EXCLUDE_FROM_ESPN_RECENT:
                continue
            if not roster_role_compatible_for_espn_lineup(profile["roles"], espn_role, key):
                continue
            if not any((compatible_name_tokens(key, alias) for alias in aliases)):
                continue
            if not espn_local_matches_full_aliases(key, aliases):
                continue
            candidates.append(key)
        if candidates:
            matched_key = max(
                candidates,
                key=lambda k: (
                    espn_local_name_match_score(k, aliases),
                    -espn_local_name_match_tiebreak(k, aliases),
                ),
            )
        if matched_key is None:
            for key, profile in roster_names:
                if key in taken or key in EXCLUDE_FROM_ESPN_RECENT:
                    continue
                if not roster_role_compatible_for_espn_lineup(profile["roles"], espn_role, key):
                    continue
                roster_tokens = [tok for tok in key.split() if tok]
                if len(roster_tokens) == 1:
                    if any((roster_tokens[0] == t for alias in espn_player["aliases"] for t in alias.split())):
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
    for key in EXCLUDE_FROM_ESPN_RECENT:
        if recent_flags.get(key):
            recent_flags[key] = False
            recent_numbers.pop(key, None)
    return (recent_flags, recent_numbers)


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
