import asyncio
import functools
import os
import re
import shutil
import sqlite3
import sys
import time
import urllib.parse
import unicodedata
from datetime import datetime, timedelta, timezone
import requests
from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

DB_PATH = 'pes.db'
HEADERS = {'User-Agent': 'Mozilla/5.0'}
_transfermarkt_waf_hint_printed = False

def html_looks_like_waf_challenge(html: str) -> bool:
    if not html:
        return False
    h = html.lower()
    if 'awswaf.com' in h or 'token.awswaf.com' in h:
        return True
    if 'human verification' in h and 'awswaf' in h:
        return True
    if 'awswafintegration' in h.replace(' ', '').lower():
        return True
    return False

async def launch_chromium(playwright, *, headless=True, hardened=False):
    launch_args = []
    if hardened:
        launch_args.append('--disable-blink-features=AutomationControlled')
    opts = {'headless': headless}
    if launch_args:
        opts['args'] = launch_args
    channel = os.environ.get('PLAYWRIGHT_BROWSER_CHANNEL', '').strip()
    if channel:
        if channel.lower() == 'chromium':
            return await playwright.chromium.launch(**opts)
        try:
            return await playwright.chromium.launch(**opts, channel=channel)
        except Exception:
            return await playwright.chromium.launch(**opts)
    if sys.platform == 'win32':
        for ch in ('chrome', 'msedge'):
            try:
                return await playwright.chromium.launch(**opts, channel=ch)
            except Exception:
                continue
    return await playwright.chromium.launch(**opts)
TRANSFERMARKT_PLAYWRIGHT_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
_TRANSFERMARKT_STEALTH_JS = "\nObject.defineProperty(navigator, 'webdriver', { get: () => undefined });\n"

def try_transfermarkt_rueckennummern_curl(url: str):
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return None
    try:
        resp = curl_requests.get(url, impersonate='chrome', timeout=60, allow_redirects=True, headers={'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7', 'Upgrade-Insecure-Requests': '1'})
        if resp.status_code != 200 or not resp.text:
            return None
        if html_looks_like_waf_challenge(resp.text):
            return None
        if 'grid-view' not in resp.text and 'yw2' not in resp.text:
            return None
        return resp.text
    except Exception:
        return None

async def _transfermarkt_rueckennummern_playwright(playwright, url: str):
    browser = await launch_chromium(playwright, hardened=True)
    context = await browser.new_context(user_agent=TRANSFERMARKT_PLAYWRIGHT_UA, locale='de-DE', timezone_id='Europe/Berlin', viewport={'width': 1920, 'height': 1080}, extra_http_headers={'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7', 'DNT': '1', 'Upgrade-Insecure-Requests': '1'})
    await context.add_init_script(_TRANSFERMARKT_STEALTH_JS)
    page = await context.new_page()
    try:
        await page.goto('https://www.transfermarkt.com/', wait_until='domcontentloaded', timeout=60000)
        await page.wait_for_timeout(800)
        for selector in ['button[title*="Accept"]', 'button:has-text("Accept all")', 'button:has-text("Alle akzeptieren")', 'button:has-text("I agree")']:
            try:
                if await page.is_visible(selector, timeout=1500):
                    await page.click(selector)
                    break
            except Exception:
                pass
        await page.goto(url, wait_until='domcontentloaded', timeout=120000)
        await page.wait_for_timeout(1500)
        html = await page.content()
        if html_looks_like_waf_challenge(html):
            await page.reload(wait_until='domcontentloaded', timeout=90000)
            await page.wait_for_timeout(2000)
            html = await page.content()
        return html
    finally:
        await context.close()
        await browser.close()

async def fetch_transfermarkt_rueckennummern_html(playwright, url: str):
    curl_html = await asyncio.to_thread(try_transfermarkt_rueckennummern_curl, url)
    if curl_html:
        return curl_html
    return await _transfermarkt_rueckennummern_playwright(playwright, url)
MANUAL_ID_OVERRIDES = {'argentina': {'nico gonzalez': {'player_id': '486031', 'preserve_name': True}}, 'brazil': {'gabriel': {'player_id': '435338', 'preserve_name': True}, 'ederson': {'player_id': '607854', 'preserve_name': True}, 'vitinho': {'player_id': '468249', 'preserve_name': True}, 'pepe': {'player_id': '520662', 'preserve_name': True}, 'pedro': {'player_id': '432895', 'preserve_name': True}, 'allan': {'player_id': '126422', 'preserve_name': True}, 'oscar': {'player_id': '85314', 'preserve_name': True}, 'leo pereira': {'player_id': '288431', 'preserve_name': True}, 'igor thiago': {'player_id': '739443', 'preserve_name': True}, 'joao gomes': {'player_id': '735570', 'preserve_name': True}, 'gerson': {'player_id': '341705', 'preserve_name': True}, 'fred': {'player_id': '191614', 'preserve_name': True}, 'douglas luiz': {'player_id': '447661', 'preserve_name': True}}, 'portugal': {'pepe': {'player_id': '14132', 'preserve_name': True}}, 'france': {'maxence lacroix': {'player_id': '434224', 'preserve_name': True}}, 'spain': {'pedro': {'player_id': '65278', 'preserve_name': True}}}

