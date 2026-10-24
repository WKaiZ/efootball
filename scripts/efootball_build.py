#!/usr/bin/env python3

import difflib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import imgcache
import tmfetch

REPO_URL = "https://github.com/WKaiZ/efootball"
NATIONS_DIR = "nations"
GROUPS = [("contenders", "contender"), ("challengers", "challenger"),
          ("backup", "backup"), ("reserve", "reserve")]

FOTMOB_SUGGEST = "https://apigw.fotmob.com/searchapi/suggest"
FOTMOB_IMG = "https://images.fotmob.com/image_resources/playerimages/{id}.png"
TM_LINK = tmfetch.TM_LINK
TM_DAILY_LIMIT = int(os.environ.get("EFOOTBALL_TM_LIMIT") or "23")
TM_NULL_LIMIT = int(os.environ.get("EFOOTBALL_TM_NULL_LIMIT", "3"))
TM_ERROR_LIMIT = int(os.environ.get("EFOOTBALL_TM_ERROR_LIMIT", "5"))
TM_BLOCK_ABORT = int(os.environ.get("EFOOTBALL_TM_BLOCK_ABORT", "3"))
TM_BLOCKED_WAIT = float(os.environ.get("TM_BLOCKED_WAIT", "45"))
TM_BLOCKED_RETRIES = int(os.environ.get("TM_BLOCKED_RETRIES", "2"))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(ROOT, "data")
SQUADS_PATH = os.path.join(ROOT, "docs", "squads.json")
PLAYERS_PATH = os.path.join(ROOT, "docs", "players.json")
HISTORY_PATH = os.path.join(ROOT, "docs", "history.json")
CACHE_PATH = os.path.join(DATA_DIR, "img_cache.json")
OVERRIDES_PATH = os.path.join(DATA_DIR, "overrides.json")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

LINE_RE = re.compile(
    r"^\s*\[(?P<slot>[A-Z]+)\]\s+(?P<name>.+?)\s+\((?P<pos>[A-Z]+)\)\s+"
    r"rating\s+(?P<rating>[\d.]+)\s+#(?P<num>\d+)\s*$"
)
_SCOT = "\U0001F3F4\U000E0067\U000E0062\U000E0073\U000E0063\U000E0074\U000E007F"
_WALES = "\U0001F3F4\U000E0067\U000E0062\U000E0077\U000E006C\U000E0073\U000E007F"
_ENG = "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F"
SUBDIVISION_FLAGS = {"england": _ENG, "scotland": _SCOT, "wales": _WALES}

