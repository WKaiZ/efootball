#!/usr/bin/env python3

import html
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

SEARCH_URL = "https://pesdb.net/efootball/players/"
NATIONS_URL = "https://pesdb.net/search-options.php?catalog=nationalities"
CARD_IMG = "https://efimg.com/efootballhub22/images/player_cards/{id}_l.png"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
POSITIONS = ["GK", "CB", "LB", "RB", "DMF", "CMF", "LMF", "RMF", "AMF", "LWF", "RWF", "SS", "CF"]
MAX_PAGES = 6
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_MAX_WAIT = 180

TYPE_LABELS = {
    "standard": "Standard",
    "epic": "Epic",
    "big time": "BigTime",
    "show time": "Showtime",
    "highlight": "Highlight",
    "trending": "Trending",
    "legendary": "Legendary",
    "strike arena": "StrikeArena",
}

WANTED = {
    "Standard": {"Standard"},
    "Epic": {"Epic", "BigTime"},
    "BigTime": {"Epic", "BigTime"},
    "Showtime": {"Showtime"},
    "Highlight": {"Highlight", "Trending"},
}
RATED = {"Standard", "Highlight"}

NATION_LABELS = {
    "central-african-republic": "Central African Rep.",
    "dpr-korea": "Korea DPR",
    "hong-kong": "Hong Kong, China",
    "macau-china": "Macau",
    "st-lucia": "Saint Lucia",
    "turks-and-caicos-islands": "Turks and Caicos Is.",
    "usa": "United States",
}
PARTICLES = {"al", "el", "de", "da", "do", "dos", "das", "del", "di", "van", "von", "der", "den",
             "bin", "ben", "ibn", "abu", "le", "la"}
FOLDS = (("dzh", "j"), ("zh", "j"), ("kh", "h"), ("ch", "c"), ("sh", "s"), ("ph", "f"),
         ("x", "h"), ("y", "i"), ("w", "v"))
_nations = None

_CARD_RE = re.compile(r'<article class="efootball-result-card">(.*?)</article>', re.S)
_ID_RE = re.compile(r'href="/efootball/players/[^"]*?-(\d+)"')
_TYPE_RE = re.compile(r'class="card-type">([^<]*)<')
_ALT_RE = re.compile(r'alt="(?P<name>[^"]*?) — (?P<pos>[A-Z]+), OVR (?P<ovr>\d+), MAX (?P<max>\d+)"')


class Unavailable(Exception):
    pass


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").lower()
    s = s.translate(str.maketrans({
        "æ": "ae", "ø": "o", "œ": "oe", "ß": "ss",
        "ł": "l", "đ": "d", "ð": "d", "þ": "th",
    }))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"(?<=\w)['\u2019\u02bc`](?=\w)", "", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _phonetic_token(token):
    """A conservative key for common vowel and consonant spelling variants."""
    token = token.replace("y", "i")
    token = re.sub(r"[aeiou]", "a", token)
    return re.sub(r"(.)\1+", r"\1", token)


def card_group(card_type):
    return "EpicBigTime" if card_type in ("Epic", "BigTime") else card_type


def card_image(card_id):
    return CARD_IMG.format(id=card_id)


def base_id(card_id):
    return int(card_id) & 0xFFFFFF


def _fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == RATE_LIMIT_RETRIES:
                raise Unavailable(f"HTTP {e.code}") from e
            try:
                wait = float(e.headers.get("Retry-After") or 60)
            except ValueError:
                wait = 60
            time.sleep(min(wait, RATE_LIMIT_MAX_WAIT) + 1)
        except Exception as e:
            if attempt == RATE_LIMIT_RETRIES:
                raise Unavailable(f"{type(e).__name__}: {e}") from e
            time.sleep(10 * (attempt + 1))


def parse_results(page):
    cards = []
    for block in _CARD_RE.findall(page):
        cid, ctype, alt = _ID_RE.search(block), _TYPE_RE.search(block), _ALT_RE.search(block)
        if not (cid and ctype and alt):
            continue
        label = html.unescape(ctype[1]).strip()
        cards.append({
            "id": cid[1],
            "name": html.unescape(alt["name"]).strip(),
            "type": TYPE_LABELS.get(label.lower(), label),
            "pos": alt["pos"],
            "ovr": int(alt["ovr"]),
            "max": int(alt["max"]),
        })
    return cards


