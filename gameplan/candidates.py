# Thin utility module — public helpers used by builder.py.

def find_player_index(players, player_id):
    """Return the index of player_id in players list, or None."""
    for i, p in enumerate(players):
        if p is not None and p.player_id == player_id:
            return i
    return None
