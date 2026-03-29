from gameplan.constants import SUB_WING_SLOTS
from gameplan.formation import FORMATION
from gameplan.jerseys import jersey_prefs_for_player


def _player_usable_for_slot_candidate(r, used_ids, subs):
    if r.player_id not in used_ids:
        return True
    if subs and any(sp and sp.player_id == r.player_id for sp in subs):
        return True
    return False


def next_candidate_for_slot(slot, roles_by_pos, used_ids, excluded_ids, subs=None):
    candidates = [
        r
        for r in roles_by_pos.get(slot, [])
        if r.player_id not in excluded_ids and _player_usable_for_slot_candidate(r, used_ids, subs)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.rating)


def find_player_index(players, player_id):
    for i, p in enumerate(players):
        if p is None:
            continue
        if p.player_id == player_id:
            return i
    return None


def next_candidate_for_sub_wing(
    slot,
    roles_by_pos,
    used_ids,
    excluded_ids,
    subs=None,
):
    repl = next_candidate_for_slot(slot, roles_by_pos, used_ids, excluded_ids, subs)
    if repl is not None:
        return repl
    ss_candidates = [
        r
        for r in roles_by_pos.get("SS", [])
        if r.player_id not in excluded_ids and _player_usable_for_slot_candidate(r, used_ids, subs)
    ]
    if not ss_candidates:
        return None
    return max(ss_candidates, key=lambda r: r.rating)


def try_free_jersey_via_swap(conn, candidate, used_numbers, assignments, lineup_players, starter_ids=None):
    if not candidate.recent:
        return None
    _, prefs = jersey_prefs_for_player(conn, candidate)
    rev = {v: k for k, v in assignments.items()}
    pid_to_player = {p.player_id: p for p in lineup_players if p is not None}
    protected = set(starter_ids) if starter_ids else set()
    for num in prefs:
        if num not in used_numbers:
            return num
        holder_id = rev.get(num)
        if holder_id is None:
            continue
        if holder_id in protected:
            continue
        holder = pid_to_player.get(holder_id)
        if holder is None or holder.recent:
            continue
        _, holder_prefs = jersey_prefs_for_player(conn, holder)
        for alt in holder_prefs:
            if alt == num or alt in used_numbers:
                continue
            assignments[holder_id] = alt
            used_numbers.discard(num)
            used_numbers.add(alt)
            return num
    return None


def _pick_replacement_sub(slot, roles_by_pos, used_ids, excluded):
    if slot in SUB_WING_SLOTS:
        return next_candidate_for_sub_wing(slot, roles_by_pos, used_ids, excluded)
    return next_candidate_for_slot(slot, roles_by_pos, used_ids, excluded)


def refill_empty_subs(subs, used_ids, sub_excluded, roles_by_pos):
    for j, sp in enumerate(subs):
        if sp is not None:
            continue
        excluded = sub_excluded.setdefault(j, set())
        slot = FORMATION[j]
        repl = _pick_replacement_sub(slot, roles_by_pos, used_ids, excluded)
        subs[j] = repl
        if repl is not None:
            used_ids.add(repl.player_id)
