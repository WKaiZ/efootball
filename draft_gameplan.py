import os
import sqlite3
import sys

DB_PATH = "pes.db"


class PlayerRole:
    def __init__(
        self,
        player_id,
        name,
        position,
        rating,
        recent,
        card_type,
        proficient_positions,
        semiproficient_positions,
    ):
        self.player_id = player_id
        self.name = name
        self.position = position
        self.rating = rating
        self.recent = recent
        self.card_type = card_type
        self.proficient_positions = proficient_positions
        self.semiproficient_positions = semiproficient_positions


class Assignment:
    def __init__(self, slot, player, jersey):
        self.slot = slot
        self.player = player
        self.jersey = jersey


DEFAULT_FORMATION = ["CF", "LWF", "RWF", "AMF", "CMF", "DMF", "LB", "CB", "CB", "RB", "GK"]
FORMATION = DEFAULT_FORMATION[:]

NON_STANDARD = {"epic", "bigtime", "showtime", "highlight"}


def load_roles(conn, country_name):
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(game_data)")
    columns = [row[1] for row in cur.fetchall()]
    if "country" not in columns:
        raise RuntimeError(
            "game_data is not country-scoped yet. Run fetch_game_data.py again for your countries."
        )

    cur.execute(
        """
        SELECT gd.player_id, p.name, gd.position, gd.rating, gd.recent, gd.card_type,
               gd.proficient_positions, gd.semiproficient_positions
        FROM game_data gd
        JOIN players p ON gd.player_id = p.player_id
        WHERE gd.country = ?
        """,
        (country_name,),
    )
    roles_by_pos = {}
    for pid, name, pos, rating, recent, card_type, profs, semis in cur.fetchall():
        main_pos = pos.strip().upper()
        recent_flag = bool(recent)
        prof_list = []
        if profs:
            prof_list = [x.strip().upper() for x in profs.split(",") if x.strip()]
        semi_list = []
        if semis:
            semi_list = [x.strip().upper() for x in semis.split(",") if x.strip()]
        role = PlayerRole(
            player_id=str(pid),
            name=name,
            position=main_pos,
            rating=float(rating),
            recent=recent_flag,
            card_type=(card_type or "").strip(),
            proficient_positions=set(prof_list),
            semiproficient_positions=set(semi_list),
        )
        roles_by_pos.setdefault(main_pos, []).append(role)
    return roles_by_pos


def load_formation(formation_file):
    if not os.path.exists(formation_file):
        return DEFAULT_FORMATION[:]
    with open(formation_file, "r", encoding="utf-8") as f:
        raw_lines = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
    slots = []
    for line in raw_lines:
        parts = [p.strip().upper() for p in line.split(",") if p.strip()]
        slots.extend(parts)
    if not slots:
        return DEFAULT_FORMATION[:]
    return slots


def resolve_country_paths(country_folder):
    folder = country_folder.strip()
    country_name = os.path.basename(os.path.normpath(folder))
    formation_file = os.path.join(folder, f"{country_name}_formation.txt")
    output_file = os.path.join(folder, f"{country_name}.txt")
    return formation_file, output_file


def is_standard(p):
    return p.card_type.strip().lower() not in NON_STANDARD


def pick_best(candidates):
    if not candidates:
        return None
    return max(candidates, key=lambda r: r.rating)