ISO2 = {
    'afghanistan': 'af',
    'albania': 'al',
    'algeria': 'dz',
    'american-samoa': 'as',
    'andorra': 'ad',
    'angola': 'ao',
    'anguilla': 'ai',
    'antigua-and-barbuda': 'ag',
    'argentina': 'ar',
    'armenia': 'am',
    'aruba': 'aw',
    'australia': 'au',
    'austria': 'at',
    'azerbaijan': 'az',
    'bahamas': 'bs',
    'bahrain': 'bh',
    'bangladesh': 'bd',
    'barbados': 'bb',
    'belarus': 'by',
    'belgium': 'be',
    'belize': 'bz',
    'benin': 'bj',
    'bermuda': 'bm',
    'bhutan': 'bt',
    'bolivia': 'bo',
    'bosnia-and-herzegovina': 'ba',
    'botswana': 'bw',
    'brazil': 'br',
    'british-virgin-islands': 'vg',
    'brunei': 'bn',
    'bulgaria': 'bg',
    'burkina-faso': 'bf',
    'burundi': 'bi',
    'cabo-verde': 'cv',
    'cambodia': 'kh',
    'cameroon': 'cm',
    'canada': 'ca',
    'cayman-islands': 'ky',
    'central-african-republic': 'cf',
    'chad': 'td',
    'chile': 'cl',
    'china-pr': 'cn',
    'chinese-taipei': 'tw',
    'colombia': 'co',
    'comoros': 'km',
    'congo': 'cg',
    'congo-dr': 'cd',
    'cook-islands': 'ck',
    'costa-rica': 'cr',
    'cote-divoire': 'ci',
    'croatia': 'hr',
    'cuba': 'cu',
    'curacao': 'cw',
    'cyprus': 'cy',
    'czechia': 'cz',
    'denmark': 'dk',
    'djibouti': 'dj',
    'dominica': 'dm',
    'dominican-republic': 'do',
    'dpr-korea': 'kp',
    'ecuador': 'ec',
    'egypt': 'eg',
    'el-salvador': 'sv',
    'equatorial-guinea': 'gq',
    'eritrea': 'er',
    'estonia': 'ee',
    'eswatini': 'sz',
    'ethiopia': 'et',
    'faroe-islands': 'fo',
    'fiji': 'fj',
    'finland': 'fi',
    'france': 'fr',
    'gabon': 'ga',
    'gambia': 'gm',
    'georgia': 'ge',
    'germany': 'de',
    'ghana': 'gh',
    'gibraltar': 'gi',
    'greece': 'gr',
    'grenada': 'gd',
    'guam': 'gu',
    'guatemala': 'gt',
    'guinea': 'gn',
    'guinea-bissau': 'gw',
    'guyana': 'gy',
    'haiti': 'ht',
    'honduras': 'hn',
    'hong-kong': 'hk',
    'hungary': 'hu',
    'iceland': 'is',
    'india': 'in',
    'indonesia': 'id',
    'ir-iran': 'ir',
    'iraq': 'iq',
    'israel': 'il',
    'italy': 'it',
    'jamaica': 'jm',
    'japan': 'jp',
    'jordan': 'jo',
    'kazakhstan': 'kz',
    'kenya': 'ke',
    'korea-republic': 'kr',
    'kosovo': 'xk',
    'kuwait': 'kw',
    'kyrgyz-republic': 'kg',
    'laos': 'la',
    'latvia': 'lv',
    'lebanon': 'lb',
    'lesotho': 'ls',
    'liberia': 'lr',
    'libya': 'ly',
    'liechtenstein': 'li',
    'lithuania': 'lt',
    'luxembourg': 'lu',
    'macau-china': 'mo',
    'madagascar': 'mg',
    'malawi': 'mw',
    'malaysia': 'my',
    'maldives': 'mv',
    'mali': 'ml',
    'malta': 'mt',
    'mauritania': 'mr',
    'mauritius': 'mu',
    'mexico': 'mx',
    'moldova': 'md',
    'mongolia': 'mn',
    'montenegro': 'me',
    'montserrat': 'ms',
    'morocco': 'ma',
    'mozambique': 'mz',
    'myanmar': 'mm',
    'namibia': 'na',
    'nepal': 'np',
    'netherlands': 'nl',
    'new-caledonia': 'nc',
    'new-zealand': 'nz',
    'nicaragua': 'ni',
    'niger': 'ne',
    'nigeria': 'ng',
    'north-macedonia': 'mk',
    'northern-ireland': 'gb',
    'norway': 'no',
    'oman': 'om',
    'pakistan': 'pk',
    'palestine': 'ps',
    'panama': 'pa',
    'papua-new-guinea': 'pg',
    'paraguay': 'py',
    'peru': 'pe',
    'philippines': 'ph',
    'poland': 'pl',
    'portugal': 'pt',
    'puerto-rico': 'pr',
    'qatar': 'qa',
    'republic-of-ireland': 'ie',
    'romania': 'ro',
    'russia': 'ru',
    'rwanda': 'rw',
    'samoa': 'ws',
    'san-marino': 'sm',
    'sao-tome-and-principe': 'st',
    'saudi-arabia': 'sa',
    'senegal': 'sn',
    'serbia': 'rs',
    'seychelles': 'sc',
    'sierra-leone': 'sl',
    'singapore': 'sg',
    'slovakia': 'sk',
    'slovenia': 'si',
    'solomon-islands': 'sb',
    'somalia': 'so',
    'south-africa': 'za',
    'south-sudan': 'ss',
    'spain': 'es',
    'sri-lanka': 'lk',
    'st-kitts-and-nevis': 'kn',
    'st-lucia': 'lc',
    'st-vincent-and-grenadines': 'vc',
    'sudan': 'sd',
    'suriname': 'sr',
    'sweden': 'se',
    'switzerland': 'ch',
    'syria': 'sy',
    'tahiti': 'pf',
    'tajikistan': 'tj',
    'tanzania': 'tz',
    'thailand': 'th',
    'timor-leste': 'tl',
    'togo': 'tg',
    'tonga': 'to',
    'trinidad-and-tobago': 'tt',
    'tunisia': 'tn',
    'turkiye': 'tr',
    'turkmenistan': 'tm',
    'turks-and-caicos-islands': 'tc',
    'uganda': 'ug',
    'ukraine': 'ua',
    'united-arab-emirates': 'ae',
    'uruguay': 'uy',
    'us-virgin-islands': 'vi',
    'usa': 'us',
    'uzbekistan': 'uz',
    'vanuatu': 'vu',
    'venezuela': 've',
    'vietnam': 'vn',
    'yemen': 'ye',
    'zambia': 'zm',
    'zimbabwe': 'zw',
}
DISPLAY = {"usa": "USA", "china-pr": "China PR", "congo-dr": "Congo DR",
           "ir-iran": "IR Iran", "republic-of-ireland": "Republic of Ireland",
           "cote-divoire": "Côte d'Ivoire", "korea-republic": "Korea Republic",
           "turkiye": "Türkiye", "united-arab-emirates": "United Arab Emirates",
           "bosnia-and-herzegovina": "Bosnia and Herzegovina", "cabo-verde": "Cabo Verde",
           "curacao": "Curaçao", "gambia": "The Gambia", "dpr-korea": "DPR Korea",
           "congo": "Congo", "singapore": "Singapore", "st-kitts-and-nevis": "St. Kitts and Nevis",
           "st-lucia": "St. Lucia", "st-vincent-and-grenadines": "St. Vincent / Grenadines",
           "sao-tome-and-principe": "São Tomé and Príncipe", "macau-china": "Macau, China",
           "chinese-taipei": "Chinese Taipei", "us-virgin-islands": "US Virgin Islands"}

def flag_for(country):
    if country in SUBDIVISION_FLAGS:
        return SUBDIVISION_FLAGS[country]
    iso = ISO2.get(country)
    if not iso:
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("a")) for c in iso.lower())

def log(*a):
    print(*a, file=sys.stderr, flush=True)

def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()

def deaccent(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))

