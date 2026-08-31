import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path

import app as app_module
from app import (
    Player,
    Room,
    deserialize_room,
    record_room_event,
    rooms,
    serialize_room,
    start_room_recording,
)
from recording_store import RecordingStore, snapshot_hash, validate_snapshot_state


class RecordingStateTests(unittest.TestCase):
    def make_acquisition_room(self) -> Room:
        first = Player(id="p1", name="Alice", tiles=["C3", None])
        second = Player(id="p2", name="Bob", tiles=["D4"])
        first.stocks["yellow"] = 2
        room = Room(
            id="STATE1",
            name="State test",
            password="do-not-record",
            creator_id=first.id,
            mode="expanded",
            seed=123456,
            recording_id="recording-1",
            recording_sequence=7,
            players=[first, second],
            spectator_ids={"spectator-secret"},
            spectator_names={"spectator-secret": "Watcher"},
            started=True,
            current_turn=0,
            deck=["K14", "J13"],
            board={
                "A1": {"placed_by": "Alice", "company": "red"},
                "A2": {"placed_by": "Alice", "company": "red"},
                "B1": {"placed_by": "Bob", "company": "yellow"},
                "B2": {"placed_by": "Bob", "company": "yellow"},
                "A3": {"placed_by": "Alice", "company": "acquire"},
            },
            stocks_bought_this_turn=1,
            pending_acquire_starter_id=first.id,
            pending_acquire_survivor="red",
            pending_acquire_targets=["yellow"],
            pending_acquire_sizes={"red": 2, "yellow": 2},
            pending_acquire_reward_details=[
                {
                    "color": "yellow",
                    "rank": "first and third",
                    "player_ids": [first.id],
                    "names": [first.name],
                    "shares": 2,
                    "amount": 3000,
                    "each": 3000,
                }
            ],
            pending_acquire_player_order=[first.id, second.id],
            pending_acquire_player_index=0,
            pending_acquire_target_index=0,
            end_pending=True,
            last_action="Resolve the acquisition.",
            last_placed_tile="A3",
            last_placed_started_acquire=True,
        )
        room.companies_found["red"] = True
        room.companies_found["yellow"] = True
        room.bank_stocks["yellow"] = 23
        return room

    def test_room_round_trip_preserves_complete_state_without_password(self):
        room = self.make_acquisition_room()

        state = serialize_room(room)
        restored = deserialize_room(state, password="replacement")

        self.assertEqual(validate_snapshot_state(state), [])
        self.assertEqual(serialize_room(restored), state)
        self.assertNotIn("password", state)
        self.assertNotIn("do-not-record", str(state))
        self.assertNotIn("socket_membership", state)
        self.assertNotIn("room_connected_sids", state)
        self.assertNotIn("cleanup", state)
        self.assertEqual(restored.password, "replacement")

    def test_completed_room_round_trip_preserves_rankings(self):
        room = self.make_acquisition_room()
        room.pending_acquire_starter_id = None
        room.pending_acquire_survivor = None
        room.pending_acquire_targets = []
        room.pending_acquire_sizes = {}
        room.pending_acquire_reward_details = []
        room.pending_acquire_player_order = []
        room.board["A3"]["company"] = "red"
        for tile in ("B1", "B2"):
            room.board[tile]["company"] = "red"
        room.companies_found["yellow"] = False
        room.game_over = True
        room.end_pending = False
        room.winner = "Alice"
        room.final_rankings = [{"player_id": "p1", "name": "Alice", "final_total": 9000}]

        state = serialize_room(room)
        restored = deserialize_room(state)

        self.assertEqual(validate_snapshot_state(state), [])
        self.assertEqual(serialize_room(restored), state)

    def test_hash_is_canonical_and_detects_changes(self):
        state = serialize_room(self.make_acquisition_room())
        reordered = dict(reversed(list(state.items())))
        changed = copy.deepcopy(state)
        changed["seed"] += 1

        self.assertEqual(snapshot_hash(state), snapshot_hash(reordered))
        self.assertNotEqual(snapshot_hash(state), snapshot_hash(changed))

    def test_invariants_report_duplicate_tiles(self):
        state = serialize_room(self.make_acquisition_room())
        state["deck"].append("C3")

        errors = validate_snapshot_state(state)

        self.assertTrue(any("appears in both" in error for error in errors))


class RecordingStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = str(Path(self.temp_directory.name) / "recordings.sqlite3")
        self.store = RecordingStore(self.database_path)

    def tearDown(self):
        self.temp_directory.cleanup()

    def state_for(self, index: int) -> dict:
        player = Player(id=f"p{index}", name=f"Player{index}")
        room = Room(
            id=f"ROOM{index}",
            name=f"Room {index}",
            password="secret",
            creator_id=player.id,
            seed=index,
            recording_id=f"recording-{index}",
            recording_sequence=0,
            players=[player],
            started=True,
        )
        return serialize_room(room)

    def create_recording(self, index: int) -> list[str]:
        state = self.state_for(index)
        return self.store.create_game(
            recording_id=f"recording-{index}",
            room_id=f"ROOM{index}",
            room_name=f"Room {index}",
            mode="classic",
            seed=index,
            state=state,
            actor_id=f"p{index}",
            event_input={"seed": index},
        )

    def test_store_keeps_newest_ten_games_and_cascade_deletes_oldest(self):
        for index in range(10):
            self.create_recording(index)
        self.store.append_snapshot(
            "recording-0",
            event_type="sort_tiles",
            actor_id="p0",
            event_input={},
            state=self.state_for(0),
        )

        pruned = self.create_recording(10)

        self.assertEqual(pruned, ["recording-0"])
        self.assertEqual(len(self.store.list_games()), 10)
        self.assertIsNone(self.store.get_game("recording-0"))
        with sqlite3.connect(self.database_path) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM game_snapshots WHERE recording_id = 'recording-0'"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_snapshots_have_sequences_hashes_and_completion_status(self):
        self.create_recording(1)
        state = self.state_for(1)
        state["recording_sequence"] = 1

        sequence = self.store.append_snapshot(
            "recording-1",
            event_type="finish_turn",
            actor_id="p1",
            event_input={"purchases": {}},
            state=state,
            completed=True,
        )
        recording = self.store.get_game("recording-1")

        self.assertEqual(sequence, 1)
        self.assertEqual([item["sequence"] for item in recording["snapshots"]], [0, 1])
        self.assertEqual(recording["game"]["status"], "completed")
        self.assertEqual(recording["snapshots"][1]["state_hash"], snapshot_hash(state))
        self.assertEqual(self.store.verify_game("recording-1"), [])

    def test_default_export_redacts_ids(self):
        self.create_recording(1)

        exported = self.store.export_game("recording-1")
        raw_export = self.store.export_game("recording-1", raw_ids=True)

        self.assertNotIn("p1", str(exported))
        self.assertIn("player-1", str(exported))
        self.assertIn("p1", str(raw_export))

    def test_evicted_active_room_does_not_recreate_recording(self):
        original_store = app_module.recording_store
        app_module.recording_store = RecordingStore(self.database_path, max_games=1)
        rooms.clear()
        try:
            first_player = Player(id="first-player", name="First")
            first = Room(
                id="FIRST",
                name="First room",
                password="pw",
                creator_id=first_player.id,
                seed=1,
                players=[first_player],
                started=True,
            )
            second_player = Player(id="second-player", name="Second")
            second = Room(
                id="SECOND",
                name="Second room",
                password="pw",
                creator_id=second_player.id,
                seed=2,
                players=[second_player],
                started=True,
            )
            rooms[first.id] = first
            rooms[second.id] = second

            start_room_recording(first, first_player.id)
            first_recording_id = first.recording_id
            start_room_recording(second, second_player.id)

            self.assertIsNone(first.recording_id)
            self.assertIsNone(first.recording_sequence)
            record_room_event(first, "sort_tiles", first_player.id)
            self.assertIsNone(app_module.recording_store.get_game(first_recording_id))
            self.assertEqual(len(app_module.recording_store.list_games()), 1)
        finally:
            rooms.clear()
            app_module.recording_store = original_store


if __name__ == "__main__":
    unittest.main()