def choose_initial_lineup(roles_by_pos):
    slot_count = len(FORMATION)
    slots = FORMATION[:]

    def available_roles_for_sub(slot, used_ids):
        direct_roles = roles_by_pos.get(slot, [])

        nonstd = [
            r for r in direct_roles if r.player_id not in used_ids and not is_standard(r)
        ]

        if slot in ("LWF", "RWF") and not nonstd:
            ss_roles = roles_by_pos.get("SS", [])
            nonstd = [
                r for r in ss_roles if r.player_id not in used_ids and not is_standard(r)
            ]

        if nonstd:
            return nonstd

        std = [
            r for r in direct_roles if r.player_id not in used_ids and is_standard(r)
        ]
        if slot in ("LWF", "RWF") and not std:
            return []
        return std

    all_roles = []
    for lst in roles_by_pos.values():
        all_roles.extend(lst)

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

    starters = [None] * slot_count
    used_ids = set()
    empty_slots = set(range(slot_count))

    def cand_stage_a(slot, used_ids):
        return [
            r
            for r in roles_by_pos.get(slot, [])
            if r.player_id not in used_ids and not is_standard(r)
        ]

    stage_a_filled = fill_starters_stage(empty_slots, used_ids, cand_stage_a)
    for idx in range(slot_count):
        if stage_a_filled[idx] is not None:
            starters[idx] = stage_a_filled[idx]
            used_ids.add(starters[idx].player_id)
            empty_slots.discard(idx)

    def cand_stage_b(slot, used_ids):
        return [
            r
            for r in all_roles
            if r.player_id not in used_ids
            and (slot in r.proficient_positions)
            and not is_standard(r)
        ]

    stage_b_filled = fill_starters_stage(empty_slots, used_ids, cand_stage_b)
    for idx in range(slot_count):
        if stage_b_filled[idx] is not None:
            starters[idx] = stage_b_filled[idx]
            used_ids.add(starters[idx].player_id)
            empty_slots.discard(idx)

    def cand_stage_c(slot, used_ids):
        return [
            r
            for r in roles_by_pos.get(slot, [])
            if r.player_id not in used_ids and is_standard(r)
        ]

    stage_c_filled = fill_starters_stage(empty_slots, used_ids, cand_stage_c)
    for idx in range(slot_count):
        if stage_c_filled[idx] is not None:
            starters[idx] = stage_c_filled[idx]
            used_ids.add(starters[idx].player_id)
            empty_slots.discard(idx)

    def cand_stage_d(slot, used_ids):
        return [
            r
            for r in all_roles
            if r.player_id not in used_ids
            and (slot in r.proficient_positions)
            and is_standard(r)
        ]

    stage_d_filled = fill_starters_stage(empty_slots, used_ids, cand_stage_d)
    for idx in range(slot_count):
        if stage_d_filled[idx] is not None:
            starters[idx] = stage_d_filled[idx]
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
            candidates = available_roles_for_sub(slot, used_for_subs)
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


def load_jersey_stats(conn, player_id):
    cur = conn.cursor()
    cur.execute(
        "SELECT number FROM jersey WHERE player_id = ? ORDER BY idx ASC",
        (player_id,),
    )
    rows = cur.fetchall()
    if not rows:
        return None, [], []
    all_nums = [int(r[0]) for r in rows]
    most_recent = all_nums[0]
    recent_slice = all_nums[:10]

    def pref_list(nums):
        counts = {}
        first_idx = {}
        for idx, n in enumerate(nums):
            counts[n] = counts.get(n, 0) + 1
            if n not in first_idx:
                first_idx[n] = idx
        return [n for n, _ in sorted(counts.items(), key=lambda kv: (-kv[1], first_idx[kv[0]], kv[0]))]

    overall_prefs = pref_list(all_nums)
    recent_prefs = pref_list(recent_slice)
    return most_recent, overall_prefs, recent_prefs


def card_priority(card_type):
    ct = card_type.lower()
    if ct in ("epic", "bigtime"):
        return 0
    if ct == "showtime":
        return 1
    if ct == "highlight":
        return 2
    return 3


def jersey_prefs_for_player(conn, p):
    most_recent, overall_prefs, recent_prefs = load_jersey_stats(conn, p.player_id)
    ct = p.card_type.lower()
    if ct == "epic":
        prefs = overall_prefs
    elif ct == "bigtime":
        cur = conn.cursor()
        cur.execute(
            "SELECT number FROM jersey WHERE player_id = ? ORDER BY idx ASC",
            (p.player_id,),
        )
        seq_rows = cur.fetchall()
        seq = [int(r[0]) for r in seq_rows]
        seen = set()
        ordered_unique = []
        for n in seq:
            if n not in seen:
                seen.add(n)
                ordered_unique.append(n)
        prefs = ordered_unique
    else:
        cur = conn.cursor()
        cur.execute(
            "SELECT number FROM jersey WHERE player_id = ? ORDER BY idx ASC",
            (p.player_id,),
        )
        seq_rows = cur.fetchall()
        seq = [int(r[0]) for r in seq_rows]
        seen = set()
        ordered_unique = []
        for n in seq:
            if n not in seen:
                seen.add(n)
                ordered_unique.append(n)
        prefs = ordered_unique
    return most_recent, prefs


