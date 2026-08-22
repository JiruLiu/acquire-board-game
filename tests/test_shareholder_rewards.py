import unittest

from app import Player, Room, shareholder_reward_allocations


class ShareholderRewardAllocationTests(unittest.TestCase):
    def make_room(self, share_counts: list[int]) -> Room:
        players = []
        for index, shares in enumerate(share_counts):
            player = Player(id=f"p{index}", name=f"Player{index}")
            player.stocks["purple"] = shares
            players.append(player)

        room = Room(
            id="TEST",
            name="Reward test",
            password="pw",
            creator_id=players[0].id,
            players=players,
            board={
                "E11": {"placed_by": players[0].name, "company": "purple"},
                "E12": {"placed_by": players[0].name, "company": "purple"},
            },
        )
        room.companies_found["purple"] = True
        return room

    def allocations_for(self, share_counts: list[int]) -> tuple[list[dict], dict[str, int]]:
        return shareholder_reward_allocations(self.make_room(share_counts), "purple")

    def test_single_stockholder_gets_primary_and_tertiary(self):
        details, awards = self.allocations_for([5])

        self.assertEqual(awards, {"p0": 4500})
        self.assertEqual([detail["rank"] for detail in details], ["first and third"])

    def test_only_two_stockholders_ignore_tertiary(self):
        _details, awards = self.allocations_for([5, 4])

        self.assertEqual(awards, {"p0": 3000, "p1": 2200})

    def test_three_distinct_stockholders_receive_each_rank(self):
        _details, awards = self.allocations_for([5, 4, 3])

        self.assertEqual(awards, {"p0": 3000, "p1": 2200, "p2": 1500})

    def test_tied_primary_then_next_group_gets_tertiary(self):
        details, awards = self.allocations_for([2, 2, 1])

        self.assertEqual(awards, {"p0": 2600, "p1": 2600, "p2": 1500})
        self.assertEqual([detail["rank"] for detail in details], ["tied first", "third"])

    def test_three_way_primary_tie_shares_all_rewards_and_ends_distribution(self):
        details, awards = self.allocations_for([5, 5, 5, 1])

        self.assertEqual(
            awards,
            {"p0": 2300, "p1": 2300, "p2": 2300},
        )
        self.assertEqual([detail["rank"] for detail in details], ["tied first"])

    def test_two_way_primary_tie_then_next_group_shares_tertiary(self):
        details, awards = self.allocations_for([5, 5, 4, 4])

        self.assertEqual(
            awards,
            {"p0": 2600, "p1": 2600, "p2": 800, "p3": 800},
        )
        self.assertEqual([detail["rank"] for detail in details], ["tied first", "tied third"])

    def test_tied_secondary_combines_secondary_and_tertiary_and_rounds_up(self):
        details, awards = self.allocations_for([5, 4, 4, 1])

        self.assertEqual(awards, {"p0": 3000, "p1": 1900, "p2": 1900})
        self.assertEqual([detail["rank"] for detail in details], ["first", "tied second"])

    def test_tied_tertiary_splits_tertiary_and_rounds_up(self):
        details, awards = self.allocations_for([5, 4, 1, 1])

        self.assertEqual(
            awards,
            {"p0": 3000, "p1": 2200, "p2": 800, "p3": 800},
        )
        self.assertEqual(
            [detail["rank"] for detail in details],
            ["first", "second", "tied third"],
        )

    def test_zero_stock_holders_are_excluded_from_rank_groups(self):
        details, awards = self.allocations_for([5, 0, 4, 0, 3])

        self.assertEqual(awards, {"p0": 3000, "p2": 2200, "p4": 1500})
        self.assertEqual(
            [detail["player_ids"] for detail in details],
            [["p0"], ["p2"], ["p4"]],
        )


if __name__ == "__main__":
    unittest.main()
