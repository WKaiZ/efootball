from gameplan.constants import SUB_WING_SLOTS, is_standard
from gameplan.formation import FORMATION


def _load_history(conn, player_id):
    cur = conn.cursor()
    cur.execute("SELECT number FROM jersey WHERE player_id = ? ORDER BY idx ASC", (player_id,))
    return [int(r[0]) for r in cur.fetchall()]


def _epic_prefs(nums):
    """Most-worn count; ties broken by earliest first occurrence in the history list."""
    counts = {}
    first_idx = {}
    for idx, n in enumerate(nums):
        counts[n] = counts.get(n, 0) + 1
        if n not in first_idx:
            first_idx[n] = idx
    return [n for n, _ in sorted(counts.items(), key=lambda kv: (-kv[1], first_idx[kv[0]]))]


def _ordered_unique(nums):
    """Newest-to-oldest with duplicates removed."""
    seen = set()
    out = []
    for n in nums:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def jersey_prefs(conn, player_id, card_type):
    """Return (most_recent, preference_list). most_recent is None if no history."""
    history = _load_history(conn, player_id)
    if not history:
        return None, []
    most_recent = history[0]
    prefs = _epic_prefs(history) if card_type.strip().lower() == "epic" else _ordered_unique(history)
    return most_recent, prefs


def card_priority(card_type):
    ct = card_type.strip().lower()
    if ct in ("epic", "bigtime"):
        return 0
    if ct == "showtime":
        return 1
    if ct == "highlight":
        return 2
    return 3


def assign_group(conn, players, used_numbers, assignments):
    """
    Assign jerseys to one group of players:
    1. recent=True lock — highest-rated recent players secure their most-recent jersey first.
    2. Card-tier buckets (0-3) — highest-rated first within each tier.
       A player skips a non-first-choice number if another unassigned same-tier player
       has it as their first choice.
    """
    if not players:
        return

    mr_map = {}
    prefs_map = {}
    for p in players:
        if p.player_id not in prefs_map:
            mr, prefs = jersey_prefs(conn, p.player_id, p.card_type)
            mr_map[p.player_id] = mr
            prefs_map[p.player_id] = prefs

    # Step 1: recent=True lock
    for p in sorted(players, key=lambda r: -r.rating):
        if not p.recent or p.player_id in assignments:
            continue
        mr = mr_map.get(p.player_id)
        if mr is not None and mr not in used_numbers:
            assignments[p.player_id] = mr
            used_numbers.add(mr)

    # Step 2: card-tier buckets
    buckets = {0: [], 1: [], 2: [], 3: []}
    for p in players:
        if p.player_id not in assignments:
            buckets[card_priority(p.card_type)].append(p)

    for tier in range(4):
        tier_players = sorted(buckets[tier], key=lambda r: -r.rating)
        for p in tier_players:
            if p.player_id in assignments:
                continue
            prefs = prefs_map.get(p.player_id, [])
            for pref_idx, num in enumerate(prefs):
                if num in used_numbers:
                    continue
                if pref_idx > 0:
                    # Don't take a number that is another unassigned same-tier player's first choice
                    blocked = False
                    for o in tier_players:
                        if o.player_id == p.player_id or o.player_id in assignments:
                            continue
                        o_prefs = prefs_map.get(o.player_id, [])
                        if o_prefs and o_prefs[0] == num:
                            blocked = True
                            break
                    if blocked:
                        continue
                assignments[p.player_id] = num
                used_numbers.add(num)
                break


def assign_jerseys(conn, starters, subs):
    """
    Assign jersey numbers to all starters and subs following the rules.
    Returns (assignments dict: player_id -> jersey, used_numbers set).

    Groups processed in order:
      starters: main-nonstd, prof-nonstd, main-std, prof-std
      subs:     nonstd-normal, ss-main-nonstd, std, ss-prof-nonstd
    """
    starter_main_nonstd, starter_prof_nonstd = [], []
    starter_main_std, starter_prof_std = [], []
    for slot, p in zip(FORMATION, starters):
        if p is None:
            continue
        if p.position == slot:
            (starter_main_std if is_standard(p) else starter_main_nonstd).append(p)
        else:
            (starter_prof_std if is_standard(p) else starter_prof_nonstd).append(p)

    sub_nonstd_normal, sub_ss_main_nonstd, sub_std, sub_ss_prof_nonstd = [], [], [], []
    for slot, p in zip(FORMATION, subs):
        if p is None:
            continue
        if is_standard(p):
            sub_std.append(p)
        elif slot in SUB_WING_SLOTS and p.position == "SS":
            sub_ss_main_nonstd.append(p)
        elif (slot in SUB_WING_SLOTS
              and p.position not in SUB_WING_SLOTS
              and "SS" in p.proficient_positions):
            sub_ss_prof_nonstd.append(p)
        else:
            sub_nonstd_normal.append(p)

    used_numbers = set()
    assignments = {}
    for group in (starter_main_nonstd, starter_prof_nonstd,
                  starter_main_std, starter_prof_std,
                  sub_nonstd_normal, sub_ss_main_nonstd,
                  sub_std, sub_ss_prof_nonstd):
        assign_group(conn, group, used_numbers, assignments)
    return assignments, used_numbers
