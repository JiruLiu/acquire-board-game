import unittest
import tempfile
from pathlib import Path

import app as app_module
from app import (
    ALL_TILES,
    Player,
    Room,
    app,
    adjacent_tiles,
    build_public_room_state,
    game_end_condition,
    player_socket_room,
    room_connected_sids,
    room_cleanup_timers,
    room_tiles,
    rooms,
    serialize_room,
    socket_membership,
    socketio,
)
from recording_store import RecordingStore, snapshot_hash


class GameRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.original_recording_store = app_module.recording_store
        app_module.recording_store = RecordingStore(
            str(Path(self.temp_directory.name) / "recordings.sqlite3")
        )
        for timer in room_cleanup_timers.values():
            timer.cancel()
        room_cleanup_timers.clear()
        room_connected_sids.clear()
        socket_membership.clear()
        rooms.clear()
        self.client = app.test_client()

    def tearDown(self):
        for timer in room_cleanup_timers.values():
            timer.cancel()
        room_cleanup_timers.clear()
        room_connected_sids.clear()
        socket_membership.clear()
        rooms.clear()
        app_module.recording_store = self.original_recording_store
        self.temp_directory.cleanup()

    def make_room(self, room_id="TEST", mode="classic"):
        player = Player(id="player-1", name="Player1", tiles=["I12"])
        room = Room(
            id=room_id,
            name=f"Room {room_id}",
            password="pw",
            creator_id=player.id,
            mode=mode,
            players=[player],
            deck=["I11"],
        )
        rooms[room_id] = room
        return room, player

    def test_expanded_mode_uses_11_by_14_board(self):
        room, player = self.make_room(mode="expanded")
        state = build_public_room_state(room, player.id)

        self.assertEqual(state["game_mode"], "expanded")
        self.assertEqual(state["game_mode_label"], "Expanded")
        self.assertEqual(len(state["board_rows"]), 11)
        self.assertEqual(len(state["board_columns"]), 14)
        self.assertEqual(state["max_players"], 8)
        self.assertEqual(len(room_tiles(room)), 154)
        self.assertEqual(adjacent_tiles(room, "K14"), ["J14", "K13"])

    def test_expanded_room_allows_eight_players_and_deals_from_larger_deck(self):
        room, creator = self.make_room(mode="expanded")
        room.players.extend(
            Player(id=f"player-{index}", name=f"Player{index}")
            for index in range(2, 9)
        )

        response = self.client.post(
            "/api/rooms/TEST/start",
            json={"player_id": creator.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(room.players), 8)
        self.assertTrue(all(len(player.tiles) == 6 for player in room.players))
        self.assertEqual(len(room.deck), 154 - (8 * 6))

    def test_room_capacity_depends_on_game_mode(self):
        classic, _creator = self.make_room("CLASSIC", mode="classic")
        classic.players.extend(
            Player(id=f"classic-{index}", name=f"Classic{index}")
            for index in range(2, 6)
        )
        expanded, _creator = self.make_room("EXPANDED", mode="expanded")
        expanded.players.extend(
            Player(id=f"expanded-{index}", name=f"Expand{index}")
            for index in range(2, 9)
        )

        classic_response = self.client.post(
            "/api/rooms/CLASSIC/join",
            json={"player_name": "Extra", "room_password": "pw"},
        )
        expanded_response = self.client.post(
            "/api/rooms/EXPANDED/join",
            json={"player_name": "Extra", "room_password": "pw"},
        )

        self.assertEqual(classic_response.status_code, 400)
        self.assertIn("limit is 5", classic_response.get_json()["error"])
        self.assertEqual(expanded_response.status_code, 400)
        self.assertIn("limit is 8", expanded_response.get_json()["error"])

    def test_room_creation_validates_and_returns_game_mode(self):
        response = self.client.post(
            "/api/rooms",
            json={
                "player_name": "Creator",
                "invitation_code": "evanston",
                "room_password": "pw",
                "game_mode": "expanded",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["state"]["game_mode"], "expanded")
        self.assertGreaterEqual(response.get_json()["state"]["seed"], 0)
        self.assertLessEqual(response.get_json()["state"]["seed"], 0xFFFFFFFF)

        invalid_response = self.client.post(
            "/api/rooms",
            json={
                "player_name": "Other",
                "invitation_code": "evanston",
                "room_password": "pw",
                "game_mode": "giant",
            },
        )
        self.assertEqual(invalid_response.status_code, 400)
        self.assertIn("Unknown game mode", invalid_response.get_json()["error"])

    def test_seed_validation_rejects_invalid_values(self):
        for seed in (-1, 4294967296, "1.5", "abc", True):
            with self.subTest(seed=seed):
                response = self.client.post(
                    "/api/rooms",
                    json={
                        "player_name": "Creator",
                        "invitation_code": "evanston",
                        "room_password": "pw",
                        "game_mode": "classic",
                        "seed": seed,
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("Seed must be", response.get_json()["error"])

    def test_same_seed_reproduces_player_order_racks_and_deck(self):
        def add_room(room_id, seed):
            players = [
                Player(id=f"p{index}", name=f"Player{index}")
                for index in range(1, 5)
            ]
            room = Room(
                id=room_id,
                name=room_id,
                password="pw",
                creator_id=players[0].id,
                mode="expanded",
                seed=seed,
                players=players,
            )
            rooms[room_id] = room
            return room

        first = add_room("SEEDONE", 8675309)
        second = add_room("SEEDTWO", 8675309)

        first_response = self.client.post(
            "/api/rooms/SEEDONE/start", json={"player_id": "p1"}
        )
        second_response = self.client.post(
            "/api/rooms/SEEDTWO/start", json={"player_id": "p1"}
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual([player.name for player in first.players], [player.name for player in second.players])
        self.assertEqual(
            {player.name: player.tiles for player in first.players},
            {player.name: player.tiles for player in second.players},
        )
        self.assertEqual(first.deck, second.deck)

    def test_different_seeds_change_initial_distribution(self):
        players_one = [Player(id=f"a{index}", name=f"Player{index}") for index in range(1, 5)]
        players_two = [Player(id=f"b{index}", name=f"Player{index}") for index in range(1, 5)]
        first = Room(
            id="DIFFONE",
            name="First",
            password="pw",
            creator_id="a1",
            seed=1,
            players=players_one,
        )
        second = Room(
            id="DIFFTWO",
            name="Second",
            password="pw",
            creator_id="b1",
            seed=2,
            players=players_two,
        )
        rooms[first.id] = first
        rooms[second.id] = second

        self.client.post("/api/rooms/DIFFONE/start", json={"player_id": "a1"})
        self.client.post("/api/rooms/DIFFTWO/start", json={"player_id": "b1"})

        first_distribution = {player.name: player.tiles for player in first.players}
        second_distribution = {player.name: player.tiles for player in second.players}
        self.assertNotEqual(first_distribution, second_distribution)

    def test_successful_game_actions_append_full_recording_snapshots(self):
        players = [
            Player(id="recorder", name="Recorder"),
            Player(id="opponent", name="Opponent"),
        ]
        room = Room(
            id="RECORD",
            name="Recorded room",
            password="pw",
            creator_id=players[0].id,
            seed=20260829,
            players=players,
        )
        rooms[room.id] = room

        start_response = self.client.post(
            "/api/rooms/RECORD/start",
            json={"player_id": "recorder"},
        )
        self.assertEqual(start_response.status_code, 200)
        current_player = room.players[room.current_turn]
        sort_response = self.client.post(
            "/api/rooms/RECORD/sort_tiles",
            json={"player_id": current_player.id},
        )
        tile = next(tile for tile in current_player.tiles if tile)
        place_response = self.client.post(
            "/api/rooms/RECORD/place_tile",
            json={"player_id": current_player.id, "tile": tile},
        )

        self.assertEqual(sort_response.status_code, 200)
        self.assertEqual(place_response.status_code, 200)
        recording = app_module.recording_store.get_game(room.recording_id)
        self.assertEqual(
            [snapshot["event_type"] for snapshot in recording["snapshots"]],
            ["start_game", "sort_tiles", "place_tile", "auto_finish_turn"],
        )
        self.assertEqual(recording["snapshots"][-1]["state"]["board"], room.board)
        self.assertEqual(recording["snapshots"][-1]["state_hash"], snapshot_hash(serialize_room(room)))
        replay_actions = self.client.get(
            f"/api/replays/{room.recording_id}"
        ).get_json()["actions"]
        self.assertEqual(
            [action["message"] for action in replay_actions],
            [
                recording["snapshots"][0]["state"]["last_action"],
                recording["snapshots"][1]["state"]["last_action"],
                recording["snapshots"][2]["state"]["last_action"],
                recording["snapshots"][3]["state"]["last_action"],
            ],
        )
        self.assertIsNone(room.pending_finish_player_id)
        self.assertNotEqual(room.players[room.current_turn].id, current_player.id)
        self.assertEqual(len([tile for tile in current_player.tiles if tile]), 6)
        self.assertIn("automatically finished", room.last_action)

    def test_company_on_board_keeps_normal_buy_and_finish_step(self):
        players = [
            Player(id="active", name="Active", tiles=["B1"]),
            Player(id="waiting", name="Waiting", tiles=["I12"]),
        ]
        room = Room(
            id="HASCOMPANY",
            name="Company room",
            password="pw",
            creator_id=players[0].id,
            players=players,
            started=True,
            deck=["I11"],
            board={
                "A1": {"placed_by": "Active", "company": "red"},
                "A2": {"placed_by": "Active", "company": "red"},
            },
        )
        room.companies_found["red"] = True
        rooms[room.id] = room

        response = self.client.post(
            "/api/rooms/HASCOMPANY/place_tile",
            json={"player_id": "active", "tile": "B1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(room.pending_finish_player_id, "active")
        self.assertEqual(room.players[room.current_turn].id, "active")
        self.assertIn("Buy stocks or click Finish", room.last_action)

        finish_response = self.client.post(
            "/api/rooms/HASCOMPANY/finish_turn",
            json={"player_id": "active", "purchases": {}},
        )
        self.assertEqual(finish_response.status_code, 200)
        self.assertIsNone(room.pending_finish_player_id)
        self.assertEqual(room.players[room.current_turn].id, "waiting")
        self.assertNotIn("automatically finished", room.last_action)

    def test_founding_choice_waits_then_declining_auto_finishes_without_companies(self):
        players = [
            Player(id="active", name="Active", tiles=["A2"]),
            Player(id="waiting", name="Waiting", tiles=["I12"]),
        ]
        room = Room(
            id="DECLINE",
            name="Founding room",
            password="pw",
            creator_id=players[0].id,
            players=players,
            started=True,
            deck=["I11"],
            board={"A1": {"placed_by": "Waiting", "company": None}},
        )
        rooms[room.id] = room

        place_response = self.client.post(
            "/api/rooms/DECLINE/place_tile",
            json={"player_id": "active", "tile": "A2"},
        )
        self.assertEqual(place_response.status_code, 200)
        self.assertEqual(room.pending_found_player_id, "active")
        self.assertEqual(room.players[room.current_turn].id, "active")

        decline_response = self.client.post(
            "/api/rooms/DECLINE/found_company",
            json={"player_id": "active", "color": None},
        )

        self.assertEqual(decline_response.status_code, 200)
        self.assertIsNone(room.pending_found_player_id)
        self.assertIsNone(room.pending_finish_player_id)
        self.assertEqual(room.players[room.current_turn].id, "waiting")
        self.assertIn("automatically finished", room.last_action)

    def test_replay_endpoints_list_actions_and_return_redacted_spectator_state(self):
        room, creator = self.make_room("REPLAY")
        creator.id = "secret-creator-id"
        room.creator_id = creator.id
        room.players.append(Player(id="secret-opponent-id", name="Player2"))
        start_response = self.client.post(
            "/api/rooms/REPLAY/start",
            json={"player_id": creator.id},
        )
        self.assertEqual(start_response.status_code, 200)
        recording_id = room.recording_id

        list_response = self.client.get("/api/replays")
        details_response = self.client.get(f"/api/replays/{recording_id}")
        snapshot_response = self.client.get(
            f"/api/replays/{recording_id}/snapshots/0"
        )
        page_response = self.client.get(f"/replay/{recording_id}")

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.get_json()["replays"][0]["action_count"], 1)
        self.assertEqual(details_response.status_code, 200)
        replay_action = details_response.get_json()["actions"][0]
        self.assertEqual(replay_action["sequence"], 0)
        self.assertEqual(replay_action["event_type"], "start_game")
        self.assertEqual(replay_action["message"], room.last_action)
        self.assertEqual(snapshot_response.status_code, 200)
        replay_state = snapshot_response.get_json()["state"]
        self.assertTrue(replay_state["is_spectator"])
        self.assertTrue(replay_state["is_replay"])
        self.assertEqual(replay_state["players"][0]["id"], "player-1")
        self.assertNotIn(creator.id, str(snapshot_response.get_json()))
        self.assertNotIn("deck", replay_state)
        self.assertEqual(page_response.status_code, 200)
        self.assertIn(recording_id.encode(), page_response.data)

    def test_replay_snapshot_restores_as_new_live_room_with_fresh_access_ids(self):
        room, creator = self.make_room("RESTORESOURCE")
        creator.id = "original-creator-secret"
        room.creator_id = creator.id
        room.players.append(Player(id="original-opponent-secret", name="Player2"))
        start_response = self.client.post(
            "/api/rooms/RESTORESOURCE/start",
            json={"player_id": creator.id},
        )
        self.assertEqual(start_response.status_code, 200)
        source_recording_id = room.recording_id
        current_player = room.players[room.current_turn]
        room.pending_finish_player_id = current_player.id
        room.last_action = f"{current_player.name} is ready to finish."
        app_module.record_room_event(room, "place_tile", current_player.id)
        source_recording = app_module.recording_store.get_game(source_recording_id)
        source_snapshot = source_recording["snapshots"][1]["state"]
        expected_status_history = []
        for recorded_snapshot in source_recording["snapshots"]:
            message = recorded_snapshot["state"]["last_action"]
            if not expected_status_history or expected_status_history[-1] != message:
                expected_status_history.append(message)

        response = self.client.post(
            f"/api/replays/{source_recording_id}/restore",
            json={"sequence": 1},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        restored = rooms[payload["room_id"]]
        original_ids = {"original-creator-secret", "original-opponent-secret"}
        restored_ids = {player.id for player in restored.players}
        self.assertNotEqual(restored.id, room.id)
        self.assertTrue(restored.started)
        self.assertTrue(restored.restored_from_replay)
        self.assertTrue(restored_ids.isdisjoint(original_ids))
        self.assertIn(payload["player_id"], restored.spectator_ids)
        self.assertTrue(payload["state"]["is_spectator"])
        self.assertEqual(payload["state"]["status_history"], expected_status_history)
        self.assertEqual(restored.status_history, expected_status_history)
        self.assertNotIn("original-creator-secret", str(payload))
        self.assertNotIn("original-opponent-secret", str(payload))
        self.assertEqual(
            restored.players[restored.current_turn].name,
            source_snapshot["players"][source_snapshot["current_turn"]]["name"],
        )
        self.assertEqual(
            restored.pending_finish_player_id,
            restored.players[restored.current_turn].id,
        )
        self.assertEqual(restored.board, source_snapshot["board"])
        self.assertEqual(restored.deck, source_snapshot["deck"])

        restored_recording = app_module.recording_store.get_game(restored.recording_id)
        self.assertEqual(restored_recording["game"]["schema_version"], 1)
        self.assertEqual(restored_recording["snapshots"][0]["event_type"], "restore_replay")
        self.assertEqual(
            restored_recording["snapshots"][0]["input"],
            {
                "source_recording_id": source_recording_id,
                "source_sequence": 1,
                "status_history": expected_status_history,
            },
        )
        restored_details = self.client.get(
            f"/api/replays/{restored.recording_id}"
        ).get_json()
        self.assertEqual(
            restored_details["actions"][0]["status_history"],
            expected_status_history,
        )

        restored.last_action = "The restored game continued."
        continued_state = app_module.build_public_room_state(
            restored, payload["player_id"]
        )
        self.assertEqual(
            continued_state["status_history"],
            expected_status_history + ["The restored game continued."],
        )

        spectator_client = socketio.test_client(app)
        try:
            spectator_client.emit(
                "join_room_state",
                {"room_id": restored.id, "player_id": payload["player_id"]},
            )
            self.assertNotIn(restored.id, room_cleanup_timers)
        finally:
            spectator_client.disconnect()

    def test_replay_restore_rejects_snapshot_with_invalid_hash(self):
        room, creator = self.make_room("CORRUPT")
        room.players.append(Player(id="player-2", name="Player2"))
        self.client.post(
            "/api/rooms/CORRUPT/start",
            json={"player_id": creator.id},
        )
        recording_id = room.recording_id
        with app_module.recording_store.connect() as connection:
            connection.execute(
                """
                UPDATE game_snapshots
                SET state_hash = 'invalid'
                WHERE recording_id = ? AND sequence = 0
                """,
                (recording_id,),
            )

        response = self.client.post(
            f"/api/replays/{recording_id}/restore",
            json={"sequence": 0},
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("integrity", response.get_json()["error"])
        self.assertEqual(set(rooms), {"CORRUPT"})

    def test_replay_final_snapshot_preserves_game_end_results(self):
        room, creator = self.make_room("FINISHED")
        room.players.append(Player(id="player-2", name="Player2"))
        self.client.post(
            "/api/rooms/FINISHED/start",
            json={"player_id": creator.id},
        )
        winner = room.players[0]
        room.game_over = True
        room.winner = winner.name
        room.final_rankings = [{
            "player_id": winner.id,
            "name": winner.name,
            "final_total": winner.money,
        }]
        app_module.record_room_event(room, "finish_turn", winner.id)

        response = self.client.get(
            f"/api/replays/{room.recording_id}/snapshots/1"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["game"]["status"], "completed")
        self.assertTrue(payload["state"]["game_over"])
        self.assertEqual(payload["state"]["winner"], winner.name)
        self.assertEqual(payload["state"]["final_rankings"][0]["player_id"], "player-1")
        restore_response = self.client.post(
            f"/api/replays/{room.recording_id}/restore",
            json={"sequence": 1},
        )
        self.assertEqual(restore_response.status_code, 400)
        self.assertIn("already ended", restore_response.get_json()["error"])

    def test_replay_snapshot_allows_last_placed_tile_without_owner_label(self):
        room, creator = self.make_room("NULLOWNER")
        room.players.append(Player(id="player-2", name="Player2"))
        self.client.post(
            "/api/rooms/NULLOWNER/start",
            json={"player_id": creator.id},
        )
        current_player = room.players[room.current_turn]
        tile_index = next(
            index for index, tile in enumerate(current_player.tiles) if tile
        )
        tile = current_player.tiles[tile_index]
        current_player.tiles[tile_index] = None
        room.board[tile] = {"placed_by": None, "company": None}
        room.last_placed_tile = tile
        room.last_action = f"{current_player.name} placed a tile."
        app_module.record_room_event(room, "place_tile", current_player.id)

        response = self.client.get(
            f"/api/replays/{room.recording_id}/snapshots/1"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()["state"]["board"][tile]["placed_by"])

    def test_missing_replay_and_snapshot_return_not_found(self):
        self.assertEqual(self.client.get("/replay/missing").status_code, 404)
        self.assertEqual(self.client.get("/api/replays/missing").status_code, 404)

    def test_expanded_coordinates_are_valid_only_in_expanded_mode(self):
        classic, classic_player = self.make_room("CLASSIC", mode="classic")
        classic.started = True
        classic_player.tiles = ["K14"]
        expanded, expanded_player = self.make_room("EXPANDED", mode="expanded")
        expanded.started = True
        expanded_player.tiles = ["K14"]

        classic_response = self.client.post(
            "/api/rooms/CLASSIC/place_tile",
            json={"player_id": classic_player.id, "tile": "K14"},
        )
        expanded_response = self.client.post(
            "/api/rooms/EXPANDED/place_tile",
            json={"player_id": expanded_player.id, "tile": "K14"},
        )

        self.assertEqual(classic_response.status_code, 400)
        self.assertEqual(expanded_response.status_code, 200)
        self.assertIn("K14", expanded.board)

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

    def test_spectator_presence_tracks_live_socket_connection(self):
        room, player = self.make_room()
        response = self.client.post(
            "/api/rooms/TEST/spectate",
            json={"player_name": "Watcher", "room_password": "pw"},
        )
        spectator_id = response.get_json()["player_id"]
        player_client = socketio.test_client(app)
        spectator_client = socketio.test_client(app)

        try:
            player_client.emit(
                "join_room_state",
                {"room_id": room.id, "player_id": player.id},
            )
            spectator_client.emit(
                "join_room_state",
                {"room_id": room.id, "player_id": spectator_id},
            )

            connected_state = build_public_room_state(room, player.id)
            self.assertEqual(connected_state["spectators"], ["Watcher"])

            spectator_client.disconnect()
            disconnected_state = build_public_room_state(room, player.id)
            self.assertEqual(disconnected_state["spectators"], [])
        finally:
            if spectator_client.is_connected():
                spectator_client.disconnect()
            if player_client.is_connected():
                player_client.disconnect()

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
        try:
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
        finally:
            if client.is_connected():
                client.disconnect()


if __name__ == "__main__":
    unittest.main()
