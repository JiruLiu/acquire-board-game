import os
import random
import re
import string
import threading
import uuid
from dataclasses import dataclass, field

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, join_room as socket_join_room


ROWS = list("ABCDEFGHI")
COLUMNS = [str(i) for i in range(1, 13)]
ALL_TILES = [f"{row}{column}" for row in ROWS for column in COLUMNS]
STOCK_COLORS = ["red", "yellow", "green", "pink", "purple", "orange", "blue"]
STARTING_CASH = 6000
STARTING_BANK_SHARES = 25
SUPER_COMPANY_SIZE = 10
GAME_END_COMPANY_SIZE = 41
ROOM_CREATION_INVITE_CODE = "evanston"
COMPANY_LEVELS = {
    "low": ["red", "yellow"],
    "mid": ["green", "pink", "purple"],
    "high": ["orange", "blue"],
}


@dataclass
class Player:
    id: str
    name: str
    money: int = STARTING_CASH
    stocks: dict[str, int] = field(
        default_factory=lambda: {color: 0 for color in STOCK_COLORS}
    )
    tiles: list[str | None] = field(default_factory=list)


@dataclass
class Room:
    id: str
    players: list[Player] = field(default_factory=list)
    started: bool = False
    current_turn: int = 0
    deck: list[str] = field(default_factory=list)
    board: dict[str, dict[str, str | None]] = field(default_factory=dict)
    companies_found: dict[str, bool] = field(
        default_factory=lambda: {color: False for color in STOCK_COLORS}
    )
    bank_stocks: dict[str, int] = field(
        default_factory=lambda: {color: STARTING_BANK_SHARES for color in STOCK_COLORS}
    )
    stocks_bought_this_turn: int = 0
    pending_found_player_id: str | None = None
    pending_found_tiles: list[str] = field(default_factory=list)
    pending_finish_player_id: str | None = None
    pending_acquire_starter_id: str | None = None
    pending_acquire_survivor_choices: list[str] = field(default_factory=list)
    pending_acquire_survivor: str | None = None
    pending_acquire_targets: list[str] = field(default_factory=list)
    pending_acquire_sizes: dict[str, int] = field(default_factory=dict)
    pending_acquire_reward_details: list[dict] = field(default_factory=list)
    pending_acquire_ordering: bool = False
    pending_acquire_player_order: list[str] = field(default_factory=list)
    pending_acquire_player_index: int = 0
    pending_acquire_target_index: int = 0
    end_pending: bool = False
    game_over: bool = False
    final_rankings: list[dict] = field(default_factory=list)
    winner: str | None = None
    last_action: str = "Waiting for players."
    last_placed_tile: str | None = None


app = Flask(__name__)
socketio = SocketIO(app, async_mode="threading")
rooms: dict[str, Room] = {}
room_lock = threading.Lock()
PLAYER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9]{1,10}$")
ROOM_CLEANUP_GRACE_SECONDS = float(os.environ.get("ROOM_CLEANUP_GRACE_SECONDS", "10"))
socket_membership: dict[str, tuple[str, str]] = {}
room_connected_sids: dict[str, set[str]] = {}
room_cleanup_timers: dict[str, threading.Timer] = {}


class RoomNotFoundError(ValueError):
    pass


def player_socket_room(room_id: str, player_id: str) -> str:
    return f"{room_id.upper()}:{player_id}"


def cancel_room_cleanup(room_id: str) -> None:
    timer = room_cleanup_timers.pop(room_id.upper(), None)
    if timer:
        timer.cancel()


def schedule_room_cleanup(room_id: str) -> None:
    normalized_room_id = room_id.upper()
    cancel_room_cleanup(normalized_room_id)

    def cleanup() -> None:
        with room_lock:
            active_sids = room_connected_sids.get(normalized_room_id)
            if active_sids:
                return
            rooms.pop(normalized_room_id, None)
            room_connected_sids.pop(normalized_room_id, None)
            room_cleanup_timers.pop(normalized_room_id, None)

    timer = threading.Timer(ROOM_CLEANUP_GRACE_SECONDS, cleanup)
    timer.daemon = True
    room_cleanup_timers[normalized_room_id] = timer
    timer.start()


def detach_socket(sid: str) -> None:
    membership = socket_membership.pop(sid, None)
    if not membership:
        return

    room_id, _player_id = membership
    active_sids = room_connected_sids.get(room_id)
    if not active_sids:
        return

    active_sids.discard(sid)
    if active_sids:
        return

    room_connected_sids.pop(room_id, None)
    schedule_room_cleanup(room_id)


def broadcast_room_state(room: Room) -> None:
    payloads = [
        (
            player_socket_room(room.id, player.id),
            build_public_room_state(room, player.id),
        )
        for player in room.players
    ]

    def emit_payloads() -> None:
        for socket_room, state in payloads:
            socketio.emit("room_state", state, to=socket_room)

    socketio.start_background_task(emit_payloads)


def build_public_room_state(room: Room, viewer_id: str | None) -> dict:
    return {
        "room_id": room.id,
        "started": room.started,
        "current_turn_player_id": (
            room.players[room.current_turn].id if room.started and room.players else None
        ),
        "winner": room.winner,
        "end_pending": room.end_pending,
        "game_over": room.game_over,
        "final_rankings": room.final_rankings,
        "last_action": room.last_action,
        "last_placed_tile": room.last_placed_tile,
        "players": [
            {
                "id": player.id,
                "name": player.name,
                "money": player.money,
                "stocks": player.stocks,
                "tile_count": len([tile for tile in player.tiles if tile]),
                "tiles": player.tiles if player.id == viewer_id else [],
            }
            for player in room.players
        ],
        "bank": {
            "stocks": room.bank_stocks,
        },
        "companies_found": room.companies_found,
        "company_sizes": company_sizes(room),
        "share_prices": share_prices(room),
        "stocks_bought_this_turn": room.stocks_bought_this_turn,
        "pending_found_player_id": room.pending_found_player_id,
        "pending_found_tiles": room.pending_found_tiles,
        "pending_finish_player_id": room.pending_finish_player_id,
        "pending_acquire": pending_acquire_state(room),
        "deck_count": len(room.deck),
        "board": room.board,
        "viewer_id": viewer_id,
    }