def try_assign_jersey_for_player(conn, p, used_numbers, assignments):
    if p is None:
        return None
    if p.player_id in assignments:
        return assignments[p.player_id]
    most_recent, prefs = jersey_prefs_for_player(conn, p)
    if p.recent and most_recent is not None and most_recent not in used_numbers:
        assignments[p.player_id] = most_recent
        used_numbers.add(most_recent)
        return most_recent
    for num in prefs:
        if num not in used_numbers:
            assignments[p.player_id] = num
            used_numbers.add(num)
            return num
    return None


def try_assign_jersey_for_player_blocked(conn, p, used_numbers, assignments, blocked_numbers):
    if p is None:
        return None
    if p.player_id in assignments:
        num = assignments[p.player_id]
        return None if num in blocked_numbers else num
    most_recent, prefs = jersey_prefs_for_player(conn, p)
    if p.recent and most_recent is not None and most_recent not in used_numbers and most_recent not in blocked_numbers:
        assignments[p.player_id] = most_recent
        used_numbers.add(most_recent)
        return most_recent
    for num in prefs:
        if num in used_numbers or num in blocked_numbers:
            continue
        assignments[p.player_id] = num
        used_numbers.add(num)
        return num
    return None


def choose_jersey_for_player(conn, p, used_numbers, assignments, blocked_numbers, fallback_reserved=None):
    if p is None:
        return None
    blocked = blocked_numbers if blocked_numbers is not None else set()
    if p.player_id in assignments:
        num = assignments[p.player_id]
        return None if num in blocked else num
    most_recent, prefs = jersey_prefs_for_player(conn, p)
    if p.recent and most_recent is not None and most_recent not in used_numbers and most_recent not in blocked:
        return most_recent
    for pref_idx, num in enumerate(prefs):
        if num in used_numbers or num in blocked:
            continue
        if pref_idx > 0 and not p.recent and fallback_reserved and num in fallback_reserved:
            continue
        return num
    return None


def assign_group_jerseys(
    conn,
    players,
    used_numbers,
    assignments,
    allow_recent_lock,
    fallback_reserved=None,
):
    most_recent_map = {}
    prefs_map = {}

    for p in players:
        if p.player_id not in most_recent_map:
            mr, prefs = jersey_prefs_for_player(conn, p)
            most_recent_map[p.player_id] = mr
            prefs_map[p.player_id] = prefs

    if allow_recent_lock:
        for p in players:
            if p.recent:
                mr = most_recent_map.get(p.player_id)
                if mr is not None and mr not in used_numbers and p.player_id not in assignments:
                    assignments[p.player_id] = mr
                    used_numbers.add(mr)

    buckets = {0: [], 1: [], 2: [], 3: []}
    for p in players:
        if p.player_id in assignments:
            continue
        buckets[card_priority(p.card_type)].append(p)

    for prio in range(4):
        prio_players = sorted(buckets[prio], key=lambda r: (0 if r.recent else 1, -r.rating))
        for p in prio_players:
            if p.player_id in assignments:
                continue
            prefs = prefs_map.get(p.player_id, [])
            for pref_idx, num in enumerate(prefs):
                if num in used_numbers:
                    continue
                if pref_idx > 0:
                    if not p.recent and fallback_reserved and num in fallback_reserved:
                        continue
                    blocked_by_other_first_choice = False
                    for other in prio_players:
                        if other.player_id == p.player_id or other.player_id in assignments:
                            continue
                        other_prefs = prefs_map.get(other.player_id, [])
                        if other_prefs and other_prefs[0] == num:
                            blocked_by_other_first_choice = True
                            break
                    if blocked_by_other_first_choice:
                        continue
                assignments[p.player_id] = num
                used_numbers.add(num)
                break