def normalize_name(name):
    nfkd = unicodedata.normalize('NFKD', name)
    no_accents = ''.join((ch for ch in nfkd if not unicodedata.combining(ch)))
    return re.sub('\\s+', ' ', no_accents).strip().lower()
HTTP_BROWSER_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'

def unwrap_duckduckgo_link(link):
    if not link:
        return None
    if link.startswith('/l/') or 'duckduckgo.com/l/?' in link:
        if link.startswith('//'):
            link_to_parse = 'https:' + link
        elif link.startswith('/'):
            link_to_parse = 'https://duckduckgo.com' + link
        else:
            link_to_parse = link
        parsed = urllib.parse.urlparse(link_to_parse)
        qs = urllib.parse.parse_qs(parsed.query)
        if 'uddg' in qs and qs['uddg']:
            return qs['uddg'][0]
    return link

def score_transfermarkt_candidate(player_name, link, text):
    if not link or 'transfermarkt.' not in link or '/spieler/' not in link:
        return None
    m = re.search('/spieler/(\\d+)', link)
    if not m:
        return None
    pid = m.group(1)
    parsed = urllib.parse.urlparse(link)
    path = parsed.path.lower()
    slug = ''
    parts = [p for p in path.split('/') if p]
    if parts:
        slug = parts[0].replace('-', ' ')
    player_norm = normalize_name(player_name)
    text_norm = normalize_name(text or '')
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
    token_matches = sum((1 for tok in player_tokens if tok in slug_norm or tok in text_norm))
    score += token_matches * 10
    if token_matches == 0:
        return None
    return (score, pid)

def _wikidata_label_match_score(player, label):
    pn = normalize_name(player)
    ln = normalize_name(label or '')
    if not pn or not ln:
        return 0
    if ln == pn:
        return 100
    if pn in ln or ln in pn:
        return 85
    toks = [t for t in pn.split() if t]
    hits = sum((1 for t in toks if t in ln))
    if hits == 0:
        return 0
    return 45 + hits * 12

def _wikidata_p2446_transfermarkt_id(claims):
    for c in claims or []:
        try:
            sn = c['mainsnak']
            if sn.get('snaktype') != 'value':
                continue
            dv = sn['datavalue']['value']
            if isinstance(dv, str):
                m = re.search('(\\d{3,})', dv)
                if m:
                    return m.group(1)
        except (KeyError, TypeError, ValueError):
            continue
    return None

def wikidata_transfermarkt_player_id(player):
    try:
        r = requests.get('https://www.wikidata.org/w/api.php', params={'action': 'wbsearchentities', 'search': player, 'language': 'en', 'format': 'json', 'limit': 12}, headers={'User-Agent': HTTP_BROWSER_UA}, timeout=25)
        r.raise_for_status()
        hits = r.json().get('search') or []
        if not hits:
            return None
        ids = [h['id'] for h in hits][:10]
        r2 = requests.get('https://www.wikidata.org/w/api.php', params={'action': 'wbgetentities', 'ids': '|'.join(ids), 'format': 'json', 'props': 'claims|labels', 'languages': 'en'}, headers={'User-Agent': HTTP_BROWSER_UA}, timeout=25)
        r2.raise_for_status()
        entities = r2.json().get('entities') or {}
    except (requests.RequestException, KeyError, ValueError):
        return None
    best = None
    for rank, eid in enumerate(ids):
        blob = entities.get(eid)
        if not blob:
            continue
        label = (blob.get('labels') or {}).get('en', {}).get('value') or ''
        ls = _wikidata_label_match_score(player, label)
        min_ls = 55 if len(normalize_name(player).split()) <= 1 else 40
        if ls < min_ls:
            continue
        claims = (blob.get('claims') or {}).get('P2446')
        pid = _wikidata_p2446_transfermarkt_id(claims)
        if not pid:
            continue
        key = (ls, -rank)
        if best is None or key > best[:2]:
            best = (ls, -rank, pid)
    return best[2] if best else None

def duckduckgo_html_transfermarkt_player_id(player):
    queries = [f'{player} transfermarkt', f'"{player}" transfermarkt', f'{player} site:transfermarkt.com']
    headers = {'User-Agent': HTTP_BROWSER_UA, 'Referer': 'https://html.duckduckgo.com/'}
    best = None
    seen = set()
    for q in queries:
        try:
            resp = requests.post('https://html.duckduckgo.com/html/', data={'q': q, 'b': ''}, headers=headers, timeout=25)
            if resp.status_code != 200 or 'result__a' not in resp.text:
                continue
            soup = BeautifulSoup(resp.text, 'html.parser')
            for a in soup.select('a.result__a'):
                href = a.get('href')
                text = a.get_text(' ', strip=True)
                url = unwrap_duckduckgo_link(href)
                scored = score_transfermarkt_candidate(player, url, text)
                if not scored:
                    continue
                score, pid = scored
                if pid in seen:
                    continue
                seen.add(pid)
                if best is None or score > best[0]:
                    best = (score, pid)
                    if score >= 100:
                        return pid
        except requests.RequestException:
            continue
    return best[1] if best else None