def draw_tile(room: Room, player: Player, preserve_slot: bool = False) -> bool:
    while room.deck:
        tile = room.deck.pop()
        if tile_connects_super_company(room, tile):
            continue
        if preserve_slot and None in player.tiles:
            player.tiles[player.tiles.index(None)] = tile
        else:
            player.tiles.append(tile)
            player.tiles.sort(key=lambda value: (value is None, tile_sort_key(value) if value else (99, 99)))
        return True
    return False


def tile_sort_key(tile: str) -> tuple[int, int]:
    return ROWS.index(tile[0]), int(tile[1:])


def display_tile(tile: str) -> str:
    return f"{tile[1:]}{tile[0]}"


def board_company(value: dict[str, str | None] | str) -> str | None:
    if isinstance(value, dict):
        return value.get("company")
    return None


def company_sizes(room: Room) -> dict[str, int]:
    sizes = {color: 0 for color in STOCK_COLORS}
    for value in room.board.values():
        company = board_company(value)
        if company in sizes:
            sizes[company] += 1
    return sizes


def super_companies(room: Room) -> set[str]:
    return {
        color
        for color, size in company_sizes(room).items()
        if size > SUPER_COMPANY_SIZE
    }


def active_player_tiles(player: Player) -> list[str]:
    return [tile for tile in player.tiles if tile]


def tile_connects_super_company(room: Room, tile: str) -> bool:
    if tile in room.board:
        return False

    supers = super_companies(room)
    if not supers:
        return False

    connected = {tile}
    pending = [tile]
    while pending:
        current = pending.pop()
        for neighbor in adjacent_tiles(current):
            if neighbor in connected or neighbor not in room.board:
                continue
            if board_company(room.board[neighbor]):
                continue
            connected.add(neighbor)
            pending.append(neighbor)

    connected_supers = set()
    for connected_tile in connected:
        for neighbor in adjacent_tiles(connected_tile):
            if neighbor not in room.board:
                continue
            company = board_company(room.board[neighbor])
            if company in supers:
                connected_supers.add(company)
    return len(connected_supers) >= 2


def remove_invalid_tiles(room: Room) -> list[str]:
    invalid_tiles = {
        tile
        for tile in ALL_TILES
        if tile not in room.board and tile_connects_super_company(room, tile)
    }
    if not invalid_tiles:
        return []

    before_deck = len(room.deck)
    room.deck = [tile for tile in room.deck if tile not in invalid_tiles]
    removed_tiles = set(invalid_tiles) if before_deck != len(room.deck) else set()

    for player in room.players:
        for index, tile in enumerate(player.tiles):
            if tile in invalid_tiles:
                player.tiles[index] = None
                removed_tiles.add(tile)
    return sorted(removed_tiles, key=tile_sort_key)


def append_invalid_tiles_notice(room: Room, invalid_tiles: list[str]) -> None:
    if not invalid_tiles:
        return
    tile_labels = ", ".join(display_tile(tile) for tile in invalid_tiles)
    room.last_action += (
        f" Invalid tile{'' if len(invalid_tiles) == 1 else 's'} "
        f"{tile_labels} became unplayable."
    )


def fill_player_tiles(room: Room, player: Player) -> int:
    tiles_before = len(active_player_tiles(player))
    remove_invalid_tiles(room)
    while len(active_player_tiles(player)) < 6 and room.deck:
        if not draw_tile(room, player, preserve_slot=True):
            break
    return len(active_player_tiles(player)) - tiles_before


def no_tiles_left_anywhere(room: Room) -> bool:
    return not room.deck and all(not active_player_tiles(player) for player in room.players)


def game_end_condition(room: Room) -> bool:
    return no_tiles_left_anywhere(room) or any(
        size > GAME_END_COMPANY_SIZE for size in company_sizes(room).values()
    )


def mark_end_pending_if_needed(room: Room) -> None:
    if game_end_condition(room):
        room.end_pending = True


def has_unfounded_company(room: Room) -> bool:
    return any(not found for found in room.companies_found.values())


def begin_buying_if_current_player_has_no_tiles(room: Room) -> bool:
    if not room.started or room.game_over or room.pending_finish_player_id:
        return False
    current_player = room.players[room.current_turn]
    if active_player_tiles(current_player):
        return False
    room.pending_finish_player_id = current_player.id
    room.last_action = (
        f"{current_player.name} has no tiles. Buy stocks or click Finish."
    )
    return True


