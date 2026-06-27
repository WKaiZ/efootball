from gameplan.constants import SUB_WING_SLOTS, is_standard
from gameplan.formation import FORMATION


def _greedy_fill(vacant_indices, candidate_fn, used_ids):
    """
    Globally greedy: repeatedly pick the highest-rated (slot_index, player) pair
    across all vacant slots until no more assignments are possible.
    Returns dict of slot_index -> PlayerRole.
    """
    filled = {}
    remaining = set(vacant_indices)
    while remaining:
        best_idx = None
        best_player = None
        best_rating = -1e18
        for i in remaining:
            slot = FORMATION[i]
            for r in candidate_fn(slot):
                if r.player_id in used_ids:
                    continue
                if r.rating > best_rating:
                    best_rating = r.rating
                    best_player = r
                    best_idx = i
        if best_player is None:
            break
        filled[best_idx] = best_player
        used_ids.add(best_player.player_id)
        remaining.remove(best_idx)
    return filled


def sub_candidates_for_slot(slot, roles_by_pos, used_ids):
    """
    Wing slots: 4-tier priority (non-Std direct → Std direct → non-Std SS → Std SS).
    Other slots: MAIN position only.
    """
    if slot not in SUB_WING_SLOTS:
        return [r for r in roles_by_pos.get(slot, []) if r.player_id not in used_ids]

    nonstd_direct = [r for r in roles_by_pos.get(slot, [])
                     if r.player_id not in used_ids and not is_standard(r)]
    if nonstd_direct:
        return nonstd_direct
    std_direct = [r for r in roles_by_pos.get(slot, [])
                  if r.player_id not in used_ids and is_standard(r)]
    if std_direct:
        return std_direct
    ss = roles_by_pos.get("SS", [])
    nonstd_ss = [r for r in ss if r.player_id not in used_ids and not is_standard(r)]
    if nonstd_ss:
        return nonstd_ss
    return [r for r in ss if r.player_id not in used_ids and is_standard(r)]


def choose_initial_lineup(roles_by_pos):
    """
    Returns (starters, subs), each a list of PlayerRole|None aligned with FORMATION.

    Starters: 4 stages (A=non-Std main, B=non-Std proficient,
                         C=Std main, D=Std proficient). Semi-proficient never used.
    Subs: best MAIN-position match per slot; wings use 4-tier SS fallback.
    """
    n = len(FORMATION)
    all_roles = [r for lst in roles_by_pos.values() for r in lst]

    starters = [None] * n
    used_ids = set()
    vacant = list(range(n))

    stages = [
        (False, False),  # A: non-Std main
        (False, True),   # B: non-Std proficient
        (True,  False),  # C: Std main
        (True,  True),   # D: Std proficient
    ]
    for want_std, use_prof in stages:
        if not vacant:
            break
        pool = all_roles if use_prof else None

        def make_cand_fn(ws, up, p=pool):
            def fn(slot):
                src = p if up else roles_by_pos.get(slot, [])
                return [
                    r for r in src
                    if is_standard(r) == ws
                    and (slot in r.proficient_positions if up else r.position == slot)
                ]
            return fn

        filled = _greedy_fill(vacant, make_cand_fn(want_std, use_prof), used_ids)
        new_vacant = []
        for i in vacant:
            if i in filled:
                starters[i] = filled[i]
            else:
                new_vacant.append(i)
        vacant = new_vacant

    # Subs
    subs = [None] * n
    used_for_subs = {p.player_id for p in starters if p is not None}

    def sub_fn(slot):
        return sub_candidates_for_slot(slot, roles_by_pos, used_for_subs)

    filled_subs = _greedy_fill(list(range(n)), sub_fn, used_for_subs)
    for i, player in filled_subs.items():
        subs[i] = player

    return starters, subs


def all_unique(players):
    seen = set()
    for p in players:
        if p is None:
            continue
        if p.player_id in seen:
            return False
        seen.add(p.player_id)
    return True
