# Game Recording and Seeded Initialization

## Decisions

- [x] Treat a game as recorded when the room creator successfully starts it. Lobby-only rooms do not consume a recording slot.
- [x] Keep at most 10 game records. Creating the 11th recording deletes the oldest game row and all of its snapshots in the same database transaction.
- [x] If the evicted recording belongs to a game that is still running in memory, let the game continue but disable further recording for that room so it cannot recreate itself and displace newer recordings.
- [x] Use SQLite from Python's standard library, with a configurable `GAME_RECORDINGS_DB` path and a local default under `instance/`.
- [x] Store full snapshots rather than state deltas. Each snapshot also carries a small event envelope explaining the successful action that produced it.
- [x] Use an unsigned 32-bit integer seed (`0` through `4294967295`). If the seed field is blank, generate one with `secrets.randbits(32)` and show the effective value to players.
- [x] Use a room-local `random.Random(seed)` for player-order and deck shuffling. Room codes and player/spectator IDs remain unseeded security identifiers.
- [x] Treat the recorded deck order and snapshots as the authoritative reproduction data across application versions; the seed reproduces initialization under the matching shuffle algorithm/version.

## 1. Canonical game-state format

- [x] Add `schema_version`, `seed`, and nullable `recording_id` fields to the internal room model.
- [x] Implement `serialize_room(room)` as an explicit JSON-safe schema rather than serializing `Room.__dict__`.
- [x] Include all deterministic game state:
  - mode, board dimensions, and rule thresholds
  - player order, IDs, names, money, stocks, rack slots, and statistics
  - exact remaining deck order
  - board contents and company assignments
  - founded-company flags and bank shares
  - current turn and stocks bought this turn
  - all pending founding, buying, acquisition, and end-game fields
  - final rankings, winner, and last-action fields
- [x] Preserve `None` rack slots and convert sets to stable sorted lists.
- [x] Exclude room passwords, Socket.IO session IDs, connection maps, cleanup timers, and other process-only state.
- [x] Include registered spectator display names only as optional recording metadata; connected/disconnected presence is runtime state and is not required to replay gameplay.
- [x] Implement and test `deserialize_room(snapshot)` so a snapshot can reconstruct equivalent gameplay state without restoring credentials or live connections.
- [x] Add a SHA-256 hash of the canonical state JSON to each snapshot for corruption and comparison checks.

## 2. SQLite recording store

- [x] Add a small storage module, separate from Flask routes, using `sqlite3` and explicit transactions.
- [x] Create a `recorded_games` table with:
  - recording ID, room ID/name, mode, seed, schema/app version
  - started, updated, and completed timestamps
  - status and latest sequence number
- [x] Create a `game_snapshots` table with:
  - recording ID and monotonically increasing sequence number
  - timestamp, event type, actor ID, sanitized input JSON
  - full state JSON and state hash
  - a foreign key with `ON DELETE CASCADE`
- [x] Enable foreign keys and WAL mode for safe local access.
- [x] Initialize the schema idempotently when the application starts.
- [x] At successful game start, create the recording and write sequence `0` after seeded initialization and tile dealing.
- [x] In the same start transaction, retain the newest 10 games and delete every older record plus its snapshots.
- [x] Return the IDs of pruned recordings so matching in-memory rooms can have `recording_id` cleared.
- [x] Mark a recording completed when final liquidation succeeds.
- [x] Add `instance/*.sqlite3`, SQLite journal files, and exported recordings to `.gitignore`.

## 3. Action recording integration

- [x] Add one recording call after every successful state-changing action and before broadcasting the new state:
  - start game
  - sort tiles
  - buy stocks
  - place tile
  - found or decline a company
  - choose acquisition survivor
  - choose acquisition order
  - sell/trade/keep acquired shares
  - finish turn and finish game
- [x] Record normalized, validated action inputs only. Never record room passwords or raw request bodies.
- [x] Keep sequence assignment and snapshot insertion atomic.
- [x] Log recording failures with the room/recording ID while allowing the in-memory game to remain playable.
- [x] Expose a non-secret recording status and current sequence in internal diagnostics, but not player identity tokens in ordinary public room listings.

## 4. Seed input and display

- [x] Add a compact optional `Seed` input beside the game-mode selector in the room-creation UI.
- [x] Accept only decimal digits in the 32-bit range and return a clear validation error otherwise.
- [x] Generate and return the effective seed when the field is empty.
- [x] Store the seed on the room before the game starts and prevent later changes.
- [x] Show the seed in the room card and beside the mode badge on the game page so a setup can be shared and repeated.
- [x] Use only the room-local seeded RNG during initialization:
  - shuffle player order
  - shuffle the mode-specific tile deck
- [x] Replace room-code generation with `secrets.choice` so seeded gameplay never makes room identifiers predictable.
- [x] Document that identical seed, mode, player join order, and application version reproduce the same initial player order and tile/deck distribution.

## 5. Debug and export tooling

- [x] Add a local CLI script with commands to list the newest 10 recordings, inspect metadata, and export one recording as JSON.
- [x] Export snapshots in sequence order with their hashes and event envelopes.
- [x] Redact player IDs by default in exported files, with an explicit local debug flag for raw IDs.
- [x] Add a verification command that checks sequence continuity, hashes, and gameplay invariants without mutating live rooms.
- [x] Keep restoring a snapshot as a local/debug-only operation; do not expose an unauthenticated production restore endpoint.

## 6. Invariant checks

- [x] Validate serialized/restored snapshots for:
  - unique tiles across board, deck, and player racks
  - valid coordinates for the selected game mode
  - exactly 25 total shares per company across bank and players
  - valid current-turn index and pending-action player IDs
  - founded companies matching board company usage
  - valid acquisition targets, sizes, and processing indexes
- [x] Make the CLI verification output identify the first sequence and invariant that fails.

## 7. Tests and documentation

- [x] Round-trip every `Room` field through serialize/deserialize, including an acquisition in progress and a completed game.
- [x] Verify passwords and connection-only data never appear in stored JSON.
- [x] Verify snapshot sequence numbers and hashes.
- [x] Record 11 games in a temporary database and verify only the newest 10 remain and the oldest snapshots cascade-delete.
- [x] Verify an evicted active room does not recreate its recording on its next action.
- [x] Verify two rooms with the same mode, seed, and player join order receive identical player order, racks, and deck order.
- [x] Verify different seeds produce different initialization and blank seeds produce valid effective seeds.
- [x] Verify invalid, negative, and out-of-range seeds return HTTP 400.
- [x] Run the existing gameplay regression suite to ensure unseeded/default UI flows remain compatible.
- [x] Update the README with seed semantics, recording retention, database location, CLI usage, privacy notes, and visual test steps.

## Suggested implementation order

1. Canonical serializer/deserializer and invariant tests.
2. Seed parsing, room-local RNG, UI field, and reproducibility tests.
3. SQLite schema, snapshot writer, and ten-game retention tests.
4. Route integration and completion tracking.
5. Export/verification CLI and documentation.
6. Full automated regression run, followed by visual checks for the small seed input and displayed effective seed.