def bonus_values_for_price(price: int) -> tuple[int, int, int]:
    return price * 10, (price * 15 // 2) // 100 * 100, price * 5


def shareholder_reward_allocations(room: Room, color: str) -> tuple[list[dict], dict[str, int]]:
    size = company_sizes(room).get(color, 0)
    if not room.companies_found.get(color) or size <= 0:
        return [], {}

    price = share_price(color, size)
    first, second, third = bonus_values_for_price(price)
    shareholders = [
        player
        for player in room.players
        if player.stocks.get(color, 0) > 0
    ]
    if not shareholders:
        return [], {}

    shareholders.sort(key=lambda player: player.stocks.get(color, 0), reverse=True)
    groups: list[list[Player]] = []
    for player in shareholders:
        if not groups or player.stocks.get(color, 0) != groups[-1][0].stocks.get(color, 0):
            groups.append([player])
        else:
            groups[-1].append(player)

    awards_by_player = {player.id: 0 for player in room.players}
    details = []

    def pay(group: list[Player], amount: int, label: str) -> None:
        if not group or amount <= 0:
            return
        share = amount // len(group)
        names = [player.name for player in group]
        for player in group:
            awards_by_player[player.id] += share
        details.append(
            {
                "color": color,
                "rank": label,
                "player_ids": [player.id for player in group],
                "names": names,
                "shares": group[0].stocks.get(color, 0),
                "amount": amount,
                "each": share,
            }
        )

    if len(shareholders) == 1:
        pay(groups[0], first + third, "first and third")
    elif len(groups[0]) >= 2:
        pay(groups[0], first + second, "tied first")
    else:
        pay(groups[0], first, "first")
        if len(groups) > 1:
            if len(groups[1]) >= 2:
                pay(groups[1], second + third, "tied second")
            else:
                pay(groups[1], second, "second")
                if len(groups) > 2:
                    pay(groups[2], third, "third" if len(groups[2]) == 1 else "tied third")

    return details, {player_id: amount for player_id, amount in awards_by_player.items() if amount}


def pay_shareholder_rewards(room: Room, color: str) -> list[dict]:
    details, awards = shareholder_reward_allocations(room, color)
    if not awards:
        return []
    for player in room.players:
        player.money += awards.get(player.id, 0)
    return details


def describe_reward_details(details: list[dict]) -> str:
    if not details:
        return "No shareholder rewards were paid."
    parts = []
    for detail in details:
        recipients = ", ".join(detail["names"])
        if len(detail["names"]) > 1:
            parts.append(
                f"{recipients} shared ${detail['amount']} for {detail['rank']} "
                f"(${detail['each']} each)"
            )
        else:
            parts.append(f"{recipients} received ${detail['each']} for {detail['rank']}")
    return "; ".join(parts) + "."


def final_shareholder_rewards(room: Room) -> tuple[list[dict], dict[str, int]]:
    details = []
    totals = {player.id: 0 for player in room.players}
    for color in STOCK_COLORS:
        color_details, awards = shareholder_reward_allocations(room, color)
        details.extend(color_details)
        for player_id, amount in awards.items():
            totals[player_id] += amount
    return details, {player_id: amount for player_id, amount in totals.items() if amount}


def build_final_rankings(room: Room) -> list[dict]:
    prices = share_prices(room)
    reward_details, reward_totals = final_shareholder_rewards(room)
    rankings = []
    for player in room.players:
        cash_before_sales = player.money
        shareholder_rewards = reward_totals.get(player.id, 0)
        stock_sales = []
        stock_sale_total = 0
        for color in STOCK_COLORS:
            shares = player.stocks.get(color, 0)
            if not shares:
                continue
            price = prices.get(color) or 0
            subtotal = shares * price
            stock_sales.append(
                {
                    "color": color,
                    "shares": shares,
                    "price": price,
                    "subtotal": subtotal,
                }
            )
            stock_sale_total += subtotal

        final_total = cash_before_sales + shareholder_rewards + stock_sale_total
        rankings.append(
            {
                "player_id": player.id,
                "name": player.name,
                "money": final_total,
                "cash_before_sales": cash_before_sales,
                "shareholder_reward_total": shareholder_rewards,
                "shareholder_rewards": [
                    detail for detail in reward_details if player.id in detail["player_ids"]
                ],
                "stock_sale_total": stock_sale_total,
                "stock_sales": stock_sales,
                "final_total": final_total,
            }
        )

    rankings.sort(key=lambda item: item["final_total"], reverse=True)
    return rankings


def liquidate_and_rank(room: Room) -> None:
    room.final_rankings = build_final_rankings(room)
    room.winner = room.final_rankings[0]["name"] if room.final_rankings else None
    room.game_over = True
    room.end_pending = False
    room.pending_finish_player_id = None
    clear_pending_acquire(room)
    room.last_action = f"Game over. {room.winner} wins."


def company_level(color: str) -> str:
    for level, colors in COMPANY_LEVELS.items():
        if color in colors:
            return level
    return "low"


def price_row_for_size(size: int) -> int:
    if size <= 2:
        return 0
    if size == 3:
        return 1
    if size == 4:
        return 2
    if size == 5:
        return 3
    if size <= 10:
        return 4
    if size <= 20:
        return 5
    if size <= 30:
        return 6
    if size <= 40:
        return 7
    return 8


def share_price(color: str, size: int) -> int:
    row = price_row_for_size(size)
    offset = {"low": 0, "mid": 1, "high": 2}[company_level(color)]
    return (row + offset + 2) * 100


def share_prices(room: Room) -> dict[str, int | None]:
    sizes = company_sizes(room)
    return {
        color: share_price(color, sizes[color]) if room.companies_found.get(color) else None
        for color in STOCK_COLORS
    }


def pending_acquire_state(room: Room) -> dict | None:
    if not room.pending_acquire_survivor and not room.pending_acquire_survivor_choices:
        return None
    base_state = {
        "starter_id": room.pending_acquire_starter_id,
        "survivor": room.pending_acquire_survivor,
        "survivor_choices": room.pending_acquire_survivor_choices,
        "targets": room.pending_acquire_targets,
        "sizes": room.pending_acquire_sizes,
        "ordering": room.pending_acquire_ordering,
        "choosing_survivor": bool(room.pending_acquire_survivor_choices),
    }
    if room.pending_acquire_survivor_choices:
        return {
            **base_state,
            "active_target": None,
            "active_player_id": room.pending_acquire_starter_id,
            "active_player_name": "",
            "stock_count": 0,
        }
    if room.pending_acquire_ordering:
        return {
            **base_state,
            "active_target": None,
            "active_player_id": room.pending_acquire_starter_id,
            "active_player_name": "",
            "stock_count": 0,
        }
    if room.pending_acquire_target_index >= len(room.pending_acquire_targets):
        return None
    if room.pending_acquire_player_index >= len(room.pending_acquire_player_order):
        return None

    player_id = room.pending_acquire_player_order[room.pending_acquire_player_index]
    player = next((player for player in room.players if player.id == player_id), None)
    target = room.pending_acquire_targets[room.pending_acquire_target_index]
    return {
        **base_state,
        "active_target": target,
        "active_player_id": player_id,
        "active_player_name": player.name if player else "",
        "stock_count": player.stocks.get(target, 0) if player else 0,
    }


def clear_pending_acquire(room: Room) -> None:
    room.pending_acquire_starter_id = None
    room.pending_acquire_survivor_choices = []
    room.pending_acquire_survivor = None
    room.pending_acquire_targets = []
    room.pending_acquire_sizes = {}
    room.pending_acquire_reward_details = []
    room.pending_acquire_ordering = False
    room.pending_acquire_player_order = []
    room.pending_acquire_player_index = 0
    room.pending_acquire_target_index = 0


def reverse_turn_order(room: Room) -> list[str]:
    return [
        room.players[(room.current_turn - offset) % len(room.players)].id
        for offset in range(len(room.players))
    ]


def choose_acquire_survivor(room: Room, companies: set[str]) -> str:
    sizes = company_sizes(room)
    return max(
        companies,
        key=lambda color: (sizes[color], -STOCK_COLORS.index(color)),
    )


def acquire_survivor_choices(companies: set[str], sizes: dict[str, int]) -> list[str]:
    largest_size = max(sizes[color] for color in companies)
    return sorted(
        (color for color in companies if sizes[color] == largest_size),
        key=STOCK_COLORS.index,
    )


def ordered_acquire_targets(companies: set[str], survivor: str, sizes: dict[str, int]) -> list[str]:
    return sorted(
        (color for color in companies if color != survivor),
        key=lambda color: (sizes[color], STOCK_COLORS.index(color)),
    )


def acquire_order_has_tie(targets: list[str], sizes: dict[str, int]) -> bool:
    seen_sizes = set()
    for target in targets:
        size = sizes[target]
        if size in seen_sizes:
            return True
        seen_sizes.add(size)
    return False


def advance_acquire_step(room: Room) -> None:
    if room.pending_acquire_ordering:
        return

    while room.pending_acquire_survivor and room.pending_acquire_targets:
        if room.pending_acquire_target_index >= len(room.pending_acquire_targets):
            complete_acquire(room)
            return

        target = room.pending_acquire_targets[room.pending_acquire_target_index]
        while room.pending_acquire_player_index < len(room.pending_acquire_player_order):
            player_id = room.pending_acquire_player_order[room.pending_acquire_player_index]
            player = next((player for player in room.players if player.id == player_id), None)
            if player and player.stocks.get(target, 0) > 0:
                room.last_action = (
                    f"Notice, It's {player.name}'s turn to process the stocks!"
                )
                return
            room.pending_acquire_player_index += 1

        room.pending_acquire_target_index += 1
        room.pending_acquire_player_index = 0

    complete_acquire(room)


def complete_acquire(room: Room) -> None:
    survivor = room.pending_acquire_survivor
    targets = list(room.pending_acquire_targets)
    reward_details = list(room.pending_acquire_reward_details)
    if survivor:
        for value in room.board.values():
            if not isinstance(value, dict):
                continue
            if value.get("company") in targets or value.get("company") == "acquire":
                value["company"] = survivor
        for target in targets:
            room.companies_found[target] = False

    starter = next(
        (player for player in room.players if player.id == room.pending_acquire_starter_id),
        None,
    )
    clear_pending_acquire(room)
    if starter:
        room.pending_finish_player_id = starter.id
        invalid_tiles = remove_invalid_tiles(room)
        mark_end_pending_if_needed(room)
        room.last_action = (
            f"Acquire finished. {survivor} is the surviving company. "
            f"Shareholder rewards: {describe_reward_details(reward_details)} "
            "Buy stocks or click Finish."
        )
        append_invalid_tiles_notice(room, invalid_tiles)
        if room.end_pending:
            room.last_action += " Game will end when this turn is finished."


def adjacent_companies(room: Room, tile: str) -> set[str]:
    companies = set()
    for neighbor in adjacent_tiles(tile):
        if neighbor not in room.board:
            continue
        company = board_company(room.board[neighbor])
        if company in STOCK_COLORS:
            companies.add(company)
    return companies


def adjacent_tiles(tile: str) -> list[str]:
    row = tile[0]
    column = int(tile[1:])
    row_index = ROWS.index(row)
    candidates = []
    if row_index > 0:
        candidates.append(f"{ROWS[row_index - 1]}{column}")
    if row_index < len(ROWS) - 1:
        candidates.append(f"{ROWS[row_index + 1]}{column}")
    if column > 1:
        candidates.append(f"{row}{column - 1}")
    if column < len(COLUMNS):
        candidates.append(f"{row}{column + 1}")
    return candidates


def connected_colorless_tiles(room: Room, tile: str) -> list[str]:
    if tile not in room.board or board_company(room.board[tile]):
        return []

    connected = []
    pending = [tile]
    seen = {tile}
    while pending:
        current = pending.pop()
        connected.append(current)
        for neighbor in adjacent_tiles(current):
            if neighbor in seen or neighbor not in room.board:
                continue
            if board_company(room.board[neighbor]):
                continue
            seen.add(neighbor)
            pending.append(neighbor)
    return connected


def advance_turn(room: Room) -> str:
    room.current_turn = (room.current_turn + 1) % len(room.players)
    return room.players[room.current_turn].name


def new_room_id() -> str:
    while True:
        candidate = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if candidate not in rooms:
            return candidate


def get_room_or_404(room_id: str) -> Room:
    room = rooms.get(room_id.upper())
    if not room:
        raise RoomNotFoundError("Room not found.")
    return room


def find_player(room: Room, player_id: str | None) -> Player | None:
    return next((player for player in room.players if player.id == player_id), None)


def validate_player_name(player_name: str) -> None:
    if not PLAYER_NAME_PATTERN.fullmatch(player_name):
        raise ValueError("Name must be 1-10 letters or numbers only.")


def ensure_unique_player_name(room: Room, player_name: str) -> None:
    if any(player.name.lower() == player_name.lower() for player in room.players):
        raise ValueError("That name is already taken in this room.")


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/game/<room_id>")
def game_page(room_id: str):
    player_id = request.args.get("player_id", "")
    return render_template("game.html", room_id=room_id.upper(), player_id=player_id)


@socketio.on("join_room_state")
def join_room_state(data):
    room_id = (data.get("room_id") or "").upper()
    player_id = data.get("player_id") or ""
    if room_id and player_id:
        socket_join_room(player_socket_room(room_id, player_id))
        with room_lock:
            detach_socket(request.sid)
            cancel_room_cleanup(room_id)
            socket_membership[request.sid] = (room_id, player_id)
            room_connected_sids.setdefault(room_id, set()).add(request.sid)
            room = rooms.get(room_id)
            if room:
                socketio.emit(
                    "room_state",
                    build_public_room_state(room, player_id),
                    to=request.sid,
                )


@socketio.on("disconnect")
def handle_disconnect():
    with room_lock:
        detach_socket(request.sid)


@app.post("/api/rooms")
def create_room():
    data = request.get_json(silent=True) or {}
    player_name = (data.get("player_name") or "").strip()
    invitation_code = (data.get("invitation_code") or "").strip().lower()

    with room_lock:
        try:
            validate_player_name(player_name)
            if invitation_code != ROOM_CREATION_INVITE_CODE:
                raise ValueError("Invalid invitation code.")
            room_id = new_room_id()
            player = Player(id=uuid.uuid4().hex, name=player_name)
            room = Room(id=room_id, players=[player], last_action=f"{player_name} created the room.")
            rooms[room_id] = room
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    return jsonify(
        {
            "room_id": room_id,
            "player_id": player.id,
            "state": build_public_room_state(room, player.id),
        }
    )


@app.post("/api/rooms/<room_id>/join")
def join_room(room_id: str):
    data = request.get_json(silent=True) or {}
    player_name = (data.get("player_name") or "").strip()

    try:
        with room_lock:
            validate_player_name(player_name)
            room = get_room_or_404(room_id)
            if room.started:
                return jsonify({"error": "The game has already started."}), 400
            if len(room.players) >= 5:
                return jsonify({"error": "This room is full. The limit is 5 players."}), 400
            ensure_unique_player_name(room, player_name)

            player = Player(id=uuid.uuid4().hex, name=player_name)
            room.players.append(player)
            room.last_action = f"{player_name} joined the room."
            state = build_public_room_state(room, player.id)
            broadcast_room_state(room)
    except RoomNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"room_id": room.id, "player_id": player.id, "state": state})


