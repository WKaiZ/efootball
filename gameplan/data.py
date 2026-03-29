import os

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