def nation_id(country):
    global _nations
    fetched = _nations is None
    if fetched:
        _nations = {norm(n["label"]): n["id"] for n in json.loads(_fetch(NATIONS_URL))}
    return _nations.get(norm(NATION_LABELS.get(country, country.replace("-", " ")))), fetched


def search(name, pos, page=1, as_of=None, nation=None, ovr=None):
    params = [("name", name)] if name else []
    if pos:
        params.append(("pos[]", str(POSITIONS.index(pos))))
    if nation:
        params.append(("nationality_id", nation))
    if ovr is not None:
        params += [("overall_rating[min]", str(ovr)), ("overall_rating[max]", str(ovr))]
    params += [("sort", "time_added"), ("order", "desc")]
    if as_of:
        params.append(("time_added[max]", as_of))
    if page > 1:
        params.append(("page", str(page)))
    text = _fetch(f"{SEARCH_URL}?{urllib.parse.urlencode(params)}")
    if "efootball-result-grid" not in text and "efootball-result-card" not in text:
        raise Unavailable("unexpected page layout")
    has_next = 'rel="next"' in text
    return parse_results(text), has_next


def _edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _token_match(a, b):
    if a == b:
        return True
    if len(a) == 1 or len(b) == 1:
        return a[0] == b[0]
    short, long = sorted((a, b), key=len)
    if len(short) >= 3 and long.startswith(short):
        return True
    limit = 2 if len(short) >= 8 else 1 if len(short) >= 4 else 0
    return limit > 0 and _edit_distance(a, b) <= limit


def _tokens_match(short, long):
    used = set()
    for tok in short:
        hit = next((i for i, t in enumerate(long) if i not in used and _token_match(tok, t)), None)
        if hit is None:
            return False
        used.add(hit)
    return True


def name_score(want, got):
    a, b = norm(want).split(), norm(got).split()
    if not a or not b:
        return 0
    if a == b:
        return 3
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if _tokens_match(short, long):
        return 2
    if len(a) == len(b) == 2 and a[1] == b[1] and a[0][0] == b[0][0]:
        return 2

    # Transliteration often changes vowels or doubles a consonant (for example,
    # Ateya/Attia). Use this weaker match only when the complete token sequence
    # agrees phonetically; pick() requires it to identify one player uniquely.
    phonetic_a = [_phonetic_token(token) for token in a]
    phonetic_b = [_phonetic_token(token) for token in b]
    if len(phonetic_a) == len(phonetic_b) and phonetic_a == phonetic_b:
        return 1
    return 0


def _rating_value(card):
    return card["max"] if card["type"] == "Highlight" else card["ovr"]


def _rating_gap(card, rating):
    gap = abs(_rating_value(card) - rating)
    if card["type"] == "Trending":
        gap = min(gap, abs(card["max"] - rating))
    return gap


def _pick_card(cards, card_type, rating, strict):
    if card_type not in RATED or strict == "newest":
        return cards[0] if cards else None
    level = int(float(rating))
    exact = [c for c in cards if _rating_value(c) == level]
    if exact or strict == "exact":
        return exact[0] if exact else None
    near = [c for c in cards if abs(_rating_value(c) - level) <= 1]
    if strict == "near" and not near:
        return None
    best = min(near or cards, key=lambda c: (_rating_gap(c, level), cards.index(c)), default=None)
    return best and {**best, "approx": True}


def pick(cards, name, pos, card_type, rating, strict="exact", allow_phonetic=True):
    wanted = WANTED.get(card_type, {card_type})
    people = {}
    for c in cards:
        if c["pos"] == pos and c["type"] in wanted:
            people.setdefault(base_id(c["id"]), []).append(c)
    scores = (3, 2, 1) if allow_phonetic else (3, 2)
    for score in scores:
        hits = []
        for person_cards in people.values():
            if max(name_score(name, c["name"]) for c in person_cards) != score:
                continue
            card = _pick_card(person_cards, card_type, rating, strict)
            if card:
                hits.append(card)
        if len(hits) == 1:
            return hits[0]
        if hits:
            if score == 1:
                return None
            level = int(float(rating)) if card_type in RATED else None
            if level is None:
                return None
            hits.sort(key=lambda c: _rating_gap(c, level))
            gaps = [_rating_gap(c, level) for c in hits[:2]]
            return hits[0] if gaps[0] < gaps[1] else None
    return None