@app.get("/api/rooms/<room_id>/state")
def room_state(room_id: str):
    viewer_id = request.args.get("player_id")
    try:
        with room_lock:
            room = get_room_or_404(room_id)
            state = build_public_room_state(room, viewer_id)
    except RoomNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404

    return jsonify(state)


@app.post("/api/rooms/<room_id>/start")
def start_room(room_id: str):
    data = request.get_json(silent=True) or {}
    player_id = data.get("player_id")

    try:
        with room_lock:
            room = get_room_or_404(room_id)
            if room.started:
                return jsonify({"error": "The game is already running."}), 400
            if room.players[0].id != player_id:
                return jsonify({"error": "Only the room creator can start the game."}), 403
            if len(room.players) < 2 or len(room.players) > 5:
                return jsonify({"error": "A game must have 2-5 players."}), 400
            lowered_names = [player.name.lower() for player in room.players]
            if len(lowered_names) != len(set(lowered_names)):
                return jsonify({"error": "Duplicate player names are not allowed."}), 400

            room.started = True
            room.deck = ALL_TILES[:]
            random.shuffle(room.deck)
            room.board = {}
            room.companies_found = {color: False for color in STOCK_COLORS}
            room.bank_stocks = {color: STARTING_BANK_SHARES for color in STOCK_COLORS}
            room.stocks_bought_this_turn = 0
            room.pending_found_player_id = None
            room.pending_found_tiles = []
            room.pending_finish_player_id = None
            clear_pending_acquire(room)
            room.end_pending = False
            room.game_over = False
            room.final_rankings = []
            room.current_turn = 0
            room.winner = None
            room.last_placed_tile = None
            for player in room.players:
                player.tiles = []
                for _ in range(6):
                    draw_tile(room, player)
            begin_buying_if_current_player_has_no_tiles(room)
            room.last_action = f"The game started. {room.players[0].name} goes first."
            state = build_public_room_state(room, player_id)
            broadcast_room_state(room)
    except RoomNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404

    return jsonify(state)


