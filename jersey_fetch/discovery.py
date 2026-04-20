import re
import urllib.parse

import requests
from bs4 import BeautifulSoup

from jersey_fetch.constants import HTTP_BROWSER_UA
from jersey_fetch.names import normalize_name, unwrap_duckduckgo_link
from jersey_fetch.transfermarkt import html_looks_like_waf_challenge


def score_transfermarkt_candidate(player_name, link, text):
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
    text_norm = normalize_name(text or "")
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
    ln = normalize_name(label or "")
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
            sn = c["mainsnak"]
            if sn.get("snaktype") != "value":
                continue
            dv = sn["datavalue"]["value"]
            if isinstance(dv, str):
                m = re.search(r"(\d{3,})", dv)
                if m:
                    return m.group(1)
        except (KeyError, TypeError, ValueError):
            continue
    return None


def wikidata_transfermarkt_player_id(player):
    try:
        r = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": player,
                "language": "en",
                "format": "json",
                "limit": 12,
            },
            headers={"User-Agent": HTTP_BROWSER_UA},
            timeout=25,
        )
        r.raise_for_status()
        hits = r.json().get("search") or []
        if not hits:
            return None
        ids = [h["id"] for h in hits][:10]
        r2 = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbgetentities",
                "ids": "|".join(ids),
                "format": "json",
                "props": "claims|labels",
                "languages": "en",
            },
            headers={"User-Agent": HTTP_BROWSER_UA},
            timeout=25,
        )
        r2.raise_for_status()
        entities = r2.json().get("entities") or {}
    except (requests.RequestException, KeyError, ValueError):
        return None
    best = None
    for rank, eid in enumerate(ids):
        blob = entities.get(eid)
        if not blob:
            continue
        label = (blob.get("labels") or {}).get("en", {}).get("value") or ""
        ls = _wikidata_label_match_score(player, label)
        min_ls = 55 if len(normalize_name(player).split()) <= 1 else 40
        if ls < min_ls:
            continue
        claims = (blob.get("claims") or {}).get("P2446")
        pid = _wikidata_p2446_transfermarkt_id(claims)
        if not pid:
            continue
        key = (ls, -rank)
        if best is None or key > best[:2]:
            best = (ls, -rank, pid)
    return best[2] if best else None


def duckduckgo_html_transfermarkt_player_id(player):
    queries = [
        f"{player} transfermarkt",
        f'"{player}" transfermarkt',
        f"{player} site:transfermarkt.com",
    ]
    headers = {"User-Agent": HTTP_BROWSER_UA, "Referer": "https://html.duckduckgo.com/"}
    best = None
    seen = set()
    for q in queries:
        try:
            resp = requests.post(
                "https://html.duckduckgo.com/html/",
                data={"q": q, "b": ""},
                headers=headers,
                timeout=25,
            )
            if resp.status_code != 200 or "result__a" not in resp.text:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.select("a.result__a"):
                href = a.get("href")
                text = a.get_text(" ", strip=True)
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


async def get_transfermarkt_id(player, page, country_label=None, position_hint=None):
    wid = wikidata_transfermarkt_player_id(player)
    if wid:
        print(f"  Found ID for {player}: {wid} (Wikidata)")
        return wid
    ddg_html = duckduckgo_html_transfermarkt_player_id(player)
    if ddg_html:
        print(f"  Found ID for {player}: {ddg_html} (DuckDuckGo HTML)")
        return ddg_html
    name_normalized = normalize_name(player)
    query_parts = [name_normalized]
    if position_hint:
        query_parts.append(normalize_name(position_hint))
    if country_label:
        query_parts.append(normalize_name(country_label))
    search_query = " ".join(part for part in query_parts if part)
    search_url = f"https://www.transfermarkt.com/suche/spieler?query={urllib.parse.quote(search_query)}"
    try:
        await page.goto(search_url)
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(1500)
        if not html_looks_like_waf_challenge(await page.content()):
            links = await page.query_selector_all('a[href*="/spieler/"]')
            for link in links[:15]:
                href = await link.get_attribute("href")
                if not href:
                    continue
                m = re.search(r"/spieler/(\d+)", href)
                if m:
                    pid = m.group(1)
                    print(f"  Found ID for {player}: {pid} (Transfermarkt search)")
                    return pid
    except Exception as e:
        print(f"  Transfermarkt search failed for {player}: {e}")
    queries = [
        f"{player} transfermarkt",
        f'"{player}" transfermarkt',
        f"{player} transfermarkt player",
        f"{player} transfermarkt spieler",
    ]
    print(f"Searching ID for {player} via browser (DuckDuckGo)...")
    best = None
    seen_pids = set()
    ddg_urls = ["https://lite.duckduckgo.com/lite/?q={}", "https://duckduckgo.com/?q={}"]
    for raw_query in queries:
        encoded = urllib.parse.quote(raw_query)
        for template in ddg_urls:
            try:
                await page.goto(template.format(encoded))
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(2000)
                selectors = (
                    'a[href*="transfermarkt"][href*="/spieler/"]',
                    'a[data-testid="result-title-a"]',
                    "a.result-link",
                )
                for sel in selectors:
                    results = await page.query_selector_all(sel)
                    for result in results:
                        try:
                            url = await result.get_attribute("href")
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
                for m in re.finditer(
                    r"https?://www\.transfermarkt\.[a-z.]+/([a-z0-9-]+)/profil/spieler/(\d+)",
                    html,
                    re.I,
                ):
                    slug, pid = (m.group(1), m.group(2))
                    if pid in seen_pids:
                        continue
                    link = f"https://www.transfermarkt.com/{slug}/profil/spieler/{pid}"
                    scored = score_transfermarkt_candidate(player, link, slug.replace("-", " "))
                    if not scored:
                        continue
                    score, _ = scored
                    seen_pids.add(pid)
                    if best is None or score > best[0]:
                        best = (score, pid)
                if best is not None and best[0] >= 100:
                    break
            except Exception as e:
                print(f"  DuckDuckGo page failed for {player}: {e}")
                continue
        if best is not None and best[0] >= 100:
            break
    if best is not None:
        print(f"  Found ID for {player}: {best[1]} (DuckDuckGo)")
        return best[1]
    print(f"  ID not found for {player} (Wikidata, DuckDuckGo, Transfermarkt)")
    return None