def load_player_id_map(conn):
    cur = conn.cursor()
    cur.execute('SELECT player_id, name FROM players')
    mapping = {}
    for pid, name in cur.fetchall():
        mapping[normalize_name(name)] = str(pid)
    return mapping

def get_official_name(conn, player_id):
    cur = conn.cursor()
    cur.execute('SELECT name FROM players WHERE player_id = ?', (str(player_id),))
    row = cur.fetchone()
    return row[0] if row else None

def get_manual_override(country_name, player_name):
    country_overrides = MANUAL_ID_OVERRIDES.get(normalize_name(country_name), {})
    return country_overrides.get(normalize_name(player_name))

def country_display_name(country_name):
    return country_name.replace('_', ' ').strip().title()

def parse_args(argv):
    country_folder = 'belgium'
    force_refetch = False
    game_id = None
    positional = []
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in ('--refetch', '--refresh', '--no-cache'):
            force_refetch = True
        elif arg == '--gameid':
            if i + 1 < len(argv):
                game_id = argv[i + 1]
                i += 1
            else:
                raise SystemExit('Usage: python fetch_number.py [--refetch] [--gameid <id>] [country_folder]')
        else:
            positional.append(arg)
        i += 1
    if len(positional) > 1:
        raise SystemExit('Usage: python fetch_number.py [--refetch] [--gameid <id>] [country_folder]')
    if positional:
        country_folder = positional[0]
    return (country_folder, force_refetch, game_id)

def rewrite_players_txt(raw_lines, name_changes=None, recent_flags=None):
    name_changes = name_changes or {}
    recent_flags = recent_flags or {}
    changed = False
    out = []
    for line in raw_lines:
        original = line
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            out.append(original)
            continue
        comma_idx = line.find(',')
        if comma_idx == -1:
            first = line.strip()
            rest = ''
        else:
            first = line[:comma_idx].strip()
            rest = line[comma_idx:]
        if not first:
            out.append(original)
            continue
        key = normalize_name(first)
        new_first = name_changes.get(key, first)
        new_line = f'{new_first}{rest}'
        if key in recent_flags:
            parts = [p.strip() for p in new_line.split(',')]
            for idx in range(3, len(parts)):
                parsed = parse_recent_flag(parts[idx])
                if parsed is None:
                    continue
                parts[idx] = 'True' if recent_flags[key] else 'False'
                candidate = ', '.join(parts)
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
    return (out, changed)

def resolve_players_file(country_folder):
    folder = country_folder.strip()
    country_name = os.path.basename(os.path.normpath(folder))
    return os.path.join(folder, f'{country_name}_players.txt')

def parse_recent_flag(token):
    t = token.strip().lower()
    if t == 'true':
        return True
    if t == 'false':
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
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]

def espn_request_json(url, params=None, timeout=None):
    if timeout is None:
        timeout = float(os.environ.get('ESPN_REQUEST_TIMEOUT', '30'))
    r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.json()

def is_womens_espn_competition(text):
    low = (text or '').strip().lower()
    if 'wworldq' in low:
        return False
    return any((marker in low for marker in ('women', "women's", 'womens', 'wworld', 'shebelieves', 'femen', 'femin')))

@functools.lru_cache(maxsize=128)
def espn_team_slug(team_id):
    try:
        data = espn_request_json(f'https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{team_id}')
        return (data.get('team') or {}).get('slug') or ''
    except requests.RequestException:
        return ''

def is_espn_womens_national_team_id(team_id):
    slug = espn_team_slug(str(team_id))
    return bool(slug) and slug.endswith('.w')

def lookup_espn_team(country_label):
    queries = [f'{country_label} national team', country_label]
    best = None
    target = normalize_name(country_label)
    for query in queries:
        data = espn_request_json('https://site.api.espn.com/apis/common/v3/search', params={'query': query})
        for item in data.get('items', []):
            if item.get('type') != 'team' or item.get('sport') != 'soccer':
                continue
            name = item.get('displayName', '')
            name_norm = normalize_name(name)
            if name_norm != target:
                continue
            tid = str(item.get('id') or '')
            league = (item.get('league') or '').lower()
            if is_womens_espn_competition(league):
                continue
            if tid and is_espn_womens_national_team_id(tid):
                continue
            score = 0
            if league == 'fifa.world':
                score += 100
            elif league.startswith('fifa.'):
                score += 50
            if normalize_name(query) == target:
                score += 10
            if best is None or score > best[0]:
                best = (score, tid)
        if best is not None and best[0] >= 100:
            break
    return best[1] if best else None

def build_espn_player_aliases(player_entry):
    athlete = player_entry.get('athlete', {})
    aliases = set()
    for raw in (athlete.get('fullName'), athlete.get('displayName'), athlete.get('shortName'), athlete.get('lastName')):
        if raw:
            aliases.add(normalize_name(raw))
    return {alias for alias in aliases if alias}