def rack_sort_key(tile: str) -> tuple[int, int]:
    return int(tile[1:]), ROWS.index(tile[0])


def process_stock_purchases(
    room: Room,
    player_id: str,
    purchases: dict,
    require_purchase: bool = True,
) -> tuple[Player, int, int, dict[str, int]]:
    if not isinstance(purchases, dict):
        raise ValueError("Stock purchases must be a list of company quantities.")
    if pending_acquire_state(room):
        raise ValueError("Resolve the Acquire first.")
    if room.pending_found_player_id:
        raise ValueError("Resolve the company founding decision first.")
    if room.pending_finish_player_id != player_id:
        raise PermissionError("Place a tile before buying stocks.")

    player = room.players[room.current_turn]
    if player.id != player_id:
        raise PermissionError("It is not your turn.")

    clean_purchases = {}
    for color, quantity in purchases.items():
        if color not in STOCK_COLORS:
            raise ValueError("Unknown company color.")
        try:
            quantity = int(quantity)
        except (TypeError, ValueError) as exc:
            raise ValueError("Stock quantity must be a number.") from exc
        if quantity < 0:
            raise ValueError("Stock quantity cannot be negative.")
        if quantity:
            clean_purchases[color] = quantity

    quantity_total = sum(clean_purchases.values())
    if require_purchase and quantity_total <= 0:
        raise ValueError("Choose at least one stock to buy.")
    if room.stocks_bought_this_turn + quantity_total > 3:
        raise ValueError("You can buy at most three stocks per turn.")

    prices = share_prices(room)
    total_cost = 0
    for color, quantity in clean_purchases.items():
        if not room.companies_found.get(color):
            raise ValueError("That company has not been founded yet.")
        if room.bank_stocks.get(color, 0) < quantity:
            raise ValueError("The bank does not have enough shares.")
        total_cost += (prices[color] or 0) * quantity

    if player.money < total_cost:
        raise ValueError("You do not have enough money.")

    for color, quantity in clean_purchases.items():
        player.stocks[color] += quantity
        room.bank_stocks[color] -= quantity
    player.money -= total_cost
    room.stocks_bought_this_turn += quantity_total

    return player, quantity_total, total_cost, clean_purchases


@app.post("/api/rooms/<room_id>/sort_tiles")
def sort_tiles(room_id: str):
    data = request.get_json(silent=True) or {}
    player_id = data.get("player_id")

    try:
        with room_lock:
            room = get_room_or_404(room_id)
            player = find_player(room, player_id)
            if not player:
                return jsonify({"error": "Player not found in this room."}), 403
            active_tiles = sorted([tile for tile in player.tiles if tile], key=rack_sort_key)
            empty_slots = [tile for tile in player.tiles if not tile]
            player.tiles = active_tiles + empty_slots
            state = build_public_room_state(room, player_id)
            broadcast_room_state(room)
    except RoomNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404

    return jsonify(state)


@app.post("/api/rooms/<room_id>/buy_stocks")
def buy_stocks(room_id: str):
    data = request.get_json(silent=True) or {}
    player_id = data.get("player_id")
    purchases = data.get("purchases") or {}

    try:
        with room_lock:
            room = get_room_or_404(room_id)
            if not room.started:
                return jsonify({"error": "The game has not started yet."}), 400
            if room.game_over:
                return jsonify({"error": "The game is already over."}), 400
            player, quantity_total, total_cost, clean_purchases = process_stock_purchases(
                room,
                player_id,
                purchases,
            )

            bought_text = ", ".join(
                f"{quantity} {color}" for color, quantity in clean_purchases.items()
            )
            room.last_action = (
                f"{player.name} bought {bought_text} stock"
                f"{'' if quantity_total == 1 else 's'} for ${total_cost}."
            )
            state = build_public_room_state(room, player_id)
            broadcast_room_state(room)
    except RoomNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(state)


