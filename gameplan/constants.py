DB_PATH = "pes.db"

SUB_WING_SLOTS = frozenset({"LWF", "RWF"})
NON_STANDARD = frozenset({"epic", "bigtime", "showtime", "highlight"})

MATCH_STAGES = (
    ("main", False),
    ("main", True),
    ("proficient", False),
    ("proficient", True),
    ("semiproficient", False),
    ("semiproficient", True),
)


def is_standard(p):
    return p.card_type.strip().lower() not in NON_STANDARD