def local_position_role(position):
    pos = (position or '').strip().upper()
    if pos == 'GK':
        return 'G'
    if pos in {'CB', 'LB', 'RB'}:
        return 'D'
    if pos in {'DMF', 'CMF', 'AMF', 'LMF', 'RMF'}:
        return 'M'
    if pos in {'LWF', 'RWF', 'SS', 'CF'}:
        return 'F'
    return None

def build_local_player_profiles(raw_lines):
    profiles = {}
    for line in raw_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 2:
            continue
        name = parts[0]
        key = normalize_name(name)
        profile = profiles.setdefault(key, {'name': name, 'roles': set()})
        role = local_position_role(parts[1])
        if role:
            profile['roles'].add(role)
        for match in re.findall('\\[([^\\]]*)\\]', stripped):
            for token in match.split(','):
                role = local_position_role(token.strip())
                if role:
                    profile['roles'].add(role)
    return profiles

def _name_token_is_initial_abbrev(tok):
    return len(tok) == 2 and tok[1] == '.' and tok[0].isalpha()


def _espn_token_equiv(local_tok, espn_tok):
    if local_tok == espn_tok:
        return True
    if min(len(local_tok), len(espn_tok)) == 1 and max(len(local_tok), len(espn_tok)) > 1:
        return False
    if _name_token_is_initial_abbrev(espn_tok) and local_tok.startswith(espn_tok[0]) and len(local_tok) > 1:
        return True
    if _name_token_is_initial_abbrev(local_tok) and espn_tok.startswith(local_tok[0]) and len(espn_tok) > 1:
        return True
    if local_tok.startswith(espn_tok) or espn_tok.startswith(local_tok):
        return True
    return False


def _local_tokens_match_espn_ordered_subsequence(local_tokens, espn_tokens):
    """Each local token must match some ESPN token in order (ESPN may have extra given / maternal names)."""
    i = 0
    for et in espn_tokens:
        if i >= len(local_tokens):
            break
        if _espn_token_equiv(local_tokens[i], et):
            i += 1
    return i == len(local_tokens)


def compatible_name_tokens(local_name, espn_alias):
    ln = normalize_name(local_name)
    an = normalize_name(espn_alias)
    if not ln or not an:
        return False
    if ln == an:
        return True
    local_tokens = [tok for tok in ln.split() if tok]
    espn_tokens = [tok for tok in an.split() if tok]
    if not local_tokens or not espn_tokens:
        return False
    return _local_tokens_match_espn_ordered_subsequence(local_tokens, espn_tokens)

def invalid_transfermarkt_title(title_text):
    low = normalize_name(title_text)
    if 'human verification' in low or 'verify you are human' in low:
        return True
    if 'awswaf' in low.replace(' ', ''):
        return True
    return low in {'502 bad gateway', '503 service unavailable', '504 gateway timeout', '403 forbidden', '429 too many requests', 'access denied', 'just a moment', 'error'}

def espn_lineup_role(position_abbreviation):
    abbr = (position_abbreviation or '').strip().upper()
    if not abbr or abbr == 'SUB':
        return None
    if abbr in {'G', 'GK'}:
        return 'G'
    if abbr in {'D', 'CB', 'LB', 'RB', 'CD-L', 'CD-R', 'SW'}:
        return 'D'
    if abbr in {'M', 'DM', 'CM', 'CM-L', 'CM-R', 'AM', 'AM-L', 'AM-R', 'LM', 'RM'}:
        return 'M'
    if abbr in {'F', 'FW', 'CF', 'CF-L', 'CF-R', 'LW', 'RW', 'ST', 'SS'}:
        return 'F'
    return None

def roster_role_compatible(profile_roles, espn_role):
    if not espn_role or not profile_roles:
        return True
    if espn_role in profile_roles:
        return True
    if espn_role in {'M', 'F'} and profile_roles & {'M', 'F'}:
        return True
    return False

def fetch_espn_athlete_role(athlete_id):
    if not athlete_id:
        return None
    try:
        data = espn_request_json(f'https://site.web.api.espn.com/apis/common/v3/sports/soccer/athletes/{athlete_id}')
    except requests.RequestException:
        return None
    athlete = data.get('athlete', {})
    position = athlete.get('position', {}) or {}
    abbr = position.get('abbreviation')
    if abbr in {'G', 'D', 'M', 'F'}:
        return abbr
    return None

def season_label_for_match_date(match_dt):
    start_year = match_dt.year if match_dt.month >= 7 else match_dt.year - 1
    end_year = start_year + 1
    return f'{start_year % 100:02d}/{end_year % 100:02d}'

def _espn_event_team_lineup_datetime(team_id, event, now_utc):
    comp = (event.get('competitions') or [{}])[0]
    status_type = comp.get('status', {}).get('type', {}) or {}
    completed = bool(status_type.get('completed'))
    state = (status_type.get('state') or '').lower()
    if not completed and state != 'in':
        return None
    raw = event.get('date') or comp.get('date')
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt > now_utc:
        return None
    for side in comp.get('competitors', []):
        if str((side.get('team') or {}).get('id')) == str(team_id):
            return dt
    return None

