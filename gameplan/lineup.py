from gameplan.constants import SUB_WING_SLOTS, is_standard
from gameplan.formation import FORMATION
from gameplan.candidates import report_candidates


def _available_roles_for_sub_slot(slot, roles_by_pos, used_ids, candidate_observer=None):
    direct_roles = roles_by_pos.get(slot, [])

    nonstd_direct = [r for r in direct_roles if r.player_id not in used_ids and not is_standard(r)]
    report_candidates(candidate_observer, nonstd_direct, slot, "initial_sub_nonstandard_direct")
    if nonstd_direct:
        return nonstd_direct

    std_direct = [r for r in direct_roles if r.player_id not in used_ids and is_standard(r)]
    report_candidates(candidate_observer, std_direct, slot, "initial_sub_standard_direct")
    if std_direct:
        return std_direct

    if slot in SUB_WING_SLOTS:
        ss_roles = roles_by_pos.get("SS", [])
        nonstd_ss = [r for r in ss_roles if r.player_id not in used_ids and not is_standard(r)]
        report_candidates(candidate_observer, nonstd_ss, slot, "initial_sub_nonstandard_ss")
        if nonstd_ss:
            return nonstd_ss
        std_ss = [r for r in ss_roles if r.player_id not in used_ids and is_standard(r)]
        report_candidates(candidate_observer, std_ss, slot, "initial_sub_standard_ss")
        if std_ss:
            return std_ss

    return []


def choose_initial_lineup(roles_by_pos, candidate_observer=None):
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
                report_candidates(
                    candidate_observer,
                    candidates,
                    slot,
                    f"starter_{candidate_selector.__name__}",
                )
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
            candidates = _available_roles_for_sub_slot(
                slot, roles_by_pos, used_for_subs, candidate_observer=candidate_observer
            )
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