@app.post("/api/rooms/<room_id>/place_tile")
def place_tile(room_id: str):
    data = request.get_json(silent=True) or {}
    player_id = data.get("player_id")
    tile = (data.get("tile") or "").upper()

    if tile not in ALL_TILES:
        return jsonify({"error": "Unknown tile."}), 400

    try:
        with room_lock:
            room = get_room_or_404(room_id)
            if not room.started:
                return jsonify({"error": "The game has not started yet."}), 400
            if room.game_over:
                return jsonify({"error": "The game is already over."}), 400
            remove_invalid_tiles(room)
            if pending_acquire_state(room):
                return jsonify({"error": "Resolve the Acquire first."}), 400
            if room.pending_found_player_id:
                return jsonify({"error": "Resolve the company founding decision first."}), 400
            if room.pending_finish_player_id:
                return jsonify({"error": "Finish the current turn first."}), 400

            current_player = room.players[room.current_turn]
            if current_player.id != player_id:
                return jsonify({"error": "It is not your turn."}), 403
            if tile in room.board:
                return jsonify({"error": "That tile has already been placed."}), 400
            if tile_connects_super_company(room, tile):
                remove_invalid_tiles(room)
                return jsonify({"error": "That tile connects two super companies and cannot be played."}), 400
            if tile not in current_player.tiles:
                return jsonify({"error": "That tile is not in your rack."}), 400

            tile_index = current_player.tiles.index(tile)
            current_player.tiles[tile_index] = None
            room.board[tile] = {"placed_by": current_player.name, "company": None}
            room.last_placed_tile = tile

            adjacent_company_colors = adjacent_companies(room, tile)
            connected = connected_colorless_tiles(room, tile)
            tile_label = display_tile(tile)
            if len(adjacent_company_colors) >= 2:
                sizes_before_acquire = company_sizes(room)
                survivor_choices = acquire_survivor_choices(adjacent_company_colors, sizes_before_acquire)
                survivor = None if len(survivor_choices) > 1 else survivor_choices[0]
                targets = (
                    ordered_acquire_targets(adjacent_company_colors, survivor, sizes_before_acquire)
                    if survivor
                    else []
                )
                acquire_reward_details = (
                    [
                        detail
                        for target in targets
                        for detail in pay_shareholder_rewards(room, target)
                    ]
                    if survivor
                    else []
                )
                for connected_tile in connected:
                    if connected_tile in room.board and isinstance(room.board[connected_tile], dict):
                        room.board[connected_tile]["company"] = "acquire"
                room.pending_acquire_starter_id = current_player.id
                room.pending_acquire_survivor_choices = survivor_choices if len(survivor_choices) > 1 else []
                room.pending_acquire_survivor = survivor
                room.pending_acquire_targets = targets
                room.pending_acquire_sizes = {
                    color: sizes_before_acquire[color]
                    for color in adjacent_company_colors
                }
                room.pending_acquire_reward_details = acquire_reward_details
                room.pending_acquire_ordering = bool(
                    survivor and acquire_order_has_tie(targets, sizes_before_acquire)
                )
                room.pending_acquire_player_order = reverse_turn_order(room)
                room.pending_acquire_player_index = 0
                room.pending_acquire_target_index = 0
                room.pending_finish_player_id = None
                pending = pending_acquire_state(room)
                if room.pending_acquire_survivor_choices:
                    room.last_action = (
                        f"{current_player.name} placed {tile_label}. "
                        f"Acquire: tied companies {', '.join(survivor_choices)} are largest. "
                        f"{current_player.name} must choose the surviving company."
                    )
                elif room.pending_acquire_ordering:
                    tied_sizes = sorted({
                        sizes_before_acquire[target]
                        for target in targets
                        if sum(1 for other in targets if sizes_before_acquire[other] == sizes_before_acquire[target]) > 1
                    })
                    room.last_action = (
                        f"{current_player.name} placed {tile_label}. "
                        f"Acquire: {survivor} acquires {', '.join(targets)}. "
                        f"Shareholder rewards: {describe_reward_details(acquire_reward_details)} "
                        f"{current_player.name} must choose acquire order for tied size"
                        f"{'' if len(tied_sizes) == 1 else 's'} {', '.join(map(str, tied_sizes))}."
                    )
                else:
                    advance_acquire_step(room)
                    pending = pending_acquire_state(room)
                if (
                    pending
                    and not room.pending_acquire_ordering
                    and not room.pending_acquire_survivor_choices
                ):
                    room.last_action = (
                        f"{current_player.name} placed {tile_label}. "
                        f"Acquire: {survivor} acquires {', '.join(targets)}. "
                        f"Shareholder rewards: {describe_reward_details(acquire_reward_details)} "
                        f"Notice, It's {pending['active_player_name']}'s turn to process the stocks!"
                    )
                elif (
                    not room.pending_acquire_ordering
                    and not room.pending_acquire_survivor_choices
                    and room.pending_acquire_survivor
                ):
                    room.last_action = (
                        f"{current_player.name} placed {tile_label}. "
                        f"Acquire finished. {survivor} is the surviving company. "
                        f"Shareholder rewards: {describe_reward_details(acquire_reward_details)}"
                    )
            elif len(adjacent_company_colors) == 1:
                company = next(iter(adjacent_company_colors))
                for connected_tile in connected:
                    if connected_tile in room.board and isinstance(room.board[connected_tile], dict):
                        room.board[connected_tile]["company"] = company
                room.pending_finish_player_id = current_player.id
                room.last_action = (
                    f"{current_player.name} placed {tile_label} into the {company} company. "
                    "Buy stocks or click Finish."
                )
            elif len(connected) >= 2:
                if has_unfounded_company(room):
                    room.pending_found_player_id = current_player.id
                    room.pending_found_tiles = connected
                    room.last_action = (
                        f"{current_player.name} placed {tile_label}. Choose whether to found a company."
                    )
                else:
                    room.pending_finish_player_id = current_player.id
                    room.last_action = (
                        f"{current_player.name} placed {tile_label}. "
                        "All companies are already founded, so no new company can be formed. "
                        "Buy stocks or click Finish."
                    )
            else:
                room.pending_finish_player_id = current_player.id
                room.last_action = (
                    f"{current_player.name} placed {tile_label}. Buy stocks or click Finish."
                )

            removed = remove_invalid_tiles(room)
            mark_end_pending_if_needed(room)
            append_invalid_tiles_notice(room, removed)
            if room.end_pending:
                room.last_action += " Game will end when this turn is finished."
            state = build_public_room_state(room, player_id)
            broadcast_room_state(room)
    except RoomNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404

    return jsonify(state)


