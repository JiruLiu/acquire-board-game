const NAME_PATTERN = /^[A-Za-z0-9]{1,10}$/;

const state = {
  roomId: null,
  playerId: null,
  roomState: null,
  redirectedToGame: false,
  roomEntryPending: false,
  roomEntryLocked: false,
};

const socket = io();

const elements = {
  playerName: document.getElementById("player-name"),
  inviteCode: document.getElementById("invite-code"),
  roomPassword: document.getElementById("room-password"),
  gameMode: document.getElementById("game-mode"),
  gameSeed: document.getElementById("game-seed"),
  status: document.getElementById("status"),
  createRoom: document.getElementById("create-room"),
  availableRooms: document.getElementById("available-rooms"),
  recentReplays: document.getElementById("recent-replays"),
  refreshRooms: document.getElementById("refresh-rooms"),
};

function setStatus(message, isError = false) {
  elements.status.textContent = message;
  elements.status.classList.toggle("error", isError);
}

function getPlayerName() {
  return elements.playerName.value.trim();
}

function getInviteCode() {
  return elements.inviteCode.value.trim();
}

function setRoomEntryControlsDisabled(disabled) {
  elements.createRoom.disabled = disabled;
  elements.gameMode.disabled = disabled;
  elements.gameSeed.disabled = disabled;
  for (const control of elements.availableRooms.querySelectorAll("button, input")) {
    control.disabled = disabled;
  }
}

function validateNameOrThrow(name) {
  if (!NAME_PATTERN.test(name)) {
    throw new Error("Name must be 1-10 letters or numbers only.");
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed.");
  }
  return data;
}

async function loadRooms() {
  try {
    const data = await api("/api/rooms");
    elements.availableRooms.innerHTML = "";
    if (!data.rooms.length) {
      elements.availableRooms.innerHTML = '<p class="panel-note">No rooms yet. Create the first one.</p>';
      return;
    }
    for (const room of data.rooms) {
      const card = document.createElement("article");
      card.className = "available-room-card";
      const isCreator = room.room_id === state.roomId && room.creator_id === state.playerId;
      const roomEntryDisabled = state.roomEntryPending || state.roomEntryLocked;
      card.innerHTML = `
        <div class="available-room-summary">
          <strong>${room.name}</strong>
          <span class="room-player-names">${room.players.join(", ") || "No players"}</span>
          <span>${room.game_mode_label} · ${room.board_size} · ${room.player_count}/${room.max_players} · Seed ${room.seed}</span>
          <span>${room.started ? "Game in progress" : "Waiting to start"}</span>
        </div>
        <input class="room-card-password" type="password" placeholder="Room password" maxlength="24" aria-label="Password for ${room.name}" ${roomEntryDisabled ? "disabled" : ""}>
        <div class="available-room-actions">
          <button type="button" data-action="join" ${roomEntryDisabled || isCreator || room.started || room.player_count >= room.max_players ? "disabled" : ""}>Join</button>
          <button type="button" data-action="spectate" ${roomEntryDisabled || isCreator ? "disabled" : ""}>Spectate</button>
          <button type="button" data-action="start" ${isCreator && !room.started ? "" : "disabled"}>Start Game</button>
        </div>`;
      const passwordInput = card.querySelector(".room-card-password");
      if (room.room_id === state.roomId) passwordInput.value = elements.roomPassword.value;
      card.querySelector('[data-action="join"]').addEventListener("click", () => enterRoom(room.room_id, false, passwordInput.value));
      card.querySelector('[data-action="spectate"]').addEventListener("click", () => enterRoom(room.room_id, true, passwordInput.value));
      card.querySelector('[data-action="start"]').addEventListener("click", () => startGame(room.room_id));
      elements.availableRooms.appendChild(card);
    }
    elements.createRoom.disabled = state.roomEntryPending || state.roomEntryLocked;
  } catch (error) {
    setStatus(error.message, true);
  }
}

function formatReplayTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

