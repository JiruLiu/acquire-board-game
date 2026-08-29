import unittest

from app import (
    ALL_TILES,
    Player,
    Room,
    app,
    build_public_room_state,
    game_end_condition,
    player_socket_room,
    room_cleanup_timers,
    rooms,
    socketio,
)


class GameRegressionTests(unittest.TestCase):
    def setUp(self):
        for timer in room_cleanup_timers.values():
            timer.cancel()
        room_cleanup_timers.clear()
        rooms.clear()
        self.client = app.test_client()

    def tearDown(self):
        for timer in room_cleanup_timers.values():
            timer.cancel()
        room_cleanup_timers.clear()
        rooms.clear()

    def make_room(self, room_id="TEST"):
        player = Player(id="player-1", name="Player1", tiles=["I12"])
        room = Room(
            id=room_id,
            name=f"Room {room_id}",
            password="pw",
            creator_id=player.id,
            players=[player],
            deck=["I11"],
        )
        rooms[room_id] = room
        return room, player

    def test_company_with_41_tiles_triggers_end_condition(self):
        room, _player = self.make_room()
        room.board = {
            tile: {"placed_by": "Player1", "company": "red"}
            for tile in ALL_TILES[:41]
        }

        self.assertTrue(game_end_condition(room))

    def test_invalid_spectator_name_returns_validation_error(self):
        self.make_room()

        response = self.client.post(
            "/api/rooms/TEST/spectate",
            json={"player_name": "not valid!", "room_password": "pw"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Name must be", response.get_json()["error"])

    def test_non_string_spectator_name_returns_validation_error(self):
        self.make_room()

        response = self.client.post(
            "/api/rooms/TEST/spectate",
            json={"player_name": 123, "room_password": "pw"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Name must be", response.get_json()["error"])

    def test_public_room_state_is_a_stable_snapshot(self):
        room, player = self.make_room()
        room.board["A1"] = {"placed_by": player.name, "company": None}
        state = build_public_room_state(room, player.id)

        player.stocks["red"] = 4
        player.tiles[0] = "A2"
        room.board["A1"]["company"] = "red"

        self.assertEqual(state["players"][0]["stocks"]["red"], 0)
        self.assertEqual(state["players"][0]["tiles"], ["I12"])
        self.assertIsNone(state["board"]["A1"]["company"])

    def test_fractional_stock_purchase_is_rejected_without_mutation(self):
        room, player = self.make_room()
        room.started = True
        room.pending_finish_player_id = player.id
        room.companies_found["red"] = True
        room.board = {
            "A1": {"placed_by": player.name, "company": "red"},
            "A2": {"placed_by": player.name, "company": "red"},
        }

        response = self.client.post(
            "/api/rooms/TEST/buy_stocks",
            json={"player_id": player.id, "purchases": {"red": 1.5}},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(player.money, 6000)
        self.assertEqual(player.stocks["red"], 0)
        self.assertEqual(room.bank_stocks["red"], 25)

    def test_fractional_acquisition_stock_count_is_rejected(self):
        room, player = self.make_room()
        room.started = True
        player.stocks["yellow"] = 2
        room.pending_acquire_starter_id = player.id
        room.pending_acquire_survivor = "red"
        room.pending_acquire_targets = ["yellow"]
        room.pending_acquire_sizes = {"red": 2, "yellow": 2}
        room.pending_acquire_player_order = [player.id]

        response = self.client.post(
            "/api/rooms/TEST/trade_stocks",
            json={
                "player_id": player.id,
                "target": "yellow",
                "sell": 0.5,
                "trade": 0,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(player.stocks["yellow"], 2)
        self.assertEqual(player.money, 6000)

    def test_malformed_acquisition_order_returns_validation_error(self):
        room, player = self.make_room()
        room.started = True
        room.pending_acquire_starter_id = player.id
        room.pending_acquire_survivor = "red"
        room.pending_acquire_targets = ["yellow"]
        room.pending_acquire_sizes = {"red": 3, "yellow": 2}
        room.pending_acquire_ordering = True

        response = self.client.post(
            "/api/rooms/TEST/set_acquire_order",
            json={"player_id": player.id, "order": 1},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("must be a list", response.get_json()["error"])

    def test_switching_socket_subscription_leaves_previous_private_room(self):
        first_room, first_player = self.make_room("FIRST")
        second_player = Player(id="player-2", name="Player2")
        second_room = Room(
            id="SECOND",
            name="Room SECOND",
            password="pw",
            creator_id=second_player.id,
            players=[second_player],
        )
        rooms[second_room.id] = second_room
        client = socketio.test_client(app)
        self.addCleanup(client.disconnect)

        client.emit(
            "join_room_state",
            {"room_id": first_room.id, "player_id": first_player.id},
        )
        client.get_received()
        client.emit(
            "join_room_state",
            {"room_id": second_room.id, "player_id": second_player.id},
        )
        client.get_received()

        socketio.emit(
            "room_state",
            {"room_id": first_room.id},
            to=player_socket_room(first_room.id, first_player.id),
        )

        old_room_updates = [
            event
            for event in client.get_received()
            if event["name"] == "room_state"
            and event["args"][0].get("room_id") == first_room.id
        ]
        self.assertEqual(old_room_updates, [])


if __name__ == "__main__":
    unittest.main()