def _merge_scoreboard_window(team_id, dates_param, now_utc, event_times, timeout):
    board = espn_request_json(
        'https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard',
        params={'dates': dates_param, 'limit': 500},
        timeout=timeout,
    )
    for event in board.get('events', []):
        dt = _espn_event_team_lineup_datetime(team_id, event, now_utc)
        if dt is None:
            continue
        eid = str(event.get('id') or '')
        if not eid:
            continue
        prev = event_times.get(eid)
        if prev is None or dt > prev:
            event_times[eid] = dt


def resolve_latest_completed_espn_event_id_for_team(team_id, max_days_back=120, chunk_days=14):
    now = datetime.now(timezone.utc)
    event_times = {}
    latest_sched_dt = None
    schedule_timeout = float(os.environ.get('ESPN_SCHEDULE_TIMEOUT', '30'))
    scoreboard_timeout = float(os.environ.get('ESPN_SCOREBOARD_TIMEOUT', '60'))
    try:
        schedule = espn_request_json(
            f'https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{team_id}/schedule',
            params={'limit': 100},
            timeout=schedule_timeout,
        )
        for event in schedule.get('events', []):
            dt = _espn_event_team_lineup_datetime(team_id, event, now)
            if dt is None:
                continue
            eid = event.get('id')
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
                    print(f'  Warning: ESPN scoreboard failed for {dates_param} after 3 tries (timeout {scoreboard_timeout}s).')
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
                    f'  Warning: Latest ESPN lineup source looks stale ({best_dt2.date()}). '
                    'Scoreboard may be failing; try again or pass --gameid <eventId>.'
                )
    return max(event_times.items(), key=lambda kv: kv[1])[0]

def fetch_latest_espn_roster(country_label, game_id=None):
    team_id = lookup_espn_team(country_label)
    if not team_id:
        print(f'Could not resolve ESPN team ID for {country_label}.')
        return None
    if game_id:
        event_id = game_id
        print(f'Using provided gameId {event_id} for {country_label}.')
    else:
        event_id = resolve_latest_completed_espn_event_id_for_team(team_id)
        if not event_id:
            print(f'No completed ESPN matches found for {country_label}.')
            return None
    summary = espn_request_json('https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary', params={'event': event_id})
    roster_payload = None
    for roster in summary.get('rosters', []):
        if str(roster.get('team', {}).get('id')) == str(team_id):
            roster_payload = roster
            break
    if roster_payload is None:
        print(f'ESPN summary for {country_label} did not include a matching roster.')
        return None
    athlete_role_cache = {}
    roster = []
    for player in roster_payload.get('roster', []):
        jersey = player.get('jersey')
        if not jersey or not str(jersey).isdigit():
            continue
        aliases = build_espn_player_aliases(player)
        if not aliases:
            continue
        athlete_id = str(player.get('athlete', {}).get('id') or '')
        role = espn_lineup_role(player.get('position', {}).get('abbreviation'))
        if role is None and athlete_id:
            if athlete_id not in athlete_role_cache:
                athlete_role_cache[athlete_id] = fetch_espn_athlete_role(athlete_id)
            role = athlete_role_cache[athlete_id]
        roster.append({'aliases': aliases, 'jersey': int(jersey), 'role': role})
    lineup_url = f'https://www.espn.com/soccer/lineups/_/gameId/{event_id}'
    match_name = summary.get('header', {}).get('competitions', [{}])[0].get('name') or f'Match {event_id}'
    match_date = summary.get('header', {}).get('competitions', [{}])[0].get('date', '')
    if match_date:
        try:
            dt = datetime.fromisoformat(match_date.replace('Z', '+00:00'))
            date_str = dt.date().isoformat()
        except:
            date_str = match_date[:10]
    else:
        date_str = 'Unknown'
    print(f'Latest ESPN match for {country_label}: {match_name} ({date_str}) [{lineup_url}]')
    return {'event_id': str(event_id), 'date': date_str, 'season': str(summary.get('header', {}).get('season', {}).get('year', '2026')), 'country': country_label, 'lineup_url': lineup_url, 'roster': roster}

def map_recent_players_to_roster(player_profiles, latest_match):
    if not latest_match:
        return ({}, {})
    roster_names = list(player_profiles.items())
    recent_flags = {key: False for key in player_profiles.keys()}
    recent_numbers = {}
    taken = set()
    for espn_player in latest_match['roster']:
        matched_key = None
        espn_role = espn_player.get('role')
        for key, profile in roster_names:
            if key in taken:
                continue
            if not roster_role_compatible(profile['roles'], espn_role):
                continue
            if any((compatible_name_tokens(key, alias) for alias in espn_player['aliases'])):
                matched_key = key
                break
        if matched_key is None:
            for key, profile in roster_names:
                if key in taken:
                    continue
                if not roster_role_compatible(profile['roles'], espn_role):
                    continue
                roster_tokens = [tok for tok in key.split() if tok]
                if len(roster_tokens) == 1:
                    if any((roster_tokens[0] in alias.split() for alias in espn_player['aliases'])):
                        matched_key = key
                        break
                elif any((alias.startswith(key + ' ') or key.startswith(alias + ' ') for alias in espn_player['aliases'])):
                    matched_key = key
                    break
        if matched_key is None:
            continue
        taken.add(matched_key)
        recent_flags[matched_key] = True
        recent_numbers[matched_key] = {'season': latest_match['season'], 'match_date': latest_match['date'], 'country': latest_match['country'], 'number': espn_player['jersey'], 'source': 'espn'}
    return (recent_flags, recent_numbers)

