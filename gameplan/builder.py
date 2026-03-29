from gameplan.candidates import (
    find_player_index,
    next_candidate_for_slot,
    next_candidate_for_sub_wing,
    refill_empty_subs,
    try_free_jersey_via_swap,
)
from gameplan.constants import MATCH_STAGES, SUB_WING_SLOTS, is_standard
from gameplan.formation import FORMATION
from gameplan.jerseys import (
    assign_jerseys,
    choose_jersey_for_player,
    jersey_prefs_for_player,
    load_jersey_stats,
)
from gameplan.lineup import all_unique, choose_initial_lineup
from gameplan.models import Assignment


def _recent_soft_reserved_numbers(conn, starters, subs):
    out = set()
    for p in starters + subs:
        if p is not None and p.recent:
            mr, _, _ = load_jersey_stats(conn, p.player_id)
            if mr is not None:
                out.add(mr)
    return out


def build_gameplan(conn, roles_by_pos):
    starters, subs = choose_initial_lineup(roles_by_pos)
    if not all_unique(starters + subs):
        raise RuntimeError("Internal error: duplicate player_id selected.")

    recent_soft_reserved = set()
    attempts = 0
    starter_excluded = {}
    sub_excluded = {}
    while attempts < 50:
        attempts += 1

        recent_soft_reserved = _recent_soft_reserved_numbers(conn, starters, subs)

        assignments, used_numbers = assign_jerseys(conn, starters, subs, recent_soft_reserved=recent_soft_reserved)
        used_ids = {p.player_id for p in (starters + subs) if p is not None}

        replaced = False
        for i, p in enumerate(starters):
            if p is None:
                continue
            if p.player_id in assignments:
                continue
            excluded = starter_excluded.setdefault(i, set())
            excluded.add(p.player_id)
            slot = FORMATION[i]
            used_without_this_starter = used_ids - {p.player_id}
            repl = None

            best_sub_idx = None
            best_sub = None
            for j, sp in enumerate(subs):
                if sp is None:
                    continue
                if sp.player_id in excluded:
                    continue
                if sp.position != slot:
                    continue
                if best_sub is None or sp.rating > best_sub.rating:
                    best_sub = sp
                    best_sub_idx = j

            if best_sub is not None:
                repl = best_sub
                starters[i] = repl
                subs[best_sub_idx] = None
            else:
                repl = next_candidate_for_slot(slot, roles_by_pos, used_without_this_starter, excluded)
                starters[i] = repl
            replaced = True
            break

        if not replaced:
            any_sub_changed = False
            for i, p in enumerate(subs):
                if p is None:
                    continue
                if p.player_id in assignments:
                    continue
                excluded = sub_excluded.setdefault(i, set())
                excluded.add(p.player_id)
                slot = FORMATION[i]
                if slot in SUB_WING_SLOTS:
                    repl = next_candidate_for_sub_wing(
                        slot, roles_by_pos, used_ids - {p.player_id}, excluded, subs
                    )
                else:
                    repl = next_candidate_for_slot(slot, roles_by_pos, used_ids - {p.player_id}, excluded, subs)
                if repl is not None and repl.player_id in (used_ids - {p.player_id}):
                    existing_idx = find_player_index(subs, repl.player_id)
                    if existing_idx is not None:
                        existing = subs[existing_idx]
                        if existing is not None and existing.rating >= repl.rating:
                            repl = None
                        else:
                            subs[existing_idx] = None
                subs[i] = repl
                if repl is not None:
                    used_ids.add(repl.player_id)
                any_sub_changed = True

            if not any_sub_changed:
                break

            used_ids = {p.player_id for p in (starters + subs) if p is not None}
            refill_empty_subs(subs, used_ids, sub_excluded, roles_by_pos)

        if replaced:
            used_ids = {p.player_id for p in (starters + subs) if p is not None}
            refill_empty_subs(subs, used_ids, sub_excluded, roles_by_pos)

    assignments, used_numbers = assign_jerseys(conn, starters, subs, recent_soft_reserved=recent_soft_reserved)
    used_ids = {p.player_id for p in (starters + subs) if p is not None}

    for i, p in enumerate(starters):
        if p is None:
            continue
        if p.player_id not in assignments:
            starters[i] = None
            used_ids.discard(p.player_id)
    for i, p in enumerate(subs):
        if p is None:
            continue
        if p.player_id not in assignments:
            subs[i] = None
            used_ids.discard(p.player_id)

    all_roles = []
    for lst in roles_by_pos.values():
        all_roles.extend(lst)

    remaining_roles = [r for r in all_roles if r.player_id not in used_ids]

    starter_vacant_indices = [i for i, p in enumerate(starters) if p is None]
    sub_vacant_indices = [i for i, p in enumerate(subs) if p is None]

    def lineup_soft_reserved():
        return _recent_soft_reserved_numbers(conn, starters, subs)

    def fill_vacancies(
        vacant_indices,
        target_list,
        pos_set_name,
        want_standard,
        blocked_numbers,
        update_blocked,
        allow_from_subs,
    ):
        nonlocal used_ids
        while True:
            open_slots = [i for i in vacant_indices if target_list[i] is None]
            if not open_slots:
                break

            candidate_roles = all_roles if allow_from_subs else remaining_roles
            best_slot = None
            best_player = None
            best_number = None
            best_rating = -1e18

            for i in open_slots:
                slot = FORMATION[i]
                for r in candidate_roles:
                    sub_idx_for_r = find_player_index(subs, r.player_id)
                    if r.player_id in used_ids and (not allow_from_subs or sub_idx_for_r is None):
                        continue
                    if want_standard and not is_standard(r):
                        continue
                    if not want_standard and is_standard(r):
                        continue
                    if pos_set_name == "proficient":
                        if slot not in r.proficient_positions:
                            continue
                    elif pos_set_name == "semiproficient":
                        if slot not in r.semiproficient_positions:
                            continue
                    elif pos_set_name == "main":
                        if slot != r.position:
                            continue
                    else:
                        raise ValueError(f"Unknown pos_set_name: {pos_set_name}")

                    num = choose_jersey_for_player(
                        conn,
                        r,
                        used_numbers,
                        assignments,
                        blocked_numbers,
                        fallback_reserved=recent_soft_reserved,
                    )
                    if num is None and r.recent:
                        num = try_free_jersey_via_swap(
                            conn,
                            r,
                            used_numbers,
                            assignments,
                            [p for p in starters + subs if p is not None],
                            starter_ids={p.player_id for p in starters if p is not None},
                        )
                    if num is None:
                        continue

                    if r.rating > best_rating:
                        best_slot = i
                        best_player = r
                        best_number = num
                        best_rating = r.rating

            if best_player is None:
                break

            moved_from_sub_idx = find_player_index(subs, best_player.player_id)
            if moved_from_sub_idx is not None and allow_from_subs:
                subs[moved_from_sub_idx] = None

            target_list[best_slot] = best_player
            used_ids.add(best_player.player_id)
            assignments[best_player.player_id] = best_number
            used_numbers.add(best_number)
            if update_blocked and blocked_numbers is not None:
                blocked_numbers.add(best_number)

    def player_number_preference_order(p):
        most_recent, prefs = jersey_prefs_for_player(conn, p)
        ordered = []
        if p.recent and most_recent is not None:
            ordered.append(most_recent)
        for num in prefs:
            if num not in ordered:
                ordered.append(num)
        return ordered

    def role_matches_stage(slot, r, pos_set_name, want_standard):
        if want_standard != is_standard(r):
            return False
        if pos_set_name == "main":
            return slot == r.position
        if pos_set_name == "proficient":
            return slot in r.proficient_positions
        if pos_set_name == "semiproficient":
            return slot in r.semiproficient_positions
        return False

    def best_sub_replacement(slot, temp_used_ids, temp_used_numbers, temp_assignments, exclude_ids):
        for pos_set_name, want_standard in MATCH_STAGES:
            best_player = None
            best_number = None
            best_rating = -1e18
            for r in all_roles:
                if r.player_id in temp_used_ids or r.player_id in exclude_ids:
                    continue
                if not role_matches_stage(slot, r, pos_set_name, want_standard):
                    continue
                num = choose_jersey_for_player(conn, r, temp_used_numbers, temp_assignments, None)
                if num is None:
                    continue
                if r.rating > best_rating:
                    best_player = r
                    best_number = num
                    best_rating = r.rating
            if best_player is not None:
                return best_player, best_number
        return None, None

    def upgrade_subs():
        nonlocal used_ids, used_numbers, assignments
        changed = True
        while changed:
            changed = False
            dyn_reserved = lineup_soft_reserved()
            for i, p in enumerate(subs):
                if p is None:
                    continue
                slot = FORMATION[i]
                for candidate in all_roles:
                    if candidate.player_id in used_ids:
                        continue
                    if candidate.position != slot:
                        continue
                    if is_standard(candidate) != is_standard(p):
                        continue
                    if candidate.rating <= p.rating:
                        continue
                    old_num = assignments.pop(p.player_id, None)
                    if old_num is not None:
                        used_numbers.discard(old_num)
                    used_ids.discard(p.player_id)
                    num = choose_jersey_for_player(
                        conn, candidate, used_numbers, assignments, None, fallback_reserved=dyn_reserved
                    )
                    if num is None:
                        if old_num is not None:
                            assignments[p.player_id] = old_num
                            used_numbers.add(old_num)
                        used_ids.add(p.player_id)
                        continue
                    subs[i] = candidate
                    assignments[candidate.player_id] = num
                    used_numbers.add(num)
                    used_ids.add(candidate.player_id)
                    changed = True
                    break

    def try_swap_fill_sub_vacancies():
        nonlocal used_ids, used_numbers, assignments
        while True:
            vacant_indices = [i for i, p in enumerate(subs) if p is None]
            if not vacant_indices:
                break

            best_swap = None
            best_rating = -1e18

            for vacant_idx in vacant_indices:
                vacant_slot = FORMATION[vacant_idx]
                for pos_set_name, want_standard in MATCH_STAGES:
                    for candidate in all_roles:
                        if candidate.player_id in used_ids:
                            continue
                        if not role_matches_stage(vacant_slot, candidate, pos_set_name, want_standard):
                            continue

                        for num in player_number_preference_order(candidate):
                            holder_idx = None
                            holder = None
                            for j, sp in enumerate(subs):
                                if sp is None:
                                    continue
                                if assignments.get(sp.player_id) == num:
                                    holder_idx = j
                                    holder = sp
                                    break
                            if holder is None:
                                continue

                            temp_used_ids = (used_ids - {holder.player_id}) | {candidate.player_id}
                            temp_assignments = dict(assignments)
                            temp_assignments.pop(holder.player_id, None)
                            temp_assignments[candidate.player_id] = num
                            temp_used_numbers = set(used_numbers)

                            replacement, replacement_num = best_sub_replacement(
                                FORMATION[holder_idx],
                                temp_used_ids,
                                temp_used_numbers,
                                temp_assignments,
                                exclude_ids={candidate.player_id, holder.player_id},
                            )
                            if replacement is None:
                                continue

                            if candidate.rating > best_rating:
                                best_rating = candidate.rating
                                best_swap = (
                                    vacant_idx,
                                    candidate,
                                    num,
                                    holder_idx,
                                    holder,
                                    replacement,
                                    replacement_num,
                                )

                    if best_swap is not None:
                        break
                if best_swap is not None:
                    break

            if best_swap is None:
                break

            vacant_idx, candidate, num, holder_idx, holder, replacement, replacement_num = best_swap
            subs[vacant_idx] = candidate
            subs[holder_idx] = replacement
            used_ids.discard(holder.player_id)
            used_ids.add(candidate.player_id)
            used_ids.add(replacement.player_id)
            assignments.pop(holder.player_id, None)
            assignments[candidate.player_id] = num
            assignments[replacement.player_id] = replacement_num
            used_numbers = set(assignments.values())

    starter_blocked_numbers = set()
    for p in starters:
        if p is None:
            continue
        num = assignments.get(p.player_id)
        if num is not None:
            starter_blocked_numbers.add(num)

    fill_vacancies(
        starter_vacant_indices,
        starters,
        "proficient",
        want_standard=False,
        blocked_numbers=starter_blocked_numbers,
        update_blocked=True,
        allow_from_subs=True,
    )
    used_ids = {p.player_id for p in (starters + subs) if p is not None}
    fill_vacancies(
        [i for i, p in enumerate(starters) if p is None],
        starters,
        "proficient",
        want_standard=True,
        blocked_numbers=starter_blocked_numbers,
        update_blocked=True,
        allow_from_subs=True,
    )
    used_ids = {p.player_id for p in (starters + subs) if p is not None}
    fill_vacancies(
        [i for i, p in enumerate(starters) if p is None],
        starters,
        "main",
        want_standard=True,
        blocked_numbers=starter_blocked_numbers,
        update_blocked=True,
        allow_from_subs=True,
    )

    fill_vacancies(
        sub_vacant_indices,
        subs,
        "main",
        want_standard=False,
        blocked_numbers=None,
        update_blocked=False,
        allow_from_subs=False,
    )
    used_ids = {p.player_id for p in (starters + subs) if p is not None}
    for spec in (
        ("main", True),
        ("proficient", False),
        ("proficient", True),
        ("semiproficient", False),
        ("semiproficient", True),
    ):
        pos_set, want_std = spec
        fill_vacancies(
            [i for i, p in enumerate(subs) if p is None],
            subs,
            pos_set,
            want_standard=want_std,
            blocked_numbers=None,
            update_blocked=False,
            allow_from_subs=False,
        )
        used_ids = {p.player_id for p in (starters + subs) if p is not None}

    upgrade_subs()
    try_swap_fill_sub_vacancies()

    starter_asg = []
    for slot, p in zip(FORMATION, starters):
        if p is None:
            starter_asg.append(None)
            continue
        jersey = assignments.get(p.player_id)
        if jersey is None:
            starter_asg.append(None)
            continue
        starter_asg.append(Assignment(slot=slot, player=p, jersey=jersey))

    sub_asg = []
    for slot, p in zip(FORMATION, subs):
        if p is None:
            sub_asg.append(None)
            continue
        jersey = assignments.get(p.player_id)
        if jersey is None:
            sub_asg.append(None)
            continue
        sub_asg.append(Assignment(slot=slot, player=p, jersey=jersey))

    used_ids = {a.player.player_id for a in (starter_asg + sub_asg) if a is not None}
    pool = []
    for lst in roles_by_pos.values():
        for r in lst:
            if r.player_id not in used_ids:
                pool.append(r)
    wildcard_asg = None
    for candidate in sorted(pool, key=lambda r: r.rating, reverse=True):
        _mr, prefs = jersey_prefs_for_player(conn, candidate)
        num = None
        for n in prefs:
            if n not in used_numbers:
                num = n
                break
        if num is not None:
            wildcard_asg = Assignment(slot="WILD", player=candidate, jersey=num)
            break

    return starter_asg, sub_asg, wildcard_asg
