#!/usr/bin/env python3
"""Shared Transfermarkt fetch layer for the eFootball, WC26 and league builders.

Transfermarkt refuses datacenter IPs -- GitHub Actions runners in particular --
without ever saying so: a 2.4KB challenge page under HTTP 200, or a 202 with no
body at all, depending on the client. The builders used to read that as "this
player has no portrait": they bumped tm_null and, after three strikes,
blacklisted the id forever. Through late July 2026 that quietly burned 239 ids
whose photos exist and froze the shared cache at 909 entries while every daily
run reported 23/23 "null".

So resolution here is three-way, never two-way:

    a URL   -- portrait found
    None    -- the page really is a player profile and says there's no portrait
    Blocked -- anything else; retry later, do NOT record a verdict about the id

"Is a real page" is a positive test (the page has to mention the id we asked
for, or the search form we submitted), because a block page can plausibly carry
a default portrait of its own and must never be mistaken for a null.

Requests walk an ordered list of STRATEGIES: the plain hosts, r.jina.ai, and --
where the workflow provides one via TM_SOCKS_PROXY -- a Cloudflare WARP proxy,
which is the only route a GitHub runner has (see SOCKS_PROXY below). The first
strategy to return a real page wins and is remembered for the rest of the
process, so a blocked host pays the failover cost once rather than on every
player. Run this file directly to print which strategies work from here:

    python3 scripts/tmfetch.py
"""

import gzip
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TM_IMG = "https://img.a.transfermarkt.technology/portrait/big/{id}-{ts}.{ext}"
TM_LINK = "https://www.transfermarkt.com/x/profil/spieler/{id}"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# The header set the builders have always sent.
BASIC = {
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# A fuller, more browser-shaped set: Sec-Fetch-*/Sec-CH-* and a Referer, the
# headers a naive scraper omits. It does not get past the runner-IP block --
# nothing header-shaped does -- but it costs nothing and covers the milder case
# of a host that only objects to a bare request.
BROWSER = dict(BASIC, **{
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://www.google.com/",
    "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
})

READER = "https://r.jina.ai/"
PROFILE_PATH = "/x/profil/spieler/{id}"
SEARCH_PATH = "/schnellsuche/ergebnis/schnellsuche?query={q}"


def _reader_headers():
    """r.jina.ai is free but rate-limits hard by client IP. A key (set the
    JINA_API_KEY secret) lifts that; without one this strategy is best treated
    as a last resort that may answer 403 under any real load."""
    h = {"User-Agent": UA, "Accept": "text/plain"}
    key = os.environ.get("JINA_API_KEY")
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


STRATEGIES = [
    {"name": "us", "host": "https://www.transfermarkt.us", "headers": BASIC},
    {"name": "com", "host": "https://www.transfermarkt.com", "headers": BROWSER},
    {"name": "de", "host": "https://www.transfermarkt.de", "headers": BROWSER},
    {"name": "reader", "host": "https://www.transfermarkt.com", "via": READER,
     "headers": _reader_headers()},
]

# A GitHub runner cannot read Transfermarkt at all: every one of its ~30
# regional domains answers an Actions IP with HTTP 202 and an empty body, and
# r.jina.ai refuses keyless requests from those IPs (probed 2026-08-03). The
# only way through is to leave on a different network, so the workflows run
# Cloudflare WARP as a local SOCKS proxy and point TM_SOCKS_PROXY at it. Where
# it's set we try it first, since it's the one route known to work there.
SOCKS_PROXY = os.environ.get("TM_SOCKS_PROXY")
if SOCKS_PROXY:
    STRATEGIES.insert(0, {"name": "warp", "host": "https://www.transfermarkt.us",
                          "headers": BASIC, "proxy": SOCKS_PROXY})

TIMEOUT = int(os.environ.get("TM_TIMEOUT", "30"))
# Transfermarkt starts returning HTTP 403 after bursts; spacing requests avoids
# a temporary IP ban that looks like "every strategy failed".
_MIN_INTERVAL = float(os.environ.get("TM_MIN_INTERVAL", "2.0"))
_last_fetch = 0.0

# Index into STRATEGIES of the last one that returned a real page. Sticky for
# the life of the process so we don't re-pay a failed strategy per player.
_current = 0
_used = None


class Blocked(Exception):
    """No strategy returned a page we can read. Says nothing about the player."""


def strategy_used():
    """Name of the strategy that last answered, for the builders' logs."""
    return _used


def _throttle():
    global _last_fetch
    wait = _MIN_INTERVAL - (time.monotonic() - _last_fetch)
    if wait > 0:
        time.sleep(wait)
    _last_fetch = time.monotonic()


def _fetch_via_proxy(url, strategy):
    """Fetch through a SOCKS proxy. urllib can't speak SOCKS, and curl ships on
    every runner and on macOS, so shell out rather than add a dependency.

    -L matters: Transfermarkt 301s /x/profil/spieler/<id> to the canonical slug
    URL, so without it every response is an empty redirect body.
    """
    cmd = ["curl", "-sSL", "--max-time", str(TIMEOUT),
           "--proxy", f"socks5h://{strategy['proxy']}"]
    for k, v in strategy["headers"].items():
        cmd += ["-H", f"{k}: {v}"]
    cmd += ["-w", "\n%{http_code}", url]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT + 10)
    if p.returncode != 0:
        raise OSError(f"curl exit {p.returncode}: {p.stderr.strip()[:120]}")
    body, _, code = p.stdout.rpartition("\n")
    if code != "200":
        raise urllib.error.HTTPError(url, int(code or 0), "via proxy", None, None)
    return body