async function loadReplays() {
  try {
    const data = await api("/api/replays");
    elements.recentReplays.innerHTML = "";
    if (!data.replays.length) {
      elements.recentReplays.innerHTML = '<p class="panel-note">No recorded games yet.</p>';
      return;
    }

    for (const replay of data.replays) {
      const card = document.createElement("article");
      card.className = "recent-replay-card";

      const summary = document.createElement("div");
      summary.className = "recent-replay-summary";
      const title = document.createElement("strong");
      title.textContent = replay.room_name;
      const details = document.createElement("span");
      details.textContent = `${replay.game_mode_label} · ${replay.action_count} actions · Seed ${replay.seed}`;
      const timing = document.createElement("span");
      timing.textContent = `${replay.status === "completed" ? "Completed" : "In progress"} · ${formatReplayTime(replay.updated_at)}`;
      summary.append(title, details, timing);

      const link = document.createElement("a");
      link.className = "replay-open-button";
      link.href = `/replay/${encodeURIComponent(replay.recording_id)}`;
      link.textContent = "Replay";
      link.setAttribute("aria-label", `Replay ${replay.room_name}`);

      card.append(summary, link);
      elements.recentReplays.appendChild(card);
    }
  } catch (error) {
    elements.recentReplays.innerHTML = '<p class="panel-note">Replays are temporarily unavailable.</p>';
  }
}

function redirectToGameIfStarted() {
  if (!state.roomState?.started || !state.roomId || !state.playerId || state.redirectedToGame) {
    return;
  }
  state.redirectedToGame = true;
  window.location.href = `/game/${state.roomId}?player_id=${encodeURIComponent(state.playerId)}`;
}

function subscribeToRoomState() {
  if (!state.roomId || !state.playerId) return;
  socket.emit("join_room_state", {
    room_id: state.roomId,
    player_id: state.playerId,
  });
}

socket.on("connect", subscribeToRoomState);

async function createRoom() {
  const playerName = getPlayerName();
  const invitationCode = getInviteCode();
  const roomPassword = elements.roomPassword.value.trim();
  const gameMode = elements.gameMode.value;
  const seed = elements.gameSeed.value.trim();

  try {
    validateNameOrThrow(playerName);
    if (!invitationCode) {
      throw new Error("Enter the invitation code to create a room.");
    }
    if (!roomPassword) throw new Error("Enter a room password to create a room.");
    const data = await api("/api/rooms", {
      method: "POST",
      body: JSON.stringify({
        player_name: playerName,
        invitation_code: invitationCode,
        room_password: roomPassword,
        game_mode: gameMode,
        seed,
      }),
    });
    state.roomId = data.room_id;
    state.playerId = data.player_id;
    state.roomState = data.state;
    state.roomEntryLocked = true;
    elements.gameMode.disabled = true;
    elements.gameSeed.disabled = true;
    elements.roomPassword.value = roomPassword;
    setStatus(`${state.roomState.room_name} created.`);
    subscribeToRoomState();
    loadRooms();
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function enterRoom(roomCode, spectate, password) {
  if (state.roomEntryPending || state.roomEntryLocked) return;
  const playerName = getPlayerName();
  const roomPassword = password.trim();

  state.roomEntryPending = true;
  setRoomEntryControlsDisabled(true);
  try {
    validateNameOrThrow(playerName);
    if (!roomPassword) throw new Error("Enter the room password first.");
    const data = await api(`/api/rooms/${roomCode}/${spectate ? "spectate" : "join"}`, {
      method: "POST",
      body: JSON.stringify({ player_name: playerName, room_password: roomPassword }),
    });
    state.roomId = data.room_id;
    state.playerId = data.player_id;
    state.roomState = data.state;
    state.roomEntryLocked = true;
    state.roomEntryPending = false;
    elements.roomPassword.value = roomPassword;
    setStatus(
      spectate
        ? `Waiting to spectate ${state.roomState.room_name}. The creator has not started the game.`
        : `Joined ${state.roomState.room_name}. Waiting for the creator to start.`,
    );
    subscribeToRoomState();
    loadRooms();
  } catch (error) {
    state.roomEntryPending = false;
    setRoomEntryControlsDisabled(false);
    setStatus(error.message, true);
    loadRooms();
  }
}

async function startGame(roomId) {
  if (!roomId || roomId !== state.roomId || !state.playerId) return;

  try {
    await api(`/api/rooms/${roomId}/start`, {
      method: "POST",
      body: JSON.stringify({ player_id: state.playerId }),
    });
    state.redirectedToGame = true;
    window.location.href = `/game/${state.roomId}?player_id=${encodeURIComponent(state.playerId)}`;
  } catch (error) {
    setStatus(error.message, true);
  }
}

socket.on("room_state", (data) => {
  state.roomState = data;
  state.roomId = data.room_id;
  loadRooms();
  redirectToGameIfStarted();
});

elements.createRoom.addEventListener("click", createRoom);
elements.refreshRooms.addEventListener("click", () => {
  loadRooms();
  loadReplays();
});
loadRooms();
loadReplays();
