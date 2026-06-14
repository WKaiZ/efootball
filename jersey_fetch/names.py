import re
import unicodedata
import urllib.parse


def normalize_name(name):
    nfkd = unicodedata.normalize("NFKD", name)
    no_accents = "".join((ch for ch in nfkd if not unicodedata.combining(ch)))
    return re.sub(r"\s+", " ", no_accents).strip().lower()


def _nation_alias_groups():
    from jersey_fetch.constants import ESPN_TEAM_NAME_ALIASES

    return [
        {canonical, *[normalize_name(alias) for alias in aliases]}
        for canonical, aliases in ESPN_TEAM_NAME_ALIASES.items()
    ]


def nation_label_variants(label):
    key = normalize_name(label or "")
    variants = {key} if key else set()
    for group in _nation_alias_groups():
        if key in group:
            variants |= group
            break
    return variants


def nation_labels_equivalent(a, b):
    if not a or not b:
        return False
    return bool(nation_label_variants(a) & nation_label_variants(b))


def nation_country_names_for_filter(country_filter):
    from jersey_fetch.constants import ESPN_TEAM_NAME_ALIASES

    names = {country_filter}
    key = normalize_name(country_filter)
    for canonical, aliases in ESPN_TEAM_NAME_ALIASES.items():
        group_norm = {canonical, *[normalize_name(alias) for alias in aliases]}
        if key in group_norm:
            for alias in aliases:
                names.add(alias)
            break
    return sorted(names)


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
    if "most valuable players" in low:
        return True
    if low.endswith("| transfermarkt") or low == "transfermarkt":
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