def display_name(country):
    return DISPLAY.get(country, country.replace("-", " ").replace("_", " ").title())

def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True).stdout

def row_sig(line):
    return re.sub(r"\s+", " ", line.strip())

def squad_row_sig(line):
    return re.sub(r"^\[[A-Z]+\]\s+", "", row_sig(line))

def parse_squad_sigs(text):
    sigs, squad = set(), "first"
    for line in text.splitlines():
        low = line.strip().lower()
        if low == "first squad":
            squad = "first"
            continue
        if low == "second squad":
            squad = "second"
            continue
        if low == "third squad":
            squad = "third"
            continue
        if LINE_RE.match(line):
            sigs.add((squad, squad_row_sig(line)))
    return sigs

POOL_ROW_RE = re.compile(r"^\s*(?P<name>[^,\[\]]+?),\s*(?P<pos>[A-Z]+),")
POOL_BOOL_RE = re.compile(r",\s*(?:True|False),")

def pool_sig(line):
    return row_sig(POOL_BOOL_RE.sub(",", line, count=1))

def parse_pool_sigs(text):
    return {pool_sig(ln) for ln in text.splitlines() if POOL_ROW_RE.match(ln)}

def parse_pool_rows(text):
    rows = {}
    for ln in text.splitlines():
        m = POOL_ROW_RE.match(ln)
        if m:
            rows[(norm(m["name"]), m["pos"])] = pool_sig(ln)
    return rows

POOL_FULL_RE = re.compile(
    r"^\s*(?P<name>[^,\[\]]+?),\s*(?P<pos>[A-Z]+),\s*(?P<rating>[\d.]+),\s*"
    r"(?:(?P<recent>True|False),\s*)?(?P<card>[A-Za-z]+),\s*"
    r"\[(?P<prof>[^\]]*)\],\s*\[(?P<semi>[^\]]*)\]")

CARD_TYPES = ("Standard", "Highlight", "Showtime", "Epic", "BigTime")
POOL_CARD_RE = re.compile(
    r"(?m)^(\s*[^,\[\]]+?,\s*[A-Z]+,\s*[\d.]+,\s*(?:(?:True|False),\s*)?)([A-Za-z]+)(?=,\s*\[)")

def canon_card(card):
    for name in CARD_TYPES:
        if card.lower() == name.lower():
            return name
    close = difflib.get_close_matches(card, CARD_TYPES, n=1, cutoff=0.75)
    return close[0] if close else card

def clean_pool_text(text):
    return POOL_CARD_RE.sub(lambda m: m[1] + canon_card(m[2]), text)

def backfill_card_fixes(pool_texts, pool_now):
    def rows(text):
        return {(norm(m["name"]), m["pos"]): (float(m["rating"]), m["card"])
                for m in map(POOL_FULL_RE.match, (text or "").splitlines()) if m}

    ref = rows(pool_now)
    out, fixed = [], set()
    for d, text in pool_texts:
        lines = []
        for ln in text.splitlines(keepends=True):
            m = POOL_FULL_RE.match(ln)
            if m:
                newer = ref.get((norm(m["name"]), m["pos"]))
                if newer and newer[1] != m["card"] and abs(newer[0] - float(m["rating"])) <= 0.025:
                    ln = ln[:m.start("card")] + newer[1] + ln[m.end("card"):]
                    fixed.add(f"{m['name'].strip()} {m['pos']}")
            lines.append(ln)
        text = "".join(lines)
        ref.update(rows(text))
        out.append((d, text))
    return out, sorted(fixed)

def _names_in(squad_text, pool_text):
    names = {p["name"] for p in _parse_players(squad_text or "")}
    names |= {m["name"].strip() for m in map(POOL_ROW_RE.match, (pool_text or "").splitlines()) if m}
    return names

def detect_renames(squad_texts, pool_texts, squad_now, pool_now, today):
    def similar(a, b):
        a, b = norm(a), norm(b)
        whole = difflib.SequenceMatcher(None, a, b).ratio()
        surname = difflib.SequenceMatcher(None, a.split()[-1], b.split()[-1]).ratio()
        return whole if surname >= 0.85 else 0

    days = {}
    for key, texts, now in (("s", squad_texts, squad_now), ("p", pool_texts, pool_now)):
        for d, t in reversed(texts):
            days.setdefault(d, {})[key] = t
        if now is not None:
            days.setdefault(today.isoformat(), {})[key] = now
    cur, prev, renames = {}, None, {}
    for d in sorted(days):
        cur.update(days[d])
        names = _names_in(cur.get("s"), cur.get("p"))
        if prev is not None:
            new = names - prev
            for old in prev - names:
                if not new:
                    break
                best = max(new, key=lambda n: similar(old, n))
                if norm(old) != norm(best) and similar(old, best) >= 0.8:
                    renames[old] = best
        prev = names
    for old in list(renames):
        seen = {old}
        while renames[old] in renames and renames[old] not in seen:
            seen.add(renames[old])
            renames[old] = renames[renames[old]]
    return renames

def apply_renames(text, renames):
    for old, new in renames.items():
        text = re.sub(rf"(?m)^(\s*(?:\[[A-Z]+\]\s+)?){re.escape(old)}(?=\s+\(|\s*,)",
                      lambda m: m[1] + new, text)
    return text