def _collect(query, name, pos, card_type, rating, delay, requests, exclude, as_of, strict="exact"):
    seen = []
    for page in range(1, MAX_PAGES + 1):
        if requests and delay:
            time.sleep(delay)
        cards, has_next = search(query, pos, page, as_of)
        requests += 1
        seen.extend(c for c in cards if c["id"] not in exclude)
        if not has_next or pick(seen, name, pos, card_type, rating, strict, allow_phonetic=False):
            break
    return seen, requests


def _fold(token):
    for a, b in FOLDS:
        token = token.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", token)


def loose_score(want, got):
    a = [_fold(t) for t in norm(want).split() if t not in PARTICLES]
    b = [_fold(t) for t in norm(got).split() if t not in PARTICLES]
    if not a or not b:
        return 0
    if sorted(a) == sorted(b) or "".join(a) == "".join(b):
        return 3
    shared = sum(1 for t in a if len(t) >= 4 and any(
        t == u or (min(len(t), len(u)) >= 5 and (t.startswith(u) or u.startswith(t))) for u in b))
    return min(shared, 2)


def pick_loose(cards, name, card_type, rating, min_score=1, newest=False):
    wanted = WANTED.get(card_type, {card_type})
    people = {}
    for c in cards:
        if c["type"] in wanted:
            people.setdefault(base_id(c["id"]), []).append(c)
    scored = sorted(((max(loose_score(name, c["name"]) for c in cs), cs) for cs in people.values()),
                    key=lambda x: -x[0])
    if not scored or scored[0][0] < min_score or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return None
    return _pick_card(scored[0][1], card_type, rating, "newest" if newest else "any")


def _resolve_by_nation(name, pos, card_type, rating, delay, exclude, as_of, requests, nation, newest=False):
    ovr = int(float(rating)) if card_type == "Standard" else None
    stages = [(pos, 1)] + ([(None, 3)] if ovr is not None else [])
    for at, min_score in stages:
        seen = []
        for page in range(1, MAX_PAGES + 1):
            if requests and delay:
                time.sleep(delay)
            cards, has_next = search(None, at, page, as_of, nation=nation, ovr=ovr)
            requests += 1
            seen += [c for c in cards if c["id"] not in exclude]
            if not has_next:
                break
        card = pick_loose(seen, name, card_type, rating, min_score, newest)
        if card:
            return card, requests
    return None, requests


def search_terms(name):
    tokens = norm(name).split()
    terms = [name]
    if len(tokens) > 1:
        terms += [t for t in [tokens[-1]] + tokens[:-1] if len(t) >= 4]
    return list(dict.fromkeys(terms))


def _resolve_at(name, pos, card_type, rating, delay, exclude, as_of, requests, newest=False):
    seen = []
    first = "newest" if newest else "exact"
    for query in search_terms(name):
        found_now, requests = _collect(query, name, pos, card_type, rating, delay, requests, exclude, as_of, first)
        seen += [c for c in found_now if c["id"] not in {s["id"] for s in seen}]
        found = pick(seen, name, pos, card_type, rating, first) or \
            pick(seen, name, pos, card_type, rating, strict="near")
        if found:
            return found, requests
    return pick(seen, name, pos, card_type, rating, strict="any"), requests


def resolve(name, pos, card_type, rating, delay=0.0, exclude=frozenset(), as_of=None, alt_pos=None,
            newest=False, country=None):
    requests = 0
    for at in dict.fromkeys(p for p in (pos, alt_pos) if p in POSITIONS):
        for when in dict.fromkeys((as_of, None)):
            card, requests = _resolve_at(name, at, card_type, rating, delay, exclude, when, requests, newest)
            if card:
                return card, requests
    if not country:
        return None, requests
    if _nations is None and requests and delay:
        time.sleep(delay)
    nation, fetched = nation_id(country)
    requests += fetched
    if not nation:
        return None, requests
    card, requests = _resolve_by_nation(name, pos, card_type, rating, delay, exclude, as_of, requests, nation,
                                        newest)
    return (card and {**card, "approx": True} if card_type != "Standard" else card), requests


if __name__ == "__main__":
    if len(sys.argv) not in (5, 6):
        sys.exit("usage: cardfetch.py NAME POS CARD_TYPE RATING [COUNTRY]")
    card, n = resolve(*sys.argv[1:5], delay=3, country=sys.argv[5] if len(sys.argv) == 6 else None)
    print(card, card_image(card["id"]) if card else None, f"({n} request(s))")
