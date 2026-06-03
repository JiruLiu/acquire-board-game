const NAME_PATTERN = /^[A-Za-z0-9]{1,10}$/;

const state = {
  roomId: null,
  playerId: null,
  roomState: null,
  redirectedToGame: false,
};

const socket = io();

const elements = {
  playerName: document.getElementById("player-name"),
  roomCode: document.getElementById("room-code"),
  status: document.getElementById("status"),
  roomId: document.getElementById("room-id"),
  players: document.getElementById("players"),
  createRoom: document.getElementById("create-room"),
  joinRoom: document.getElementById("join-room"),
  startGame: document.getElementById("start-game"),
};

function setStatus(message, isError = false) {
  elements.status.textContent = message;
  elements.status.classList.toggle("error", isError);
}

function getPlayerName() {
  return elements.playerName.value.trim();
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

function renderPlayers() {
  const players = state.roomState?.players || [];
  elements.players.innerHTML = "";

  for (const player of players) {
    const item = document.createElement("li");
    const isViewer = player.id === state.playerId;
    const isCreator = players[0]?.id === player.id;
    item.textContent = player.name;
    if (isViewer) item.textContent += " | You";
    if (isCreator) item.textContent += " | Creator";
    elements.players.appendChild(item);
  }
}

function renderRoom() {
  elements.roomId.textContent = state.roomId || "Not connected";
  renderPlayers();

  const players = state.roomState?.players || [];
  const isCreator = players[0]?.id === state.playerId;
  elements.startGame.disabled = !state.roomId || !isCreator || !!state.roomState?.started;
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

async function createRoom() {
  const playerName = getPlayerName();

  try {
    validateNameOrThrow(playerName);
    const data = await api("/api/rooms", {
      method: "POST",
      body: JSON.stringify({ player_name: playerName }),
    });
    state.roomId = data.room_id;
    state.playerId = data.player_id;
    state.roomState = data.state;
    elements.roomCode.value = state.roomId;
    setStatus(`Room ${state.roomId} created. Share this code with your friend.`);
    subscribeToRoomState();
    renderRoom();
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function joinRoom() {
  const playerName = getPlayerName();
  const roomCode = elements.roomCode.value.trim().toUpperCase();

  try {
    validateNameOrThrow(playerName);
    if (!roomCode) {
      throw new Error("Enter a room code.");
    }
    const data = await api(`/api/rooms/${roomCode}/join`, {
      method: "POST",
      body: JSON.stringify({ player_name: playerName }),
    });
    state.roomId = data.room_id;
    state.playerId = data.player_id;
    state.roomState = data.state;
    setStatus(`Joined room ${state.roomId}.`);
    subscribeToRoomState();
    renderRoom();
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function startGame() {
  if (!state.roomId || !state.playerId) return;

  try {
    await api(`/api/rooms/${state.roomId}/start`, {
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
  renderRoom();
  redirectToGameIfStarted();
});

elements.createRoom.addEventListener("click", createRoom);
elements.joinRoom.addEventListener("click", joinRoom);
elements.startGame.addEventListener("click", startGame);