def parse_pool(text):
    pool = {}
    for ln in text.splitlines():
        m = POOL_FULL_RE.match(ln)
        if not m:
            continue
        entry = pool.setdefault(norm(m["name"]), {
            "name": m["name"].strip(), "recent": m["recent"] == "True", "rows": []})
        entry["rows"].append([m["pos"], float(m["rating"]), m["card"],
                              re.sub(r"\s+", "", m["prof"]), re.sub(r"\s+", "", m["semi"]),
                              m["recent"] == "True"])
    for entry in pool.values():
        entry["rows"].sort(key=lambda r: -r[1])
    return pool

def history_texts(repo, rel_path, related_paths=()):
    paths_to_check = list(dict.fromkeys((rel_path, *related_paths)))
    commits = []
    for rel in paths_to_check:
        out = git(repo, "log", "--follow", "--format=C|%H|%cI", "--name-status", "--", rel)
        h = stamp = None
        for ln in out.splitlines():
            if ln.startswith("C|"):
                _, h, stamp = ln.split("|", 2)
            elif ln.strip():
                status, *paths = ln.split("\t")
                if status.startswith("D"):
                    active = set(git(repo, "ls-tree", "-r", "--name-only", h,
                                     "--", *paths_to_check).splitlines())
                    path = next((candidate for candidate in paths_to_check
                                 if candidate in active), None)
                else:
                    path = paths[-1]
                commits.append((h, stamp, path, rel == rel_path))
                if status.startswith("C"):
                    break
    latest = {}
    for h, stamp, path, preferred in commits:
        d = stamp[:10]
        key = (datetime.fromisoformat(stamp), path is not None, preferred)
        if d not in latest or key > latest[d][0]:
            latest[d] = (key, h, path)
    return [(d, git(repo, "show", f"{h}:{path}") if path else "")
            for d, (_, h, path) in sorted(latest.items(), reverse=True)]

def nation_file_paths(country, suffix):
    return [
        f"{NATIONS_DIR}/{group_dir}/{country}/{country}{suffix}"
        for group_dir, _ in GROUPS
    ]

def squad_members(text):
    members = {}
    for p in _parse_players(text):
        members.setdefault(norm(p["name"]), p)
    return members

def _squad_states(text):
    states = {}
    for p in _parse_players(text):
        entry = states.setdefault((norm(p["name"]), p["pos"]), [p["name"], []])
        entry[1].append([p["squad"], p["section"], p["slot"], p["number"], p["rating"]])
    return states

def _pool_states(text):
    return {(key, row[0]): [e["name"], [row[1], row[2], row[5]]]
            for key, e in parse_pool(text).items() for row in e["rows"]}

def _join_position_changes(hist):
    events = {}
    for (name, pos), snaps in hist.items():
        for i, snap in enumerate(snaps):
            previous = snaps[i - 1] if i else None
            if previous and previous["p"] and not snap["p"] and not snap["a"]:
                events.setdefault((name, snap["d"]), {"out": [], "in": []})["out"].append(
                    (pos, previous["p"][1]))
            if snap["p"] and (previous is None or not previous["p"]):
                events.setdefault((name, snap["d"]), {"out": [], "in": []})["in"].append(
                    (pos, snap["p"][1]))

    for (name, day), changes in sorted(events.items(), key=lambda item: item[0][1]):
        if len(changes["out"]) != 1 or len(changes["in"]) != 1:
            continue
        old_pos, old_type = changes["out"][0]
        new_pos, new_type = changes["in"][0]
        if old_pos == new_pos or old_type != new_type:
            continue
        old_key, new_key = (name, old_pos), (name, new_pos)
        old_snaps, new_snaps = hist.get(old_key), hist.get(new_key)
        if not old_snaps or not new_snaps:
            continue
        prior = [s for s in old_snaps if s["d"] < day]
        remaining = [s for s in old_snaps if s["d"] > day]
        if not prior or not any(s["d"] == day and s["p"] for s in new_snaps):
            continue
        target_before = [s for s in new_snaps if s["d"] < day]
        target_at_start = next(
            (s for s in reversed(target_before) if s["d"] <= prior[0]["d"]), None)
        if (target_at_start and (target_at_start["p"] or target_at_start["a"])) or any(
            (s["p"] or s["a"]) and s["d"] >= prior[0]["d"]
            for s in target_before
        ):
            continue
        for snap in prior:
            snap.setdefault("pos", old_pos)
        for snap in new_snaps:
            snap.setdefault("pos", new_pos)
        hist[new_key] = sorted(prior + new_snaps, key=lambda s: s["d"])
        if remaining:
            hist[old_key] = remaining
        else:
            del hist[old_key]

def card_history(squad_texts, pool_texts, squad_now, pool_now, today):
    def by_day(texts, now, parser):
        days = {d: parser(t) for d, t in reversed(texts)}
        if now is not None:
            days[today.isoformat()] = parser(now)
        return days

    squads = by_day(squad_texts, squad_now, _squad_states)
    pools = by_day(pool_texts, pool_now, _pool_states)
    cur_sq, cur_pool, last, names, hist = {}, {}, {}, {}, {}
    for d in sorted(set(squads) | set(pools)):
        cur_sq = squads.get(d, cur_sq)
        cur_pool = pools.get(d, cur_pool)
        for k in set(cur_sq) | set(cur_pool) | set(last):
            sq, pl = cur_sq.get(k), cur_pool.get(k)
            if sq or pl:
                names[k[0]] = (sq or pl)[0]
            snap = {"a": sq[1] if sq else [], "p": pl[1] if pl else None}
            if snap != last.get(k):
                hist.setdefault(k, []).append({"d": d, **snap})
                last[k] = snap
    _join_position_changes(hist)
    out = {}
    for (n, pos), snaps in hist.items():
        out.setdefault(names[n], {})[pos] = snaps
    return out