@app.post("/api/rooms/<room_id>/found_company")
def found_company(room_id: str):
    data = request.get_json(silent=True) or {}
    player_id = data.get("player_id")
    color = (data.get("color") or "").lower()

    if color and color not in STOCK_COLORS:
        return jsonify({"error": "Unknown company color."}), 400

    try:
        with room_lock:
            room = get_room_or_404(room_id)
            if not room.started:
                return jsonify({"error": "The game has not started yet."}), 400
            if room.game_over:
                return jsonify({"error": "The game is already over."}), 400
            if pending_acquire_state(room):
                return jsonify({"error": "Resolve the Acquire first."}), 400
            player = next((player for player in room.players if player.id == player_id), None)
            if not player:
                return jsonify({"error": "Player not found in this room."}), 403
            if room.pending_found_player_id != player_id:
                return jsonify({"error": "No company founding decision is waiting for you."}), 400
            if color and room.companies_found.get(color):
                return jsonify({"error": "That company has already been founded."}), 400

            if color:
                room.companies_found[color] = True
                for tile in room.pending_found_tiles:
                    if tile in room.board and isinstance(room.board[tile], dict):
                        room.board[tile]["company"] = color
                if room.bank_stocks.get(color, 0) > 0:
                    player.stocks[color] += 1
                    room.bank_stocks[color] -= 1
                    action = (
                        f"{player.name} founded the {color} company and received "
                        f"1 free {color} stock."
                    )
                else:
                    action = (
                        f"{player.name} founded the {color} company, but the bank "
                        "had no free stock left."
                    )
            else:
                action = f"{player.name} chose not to found a company."

            room.pending_found_player_id = None
            room.pending_found_tiles = []
            room.pending_finish_player_id = player.id
            removed = remove_invalid_tiles(room)
            mark_end_pending_if_needed(room)
            room.last_action = f"{action} Buy stocks or click Finish."
            append_invalid_tiles_notice(room, removed)
            if room.end_pending:
                room.last_action += " Game will end when this turn is finished."
            state = build_public_room_state(room, player_id)
            broadcast_room_state(room)
    except RoomNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404

    return jsonify(state)


@app.post("/api/rooms/<room_id>/set_acquire_survivor")
def set_acquire_survivor(room_id: str):
    data = request.get_json(silent=True) or {}
    player_id = data.get("player_id")
    survivor = (data.get("survivor") or "").lower()

    try:
        with room_lock:
            room = get_room_or_404(room_id)
            if not room.pending_acquire_survivor_choices:
                return jsonify({"error": "No surviving-company decision is waiting."}), 400
            if room.pending_acquire_starter_id != player_id:
                return jsonify({"error": "Only the Acquire starter can choose the survivor."}), 403
            if survivor not in room.pending_acquire_survivor_choices:
                return jsonify({"error": "Choose one of the tied largest companies."}), 400

            sizes = room.pending_acquire_sizes
            companies = set(sizes)
            targets = ordered_acquire_targets(companies, survivor, sizes)
            reward_details = [
                detail
                for target in targets
                for detail in pay_shareholder_rewards(room, target)
            ]
            room.pending_acquire_survivor = survivor
            room.pending_acquire_survivor_choices = []
            room.pending_acquire_targets = targets
            room.pending_acquire_reward_details = reward_details
            room.pending_acquire_ordering = acquire_order_has_tie(targets, sizes)
            room.pending_acquire_player_index = 0
            room.pending_acquire_target_index = 0

            if room.pending_acquire_ordering:
                tied_sizes = sorted({
                    sizes[target]
                    for target in targets
                    if sum(1 for other in targets if sizes[other] == sizes[target]) > 1
                })
                room.last_action = (
                    f"{survivor} chosen as the surviving company. "
                    f"Shareholder rewards: {describe_reward_details(reward_details)} "
                    f"Choose acquire order for tied size"
                    f"{'' if len(tied_sizes) == 1 else 's'} {', '.join(map(str, tied_sizes))}."
                )
            else:
                advance_acquire_step(room)
                pending = pending_acquire_state(room)
                if pending:
                    room.last_action = (
                        f"{survivor} chosen as the surviving company. "
                        f"Shareholder rewards: {describe_reward_details(reward_details)} "
                        f"Notice, It's {pending['active_player_name']}'s turn to process the stocks!"
                    )
                elif room.pending_acquire_survivor:
                    room.last_action = f"{survivor} chosen as the surviving company."

            state = build_public_room_state(room, player_id)
            broadcast_room_state(room)
    except RoomNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404

    return jsonify(state)


@app.post("/api/rooms/<room_id>/set_acquire_order")
def set_acquire_order(room_id: str):
    data = request.get_json(silent=True) or {}
    player_id = data.get("player_id")
    order = data.get("order") or []

    try:
        with room_lock:
            room = get_room_or_404(room_id)
            if not room.pending_acquire_ordering:
                return jsonify({"error": "No Acquire order decision is waiting."}), 400
            if room.pending_acquire_starter_id != player_id:
                return jsonify({"error": "Only the Acquire starter can choose the order."}), 403
            if sorted(order) != sorted(room.pending_acquire_targets):
                return jsonify({"error": "Acquire order must include each acquired company once."}), 400

            sizes = room.pending_acquire_sizes
            for previous, current in zip(order, order[1:]):
                if sizes[previous] > sizes[current]:
                    return jsonify({"error": "Smaller companies must be acquired first."}), 400

            room.pending_acquire_targets = order
            room.pending_acquire_ordering = False
            room.pending_acquire_player_index = 0
            room.pending_acquire_target_index = 0
            survivor = room.pending_acquire_survivor
            advance_acquire_step(room)
            pending = pending_acquire_state(room)
            if pending:
                room.last_action = (
                    f"Acquire order set: {', '.join(order)}. "
                    f"Notice, It's {pending['active_player_name']}'s turn to process the stocks!"
                )
            else:
                room.last_action = (
                    f"Acquire order set: {', '.join(order)}. "
                    f"{survivor} is the surviving company."
                )

            state = build_public_room_state(room, player_id)
            broadcast_room_state(room)
    except RoomNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404

    return jsonify(state)