def _fetch(strategy, path):
    _throttle()
    url = strategy["host"] + path
    if strategy.get("via"):
        url = strategy["via"] + url
    if strategy.get("proxy"):
        return _fetch_via_proxy(url, strategy)
    req = urllib.request.Request(url, headers=strategy["headers"])
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        body = r.read()
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return body.decode("utf-8", "replace")


def _attempt(path, classify):
    """Walk the strategies from the sticky winner onward, handing each response
    to classify(). classify returns None to mean "this page is not a readable
    Transfermarkt page, try the next strategy"; anything else it returns
    (including the sentinel for a genuine negative) is the answer.

    An HTTP error is never read as an answer about the player, 404 included: a
    host that is fending us off can reply with whatever status it likes, so the
    only thing an error tells us is that this strategy didn't work."""
    global _current, _used
    order = list(range(_current, len(STRATEGIES))) + list(range(0, _current))
    problems = []
    for i in order:
        s = STRATEGIES[i]
        try:
            html = _fetch(s, path)
        except urllib.error.HTTPError as e:
            problems.append(f"{s['name']}:HTTP{e.code}")
            continue
        except Exception as e:
            problems.append(f"{s['name']}:{type(e).__name__}")
            continue
        verdict = classify(html)
        if verdict is None:
            problems.append(f"{s['name']}:unreadable({len(html)}b)")
            continue
        _current, _used = i, s["name"]
        return verdict
    raise Blocked(", ".join(problems))


# Portraits are keyed <id>-<timestamp>; accept jpg/jpeg/png in any case and any
# of big/header/medium, ignore the ?lm= cache-buster, and normalize to the
# canonical big/<id>-<ts>.<ext>. Older (often retired) players instead use a
# legacy "s_<id>_..." filename. The image host is case-sensitive: a portrait
# uploaded as .JPG 404s when requested as .jpg, so keep the extension verbatim.
def _portrait(html, tid):
    m = re.search(rf"portrait/(?:big|header|medium)/{tid}-(\d+)\.(jpe?g|png)", html, re.I)
    if m:
        return TM_IMG.format(id=tid, ts=m.group(1), ext=m.group(2))
    m = re.search(rf"portrait/(?:big|header|medium)/(s_{tid}_[\d_]+)\.(jpe?g|png)", html, re.I)
    if m:
        return ("https://img.a.transfermarkt.technology/portrait/big/"
                f"{m.group(1)}.{m.group(2)}")
    return None