def squad_history(texts, current, today):
    chrono = [(d, squad_members(t)) for d, t in reversed(texts)]
    chrono.append((today.isoformat(), {norm(p["name"]): p for p in current}))
    names = {n for _, members in chrono for n in members}
    callups, joined, dropouts = {}, {}, []
    for n in names:
        present = [n in members for _, members in chrono]
        runs = sum(1 for i, x in enumerate(present) if x and (i == 0 or not present[i - 1]))
        callups[n] = runs
        last = max(i for i, x in enumerate(present) if x)
        start = last
        while start > 0 and present[start - 1]:
            start -= 1
        if present[-1]:
            joined[n] = chrono[start][0]
            continue
        info = chrono[last][1][n]
        since, dropped = chrono[start][0], chrono[last + 1][0]
        dropouts.append({
            "name": info["name"], "pos": info["pos"], "rating": info["rating"],
            "number": info["number"], "squad": info["squad"], "section": info["section"],
            "since": since, "dropped": dropped,
            "days": (datetime.fromisoformat(dropped) - datetime.fromisoformat(since)).days,
            "callups": runs,
        })
    dropouts.sort(key=lambda d: (d["dropped"], d["rating"], d["name"], d["pos"]), reverse=True)
    return callups, joined, dropouts

def compute_since(versions, sig):
    since = None
    for date, sigs in versions:
        if sig in sigs:
            since = date
        else:
            break
    return since

