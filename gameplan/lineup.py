from gameplan.constants import SUB_WING_SLOTS, is_standard
from gameplan.formation import FORMATION


def _available_roles_for_sub_slot(slot, roles_by_pos, used_ids):
    direct_roles = roles_by_pos.get(slot, [])

    nonstd = [r for r in direct_roles if r.player_id not in used_ids and not is_standard(r)]

    if slot in SUB_WING_SLOTS and not nonstd:
        ss_roles = roles_by_pos.get("SS", [])
        nonstd = [r for r in ss_roles if r.player_id not in used_ids and not is_standard(r)]

    if nonstd:
        return nonstd

    std = [r for r in direct_roles if r.player_id not in used_ids and is_standard(r)]
    if slot in SUB_WING_SLOTS and not std:
        return []
    return std


def choose_initial_lineup(roles_by_pos):
    slot_count = len(FORMATION)
    slots = FORMATION[:]

    def fill_starters_stage(empty_slots, used_ids, candidate_selector):
        filled = [None] * slot_count
        for i in range(slot_count):
            if i not in empty_slots:
                filled[i] = "LOCKED"

        unfilled = set(empty_slots)
        while unfilled:
            best_player = None
            best_slot_idx = None
            best_rating = -1e18

            for slot_idx in unfilled:
                slot = slots[slot_idx]
                candidates = candidate_selector(slot, used_ids)
                if not candidates:
                    continue
                top = max(candidates, key=lambda r: r.rating)
                if top.rating > best_rating:
                    best_rating = top.rating
                    best_player = top
                    best_slot_idx = slot_idx

            if best_player is None:
                break

            filled[best_slot_idx] = best_player
            used_ids.add(best_player.player_id)
            unfilled.remove(best_slot_idx)

        for i in range(slot_count):
            if filled[i] == "LOCKED":
                filled[i] = None
        return filled

    all_roles = []
    for lst in roles_by_pos.values():
        all_roles.extend(lst)

    def cand_stage_a(slot, used_ids):
        return [
            r
            for r in roles_by_pos.get(slot, [])
            if r.player_id not in used_ids and not is_standard(r)
        ]

    def cand_stage_b(slot, used_ids):
        return [
            r
            for r in all_roles
            if r.player_id not in used_ids
            and (slot in r.proficient_positions)
            and not is_standard(r)
        ]

    def cand_stage_c(slot, used_ids):
        return [
            r
            for r in roles_by_pos.get(slot, [])
            if r.player_id not in used_ids and is_standard(r)
        ]

    def cand_stage_d(slot, used_ids):
        return [
            r
            for r in all_roles
            if r.player_id not in used_ids
            and (slot in r.proficient_positions)
            and is_standard(r)
        ]

    starters = [None] * slot_count
    used_ids = set()
    empty_slots = set(range(slot_count))

    for cand_fn in (cand_stage_a, cand_stage_b, cand_stage_c, cand_stage_d):
        stage_filled = fill_starters_stage(empty_slots, used_ids, cand_fn)
        for idx in range(slot_count):
            if stage_filled[idx] is not None:
                starters[idx] = stage_filled[idx]
                used_ids.add(starters[idx].player_id)
                empty_slots.discard(idx)

    used_for_subs = {p.player_id for p in starters if p is not None}
    subs = [None] * slot_count
    unfilled = set(range(slot_count))
    while unfilled:
        best_player = None
        best_slot_idx = None
        best_rating = -1e18
        for slot_idx in unfilled:
            slot = slots[slot_idx]
            candidates = _available_roles_for_sub_slot(slot, roles_by_pos, used_for_subs)
            if not candidates:
                continue
            top = max(candidates, key=lambda r: r.rating)
            if top.rating > best_rating:
                best_rating = top.rating
                best_player = top
                best_slot_idx = slot_idx
        if best_player is None:
            break
        subs[best_slot_idx] = best_player
        used_for_subs.add(best_player.player_id)
        unfilled.remove(best_slot_idx)

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
