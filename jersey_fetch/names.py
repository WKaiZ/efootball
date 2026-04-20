import re
import unicodedata
import urllib.parse


def normalize_name(name):
    nfkd = unicodedata.normalize("NFKD", name)
    no_accents = "".join((ch for ch in nfkd if not unicodedata.combining(ch)))
    return re.sub(r"\s+", " ", no_accents).strip().lower()


def unwrap_duckduckgo_link(link):
    if not link:
        return None
    if link.startswith("/l/") or "duckduckgo.com/l/?" in link:
        if link.startswith("//"):
            link_to_parse = "https:" + link
        elif link.startswith("/"):
            link_to_parse = "https://duckduckgo.com" + link
        else:
            link_to_parse = link
        parsed = urllib.parse.urlparse(link_to_parse)
        qs = urllib.parse.parse_qs(parsed.query)
        if "uddg" in qs and qs["uddg"]:
            return qs["uddg"][0]
    return link


def invalid_transfermarkt_title(title_text):
    low = normalize_name(title_text)
    if "human verification" in low or "verify you are human" in low:
        return True
    if "awswaf" in low.replace(" ", ""):
        return True
    return low in {
        "502 bad gateway",
        "503 service unavailable",
        "504 gateway timeout",
        "403 forbidden",
        "429 too many requests",
        "access denied",
        "just a moment",
        "error",
    }