def assign_jerseys(conn, starters, subs, recent_soft_reserved=None):
    starter_players_all = [p for p in starters if p is not None]
    sub_players_all = [p for p in subs if p is not None]

    starter_nonstd = [p for p in starter_players_all if not is_standard(p)]
    starter_std = [p for p in starter_players_all if is_standard(p)]

    sub_ss_nonstd = []
    sub_nonstd_normal = []
    sub_std = []
    for slot, p in zip(FORMATION, subs):
        if p is None:
            continue
        if is_standard(p):
            sub_std.append(p)
        else:
            if slot in ("LWF", "RWF") and p.position == "SS":
                sub_ss_nonstd.append(p)
            else:
                sub_nonstd_normal.append(p)

    used_numbers = set()
    assignments = {}

    assign_group_jerseys(conn, starter_nonstd, used_numbers, assignments, allow_recent_lock=True)
    assign_group_jerseys(conn, sub_nonstd_normal, used_numbers, assignments, allow_recent_lock=True, fallback_reserved=recent_soft_reserved)
    assign_group_jerseys(conn, sub_ss_nonstd, used_numbers, assignments, allow_recent_lock=True, fallback_reserved=recent_soft_reserved)
    assign_group_jerseys(conn, starter_std, used_numbers, assignments, allow_recent_lock=True)
    assign_group_jerseys(conn, sub_std, used_numbers, assignments, allow_recent_lock=True, fallback_reserved=recent_soft_reserved)
    return assignments, used_numbers


