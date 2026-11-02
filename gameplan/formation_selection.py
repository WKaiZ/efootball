from gameplan.builder import build_gameplan
from gameplan.formation import DEFAULT_FORMATION, FORMATION


_ALTERNATES = {
    "LWF": ("LMF",),
    "RWF": ("RMF",),
    "CF": ("SS",),
    "AMF": ("SS",),
}
_SPECIAL_TIER = {"SHOWTIME": 1, "EPIC": 2, "BIGTIME": 2}


def _rendered_special_tier(assignments, slot_index, position):
    tier = 0
    for lineup in assignments[:2]:
        if slot_index >= len(lineup):
            continue
        assignment = lineup[slot_index]
        if assignment is not None and assignment.player.position == position:
            tier = max(
                tier,
                _SPECIAL_TIER.get(assignment.player.card_type.strip().upper(), 0),
            )
    return tier


def choose_formation(conn, roles_by_pos, base_formation=None):
    selected = list(base_formation or DEFAULT_FORMATION)
    FORMATION[:] = selected
    rendered = build_gameplan(conn, roles_by_pos)
    for slot_index, position in enumerate(selected):
        for alternate in _ALTERNATES.get(position, ()):
            current_tier = _rendered_special_tier(rendered, slot_index, position)

            trial = selected[:]
            trial[slot_index] = alternate
            FORMATION[:] = trial
            candidate = build_gameplan(conn, roles_by_pos)
            candidate_tier = _rendered_special_tier(candidate, slot_index, alternate)
            if candidate_tier > current_tier:
                selected = trial
                rendered = candidate

    FORMATION[:] = selected
    return selected
