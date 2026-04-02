from gameplan.constants import SUB_WING_SLOTS, is_standard
from gameplan.formation import FORMATION


def _pref_list(nums):
    counts = {}
    first_idx = {}
    for idx, n in enumerate(nums):
        counts[n] = counts.get(n, 0) + 1
        if n not in first_idx:
            first_idx[n] = idx
    return [n for n, _ in sorted(counts.items(), key=lambda kv: (-kv[1], first_idx[kv[0]], kv[0]))]


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
    overall_prefs = _pref_list(all_nums)
    recent_prefs = _pref_list(recent_slice)
    return most_recent, overall_prefs, recent_prefs


def _ordered_unique_jersey_sequence(conn, player_id):
    cur = conn.cursor()
    cur.execute(
        "SELECT number FROM jersey WHERE player_id = ? ORDER BY idx ASC",
        (player_id,),
    )
    seq = [int(r[0]) for r in cur.fetchall()]
    seen = set()
    ordered_unique = []
    for n in seq:
        if n not in seen:
            seen.add(n)
            ordered_unique.append(n)
    return ordered_unique


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
    most_recent, overall_prefs, _recent_prefs = load_jersey_stats(conn, p.player_id)
    ct = p.card_type.lower()
    if ct == "epic":
        prefs = overall_prefs
    else:
        prefs = _ordered_unique_jersey_sequence(conn, p.player_id)
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


def _assign_epic_nonrecent_greedy(
    players, used_numbers, assignments, most_recent_map, prefs_map
):
    epic_nr = [
        p
        for p in players
        if p.player_id not in assignments
        and card_priority(p.card_type) == 0
        and not p.recent
    ]
    prio_players = sorted(epic_nr, key=lambda r: -r.rating)
    bench_recent_non_epic = [
        q
        for q in players
        if q.recent and card_priority(q.card_type) > 0 and q.player_id not in assignments
    ]
    for p in prio_players:
        prefs = prefs_map.get(p.player_id, [])
        for pref_idx, num in enumerate(prefs):
            if num in used_numbers:
                continue
            blocked_by_recent_mr = False
            for q in bench_recent_non_epic:
                mq = most_recent_map.get(q.player_id)
                if mq is None or mq != num:
                    continue
                if (
                    pref_idx > 0
                    and p.rating > q.rating
                    and most_recent_map.get(p.player_id) != num
                ):
                    continue
                blocked_by_recent_mr = True
                break
            if blocked_by_recent_mr:
                continue
            if pref_idx > 0:
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


def _assign_substitute_group(
    conn,
    players,
    used_numbers,
    assignments,
):
    if not players:
        return
    most_recent_map = {}
    prefs_map = {}
    for p in players:
        if p.player_id not in most_recent_map:
            mr, prefs = jersey_prefs_for_player(conn, p)
            most_recent_map[p.player_id] = mr
            prefs_map[p.player_id] = prefs

    _assign_epic_nonrecent_greedy(
        players, used_numbers, assignments, most_recent_map, prefs_map
    )

    for p in sorted(
        (
            x
            for x in players
            if x.player_id not in assignments
            and x.recent
            and card_priority(x.card_type) > 0
        ),
        key=lambda r: -r.rating,
    ):
        mr = most_recent_map.get(p.player_id)
        if mr is not None and mr not in used_numbers:
            assignments[p.player_id] = mr
            used_numbers.add(mr)

    remaining = [p for p in players if p.player_id not in assignments]
    if remaining:
        assign_group_jerseys(
            conn,
            remaining,
            used_numbers,
            assignments,
            allow_recent_lock=True,
            recent_lock_global=False,
        )


def assign_group_jerseys(
    conn,
    players,
    used_numbers,
    assignments,
    allow_recent_lock,
    recent_lock_global=False,
):
    most_recent_map = {}
    prefs_map = {}

    for p in players:
        if p.player_id not in most_recent_map:
            mr, prefs = jersey_prefs_for_player(conn, p)
            most_recent_map[p.player_id] = mr
            prefs_map[p.player_id] = prefs

    if allow_recent_lock and recent_lock_global:
        for p in sorted(players, key=lambda r: -r.rating):
            if p.player_id in assignments:
                continue
            if not p.recent:
                continue
            mr = most_recent_map.get(p.player_id)
            if mr is not None and mr not in used_numbers:
                assignments[p.player_id] = mr
                used_numbers.add(mr)

    buckets = {0: [], 1: [], 2: [], 3: []}
    for p in players:
        if p.player_id in assignments:
            continue
        buckets[card_priority(p.card_type)].append(p)

    for prio in range(4):
        prio_players = sorted(buckets[prio], key=lambda r: -r.rating)
        if allow_recent_lock and not recent_lock_global:
            for p in prio_players:
                if p.player_id in assignments:
                    continue
                if not p.recent:
                    continue
                mr = most_recent_map.get(p.player_id)
                if mr is not None and mr not in used_numbers:
                    assignments[p.player_id] = mr
                    used_numbers.add(mr)
        for p in prio_players:
            if p.player_id in assignments:
                continue
            prefs = prefs_map.get(p.player_id, [])
            for pref_idx, num in enumerate(prefs):
                if num in used_numbers:
                    continue
                if pref_idx > 0:
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


def assign_jerseys(conn, starters, subs):
    starter_main_nonstd = []
    starter_main_std = []
    starter_prof_nonstd = []
    starter_prof_std = []
    for slot, p in zip(FORMATION, starters):
        if p is None:
            continue
        if p.position == slot:
            if is_standard(p):
                starter_main_std.append(p)
            else:
                starter_main_nonstd.append(p)
        else:
            if is_standard(p):
                starter_prof_std.append(p)
            else:
                starter_prof_nonstd.append(p)

    sub_ss_nonstd = []
    sub_nonstd_normal = []
    sub_std = []
    for slot, p in zip(FORMATION, subs):
        if p is None:
            continue
        if is_standard(p):
            sub_std.append(p)
        else:
            if slot in SUB_WING_SLOTS and p.position == "SS":
                sub_ss_nonstd.append(p)
            else:
                sub_nonstd_normal.append(p)

    used_numbers = set()
    assignments = {}

    assign_group_jerseys(
        conn,
        starter_main_nonstd,
        used_numbers,
        assignments,
        allow_recent_lock=True,
        recent_lock_global=True,
    )
    assign_group_jerseys(
        conn,
        starter_prof_nonstd,
        used_numbers,
        assignments,
        allow_recent_lock=True,
        recent_lock_global=True,
    )
    _assign_substitute_group(conn, sub_nonstd_normal, used_numbers, assignments)
    _assign_substitute_group(conn, sub_ss_nonstd, used_numbers, assignments)
    assign_group_jerseys(
        conn,
        starter_main_std,
        used_numbers,
        assignments,
        allow_recent_lock=True,
        recent_lock_global=True,
    )
    assign_group_jerseys(
        conn,
        starter_prof_std,
        used_numbers,
        assignments,
        allow_recent_lock=True,
        recent_lock_global=True,
    )
    _assign_substitute_group(conn, sub_std, used_numbers, assignments)
    return assignments, used_numbers
