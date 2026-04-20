import asyncio
import os
import re
import sys

from jersey_fetch.constants import (
    TRANSFERMARKT_PLAYWRIGHT_UA,
    _TRANSFERMARKT_STEALTH_JS,
)

_transfermarkt_waf_hint_printed = False


def html_looks_like_waf_challenge(html: str) -> bool:
    if not html:
        return False
    h = html.lower()
    if "awswaf.com" in h or "token.awswaf.com" in h:
        return True
    if "human verification" in h and "awswaf" in h:
        return True
    if "awswafintegration" in h.replace(" ", "").lower():
        return True
    return False


def maybe_note_transfermarkt_waf_once(html: str) -> None:
    global _transfermarkt_waf_hint_printed
    if not html_looks_like_waf_challenge(html) or _transfermarkt_waf_hint_printed:
        return
    print(
        "  Note: Transfermarkt is showing a bot check (HTML still saved under debug_html/ if needed). "
        "Install curl_cffi (pip install curl_cffi) or set PLAYWRIGHT_BROWSER_CHANNEL=chrome."
    )
    _transfermarkt_waf_hint_printed = True


async def launch_chromium(playwright, *, headless=True, hardened=False):
    launch_args = []
    if hardened:
        launch_args.append("--disable-blink-features=AutomationControlled")
    opts = {"headless": headless}
    if launch_args:
        opts["args"] = launch_args
    channel = os.environ.get("PLAYWRIGHT_BROWSER_CHANNEL", "").strip()
    if channel:
        if channel.lower() == "chromium":
            return await playwright.chromium.launch(**opts)
        try:
            return await playwright.chromium.launch(**opts, channel=channel)
        except Exception:
            return await playwright.chromium.launch(**opts)
    if sys.platform == "win32":
        for ch in ("chrome", "msedge"):
            try:
                return await playwright.chromium.launch(**opts, channel=ch)
            except Exception:
                continue
    return await playwright.chromium.launch(**opts)


def try_transfermarkt_rueckennummern_curl(url: str):
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return None
    try:
        resp = curl_requests.get(
            url,
            impersonate="chrome",
            timeout=60,
            allow_redirects=True,
            headers={
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                "Upgrade-Insecure-Requests": "1",
            },
        )
        if resp.status_code != 200 or not resp.text:
            return None
        if html_looks_like_waf_challenge(resp.text):
            return None
        if "grid-view" not in resp.text and "yw2" not in resp.text:
            return None
        return resp.text
    except Exception:
        return None


async def _transfermarkt_rueckennummern_playwright(playwright, url: str):
    browser = await launch_chromium(playwright, hardened=True)
    context = await browser.new_context(
        user_agent=TRANSFERMARKT_PLAYWRIGHT_UA,
        locale="de-DE",
        timezone_id="Europe/Berlin",
        viewport={"width": 1920, "height": 1080},
        extra_http_headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
        },
    )
    await context.add_init_script(_TRANSFERMARKT_STEALTH_JS)
    page = await context.new_page()
    try:
        await page.goto("https://www.transfermarkt.com/", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(800)
        for selector in [
            'button[title*="Accept"]',
            'button:has-text("Accept all")',
            'button:has-text("Alle akzeptieren")',
            'button:has-text("I agree")',
        ]:
            try:
                if await page.is_visible(selector, timeout=1500):
                    await page.click(selector)
                    break
            except Exception:
                pass
        await page.goto(url, wait_until="domcontentloaded", timeout=120000)
        await page.wait_for_timeout(1500)
        html = await page.content()
        if html_looks_like_waf_challenge(html):
            await page.reload(wait_until="domcontentloaded", timeout=90000)
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


def extract_national_numbers_from_html(html):
    by_number = {}
    entries = []
    section_match = re.search(
        '<div id="yw2" class="grid-view">(.+?)</table>', html, flags=re.DOTALL | re.IGNORECASE
    )
    if not section_match:
        return (by_number, entries)
    section_html = section_match.group(1)
    for row in re.findall("<tr[^>]*>(.+?)</tr>", section_html, flags=re.DOTALL | re.IGNORECASE):
        cells = re.findall("<td[^>]*>(.*?)</td>", row, flags=re.DOTALL | re.IGNORECASE)
        if len(cells) < 3:
            continue
        season_cell = cells[0]
        if len(cells) >= 4:
            raw_club = cells[2]
            raw_num = cells[3]
        else:
            raw_club = cells[1]
            raw_num = cells[2]
        season = re.sub("<.*?>", "", season_cell).strip()
        club_cell = re.sub("<.*?>", "", raw_club).strip()
        num_cell = re.sub("<.*?>", "", raw_num).strip()
        if not club_cell or not num_cell or (not season):
            continue
        m = re.search(r"\b(\d{1,2})\b", num_cell)
        if not m:
            continue
        num = m.group(1)
        club_low = club_cell.strip().lower()
        if re.search(r"\s+b$", club_low):
            continue
        skip_team_markers = (
            "u15",
            "u16",
            "u17",
            "u18",
            "u19",
            "u20",
            "u21",
            "u22",
            "u23",
            "olympic",
            "olympics",
            "olympia",
            "olympiad",
        )
        if any((marker in club_low for marker in skip_team_markers)):
            continue
        by_number.setdefault(num, set()).add(club_cell)
        entries.append({"season": season, "country": club_cell, "number": num})
    return (by_number, entries)
