from gameplan.candidates import find_player_index
from gameplan.constants import MATCH_STAGES, is_standard
from gameplan.formation import FORMATION
from gameplan.jerseys import assign_jerseys, jersey_prefs
from gameplan.lineup import all_unique, choose_initial_lineup
from gameplan.models import Assignment


def _all_roles(roles_by_pos):
    return [r for lst in roles_by_pos.values() for r in lst]


def _best_sub_to_promote(slot, subs, excluded_ids):
    """Return highest-rated sub whose MAIN position matches slot, non-Standard first."""
    for want_std in (False, True):
        candidates = [
            p for p in subs
            if p is not None
            and p.player_id not in excluded_ids
            and p.position == slot
            and is_standard(p) == want_std
        ]
        if candidates:
            return max(candidates, key=lambda r: r.rating)
    return None


def _best_unused_for_slot(slot, all_roles_list, used_ids, excluded_ids):
    """Best unused candidate for slot via A/B/C/D stages."""
    for want_std, use_prof in ((False, False), (False, True), (True, False), (True, True)):
        candidates = [
            r for r in all_roles_list
            if r.player_id not in used_ids
            and r.player_id not in excluded_ids
            and is_standard(r) == want_std
            and (slot in r.proficient_positions if use_prof else r.position == slot)
        ]
        if candidates:
            return max(candidates, key=lambda r: r.rating)
    return None


def _fill_sub_vacancies(subs, roles_by_pos, used_ids):
    """Fill vacant sub slots using MATCH_STAGES order (6 stages per rules.txt)."""
    all_roles_list = _all_roles(roles_by_pos)
    for pos_set, want_std in MATCH_STAGES:
        while True:
            vacant = [i for i, p in enumerate(subs) if p is None]
            if not vacant:
                return
            best_idx = None
            best_player = None
            best_rating = -1e18
            for i in vacant:
                slot = FORMATION[i]
                for r in all_roles_list:
                    if r.player_id in used_ids:
                        continue
                    if is_standard(r) != want_std:
                        continue
                    if pos_set == "main":
                        match = r.position == slot
                    elif pos_set == "proficient":
                        match = slot in r.proficient_positions
                    else:
                        match = slot in r.semiproficient_positions
                    if not match:
                        continue
                    if r.rating > best_rating:
                        best_rating = r.rating
                        best_player = r
                        best_idx = i
            if best_player is None:
                break
            subs[best_idx] = best_player
            used_ids.add(best_player.player_id)


def build_gameplan(conn, roles_by_pos):
    starters, subs = choose_initial_lineup(roles_by_pos)
    if not all_unique(starters + subs):
        raise RuntimeError("Internal error: duplicate player_id in initial lineup.")

    all_roles_list = _all_roles(roles_by_pos)
    excluded = {}  # slot_index -> set[player_id] that failed jersey assignment there

    for _ in range(20):
        assignments, used_numbers = assign_jerseys(conn, starters, subs)
        used_ids = {p.player_id for p in starters + subs if p is not None}

        failed_idx = next(
            (i for i, p in enumerate(starters) if p is not None and p.player_id not in assignments),
            None,
        )
        if failed_idx is None:
            break

        failed = starters[failed_idx]
        slot = FORMATION[failed_idx]
        excl = excluded.setdefault(failed_idx, set())
        excl.add(failed.player_id)

        repl = _best_sub_to_promote(slot, subs, excl)
        if repl is not None:
            sub_idx = find_player_index(subs, repl.player_id)
            subs[sub_idx] = None
        else:
            repl = _best_unused_for_slot(slot, all_roles_list, used_ids - {failed.player_id}, excl)

        starters[failed_idx] = repl

    assignments, used_numbers = assign_jerseys(conn, starters, subs)
    used_ids = {p.player_id for p in starters + subs if p is not None}

    # Drop any player still without a jersey
    for i, p in enumerate(starters):
        if p is not None and p.player_id not in assignments:
            used_ids.discard(p.player_id)
            starters[i] = None
    for i, p in enumerate(subs):
        if p is not None and p.player_id not in assignments:
            used_ids.discard(p.player_id)
            subs[i] = None

    # Fill vacant sub slots (6 stages)
    _fill_sub_vacancies(subs, roles_by_pos, used_ids)

    # Final jersey run to cover newly added subs
    assignments, used_numbers = assign_jerseys(conn, starters, subs)

    # Build output assignments
    starter_asg = []
    for slot, p in zip(FORMATION, starters):
        if p is None:
            starter_asg.append(None)
        else:
            jersey = assignments.get(p.player_id)
            starter_asg.append(Assignment(slot=slot, player=p, jersey=jersey) if jersey is not None else None)

    sub_asg = []
    for slot, p in zip(FORMATION, subs):
        if p is None:
            sub_asg.append(None)
        else:
            jersey = assignments.get(p.player_id)
            sub_asg.append(Assignment(slot=slot, player=p, jersey=jersey) if jersey is not None else None)

    # Wildcard: highest-rated unused player that can get a jersey
    used_ids = {a.player.player_id for a in starter_asg + sub_asg if a is not None}
    vacant_count = sum(1 for a in starter_asg + sub_asg if a is None)
    max_wildcards = 1 + vacant_count

    wildcard_asgs = []
    seen_wc = {}
    for lst in roles_by_pos.values():
        for r in lst:
            if r.player_id not in used_ids:
                if r.player_id not in seen_wc or r.rating > seen_wc[r.player_id].rating:
                    seen_wc[r.player_id] = r
    pool = sorted(seen_wc.values(), key=lambda r: r.rating, reverse=True)
    for candidate in pool:
        if len(wildcard_asgs) >= max_wildcards:
            break
        most_recent, prefs = jersey_prefs(conn, candidate.player_id, candidate.card_type)
        num = None
        if candidate.recent and most_recent is not None and most_recent not in used_numbers:
            num = most_recent
        if num is None:
            num = next((n for n in prefs if n not in used_numbers), None)
        if num is not None:
            wildcard_asgs.append(Assignment(slot="WILD", player=candidate, jersey=num))
            used_numbers.add(num)

    return starter_asg, sub_asg, wildcard_asgs
