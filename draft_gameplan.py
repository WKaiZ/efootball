import os
import sqlite3
import sys

DB_PATH = "pes.db"


class PlayerRole:
    def __init__(self, player_id, name, position, rating, recent, card_type):
        self.player_id = player_id
        self.name = name
        self.position = position
        self.rating = rating
        self.recent = recent
        self.card_type = card_type


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
               gd.proficient_positions
        FROM game_data gd
        JOIN players p ON gd.player_id = p.player_id
        WHERE gd.country = ?
        """
        ,
        (country_name,),
    )
    roles_by_pos = {}
    for pid, name, pos, rating, recent, card_type, profs in cur.fetchall():
        main_pos = pos.strip().upper()
        recent_flag = bool(recent)
        role = PlayerRole(
            player_id=str(pid),
            name=name,
            position=main_pos,
            rating=float(rating),
            recent=recent_flag,
            card_type=(card_type or "").strip(),
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
    starters = []
    used_ids = set()
    for slot in FORMATION:
        slot_candidates = [r for r in roles_by_pos.get(slot, []) if r.player_id not in used_ids]
        non_std = [r for r in slot_candidates if not is_standard(r)]
        best = pick_best(non_std)
        if best is None:
            std = [r for r in slot_candidates if is_standard(r)]
            best = pick_best(std)
        starters.append(best)
        if best is not None:
            used_ids.add(best.player_id)

    subs = []
    for slot in FORMATION:
        slot_candidates = [r for r in roles_by_pos.get(slot, []) if r.player_id not in used_ids]
        non_std = [r for r in slot_candidates if not is_standard(r)]
        best = pick_best(non_std)

        if best is None and slot in ("LWF", "RWF"):
            ss_candidates = [r for r in roles_by_pos.get("SS", []) if r.player_id not in used_ids and not is_standard(r)]
            best = pick_best(ss_candidates)

        if best is None:
            std = [r for r in slot_candidates if is_standard(r)]
            best = pick_best(std)

        subs.append(best)
        if best is not None:
            used_ids.add(best.player_id)

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
        for n in nums:
            counts[n] = counts.get(n, 0) + 1
        return [n for n, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

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


def assign_group_jerseys(
    conn,
    players,
    used_numbers,
    assignments,
    allow_recent_lock,
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
        prio_players = sorted(buckets[prio], key=lambda r: r.rating, reverse=True)
        for p in prio_players:
            prefs = prefs_map.get(p.player_id, [])
            for num in prefs:
                if num in used_numbers:
                    continue
                assignments[p.player_id] = num
                used_numbers.add(num)
                break


def assign_jerseys(conn, starters, subs):
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

    most_recent_map = {}
    prefs_map = {}
    used_numbers = set()
    assignments = {}

    assign_group_jerseys(conn, starter_nonstd, used_numbers, assignments, allow_recent_lock=True)
    assign_group_jerseys(conn, sub_nonstd_normal, used_numbers, assignments, allow_recent_lock=True)
    assign_group_jerseys(conn, sub_ss_nonstd, used_numbers, assignments, allow_recent_lock=True)
    assign_group_jerseys(conn, starter_std, used_numbers, assignments, allow_recent_lock=True)
    assign_group_jerseys(conn, sub_std, used_numbers, assignments, allow_recent_lock=True)
    return assignments, used_numbers


def next_candidate_for_slot(slot, roles_by_pos, used_ids, excluded_ids):
    candidates = [r for r in roles_by_pos.get(slot, []) if r.player_id not in used_ids and r.player_id not in excluded_ids]
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
):
    repl = next_candidate_for_slot(slot, roles_by_pos, used_ids, excluded_ids)
    if repl is not None:
        return repl
    ss_candidates = [r for r in roles_by_pos.get("SS", []) if r.player_id not in used_ids and r.player_id not in excluded_ids and not is_standard(r)]
    if not ss_candidates:
        return None
    return max(ss_candidates, key=lambda r: r.rating)


def build_gameplan(conn, roles_by_pos):
    starters, subs = choose_initial_lineup(roles_by_pos)
    if not all_unique(starters + subs):
        raise RuntimeError("Internal error: duplicate player_id selected.")

    attempts = 0
    starter_excluded = {}
    sub_excluded = {}
    while attempts < 50:
        attempts += 1
        assignments, used_numbers = assign_jerseys(conn, starters, subs)
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
            for i, p in enumerate(subs):
                if p is None:
                    continue
                if p.player_id in assignments:
                    continue
                excluded = sub_excluded.setdefault(i, set())
                excluded.add(p.player_id)
                if FORMATION[i] in ("LWF", "RWF"):
                    repl = next_candidate_for_sub_wing(FORMATION[i], roles_by_pos, used_ids - {p.player_id}, excluded)
                else:
                    repl = next_candidate_for_slot(FORMATION[i], roles_by_pos, used_ids - {p.player_id}, excluded)
                subs[i] = repl
                replaced = True
                break

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

        if not replaced:
            break

    assignments, used_numbers = assign_jerseys(conn, starters, subs)

    starter_asg = []
    for slot, p in zip(FORMATION, starters):
        if p is None:
            continue
        jersey = assignments.get(p.player_id)
        if jersey is None:
            continue
        starter_asg.append(Assignment(slot=slot, player=p, jersey=jersey))

    sub_asg = []
    for slot, p in zip(FORMATION, subs):
        if p is None:
            continue
        jersey = assignments.get(p.player_id)
        if jersey is None:
            continue
        sub_asg.append(Assignment(slot=slot, player=p, jersey=jersey))

    used_ids = {a.player.player_id for a in starter_asg + sub_asg}
    all_roles = []
    for lst in roles_by_pos.values():
        for r in lst:
            if r.player_id not in used_ids:
                all_roles.append(r)
    wildcard_asg = None
    for candidate in sorted(all_roles, key=lambda r: r.rating, reverse=True):
        _mr, prefs = jersey_prefs_for_player(conn, candidate)
        for n in prefs:
            if n not in used_numbers:
                wildcard_asg = Assignment(slot="WILD", player=candidate, jersey=n)
                break
        if wildcard_asg is not None:
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
        for a in starter_asg:
            lines.append(f"  [{a.slot}] {a.player.name} ({a.player.position}) rating {a.player.rating:.2f} #{a.jersey}")

        lines.append("")
        lines.append("Substitutes:")
        for a in sub_asg:
            lines.append(f"  [{a.slot}] {a.player.name} ({a.player.position}) rating {a.player.rating:.2f} #{a.jersey}")

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

