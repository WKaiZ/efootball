from jersey_fetch.constants import ESPN_LINEUP_MANUAL_ROLES
from jersey_fetch.names import normalize_name
from jersey_fetch.text_utils import levenshtein


def _name_token_is_initial_abbrev(tok):
    return len(tok) == 2 and tok[1] == "." and tok[0].isalpha()


def _espn_token_equiv(local_tok, espn_tok):
    if local_tok == espn_tok:
        return True
    if min(len(local_tok), len(espn_tok)) == 1 and max(len(local_tok), len(espn_tok)) > 1:
        return False
    if _name_token_is_initial_abbrev(espn_tok) and local_tok.startswith(espn_tok[0]) and len(local_tok) > 1:
        return True
    if _name_token_is_initial_abbrev(local_tok) and espn_tok.startswith(local_tok[0]) and len(espn_tok) > 1:
        return True
    short = min(len(local_tok), len(espn_tok))
    long_tok, short_tok = (
        (local_tok, espn_tok) if len(local_tok) >= len(espn_tok) else (espn_tok, local_tok)
    )
    if (
        min(len(local_tok), len(espn_tok)) >= 3
        and short < 4
        and (local_tok.startswith(espn_tok) or espn_tok.startswith(local_tok))
    ):
        return True
    if short >= 3 and long_tok.startswith(short_tok) and short_tok != long_tok:
        return True
    if (
        min(len(local_tok), len(espn_tok)) >= 4
        and levenshtein(local_tok, espn_tok) <= 2
        and local_tok[0] == espn_tok[0]
    ):
        return True
    return False


def _surname_tokens_compatible(local_last, espn_last):
    if local_last == espn_last:
        return True
    if min(len(local_last), len(espn_last)) >= 4 and levenshtein(local_last, espn_last) <= 2:
        return True
    return False


def _local_tokens_match_espn_ordered_subsequence(local_tokens, espn_tokens):
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
    if len(espn_tokens) == 2 and _name_token_is_initial_abbrev(espn_tokens[0]):
        if len(local_tokens) != 2:
            return False
        if not _surname_tokens_compatible(local_tokens[-1], espn_tokens[-1]):
            return False
        return local_tokens[0][0] == espn_tokens[0][0]
    if len(local_tokens) >= 2 and len(espn_tokens) >= 2:
        if not _surname_tokens_compatible(local_tokens[-1], espn_tokens[-1]):
            return False
    return _local_tokens_match_espn_ordered_subsequence(local_tokens, espn_tokens)


def espn_lineup_role(position_abbreviation):
    abbr = (position_abbreviation or "").strip().upper()
    if not abbr or abbr == "SUB":
        return None
    if abbr in {"G", "GK"}:
        return "G"
    if abbr in {"D", "CB", "LB", "RB", "CD-L", "CD-R", "SW", "LWB", "RWB", "WB"}:
        return "D"
    if abbr in {"M", "DM", "CM", "CM-L", "CM-R", "AM", "AM-L", "AM-R", "LM", "RM", "CAM", "CDM"}:
        return "M"
    if abbr in {"F", "FW", "CF", "CF-L", "CF-R", "LW", "RW", "ST", "SS"}:
        return "F"
    return None


def roster_role_compatible(profile_roles, espn_role):
    if not espn_role or not profile_roles:
        return True
    return espn_role in profile_roles


def roster_role_compatible_for_espn_lineup(profile_roles, espn_role, player_key):
    if roster_role_compatible(profile_roles, espn_role):
        return True
    manual = ESPN_LINEUP_MANUAL_ROLES.get(player_key)
    if manual is not None and espn_role in manual:
        return True
    return False


def espn_full_given_family_aliases(aliases):
    out = []
    for a in aliases:
        parts = [p for p in a.split() if p]
        if len(parts) < 2:
            continue
        if _name_token_is_initial_abbrev(parts[0]):
            continue
        out.append(a)
    return out


def espn_local_matches_full_aliases(key, aliases):
    fulls = espn_full_given_family_aliases(aliases)
    if not fulls:
        return True
    return any(compatible_name_tokens(key, fa) for fa in fulls)


def espn_local_name_match_score(key, aliases):
    if key in aliases:
        return 100000
    best = 0
    for a in aliases:
        if compatible_name_tokens(key, a):
            best = max(best, 1000 + len(a))
    return best


def espn_local_name_match_tiebreak(key, aliases):
    dists = []
    for a in aliases:
        if compatible_name_tokens(key, a):
            dists.append(levenshtein(key, a))
    return min(dists) if dists else 9999