def next_candidate_for_slot(slot, roles_by_pos, used_ids, excluded_ids, subs=None):
    candidates = [r for r in roles_by_pos.get(slot, []) if r.player_id not in excluded_ids and (r.player_id not in used_ids or (subs and any(sp and sp.player_id == r.player_id for sp in subs)))]
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
    ss_candidates = [r for r in roles_by_pos.get("SS", []) if r.player_id not in excluded_ids and (r.player_id not in used_ids or (subs and any(sp and sp.player_id == r.player_id for sp in subs)))]
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

        recent_soft_reserved = set()
        for p in starters + subs:
            if p is not None and p.recent:
                mr, _, _ = load_jersey_stats(conn, p.player_id)
                if mr is not None:
                    recent_soft_reserved.add(mr)

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
                if FORMATION[i] in ("LWF", "RWF"):
                    repl = next_candidate_for_sub_wing(FORMATION[i], roles_by_pos, used_ids - {p.player_id}, excluded, subs)
                else:
                    repl = next_candidate_for_slot(FORMATION[i], roles_by_pos, used_ids - {p.player_id}, excluded, subs)
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
            for j, sp in enumerate(subs):
                if sp is not None:
                    continue
                excluded = sub_excluded.setdefault(j, set())
                slot = FORMATION[j]
                if slot in ("LWF", "RWF"):
                    repl = next_candidate_for_sub_wing(slot, roles_by_pos, used_ids, excluded)
                else:
                    repl = next_candidate_for_slot(slot, roles_by_pos, used_ids, excluded)
                subs[j] = repl
                if repl is not None:
                    used_ids.add(repl.player_id)

        if replaced:
            used_ids = {p.player_id for p in (starters + subs) if p is not None}
            for j, sp in enumerate(subs):
                if sp is not None:
                    continue
                excluded = sub_excluded.setdefault(j, set())
                slot = FORMATION[j]
                if slot in ("LWF", "RWF"):
                    repl = next_candidate_for_sub_wing(slot, roles_by_pos, used_ids, excluded)
                else:
                    repl = next_candidate_for_slot(slot, roles_by_pos, used_ids, excluded)
                subs[j] = repl
                if repl is not None:
                    used_ids.add(repl.player_id)

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
        result = set()
        for p in starters + subs:
            if p is not None and p.recent:
                mr, _, _ = load_jersey_stats(conn, p.player_id)
                if mr is not None:
                    result.add(mr)
        return result

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

                    num = choose_jersey_for_player(conn, r, used_numbers, assignments, blocked_numbers, fallback_reserved=recent_soft_reserved)
                    if num is None and r.recent:
                        num = try_free_jersey_via_swap(
                            conn, r, used_numbers, assignments,
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
        stage_order = [
            ("main", False),
            ("main", True),
            ("proficient", False),
            ("proficient", True),
            ("semiproficient", False),
            ("semiproficient", True),
        ]
        for pos_set_name, want_standard in stage_order:
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
                    num = choose_jersey_for_player(conn, candidate, used_numbers, assignments, None, fallback_reserved=dyn_reserved)
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
        stage_order = [
            ("main", False),
            ("main", True),
            ("proficient", False),
            ("proficient", True),
            ("semiproficient", False),
            ("semiproficient", True),
        ]
        while True:
            vacant_indices = [i for i, p in enumerate(subs) if p is None]
            if not vacant_indices:
                break

            best_swap = None
            best_rating = -1e18

            for vacant_idx in vacant_indices:
                vacant_slot = FORMATION[vacant_idx]
                for pos_set_name, want_standard in stage_order:
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
    fill_vacancies(
        [i for i, p in enumerate(subs) if p is None],
        subs,
        "main",
        want_standard=True,
        blocked_numbers=None,
        update_blocked=False,
        allow_from_subs=False,
    )
    used_ids = {p.player_id for p in (starters + subs) if p is not None}
    fill_vacancies(
        [i for i, p in enumerate(subs) if p is None],
        subs,
        "proficient",
        want_standard=False,
        blocked_numbers=None,
        update_blocked=False,
        allow_from_subs=False,
    )
    used_ids = {p.player_id for p in (starters + subs) if p is not None}
    fill_vacancies(
        [i for i, p in enumerate(subs) if p is None],
        subs,
        "proficient",
        want_standard=True,
        blocked_numbers=None,
        update_blocked=False,
        allow_from_subs=False,
    )
    used_ids = {p.player_id for p in (starters + subs) if p is not None}
    fill_vacancies(
        [i for i, p in enumerate(subs) if p is None],
        subs,
        "semiproficient",
        want_standard=False,
        blocked_numbers=None,
        update_blocked=False,
        allow_from_subs=False,
    )
    used_ids = {p.player_id for p in (starters + subs) if p is not None}
    fill_vacancies(
        [i for i, p in enumerate(subs) if p is None],
        subs,
        "semiproficient",
        want_standard=True,
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
    all_roles = []
    for lst in roles_by_pos.values():
        for r in lst:
            if r.player_id not in used_ids:
                all_roles.append(r)
    wildcard_asg = None
    for candidate in sorted(all_roles, key=lambda r: r.rating, reverse=True):
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


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        country_folder = sys.argv[1] if len(sys.argv) > 1 else "belgium"
        country_name = os.path.basename(os.path.normpath(country_folder.strip()))
        formation_file, out_path = resolve_country_paths(country_folder)

        global FORMATION
        FORMATION = load_formation(formation_file)

        roles_by_pos = load_roles(conn, country_name)
        if not roles_by_pos:
            raise RuntimeError(
                f"No game_data rows found for country '{country_name}'. Run fetch_game_data.py {country_name} first."
            )
        starter_asg, sub_asg, wildcard_asg = build_gameplan(conn, roles_by_pos)

        lines = []
        lines.append("Starters:")
        for slot, a in zip(FORMATION, starter_asg):
            if a is None:
                lines.append(f"  [{slot}] VACANT")
            else:
                lines.append(
                    f"  [{a.slot}] {a.player.name} ({a.player.position}) rating {a.player.rating:.2f} #{a.jersey}"
                )

        lines.append("")
        lines.append("Substitutes:")
        for slot, a in zip(FORMATION, sub_asg):
            if a is None:
                lines.append(f"  [{slot}] VACANT")
            else:
                lines.append(
                    f"  [{a.slot}] {a.player.name} ({a.player.position}) rating {a.player.rating:.2f} #{a.jersey}"
                )

        if wildcard_asg is not None:
            lines.append("")
            lines.append("Wildcard:")
            a = wildcard_asg
            lines.append(f"  [{a.slot}] {a.player.name} ({a.player.position}) rating {a.player.rating:.2f} #{a.jersey}")

        text = "\n".join(lines) + "\n"
        print(text, end="")

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

