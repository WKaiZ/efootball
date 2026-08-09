import os

from country_locator import resolve_country_dir
from gameplan.formation import DEFAULT_FORMATION
from gameplan.models import PlayerRole


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


def _parse_formation_block(lines):
    slots = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = [p.strip().upper() for p in stripped.split(",") if p.strip()]
        slots.extend(parts)
    return slots


def load_formations(formation_file):
    """Return (primary_formation, secondary_formation_or_None).

    Blocks in ``*_formation.txt`` are separated by a blank line. The first
    non-empty block is the primary (first-squad) formation. If a second block
    is present it is used for the contender second squad; otherwise the second
    squad reuses the primary formation.
    """
    if not os.path.exists(formation_file):
        return DEFAULT_FORMATION[:], None

    with open(formation_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    blocks = []
    current = []
    for line in lines:
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)

    formations = []
    for block in blocks:
        slots = _parse_formation_block(block)
        if slots:
            formations.append(slots)

    if not formations:
        return DEFAULT_FORMATION[:], None
    if len(formations) == 1:
        return formations[0], None
    return formations[0], formations[1]


def load_formation(formation_file):
    primary, _secondary = load_formations(formation_file)
    return primary


def resolve_country_paths(country_folder):
    folder = resolve_country_dir(country_folder)
    country_name = os.path.basename(os.path.normpath(folder))
    formation_file = os.path.join(folder, f"{country_name}_formation.txt")
    output_file = os.path.join(folder, f"{country_name}.txt")
    return formation_file, output_file