def http_get(url, timeout=30, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def _fotmob_query(term):
    url = f"{FOTMOB_SUGGEST}?term={urllib.parse.quote(term)}&lang=en"
    try:
        data = json.loads(http_get(url, timeout=15))
    except Exception:
        return None
    best_player = best_any = None
    for group in data.get("squadMemberSuggest", []):
        for opt in group.get("options", []):
            payload = opt.get("payload") or {}
            pid = payload.get("id") or (opt.get("text", "").rsplit("|", 1)[-1])
            score = opt.get("score") or 0
            if not pid:
                continue
            if best_any is None or score > best_any[1]:
                best_any = (str(pid), score)
            if not payload.get("isCoach") and (best_player is None or score > best_player[1]):
                best_player = (str(pid), score)
    chosen = best_player or best_any
    return chosen[0] if chosen else None

def fotmob_lookup(name):
    tokens = name.split()
    variants = [name, deaccent(name)]
    if len(tokens) > 2:
        fl = f"{tokens[0]} {tokens[-1]}"
        variants += [fl, deaccent(fl)]
    seen = set()
    for v in variants:
        if v in seen:
            continue
        seen.add(v)
        pid = _fotmob_query(v)
        if pid:
            return pid
        time.sleep(0.2)
    return None

def load_game_data(db_path):
    conn = sqlite3.connect(db_path)
    rows, cards = {}, {}
    for country, pid, name, pos, rating, card_type in conn.execute(
        "SELECT g.country, g.player_id, p.name, g.position, g.rating, g.card_type "
        "FROM game_data g JOIN players p ON p.player_id = g.player_id"
    ):
        rows.setdefault(country, []).append((str(pid), name, pos, rating))
        cards[(country, str(pid), pos)] = card_type
    conn.close()
    return rows, cards

def find_tm_id(rows, player, override):
    if override:
        return str(override)
    target = norm(player["name"])
    for pid, name, pos, _ in rows:
        if pos == player["pos"] and norm(name) == target:
            return pid
    cands = [r for r in rows if r[2] == player["pos"] and abs(r[3] - player["rating"]) < 0.01]
    if len(cands) == 1:
        return cands[0][0]
    if len(cands) > 1:
        for pid, name, _, _ in cands:
            if target in norm(name) or norm(name) in target:
                return pid
        return cands[0][0]
    for pid, name, _, _ in rows:
        if norm(name) == target:
            return pid
    return None

def load_cache():
    if not os.path.exists(CACHE_PATH):
        return {"fotmob": {}, "transfermarkt": {}, "tm_null": {}}
    data = json.load(open(CACHE_PATH))
    if "fotmob" in data or "transfermarkt" in data:
        data.setdefault("fotmob", {})
        data.setdefault("transfermarkt", {})
        data.setdefault("tm_null", {})
        data.setdefault("tm_err", {})
        return data
    return {"fotmob": {k: v for k, v in data.items() if v},
            "transfermarkt": {}, "tm_null": {}, "tm_err": {}}

def save_cache(cache):
    json.dump({"fotmob": cache["fotmob"]}, open(CACHE_PATH, "w"),
              ensure_ascii=False, indent=1)
    imgcache.save(cache)

def _parse_players(text):
    players, section, squad = [], None, "first"
    for line in text.splitlines():
        low = line.strip().lower()
        if low == "first squad":
            squad = "first"
            section = None
            continue
        if low == "second squad":
            squad = "second"
            section = None
            continue
        if low == "third squad":
            squad = "third"
            section = None
            continue
        if low.startswith("starters"):
            section = "starters"; continue
        if low.startswith("substitutes"):
            section = "substitutes"; continue
        if low.startswith("wildcard"):
            section = "wildcard"; continue
        m = LINE_RE.match(line)
        if m:
            players.append({
                "squad": squad, "section": section, "slot": m["slot"],
                "name": m["name"].strip(),
                "pos": m["pos"], "rating": float(m["rating"]), "number": int(m["num"]),
                "row": row_sig(line),
            })
    return players

def _assign_medals(players):
    for p in players:
        p["tenureRank"] = 0
    ranked = sorted(players, key=lambda p: (p["since"], -p["rating"], p["name"]))
    for i, p in enumerate(ranked[:3]):
        p["tenureRank"] = i + 1

def apply_player_history(country, players, texts, pool_texts, pool_now, today):
    versions = [(d, parse_squad_sigs(t)) for d, t in texts]
    pool_rows = parse_pool_rows(pool_now) if pool_now is not None else {}
    pool_versions = ([(d, parse_pool_sigs(t)) for d, t in pool_texts]
                     if pool_rows else [])
    for p in players:
        dates = [compute_since(versions, (p["squad"], squad_row_sig(p["row"])))]
        pool_row = pool_rows.get((norm(p["name"]), p["pos"]))
        if pool_row:
            dates.append(compute_since(pool_versions, pool_row))
        since = (today.isoformat() if any(d is None for d in dates)
                 else max(dates))
        p["since"] = since
        p["days"] = (today - datetime.fromisoformat(since).date()).days
    for squad in ("first", "second", "third"):
        _assign_medals([p for p in players if p["squad"] == squad])
    callups, joined, dropouts = squad_history(texts, players, today)
    for p in players:
        p["callups"] = callups.get(norm(p["name"]), 1)
        p["joined"] = min(joined.get(norm(p["name"]), p["since"]), p["since"])
    if pool_now is not None:
        current = set(parse_pool(pool_now)) | {norm(p["name"]) for p in players}
        gone = {d["name"] for d in dropouts if norm(d["name"]) not in current}
        dropouts = [d for d in dropouts if norm(d["name"]) in current]
        if gone:
            log(f"  {country}: hiding {len(gone)} player(s) no longer in the pool")
    return dropouts

def nation_history_inputs(country, group_dir, squad_now, pool_now, today):
    rel = f"{NATIONS_DIR}/{group_dir}/{country}/{country}.txt"
    texts = history_texts(ROOT, rel, nation_file_paths(country, ".txt"))
    pool_rel = f"{NATIONS_DIR}/{group_dir}/{country}/{country}_players.txt"
    pool_texts = ([(d, clean_pool_text(t)) for d, t in history_texts(
        ROOT, pool_rel, nation_file_paths(country, "_players.txt"))]
                  if pool_now is not None else [])
    renames = detect_renames(texts, pool_texts, squad_now, pool_now, today)
    if renames:
        log(f"  {country}: treating renames as one player: "
            + ", ".join(f"{o} -> {n}" for o, n in renames.items()))
        texts = [(d, apply_renames(t, renames)) for d, t in texts]
        pool_texts = [(d, apply_renames(t, renames)) for d, t in pool_texts]
    pool_texts, fixed = backfill_card_fixes(pool_texts, pool_now)
    if fixed:
        log(f"  {country}: card-type corrections carried back: {', '.join(fixed)}")
    return texts, pool_texts

def refresh_history():
    squads = json.load(open(SQUADS_PATH))
    countries = squads["countries"]
    pool_data = json.load(open(PLAYERS_PATH))["countries"]
    group_dirs = {group: group_dir for group_dir, group in GROUPS}
    today = datetime.fromisoformat(squads["updated"][:10]).date()
    histories = {}
    for country in countries:
        c, group_dir = country["id"], group_dirs[country["group"]]
        rel = f"{NATIONS_DIR}/{group_dir}/{c}/{c}.txt"
        pool_rel = f"{NATIONS_DIR}/{group_dir}/{c}/{c}_players.txt"
        squad_path = os.path.join(ROOT, rel)
        squad_now = open(squad_path).read() if os.path.exists(squad_path) else ""
        pool_path = os.path.join(ROOT, pool_rel)
        pool_now = clean_pool_text(open(pool_path).read()) if os.path.exists(pool_path) else None
        texts, pool_texts = nation_history_inputs(c, group_dir, squad_now, pool_now, today)
        raw_players = _parse_players(squad_now)
        published = country["players"]
        identity = lambda p: (p["name"], p["pos"], p["squad"], p["section"],
                              p["slot"], p["number"], p["rating"])
        if [identity(p) for p in raw_players] != [identity(p) for p in published]:
            raise ValueError(f"{c}: published squads differ from current local squad file")
        dropouts = apply_player_history(c, raw_players, texts, pool_texts, pool_now, today)
        for current, rebuilt in zip(published, raw_players):
            for field in ("since", "days", "tenureRank", "callups", "joined"):
                current[field] = rebuilt[field]
        old_drops = {norm(d["name"]): d for d in country["dropouts"]}
        pool_meta = {norm(p["name"]): p for p in pool_data.get(c, [])}
        for drop in dropouts:
            source = old_drops.get(norm(drop["name"])) or pool_meta.get(norm(drop["name"])) or {}
            drop["img"], drop["tm"] = source.get("img"), source.get("tm")
        country["dropouts"] = dropouts
        histories[c] = card_history(texts, pool_texts, squad_now, pool_now, today)
    json.dump(squads, open(SQUADS_PATH, "w"), ensure_ascii=False, indent=1)
    json.dump({"updated": squads["updated"],
               "countries": histories}, open(HISTORY_PATH, "w"),
              ensure_ascii=False, separators=(",", ":"))
    log(f"Refreshed squads.json and history.json: {len(histories)} nations.")

def build():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(SQUADS_PATH), exist_ok=True)
    cache = load_cache()
    imgcache.merge_legacy(imgcache.load(), cache)
    fm_cache, tm_cache = cache["fotmob"], cache["transfermarkt"]
    overrides = json.load(open(OVERRIDES_PATH)) if os.path.exists(OVERRIDES_PATH) else {}

    prev_ids = set()
    if os.path.exists(SQUADS_PATH):
        try:
            prev_ids = {c["id"] for c in json.load(open(SQUADS_PATH)).get("countries", [])}
        except Exception:
            pass

    game_data, card_types = load_game_data(os.path.join(ROOT, "pes.db"))
    today = datetime.now(timezone.utc).date()

    out_countries, all_players, extras, pools, histories = [], [], [], {}, {}
    for group_dir, group in GROUPS:
        base = os.path.join(ROOT, NATIONS_DIR, group_dir)
        if not os.path.isdir(base):
            continue
        for c in sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))):
            rel = f"{NATIONS_DIR}/{group_dir}/{c}/{c}.txt"
            path = os.path.join(ROOT, rel)
            pool_rel = f"{NATIONS_DIR}/{group_dir}/{c}/{c}_players.txt"
            pool_path = os.path.join(ROOT, pool_rel)
            if not os.path.exists(path) and not (group_dir == "reserve" and os.path.isfile(pool_path)):
                continue
            squad_now = open(path).read() if os.path.exists(path) else ""
            players = _parse_players(squad_now)
            pool_now = clean_pool_text(open(pool_path).read()) if os.path.exists(pool_path) else None
            texts, pool_texts = nation_history_inputs(c, group_dir, squad_now, pool_now, today)
            ov = {norm(k): v for k, v in (overrides.get(c) or {}).items()
                  if not str(k).startswith("_")}
            for p in players:
                p["fm_id"] = fm_cache.get(f"{c}|{norm(p['name'])}")
                p["tm_id"] = find_tm_id(game_data.get(c, []), p, ov.get(norm(p["name"])))
                p["card_type"] = card_types.get((c, p["tm_id"], p["pos"])) or "Standard"
            dropouts = apply_player_history(c, players, texts, pool_texts, pool_now, today)
            pool = parse_pool(pool_now) if pool_now is not None else {}
            for d in dropouts:
                d["tm_id"] = find_tm_id(game_data.get(c, []), d, ov.get(norm(d["name"])))
            for key, entry in pool.items():
                best = entry["rows"][0]
                entry["tm_id"] = find_tm_id(game_data.get(c, []),
                                            {"name": entry["name"], "pos": best[0], "rating": best[1]},
                                            ov.get(key))
            pools[c] = list(pool.values())
            histories[c] = card_history(
                texts, pool_texts, squad_now, pool_now, today)
            flag = flag_for(c)
            if not flag:
                log(f"  WARNING: no flag mapping for '{c}' — add it to "
                    f"ISO2 in efootball_build.py (flag will be blank).")
            out_countries.append({
        "id": c, "name": display_name(c), "flag": flag, "group": group,
                "players": players, "dropouts": dropouts,
            })
            all_players.extend((c, p) for p in players)
            extras.extend((c, {**d, "days": -1}) for d in dropouts)
            extras.extend((c, {"name": e["name"], "tm_id": e["tm_id"], "days": -1})
                          for e in pools[c])
            log(f"  {group_dir}/{c}: {len(players)} players")

    out_countries.sort(key=lambda c: c["name"].lower())

    curr_ids = {c["id"] for c in out_countries}
    if prev_ids:
        added = sorted(curr_ids - prev_ids)
        removed = sorted(prev_ids - curr_ids)
        if added:
            log(f"Nations added: {', '.join(added)}")
        if removed:
            log(f"Nations removed: {', '.join(removed)}")
        if not added and not removed:
            log("Nations unchanged.")

    _resolve_fotmob(all_players, cache)
    _backfill_transfermarkt(all_players + extras, cache)

    def photo(tm_id):
        return tm_cache.get(tm_id) if tm_id else None

    def tm_link(tm_id):
        return TM_LINK.format(id=tm_id) if tm_id else None

    for c in out_countries:
        for p in c["players"]:
            tm = tm_cache.get(p["tm_id"]) if p["tm_id"] else None
            if tm:
                p["img"] = tm
            elif p["tm_id"]:
                p["img"] = None
            elif p["fm_id"]:
                p["img"] = FOTMOB_IMG.format(id=p["fm_id"])
            else:
                p["img"] = None
            if p["tm_id"]:
                p["tm"] = TM_LINK.format(id=p["tm_id"])
            p.pop("fm_id", None); p.pop("tm_id", None); p.pop("row", None)
        for d in c["dropouts"]:
            d["img"], d["tm"] = photo(d["tm_id"]), tm_link(d.pop("tm_id"))

    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source": REPO_URL,
        "countries": out_countries,
    }
    json.dump(out, open(SQUADS_PATH, "w"), ensure_ascii=False, indent=1)
    json.dump({
        "updated": out["updated"],
        "countries": {c: [{"name": e["name"], "recent": e["recent"], "rows": e["rows"],
                           "img": photo(e["tm_id"]), "tm": tm_link(e["tm_id"])}
                          for e in pool] for c, pool in pools.items()},
    }, open(PLAYERS_PATH, "w"), ensure_ascii=False, separators=(",", ":"))
    json.dump({"updated": out["updated"], "countries": histories},
              open(HISTORY_PATH, "w"), ensure_ascii=False, separators=(",", ":"))
    save_cache(cache)

    have = sum(1 for c in out_countries for p in c["players"] if p["img"])
    tot = sum(len(c["players"]) for c in out_countries)
    log(f"Wrote squads.json: {len(out_countries)} nations, {have}/{tot} photos "
        f"({sum(1 for v in tm_cache.values() if v)} via Transfermarkt backfill).")