NO_PHOTO_RE = re.compile(r"portrait/(?:big|header|medium)/default\.jpg", re.I)

# Every page on the site embeds the quick-search form, so this is a decent
# "we really did reach Transfermarkt" test -- true of a profile, true of the
# landing page an unknown id redirects to, false of a block page.
SITE_MARKER = "schnellsuche"

# Distinct object returned for "real page, genuinely no portrait", so _attempt
# can tell it apart from "unreadable page" (both would otherwise be None).
_NO_PHOTO = object()


def _portrait_classifier(tid):
    """Sort a response into portrait / genuinely-no-portrait / can't-tell.

    Verified against live Transfermarkt (2026-08): a profile echoes
    "spieler/<id>" back in its canonical link and tabs, an unknown id lands on
    a generic page that does not, and both carry the site chrome.
    """
    def classify(html):
        url = _portrait(html, tid)
        if url:
            return url
        ours = f"spieler/{tid}" in html
        if ours:
            # Our player's profile. Only a default portrait proves "no photo";
            # a profile with neither means markup we don't recognize, which is
            # worth retrying rather than blacklisting the id over.
            return _NO_PHOTO if NO_PHOTO_RE.search(html) else None
        if SITE_MARKER in html.lower():
            # Transfermarkt's own page, but not this player's -- the id no
            # longer resolves, so there is no photo to wait for.
            return _NO_PHOTO
        return None
    return classify


def resolve_portrait(tid):
    """Portrait URL for a Transfermarkt player id, or None if there is no photo
    to be had -- either the profile says so, or the id no longer resolves.
    Raises Blocked if no strategy managed to read a Transfermarkt page."""
    tid = str(tid)
    got = _attempt(PROFILE_PATH.format(id=tid), _portrait_classifier(tid))
    return None if got is _NO_PHOTO else got


_MISS = object()


def search_player(name):
    """Transfermarkt id for a player name, or None if the search genuinely
    found nobody. Raises Blocked if no strategy returned a search page."""
    path = SEARCH_PATH.format(q=urllib.parse.quote_plus(name))

    def classify(html):
        m = re.search(r"profil/spieler/(\d+)", html)
        if m:
            return m.group(1)
        # A real results page always echoes the quick-search form back, so its
        # absence means we never reached the search at all.
        if SITE_MARKER in html.lower():
            return _MISS
        return None

    got = _attempt(path, classify)
    return None if got is _MISS else got


def _probe_one(strategy, tid):
    """Test a single strategy in isolation, bypassing the failover in _attempt."""
    try:
        html = _fetch(strategy, PROFILE_PATH.format(id=tid))
    except urllib.error.HTTPError as e:
        return f"HTTP{e.code}"
    except Exception as e:
        return type(e).__name__
    verdict = _portrait_classifier(tid)(html)
    if verdict is None:
        return f"unreadable({len(html)}b)"
    return "NULL" if verdict is _NO_PHOTO else "PORTRAIT"


def probe(argv=()):
    """Report, per strategy, whether it can read Transfermarkt from this host.
    Run in CI to find out which strategy the runners can actually use."""
    has_photo = argv[0] if len(argv) > 0 else "2219"       # Philipp Lahm
    no_photo = argv[1] if len(argv) > 1 else "1146046"     # profile, no portrait
    print(f"probe: expecting PORTRAIT for #{has_photo}, NULL for #{no_photo}\n")
    width = max(len(s["name"]) for s in STRATEGIES)
    for s in STRATEGIES:
        photo = _probe_one(s, has_photo)
        null = _probe_one(s, no_photo)
        verdict = "USABLE" if (photo == "PORTRAIT" and null == "NULL") else "no"
        print(f"  {s['name']:<{width}}  photo={photo:<18s} null={null:<18s} {verdict}")
    print("\nA strategy is usable only when it reports both PORTRAIT and NULL:\n"
          "reading a portrait but not the null case means block pages would be\n"
          "misfiled as 'player has no photo', which is the bug this guards.")


if __name__ == "__main__":
    probe(sys.argv[1:])
