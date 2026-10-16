import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pes.db")

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