@app.post("/api/rooms/<room_id>/trade_stocks")
def trade_stocks(room_id: str):
    data = request.get_json(silent=True) or {}
    player_id = data.get("player_id")
    target = (data.get("target") or "").lower()

    try:
        sell_count = int(data.get("sell") or 0)
        trade_count = int(data.get("trade") or 0)
        with room_lock:
            room = get_room_or_404(room_id)
            if room.game_over:
                return jsonify({"error": "The game is already over."}), 400
            pending = pending_acquire_state(room)
            if not pending:
                return jsonify({"error": "No Acquire trade is waiting."}), 400
            if pending.get("ordering"):
                return jsonify({"error": "Choose the Acquire order first."}), 400
            if pending["active_player_id"] != player_id:
                return jsonify({"error": "It is not your trade decision."}), 403
            if pending["active_target"] != target:
                return jsonify({"error": "Process the active acquired company first."}), 400
            if sell_count < 0 or trade_count < 0:
                return jsonify({"error": "Stock counts cannot be negative."}), 400
            if trade_count % 2:
                return jsonify({"error": "Trade must use an even number of stocks."}), 400

            player = next((player for player in room.players if player.id == player_id), None)
            if not player:
                return jsonify({"error": "Player not found in this room."}), 403

            survivor = pending["survivor"]
            owned = player.stocks.get(target, 0)
            if sell_count + trade_count > owned:
                return jsonify({"error": "You cannot use more stocks than you own."}), 400

            survivor_needed = trade_count // 2
            if room.bank_stocks.get(survivor, 0) < survivor_needed:
                return jsonify({"error": "The bank does not have enough surviving-company shares."}), 400

            price = share_prices(room).get(target) or 0
            sale_money = sell_count * price
            player.stocks[target] -= sell_count + trade_count
            player.money += sale_money
            room.bank_stocks[target] += sell_count + trade_count

            if survivor_needed:
                player.stocks[survivor] += survivor_needed
                room.bank_stocks[survivor] -= survivor_needed

            kept = player.stocks.get(target, 0)
            room.pending_acquire_player_index += 1
            player_name = player.name
            advance_acquire_step(room)
            room.last_action = (
                f"{player_name} processed {target}: sold {sell_count}, "
                f"traded {trade_count}, kept {kept}."
            )
            pending = pending_acquire_state(room)
            if pending:
                room.last_action += (
                    f" Notice, It's {pending['active_player_name']}'s turn to process the stocks!"
                )
            elif not room.pending_acquire_survivor:
                room.last_action += f" {survivor} survives."
                if room.end_pending:
                    room.last_action += " Game will end when this turn is finished."

            state = build_public_room_state(room, player_id)
            broadcast_room_state(room)
    except RoomNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except (TypeError, ValueError):
        return jsonify({"error": "Stock counts must be numbers."}), 400

    return jsonify(state)


@app.post("/api/rooms/<room_id>/finish_turn")
def finish_turn(room_id: str):
    data = request.get_json(silent=True) or {}
    player_id = data.get("player_id")
    purchases = data.get("purchases") or {}

    try:
        with room_lock:
            room = get_room_or_404(room_id)
            if not room.started:
                return jsonify({"error": "The game has not started yet."}), 400
            if room.game_over:
                return jsonify({"error": "The game is already over."}), 400
            if pending_acquire_state(room):
                return jsonify({"error": "Resolve the Acquire first."}), 400
            if room.pending_found_player_id:
                return jsonify({"error": "Resolve the company founding decision first."}), 400
            if room.pending_finish_player_id != player_id:
                return jsonify({"error": "It is not time for you to finish."}), 403

            player = room.players[room.current_turn]
            if player.id != player_id:
                return jsonify({"error": "It is not your turn."}), 403

            quantity_total = 0
            total_cost = 0
            clean_purchases = {}
            if purchases:
                player, quantity_total, total_cost, clean_purchases = process_stock_purchases(
                    room,
                    player_id,
                    purchases,
                    require_purchase=False,
                )

            if room.end_pending:
                liquidate_and_rank(room)
                if clean_purchases:
                    bought_text = ", ".join(
                        f"{quantity} {color}" for color, quantity in clean_purchases.items()
                    )
                    room.last_action = (
                        f"{player.name} bought {bought_text} stock"
                        f"{'' if quantity_total == 1 else 's'} for ${total_cost}. "
                        f"Game over. {room.winner} wins."
                    )
                state = build_public_room_state(room, player_id)
                broadcast_room_state(room)
                return jsonify(state)

            tiles_drawn = fill_player_tiles(room, player)

            room.pending_finish_player_id = None
            room.stocks_bought_this_turn = 0
            next_name = advance_turn(room)
            no_tile_buying = begin_buying_if_current_player_has_no_tiles(room)
            if tiles_drawn:
                room.last_action = (
                    f"{player.name} finished and drew {tiles_drawn} tile"
                    f"{'' if tiles_drawn == 1 else 's'}. {next_name}'s turn."
                )
                if no_tile_buying:
                    room.last_action += f" {next_name} has no tiles and may buy stocks."
            else:
                room.last_action = f"{player.name} finished. {next_name}'s turn."
                if no_tile_buying:
                    room.last_action += f" {next_name} has no tiles and may buy stocks."
            if clean_purchases:
                bought_text = ", ".join(
                    f"{quantity} {color}" for color, quantity in clean_purchases.items()
                )
                room.last_action = (
                    f"{player.name} bought {bought_text} stock"
                    f"{'' if quantity_total == 1 else 's'} for ${total_cost}. "
                    f"{room.last_action}"
                )
            state = build_public_room_state(room, player_id)
            broadcast_room_state(room)
    except RoomNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(state)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    socketio.run(app, host="0.0.0.0", port=port, debug=True, allow_unsafe_werkzeug=True)
