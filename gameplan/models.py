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