def season_matches_year(season_text, year):
    if not season_text:
        return False
    nums = re.findall('\\d{2,4}', season_text)
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
    espn_season = str(espn_entry.get('season') or '').strip()
    for entry in entries:
        if int(entry['number']) != int(espn_entry['number']):
            continue
        if normalize_name(entry['country']) != normalize_name(espn_entry['country']):
            continue
        if (entry.get('season') or '').strip() == espn_season:
            return entries
    return [espn_entry] + entries

def store_jersey_entries(conn, player_id, official_name, entries, cache_country_filter=None):
    by_number = {}
    for entry in entries:
        by_number.setdefault(str(entry['number']), set()).add(entry['country'])
    nums = sorted(by_number.keys(), key=int)
    cur = conn.cursor()
    cur.execute('INSERT OR REPLACE INTO players (player_id, name) VALUES (?, ?)', (str(player_id), official_name))
    if cache_country_filter:
        cur.execute('DELETE FROM jersey WHERE player_id = ? AND LOWER(country) = LOWER(?)', (str(player_id), cache_country_filter))
    else:
        cur.execute('DELETE FROM jersey WHERE player_id = ?', (str(player_id),))
    for idx, entry in enumerate(entries):
        cur.execute('INSERT OR REPLACE INTO jersey (player_id, idx, season, country, number) VALUES (?, ?, ?, ?, ?)', (str(player_id), idx, entry['season'], entry['country'], int(entry['number'])))
    conn.commit()
    return (nums, by_number)

def extract_national_numbers_from_html(html):
    by_number = {}
    entries = []
    section_match = re.search('<div id="yw2" class="grid-view">(.+?)</table>', html, flags=re.DOTALL | re.IGNORECASE)
    if not section_match:
        return (by_number, entries)
    section_html = section_match.group(1)
    for row in re.findall('<tr[^>]*>(.+?)</tr>', section_html, flags=re.DOTALL | re.IGNORECASE):
        cells = re.findall('<td[^>]*>(.*?)</td>', row, flags=re.DOTALL | re.IGNORECASE)
        if len(cells) < 3:
            continue
        season_cell = cells[0]
        if len(cells) >= 4:
            raw_club = cells[2]
            raw_num = cells[3]
        else:
            raw_club = cells[1]
            raw_num = cells[2]
        season = re.sub('<.*?>', '', season_cell).strip()
        club_cell = re.sub('<.*?>', '', raw_club).strip()
        num_cell = re.sub('<.*?>', '', raw_num).strip()
        if not club_cell or not num_cell or (not season):
            continue
        m = re.search('\\b(\\d{1,2})\\b', num_cell)
        if not m:
            continue
        num = m.group(1)
        club_low = club_cell.strip().lower()
        if re.search('\\s+b$', club_low):
            continue
        if any((u in club_cell for u in ('U15', 'U16', 'U17', 'U18', 'U19', 'U20', 'U21', 'U23', 'Olympic'))):
            continue
        by_number.setdefault(num, set()).add(club_cell)
        entries.append({'season': season, 'country': club_cell, 'number': num})
    return (by_number, entries)

