#!/usr/bin/env python3

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

BASIC = {
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

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

SOCKS_PROXY = os.environ.get("TM_SOCKS_PROXY")
if SOCKS_PROXY:
    STRATEGIES.insert(0, {"name": "warp", "host": "https://www.transfermarkt.us",
                          "headers": BASIC, "proxy": SOCKS_PROXY})

TIMEOUT = int(os.environ.get("TM_TIMEOUT", "30"))
_MIN_INTERVAL = float(os.environ.get("TM_MIN_INTERVAL", "2.0"))
_last_fetch = 0.0

_current = 0
_used = None


class Blocked(Exception):
    pass


def strategy_used():
    return _used


def _throttle():
    global _last_fetch
    wait = _MIN_INTERVAL - (time.monotonic() - _last_fetch)
    if wait > 0:
        time.sleep(wait)
    _last_fetch = time.monotonic()


def _fetch_via_proxy(url, strategy):
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

SITE_MARKER = "schnellsuche"

_NO_PHOTO = object()


def _portrait_classifier(tid):
    def classify(html):
        url = _portrait(html, tid)
        if url:
            return url
        ours = f"spieler/{tid}" in html
        if ours:
            return _NO_PHOTO if NO_PHOTO_RE.search(html) else None
        if SITE_MARKER in html.lower():
            return _NO_PHOTO
        return None
    return classify


def resolve_portrait(tid):
    tid = str(tid)
    got = _attempt(PROFILE_PATH.format(id=tid), _portrait_classifier(tid))
    return None if got is _NO_PHOTO else got


_MISS = object()


def search_player(name):
    path = SEARCH_PATH.format(q=urllib.parse.quote_plus(name))

    def classify(html):
        m = re.search(r"profil/spieler/(\d+)", html)
        if m:
            return m.group(1)
        if SITE_MARKER in html.lower():
            return _MISS
        return None

    got = _attempt(path, classify)
    return None if got is _MISS else got


def _probe_one(strategy, tid):
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
    has_photo = argv[0] if len(argv) > 0 else "2219"
    no_photo = argv[1] if len(argv) > 1 else "1146046"
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
