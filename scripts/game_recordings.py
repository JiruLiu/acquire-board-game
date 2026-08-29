from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recording_store import RecordingStore, default_database_path  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect, export, and verify Acquire game recordings."
    )
    parser.add_argument(
        "--database",
        default=default_database_path(PROJECT_ROOT),
        help="SQLite recording database path.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List retained recordings newest first.")

    inspect_parser = subparsers.add_parser("inspect", help="Show recording metadata and events.")
    inspect_parser.add_argument("recording_id")

    export_parser = subparsers.add_parser("export", help="Export a recording as JSON.")
    export_parser.add_argument("recording_id")
    export_parser.add_argument("output", nargs="?")
    export_parser.add_argument(
        "--raw-ids",
        action="store_true",
        help="Keep raw player and spectator IDs instead of redacting them.",
    )

    verify_parser = subparsers.add_parser("verify", help="Verify hashes and game-state invariants.")
    verify_parser.add_argument("recording_id")

    snapshot_parser = subparsers.add_parser(
        "snapshot", help="Write one restorable state snapshot to stdout."
    )
    snapshot_parser.add_argument("recording_id")
    snapshot_parser.add_argument("--sequence", type=int)
    return parser


def print_games(store: RecordingStore) -> int:
    games = store.list_games()
    if not games:
        print("No recorded games.")
        return 0
    for game in games:
        print(
            f"{game['recording_id']}  {game['status']:<9}  "
            f"{game['mode']:<8}  seed={game['seed']:<10}  "
            f"snapshots={game['latest_sequence'] + 1:<3}  "
            f"room={game['room_id']}  started={game['started_at']}"
        )
    return 0


def inspect_game(store: RecordingStore, recording_id: str) -> int:
    recording = store.get_game(recording_id)
    if not recording:
        print(f"Recording {recording_id} was not found.", file=sys.stderr)
        return 1
    print(json.dumps(recording["game"], indent=2, sort_keys=True))
    print("Events:")
    for snapshot in recording["snapshots"]:
        print(
            f"  {snapshot['sequence']:>3}  {snapshot['recorded_at']}  "
            f"{snapshot['event_type']}"
        )
    return 0


def export_game(
    store: RecordingStore,
    recording_id: str,
    output: str | None,
    raw_ids: bool,
) -> int:
    recording = store.export_game(recording_id, raw_ids=raw_ids)
    if not recording:
        print(f"Recording {recording_id} was not found.", file=sys.stderr)
        return 1
    output_path = Path(output) if output else PROJECT_ROOT / "recording-exports" / f"{recording_id}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(recording, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output_path.resolve())
    return 0


def verify_game(store: RecordingStore, recording_id: str) -> int:
    errors = store.verify_game(recording_id)
    if errors:
        print(errors[0], file=sys.stderr)
        return 1
    print(f"Recording {recording_id} is valid.")
    return 0


def print_snapshot(store: RecordingStore, recording_id: str, sequence: int | None) -> int:
    recording = store.get_game(recording_id)
    if not recording:
        print(f"Recording {recording_id} was not found.", file=sys.stderr)
        return 1
    snapshots = recording["snapshots"]
    if sequence is None:
        snapshot = snapshots[-1] if snapshots else None
    else:
        snapshot = next(
            (item for item in snapshots if item["sequence"] == sequence),
            None,
        )
    if not snapshot:
        print("Requested snapshot was not found.", file=sys.stderr)
        return 1
    print(json.dumps(snapshot["state"], indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def main() -> int:
    args = build_parser().parse_args()
    store = RecordingStore(args.database)
    if args.command == "list":
        return print_games(store)
    if args.command == "inspect":
        return inspect_game(store, args.recording_id)
    if args.command == "export":
        return export_game(store, args.recording_id, args.output, args.raw_ids)
    if args.command == "verify":
        return verify_game(store, args.recording_id)
    if args.command == "snapshot":
        return print_snapshot(store, args.recording_id, args.sequence)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