async def get_transfermarkt_id(player, page):
    wid = wikidata_transfermarkt_player_id(player)
    if wid:
        print(f'  Found ID for {player}: {wid} (Wikidata)')
        return wid
    ddg_html = duckduckgo_html_transfermarkt_player_id(player)
    if ddg_html:
        print(f'  Found ID for {player}: {ddg_html} (DuckDuckGo HTML)')
        return ddg_html
    name_normalized = normalize_name(player)
    search_url = f'https://www.transfermarkt.com/suche/spieler?query={urllib.parse.quote(name_normalized)}'
    try:
        await page.goto(search_url)
        await page.wait_for_load_state('domcontentloaded')
        await page.wait_for_timeout(1500)
        if not html_looks_like_waf_challenge(await page.content()):
            links = await page.query_selector_all('a[href*="/spieler/"]')
            for link in links[:15]:
                href = await link.get_attribute('href')
                if not href:
                    continue
                m = re.search('/spieler/(\\d+)', href)
                if m:
                    pid = m.group(1)
                    print(f'  Found ID for {player}: {pid} (Transfermarkt search)')
                    return pid
    except Exception as e:
        print(f'  Transfermarkt search failed for {player}: {e}')
    queries = [f'{player} transfermarkt', f'"{player}" transfermarkt', f'{player} transfermarkt player', f'{player} transfermarkt spieler']
    print(f'Searching ID for {player} via browser (DuckDuckGo)...')
    best = None
    seen_pids = set()
    ddg_urls = ['https://lite.duckduckgo.com/lite/?q={}', 'https://duckduckgo.com/?q={}']
    for raw_query in queries:
        encoded = urllib.parse.quote(raw_query)
        for template in ddg_urls:
            try:
                await page.goto(template.format(encoded))
                await page.wait_for_load_state('domcontentloaded')
                await page.wait_for_timeout(2000)
                selectors = ('a[href*="transfermarkt"][href*="/spieler/"]', 'a[data-testid="result-title-a"]', 'a.result-link')
                for sel in selectors:
                    results = await page.query_selector_all(sel)
                    for result in results:
                        try:
                            url = await result.get_attribute('href')
                            text = await result.inner_text()
                        except Exception:
                            continue
                        url = unwrap_duckduckgo_link(url)
                        scored = score_transfermarkt_candidate(player, url, text)
                        if not scored:
                            continue
                        score, pid = scored
                        if pid in seen_pids:
                            continue
                        seen_pids.add(pid)
                        if best is None or score > best[0]:
                            best = (score, pid)
                html = await page.content()
                for m in re.finditer('https?://www\\.transfermarkt\\.[a-z.]+\\/([a-z0-9-]+)\\/profil\\/spieler\\/(\\d+)', html, re.I):
                    slug, pid = (m.group(1), m.group(2))
                    if pid in seen_pids:
                        continue
                    link = f'https://www.transfermarkt.com/{slug}/profil/spieler/{pid}'
                    scored = score_transfermarkt_candidate(player, link, slug.replace('-', ' '))
                    if not scored:
                        continue
                    score, _ = scored
                    seen_pids.add(pid)
                    if best is None or score > best[0]:
                        best = (score, pid)
                if best is not None and best[0] >= 100:
                    break
            except Exception as e:
                print(f'  DuckDuckGo page failed for {player}: {e}')
                continue
        if best is not None and best[0] >= 100:
            break
    if best is not None:
        print(f'  Found ID for {player}: {best[1]} (DuckDuckGo)')
        return best[1]
    print(f'  ID not found for {player} (Wikidata, DuckDuckGo, Transfermarkt)')
    return None

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('\n        CREATE TABLE IF NOT EXISTS players (\n            player_id TEXT PRIMARY KEY,\n            name TEXT NOT NULL\n        )\n        ')
    cur.execute('\n        CREATE TABLE IF NOT EXISTS jersey (\n            player_id TEXT NOT NULL,\n            idx INTEGER NOT NULL,\n            season TEXT,\n            country TEXT,\n            number INTEGER,\n            PRIMARY KEY (player_id, idx)\n        )\n        ')
    conn.commit()
    return conn

def load_cached_numbers_from_db(conn, player_id, country_filter=None):
    cur = conn.cursor()
    cur.execute('SELECT name FROM players WHERE player_id = ?', (str(player_id),))
    name_row = cur.fetchone()
    db_name = name_row[0] if name_row else str(player_id)
    if country_filter:
        cur.execute('\n            SELECT number, country\n            FROM jersey\n            WHERE player_id = ? AND LOWER(country) = LOWER(?)\n            ORDER BY idx ASC\n            ', (str(player_id), country_filter))
    else:
        cur.execute('SELECT number, country FROM jersey WHERE player_id = ? ORDER BY idx ASC', (str(player_id),))
    rows = cur.fetchall()
    if not rows:
        return []
    nums_by_country = {}
    for num, country in rows:
        nums_by_country.setdefault(str(num), set()).add(country)
    if country_filter:
        print(f'{db_name} {player_id} national jersey numbers (cached for {country_filter}):')
    else:
        print(f'{db_name} {player_id} national jersey numbers (cached):')
    for n in sorted(nums_by_country.keys(), key=int):
        countries = ', '.join(sorted(nums_by_country[n]))
        print(f'  {n}: {countries}')
    return sorted(nums_by_country.keys(), key=int)

