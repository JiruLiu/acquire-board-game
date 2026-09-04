from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
APP_RECORDING_VERSION = "1"
DEFAULT_MAX_GAMES = 10


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def snapshot_hash(state: dict) -> str:
    return hashlib.sha256(canonical_json(state).encode("utf-8")).hexdigest()


def default_database_path(project_root: str | os.PathLike | None = None) -> str:
    configured = os.environ.get("GAME_RECORDINGS_DB")
    if configured:
        return configured
    root = Path(project_root or Path(__file__).resolve().parent)
    return str(root / "instance" / "game_recordings.sqlite3")


def validate_snapshot_state(state: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(state, dict):
        return ["state must be a JSON object"]
    if state.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"unsupported schema_version {state.get('schema_version')!r}")

    expected_dimensions = {
        "classic": (list("ABCDEFGHI"), [str(index) for index in range(1, 13)]),
        "expanded": (list("ABCDEFGHIJK"), [str(index) for index in range(1, 15)]),
    }
    mode = state.get("mode")
    if mode not in expected_dimensions:
        errors.append(f"unknown game mode {mode!r}")

    rows = state.get("board_rows") or []
    columns = state.get("board_columns") or []
    if mode in expected_dimensions and (rows, columns) != expected_dimensions[mode]:
        errors.append(f"board dimensions do not match {mode} mode")
    expected_rules = {
        "starting_cash": 6000,
        "starting_bank_shares": 25,
        "super_company_size": 10,
        "game_end_company_size": 41,
        "max_players": 8 if mode == "expanded" else 5,
    }
    if state.get("rules") != expected_rules:
        errors.append("recorded rules do not match schema version 1")
    seed = state.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 0xFFFFFFFF:
        errors.append("seed is outside the unsigned 32-bit range")
    valid_tiles = {f"{row}{column}" for row in rows for column in columns}
    board = state.get("board") or {}
    deck = state.get("deck") or []
    players = state.get("players") or []

    locations: list[tuple[str, str]] = []
    locations.extend((tile, "board") for tile in board)
    locations.extend((tile, "deck") for tile in deck)
    for player in players:
        locations.extend(
            (tile, f"rack:{player.get('id', '?')}")
            for tile in (player.get("tiles") or [])
            if tile is not None
        )

    seen: dict[str, str] = {}
    for tile, location in locations:
        if tile not in valid_tiles:
            errors.append(f"invalid tile {tile!r} in {location}")
            continue
        if tile in seen:
            errors.append(f"tile {tile} appears in both {seen[tile]} and {location}")
        else:
            seen[tile] = location

    player_ids = [player.get("id") for player in players]
    if len(player_ids) != len(set(player_ids)):
        errors.append("player IDs must be unique")

    current_turn = state.get("current_turn", 0)
    if players and not isinstance(current_turn, int):
        errors.append("current_turn must be an integer")
    elif players and not 0 <= current_turn < len(players):
        errors.append("current_turn is outside the player list")

    player_id_set = set(player_ids)
    for field_name in (
        "creator_id",
        "pending_found_player_id",
        "pending_finish_player_id",
        "pending_acquire_starter_id",
    ):
        player_id = state.get(field_name)
        if player_id is not None and player_id not in player_id_set:
            errors.append(f"{field_name} does not identify a player")

    acquire_order = state.get("pending_acquire_player_order") or []
    unknown_acquire_players = [player_id for player_id in acquire_order if player_id not in player_id_set]
    if unknown_acquire_players:
        errors.append("pending_acquire_player_order contains an unknown player")

    bank_stocks = state.get("bank_stocks") or {}
    company_colors = set(bank_stocks)
    companies_found = state.get("companies_found") or {}
    for color in company_colors:
        bank_count = bank_stocks.get(color)
        if not isinstance(bank_count, int) or bank_count < 0:
            errors.append(f"bank stock count for {color} is invalid")
            continue
        player_total = sum(
            (player.get("stocks") or {}).get(color, 0)
            for player in players
        )
        if bank_count + player_total != 25:
            errors.append(
                f"{color} shares total {bank_count + player_total}, expected 25"
            )

    board_companies = {
        value.get("company")
        for value in board.values()
        if isinstance(value, dict) and value.get("company") in company_colors
    }
    for color in board_companies:
        if not companies_found.get(color):
            errors.append(f"board uses unfounded company {color}")
    for color, is_found in companies_found.items():
        if is_found and color not in board_companies:
            errors.append(f"founded company {color} has no board tiles")

    survivor = state.get("pending_acquire_survivor")
    survivor_choices = state.get("pending_acquire_survivor_choices") or []
    targets = state.get("pending_acquire_targets") or []
    sizes = state.get("pending_acquire_sizes") or {}
    for color in [survivor, *survivor_choices, *targets]:
        if color is not None and color not in company_colors:
            errors.append(f"unknown acquisition company {color}")
    if survivor and survivor in targets:
        errors.append("acquisition survivor cannot also be a target")
    if targets and any(target not in sizes for target in targets):
        errors.append("an acquisition target has no recorded pre-acquisition size")

    player_index = state.get("pending_acquire_player_index", 0)
    target_index = state.get("pending_acquire_target_index", 0)
    if not isinstance(player_index, int) or not 0 <= player_index <= len(acquire_order):
        errors.append("pending_acquire_player_index is invalid")
    if not isinstance(target_index, int) or not 0 <= target_index <= len(targets):
        errors.append("pending_acquire_target_index is invalid")

    return errors