def _resolve_fotmob(all_players, cache):
    fm_cache = cache["fotmob"]
    todo = [(c, p) for c, p in all_players if not p["fm_id"] and not p["tm_id"]]
    if not todo:
        log("Fotmob: nothing to look up.")
        return
    log(f"Fotmob: looking up {len(todo)} player(s) ...")
    for i, (c, p) in enumerate(todo, 1):
        pid = fotmob_lookup(p["name"])
        fm_cache[f"{c}|{norm(p['name'])}"] = pid
        p["fm_id"] = pid
        if i % 25 == 0:
            save_cache(cache)
            log(f"  ... {i}/{len(todo)}")
        time.sleep(0.15)
    save_cache(cache)

def _backfill_transfermarkt(all_players, cache):
    tm_cache = cache["transfermarkt"]
    tm_null = cache.setdefault("tm_null", {})
    tm_err = cache.setdefault("tm_err", {})
    pending = {}
    for c, p in all_players:
        tid = p["tm_id"]
        if not tid or tm_cache.get(tid):
            continue
        if tm_null.get(tid, 0) >= TM_NULL_LIMIT or tm_err.get(tid, 0) >= TM_ERROR_LIMIT:
            continue
        if tid not in pending or p["days"] > pending[tid][0]:
            pending[tid] = (p["days"], p["name"])
    queue = sorted(pending.items(), key=lambda kv: -kv[1][0])[:TM_DAILY_LIMIT]
    if not queue:
        log("Transfermarkt: nothing to backfill.")
        return
    log(f"Transfermarkt: resolving {len(queue)} photo(s) (limit {TM_DAILY_LIMIT}).")
    blocked = 0
    for tid, (days, name) in queue:
        url = None
        was_blocked = False
        for attempt in range(TM_BLOCKED_RETRIES + 1):
            try:
                url = tmfetch.resolve_portrait(tid)
                blocked = 0
                break
            except tmfetch.Blocked as e:
                if attempt < TM_BLOCKED_RETRIES:
                    log(f"  blocked {name} (#{tid}) — waiting {TM_BLOCKED_WAIT:.0f}s "
                        f"(retry {attempt + 1}/{TM_BLOCKED_RETRIES})")
                    time.sleep(TM_BLOCKED_WAIT)
                    continue
                blocked += 1
                was_blocked = True
                log(f"  blocked {name} (#{tid}): {e}")
                if blocked >= TM_BLOCK_ABORT:
                    log(f"Transfermarkt: still blocked after retries ({blocked} in a "
                        f"row) — stopping early, no retry counters touched.")
                    break
                break
            except Exception as e:
                n = tm_err.get(tid, 0) + 1
                tm_err[tid] = n
                if n >= TM_ERROR_LIMIT:
                    log(f"  fail {name} (#{tid}): {e} — giving up after {n} error(s)")
                else:
                    log(f"  fail {name} (#{tid}): {e} — attempt {n}/{TM_ERROR_LIMIT}, will retry")
                url = "error"
                break
        if blocked >= TM_BLOCK_ABORT:
            break
        if was_blocked:
            continue
        if url == "error":
            continue
        if url:
            tm_cache[tid] = url
            tm_null.pop(tid, None)
            tm_err.pop(tid, None)
            log(f"  ok   {name} (#{tid}, {days}d)")
        else:
            n = tm_null.get(tid, 0) + 1
            tm_null[tid] = n
            if n >= TM_NULL_LIMIT:
                log(f"  null {name} (#{tid}) — giving up after {n} null result(s)")
            else:
                log(f"  null {name} (#{tid}) — attempt {n}/{TM_NULL_LIMIT}, will retry")
    if tmfetch.strategy_used():
        log(f"Transfermarkt: reachable via the '{tmfetch.strategy_used()}' strategy.")
    save_cache(cache)

if __name__ == "__main__":
    if sys.argv[1:] == ["--history-only"]:
        refresh_history()
    else:
        build()