async def fetch_numbers_for_player(playwright, name, player_id, conn, db_name_override=None, cache_country_filter=None, espn_seed_entry=None):
    nums = load_cached_numbers_from_db(conn, player_id, country_filter=cache_country_filter)
    if nums:
        return (nums, True)
    url = f'https://www.transfermarkt.com/-/rueckennummern/spieler/{player_id}'
    try:
        html = await fetch_transfermarkt_rueckennummern_html(playwright, url)
    except PlaywrightTimeoutError:
        print(f'  Timeout loading {url}. Skipping for now.')
        if espn_seed_entry:
            official_name = db_name_override or name
            nums, by_number = store_jersey_entries(conn, player_id, official_name, [espn_seed_entry], cache_country_filter=cache_country_filter)
            print(f'{official_name} {player_id} national jersey numbers (ESPN fallback):')
            for n in nums:
                countries = ', '.join(sorted(by_number[n]))
                print(f'  {n}: {countries}')
            return (nums, False)
        return ([], False)
    global _transfermarkt_waf_hint_printed
    if html_looks_like_waf_challenge(html) and (not _transfermarkt_waf_hint_printed):
        print('  Note: Transfermarkt is showing a bot check (HTML still saved under debug_html/ if needed). Install curl_cffi (pip install curl_cffi) or set PLAYWRIGHT_BROWSER_CHANNEL=chrome.')
        _transfermarkt_waf_hint_printed = True
    soup = BeautifulSoup(html, 'html.parser')
    official_name = name
    title_tag = soup.find('title')
    if title_tag and title_tag.string:
        title_text = title_tag.string.strip()
        parts = title_text.split(' - ', 1)
        if parts:
            candidate_name = parts[0].strip()
            if not invalid_transfermarkt_title(candidate_name):
                official_name = candidate_name
    if db_name_override:
        official_name = db_name_override
    _, tm_only_entries = extract_national_numbers_from_html(html)
    if html_looks_like_waf_challenge(html) or not tm_only_entries:
        debug_dir = 'debug_html'
        os.makedirs(debug_dir, exist_ok=True)
        debug_path = os.path.join(debug_dir, f'debug_playwright_{player_id}.html')
        try:
            with open(debug_path, 'w', encoding='utf-8') as f:
                f.write(html)
            print(f'  Wrote debug HTML to {debug_path}')
        except Exception as e:
            print(f'  Failed to write debug HTML for {player_id}: {e}')
    entries = tm_only_entries
    entries = merge_jersey_entries(espn_seed_entry, entries)
    nums, by_number = store_jersey_entries(conn, player_id, official_name, entries, cache_country_filter=cache_country_filter)
    if by_number:
        print(f'{official_name} {player_id} national jersey numbers:')
        for n in nums:
            countries = ', '.join(sorted(by_number[n]))
            print(f'  {n}: {countries}')
    else:
        print(f'{name} {player_id} national jersey numbers: NONE FOUND')
    return (nums, False)

async def main():
    conn = init_db()
    async with async_playwright() as p:
        country_folder, force_refetch, game_id = parse_args(sys.argv)
        players_file = resolve_players_file(country_folder)
        if not os.path.exists(players_file):
            print(f'No {players_file} found; nothing to do.')
            return
        with open(players_file, 'r', encoding='utf-8') as f:
            raw_lines = [line.rstrip('\n') for line in f]
        country_name = os.path.basename(os.path.normpath(country_folder.strip()))
        country_label = country_display_name(country_name)
        players = []
        seen_names = set()
        for line in raw_lines:
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            parts = [p.strip() for p in line.split(',')]
            if not parts:
                continue
            nk = normalize_name(parts[0])
            if nk in seen_names:
                continue
            seen_names.add(nk)
            players.append(parts[0])
        player_profiles = build_local_player_profiles(raw_lines)
        latest_match = None
        recent_flags = {}
        recent_numbers = {}
        if force_refetch:
            latest_match = fetch_latest_espn_roster(country_label, game_id)
            recent_flags, recent_numbers = map_recent_players_to_roster(player_profiles, latest_match)
            if recent_flags:
                raw_lines, changed = rewrite_players_txt(raw_lines, recent_flags=recent_flags)
                if changed:
                    with open(players_file, 'w', encoding='utf-8') as f:
                        for ln in raw_lines:
                            f.write(ln + '\n')
                    print(f'Updated recent flags in {players_file} from ESPN latest match.')
        id_map = load_player_id_map(conn)
        had_error = False
        name_changes = {}
        refreshed_player_ids = set()
        browser = await launch_chromium(p)
        page = await browser.new_page()
        for name in players:
            override = get_manual_override(country_name, name)
            pid_str = id_map.get(normalize_name(name))
            if override:
                pid_str = override['player_id']
            if not pid_str:
                pid_str = await get_transfermarkt_id(name, page)
                await asyncio.sleep(5)
            if not pid_str:
                print(f'Skipping {name}: could not resolve Transfermarkt ID.')
                had_error = True
                continue
            id_map[normalize_name(name)] = str(pid_str)
            pid = int(pid_str)
            should_clear_country_cache = force_refetch and pid not in refreshed_player_ids
            if should_clear_country_cache:
                cur = conn.cursor()
                cur.execute('\n                    DELETE FROM jersey\n                    WHERE player_id = ? AND LOWER(country) = LOWER(?)\n                    ', (str(pid), country_label))
                conn.commit()
            db_name_override = name if override and override.get('preserve_name') else None
            cache_country_filter = country_label if force_refetch else None
            espn_seed_entry = recent_numbers.get(normalize_name(name)) if force_refetch else None
            nums, used_cache = await fetch_numbers_for_player(p, name, pid, conn, db_name_override=db_name_override, cache_country_filter=cache_country_filter, espn_seed_entry=espn_seed_entry)
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
                with open(players_file, 'w', encoding='utf-8') as f:
                    for ln in new_lines:
                        f.write(ln + '\n')
                print(f'Updated names in {players_file} to match Transfermarkt.')
        if not had_error and os.path.isdir('debug_html'):
            try:
                shutil.rmtree('debug_html')
            except Exception:
                pass
if __name__ == '__main__':
    asyncio.run(main())