def _replace_ids(value, replacements: dict[str, str]):
    if isinstance(value, dict):
        return {key: _replace_ids(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_ids(item, replacements) for item in value]
    if isinstance(value, str):
        return replacements.get(value, value)
    return value


def redact_recording(recording: dict) -> dict:
    redacted = copy.deepcopy(recording)
    snapshots = redacted.get("snapshots") or []
    replacements: dict[str, str] = {}
    player_index = 1
    spectator_index = 1
    for snapshot in snapshots:
        state = snapshot.get("state") or {}
        for player in state.get("players") or []:
            player_id = player.get("id")
            if player_id and player_id not in replacements:
                replacements[player_id] = f"player-{player_index}"
                player_index += 1
        for spectator_id in state.get("spectator_ids") or []:
            if spectator_id not in replacements:
                replacements[spectator_id] = f"spectator-{spectator_index}"
                spectator_index += 1
    return _replace_ids(redacted, replacements)


class RecordingStore:
    def __init__(self, database_path: str, max_games: int = DEFAULT_MAX_GAMES):
        self.database_path = database_path
        self.max_games = max_games
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        path = Path(self.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS recorded_games (
                    created_order INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id TEXT NOT NULL UNIQUE,
                    room_id TEXT NOT NULL,
                    room_name TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    schema_version INTEGER NOT NULL,
                    app_version TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    latest_sequence INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS game_snapshots (
                    recording_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    recorded_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_id TEXT,
                    input_json TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    state_hash TEXT NOT NULL,
                    PRIMARY KEY (recording_id, sequence),
                    FOREIGN KEY (recording_id)
                        REFERENCES recorded_games(recording_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_recorded_games_started
                    ON recorded_games(created_order DESC);
                """
            )

    def create_game(
        self,
        *,
        recording_id: str,
        room_id: str,
        room_name: str,
        mode: str,
        seed: int,
        state: dict,
        actor_id: str | None,
        event_input: dict,
        app_version: str = APP_RECORDING_VERSION,
        event_type: str = "start_game",
    ) -> list[str]:
        now = utc_now()
        state_json = canonical_json(state)
        digest = snapshot_hash(state)
        pruned_ids: list[str] = []
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO recorded_games (
                    recording_id, room_id, room_name, mode, seed,
                    schema_version, app_version, started_at, updated_at,
                    completed_at, status, latest_sequence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'active', 0)
                """,
                (
                    recording_id,
                    room_id,
                    room_name,
                    mode,
                    seed,
                    SCHEMA_VERSION,
                    app_version,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO game_snapshots (
                    recording_id, sequence, recorded_at, event_type,
                    actor_id, input_json, state_json, state_hash
                ) VALUES (?, 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recording_id,
                    now,
                    event_type,
                    actor_id,
                    canonical_json(event_input),
                    state_json,
                    digest,
                ),
            )
            old_rows = connection.execute(
                """
                SELECT recording_id
                FROM recorded_games
                ORDER BY created_order DESC
                LIMIT -1 OFFSET ?
                """,
                (self.max_games,),
            ).fetchall()
            pruned_ids = [row["recording_id"] for row in old_rows]
            if pruned_ids:
                connection.executemany(
                    "DELETE FROM recorded_games WHERE recording_id = ?",
                    ((recording_id,) for recording_id in pruned_ids),
                )
        return pruned_ids

    def append_snapshot(
        self,
        recording_id: str,
        *,
        event_type: str,
        actor_id: str | None,
        event_input: dict,
        state: dict,
        completed: bool = False,
    ) -> int | None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            game = connection.execute(
                "SELECT latest_sequence FROM recorded_games WHERE recording_id = ?",
                (recording_id,),
            ).fetchone()
            if not game:
                return None
            sequence = game["latest_sequence"] + 1
            connection.execute(
                """
                INSERT INTO game_snapshots (
                    recording_id, sequence, recorded_at, event_type,
                    actor_id, input_json, state_json, state_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recording_id,
                    sequence,
                    now,
                    event_type,
                    actor_id,
                    canonical_json(event_input),
                    canonical_json(state),
                    snapshot_hash(state),
                ),
            )
            connection.execute(
                """
                UPDATE recorded_games
                SET updated_at = ?, completed_at = ?, status = ?, latest_sequence = ?
                WHERE recording_id = ?
                """,
                (
                    now,
                    now if completed else None,
                    "completed" if completed else "active",
                    sequence,
                    recording_id,
                ),
            )
        return sequence

    def list_games(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT recording_id, room_id, room_name, mode, seed,
                       schema_version, app_version, started_at, updated_at,
                       completed_at, status, latest_sequence
                FROM recorded_games
                ORDER BY created_order DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_game(self, recording_id: str) -> dict | None:
        with self.connect() as connection:
            game = connection.execute(
                """
                SELECT recording_id, room_id, room_name, mode, seed,
                       schema_version, app_version, started_at, updated_at,
                       completed_at, status, latest_sequence
                FROM recorded_games
                WHERE recording_id = ?
                """,
                (recording_id,),
            ).fetchone()
            if not game:
                return None
            rows = connection.execute(
                """
                SELECT sequence, recorded_at, event_type, actor_id,
                       input_json, state_json, state_hash
                FROM game_snapshots
                WHERE recording_id = ?
                ORDER BY sequence
                """,
                (recording_id,),
            ).fetchall()

        snapshots = []
        for row in rows:
            snapshot = dict(row)
            snapshot["input"] = json.loads(snapshot.pop("input_json"))
            snapshot["state"] = json.loads(snapshot.pop("state_json"))
            snapshots.append(snapshot)
        return {"game": dict(game), "snapshots": snapshots}

    def export_game(self, recording_id: str, raw_ids: bool = False) -> dict | None:
        recording = self.get_game(recording_id)
        if not recording or raw_ids:
            return recording
        return redact_recording(recording)

    def verify_game(self, recording_id: str) -> list[str]:
        recording = self.get_game(recording_id)
        if not recording:
            return [f"recording {recording_id} was not found"]
        snapshots = recording["snapshots"]
        if not snapshots:
            return ["recording has no snapshots"]
        if recording["game"]["latest_sequence"] != snapshots[-1]["sequence"]:
            return ["latest_sequence does not match the final snapshot"]
        for expected_sequence, snapshot in enumerate(snapshots):
            sequence = snapshot["sequence"]
            if sequence != expected_sequence:
                return [
                    f"sequence {sequence}: expected sequence {expected_sequence}"
                ]
            actual_hash = snapshot_hash(snapshot["state"])
            if actual_hash != snapshot["state_hash"]:
                return [f"sequence {sequence}: state hash does not match"]
            state_errors = validate_snapshot_state(snapshot["state"])
            if state_errors:
                return [f"sequence {sequence}: {state_errors[0]}"]
        return []


def new_recording_id() -> str:
    return uuid.uuid4().hex
