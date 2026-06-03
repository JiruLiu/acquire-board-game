const ROWS = "ABCDEFGHI".split("");
const COLUMNS = Array.from({ length: 12 }, (_, index) => String(index + 1));
const STOCK_COLORS = ["red", "yellow", "green", "pink", "purple", "orange", "blue"];
const MAX_PLAYERS = 5;

const state = {
  roomId: window.GAME_BOOTSTRAP.roomId,
  playerId: window.GAME_BOOTSTRAP.playerId,
  roomState: null,
  selectedTile: null,
  selectedCompany: null,
  buySelection: {},
  tradeSelection: { sell: 0, trade: 0 },
  acquireOrder: [],
  statusHistory: [],
  copyLinkResetTimer: null,
};

const socket = io();

const elements = {
  status: document.getElementById("status"),
  tileRack: document.getElementById("tile-rack"),
  board: document.getElementById("board"),
  placeButton: document.getElementById("place-button"),
  finishButton: document.getElementById("finish-button"),
  holdingsBody: document.getElementById("holdings-body"),
  copyLinkButton: document.getElementById("copy-link-button"),
  buyingPanel: document.getElementById("buying-panel"),
  buyingOptions: document.getElementById("buying-options"),
  buyingCount: document.getElementById("buying-count"),
  buyingTotal: document.getElementById("buying-total"),
  buyingNote: document.getElementById("buying-note"),
  buyButton: document.getElementById("buy-button"),
  tradePanel: document.getElementById("trade-panel"),
  tradePlayer: document.getElementById("trade-player"),
  tradeNote: document.getElementById("trade-note"),
  tradeCompanyOptions: document.getElementById("trade-company-options"),
  tradeSurvivor: document.getElementById("trade-survivor"),
  tradeOwned: document.getElementById("trade-owned"),
  sellMinus: document.getElementById("sell-minus"),
  sellPlus: document.getElementById("sell-plus"),
  sellCount: document.getElementById("sell-count"),
  tradeMinus: document.getElementById("trade-minus"),
  tradePlus: document.getElementById("trade-plus"),
  tradeCount: document.getElementById("trade-count"),
  keepCount: document.getElementById("keep-count"),
  tradeResult: document.getElementById("trade-result"),
  processTradeButton: document.getElementById("process-trade-button"),
  foundPanel: document.getElementById("found-panel"),
  companyOptions: document.getElementById("company-options"),
  foundButton: document.getElementById("found-button"),
  foundNote: document.getElementById("found-note"),
  acquireOrderPanel: document.getElementById("acquire-order-panel"),
  acquireOrderButton: document.getElementById("acquire-order-button"),
  acquireOrderNote: document.getElementById("acquire-order-note"),
  acquireOrderList: document.getElementById("acquire-order-list"),
  endingPanel: document.getElementById("ending-panel"),
  endingWinner: document.getElementById("ending-winner"),
  endingRankings: document.getElementById("ending-rankings"),
};

let audioContext = null;

function getAudioContext() {
  if (audioContext) {
    return audioContext;
  }
  const Context = window.AudioContext || window.webkitAudioContext;
  if (!Context) {
    return null;
  }
  audioContext = new Context();
  return audioContext;
}

function unlockAudio() {
  const context = getAudioContext();
  if (!context || context.state !== "suspended") {
    return;
  }
  context.resume().catch(() => {});
}

function scheduleTone(context, {
  type = "sine",
  frequency,
  endFrequency = frequency,
  start,
  duration,
  gain = 0.08,
  attack = 0.01,
  release = 0.08,
}) {
  const oscillator = context.createOscillator();
  const amplifier = context.createGain();
  oscillator.type = type;
  oscillator.frequency.setValueAtTime(frequency, start);
  oscillator.frequency.exponentialRampToValueAtTime(
    Math.max(1, endFrequency),
    start + duration
  );
  amplifier.gain.setValueAtTime(0.0001, start);
  amplifier.gain.exponentialRampToValueAtTime(gain, start + attack);
  amplifier.gain.exponentialRampToValueAtTime(0.0001, start + duration + release);
  oscillator.connect(amplifier);
  amplifier.connect(context.destination);
  oscillator.start(start);
  oscillator.stop(start + duration + release + 0.02);
}

function playSound(recipe) {
  const context = getAudioContext();
  if (!context || context.state !== "running") {
    return;
  }
  const start = context.currentTime + 0.01;
  recipe(context, start);
}

function playMoneyDeductSound() {
  playSound((context, start) => {
    scheduleTone(context, {
      type: "square",
      frequency: 820,
      endFrequency: 660,
      start,
      duration: 0.08,
      gain: 0.035,
      attack: 0.004,
      release: 0.035,
    });
    scheduleTone(context, {
      type: "square",
      frequency: 640,
      endFrequency: 430,
      start: start + 0.06,
      duration: 0.12,
      gain: 0.04,
      attack: 0.004,
      release: 0.05,
    });
  });
}

function playMoneyIncomingSound() {
  playSound((context, start) => {
    scheduleTone(context, {
      type: "triangle",
      frequency: 420,
      endFrequency: 620,
      start,
      duration: 0.09,
      gain: 0.04,
      attack: 0.005,
      release: 0.04,
    });
    scheduleTone(context, {
      type: "triangle",
      frequency: 620,
      endFrequency: 880,
      start: start + 0.08,
      duration: 0.12,
      gain: 0.045,
      attack: 0.005,
      release: 0.06,
    });
    scheduleTone(context, {
      type: "sine",
      frequency: 930,
      endFrequency: 1220,
      start: start + 0.16,
      duration: 0.16,
      gain: 0.03,
      attack: 0.006,
      release: 0.09,
    });
  });
}

function playCelebrateSound() {
  playSound((context, start) => {
    const notes = [523.25, 659.25, 783.99, 1046.5];
    for (const [index, note] of notes.entries()) {
      scheduleTone(context, {
        type: "triangle",
        frequency: note,
        endFrequency: note * 1.02,
        start: start + (index * 0.06),
        duration: 0.16,
        gain: 0.04,
        attack: 0.005,
        release: 0.08,
      });
    }
  });
}

function playAcquireImpactSound() {
  playSound((context, start) => {
    scheduleTone(context, {
      type: "sawtooth",
      frequency: 180,
      endFrequency: 72,
      start,
      duration: 0.34,
      gain: 0.05,
      attack: 0.01,
      release: 0.12,
    });
    scheduleTone(context, {
      type: "triangle",
      frequency: 260,
      endFrequency: 510,
      start: start + 0.06,
      duration: 0.24,
      gain: 0.028,
      attack: 0.01,
      release: 0.1,
    });
    scheduleTone(context, {
      type: "sine",
      frequency: 510,
      endFrequency: 760,
      start: start + 0.13,
      duration: 0.22,
      gain: 0.026,
      attack: 0.01,
      release: 0.1,
    });
  });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[character]));
}

function setStatus(message, isError = false) {
  if (message && state.statusHistory[state.statusHistory.length - 1] !== message) {
    state.statusHistory.push(message);
  }

  elements.status.innerHTML = state.statusHistory
    .map((entry) => `<span class="status-line">${escapeHtml(entry)}</span>`)
    .join("");
  elements.status.scrollTop = elements.status.scrollHeight;
  elements.status.classList.toggle("error", isError);
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

function canPlaceTile(tile) {
  if (!tile) return false;
  if (!state.roomState?.started) return false;
  if (state.roomState.game_over) return false;
  if (state.roomState.pending_found_player_id) return false;
  if (state.roomState.pending_acquire) return false;
  if (state.roomState.pending_finish_player_id) return false;
  if (state.roomState.current_turn_player_id !== state.playerId) return false;
  const viewer = state.roomState.players.find((player) => player.id === state.playerId);
  return viewer?.tiles.includes(tile);
}

function canFinishTurn() {
  return state.roomState?.pending_finish_player_id === state.playerId
    && !state.roomState?.game_over
    && !state.roomState?.pending_acquire;
}

function renderRack() {
  const viewer = state.roomState?.players?.find((player) => player.id === state.playerId);
  const tiles = viewer?.tiles?.length ? viewer.tiles : Array(6).fill(null);
  elements.tileRack.innerHTML = "";
  elements.finishButton.disabled = !canFinishTurn();

  if (state.selectedTile && !tiles.includes(state.selectedTile)) {
    state.selectedTile = null;
  }

  for (const tile of tiles) {
    const chip = document.createElement("button");
    chip.className = "board-cell rack-cell";
    if (!tile) {
      chip.classList.add("empty-rack-cell");
      chip.disabled = true;
      chip.innerHTML = "";
      elements.tileRack.appendChild(chip);
      continue;
    }

    const tileLabel = `${tile.slice(1)}${tile[0]}`;
    if (tile === state.selectedTile) {
      chip.classList.add("selected");
    }
    chip.innerHTML = `<span class="coord">${tileLabel}</span>`;
    chip.disabled = !canPlaceTile(tile);
    chip.addEventListener("click", () => {
      if (!canPlaceTile(tile)) return;
      state.selectedTile = tile;
      renderRack();
    });
    elements.tileRack.appendChild(chip);
  }

  elements.placeButton.disabled = !state.selectedTile || !canPlaceTile(state.selectedTile);
  elements.finishButton.disabled = !canFinishTurn();
}

function renderBoard() {
  elements.board.innerHTML = "";
  const boardData = state.roomState?.board || {};
  const lastPlacedTile = state.roomState?.last_placed_tile;

  for (const row of ROWS) {
    for (const column of COLUMNS) {
      const tile = `${row}${column}`;
      const tileLabel = `${column}${row}`;
      const button = document.createElement("button");
      button.className = "board-cell";
      button.dataset.tile = tile;

      const boardEntry = boardData[tile];
      if (boardEntry) {
        const placedBy = typeof boardEntry === "string" ? boardEntry : boardEntry.placed_by;
        const company = typeof boardEntry === "string" ? null : boardEntry.company;
        button.classList.add("placed");
        if (company) {
          button.classList.add(`company-${company}`);
        }
        const ownerMarkup = tile === lastPlacedTile
          ? `<span class="owner">${placedBy}</span>`
          : "";
        button.innerHTML = `<span class="coord">${tileLabel}</span>${ownerMarkup}`;
      } else {
        button.innerHTML = `<span class="coord">${tileLabel}</span>`;
        button.disabled = !canPlaceTile(tile);
      }

      button.addEventListener("click", () => placeTile(tile));
      elements.board.appendChild(button);
    }
  }
}

function formatMoney(value) {
  if (value === null || value === undefined || value === "") return "";
  return `$${Number(value).toLocaleString()}`;
}

function selectedBuyCount() {
  return Object.values(state.buySelection).reduce((total, quantity) => total + quantity, 0);
}

function currentViewer() {
  return state.roomState?.players?.find((player) => player.id === state.playerId);
}

function roomPlayerById(roomState, playerId) {
  return roomState?.players?.find((player) => player.id === playerId);
}

function anyPlayerMoneyIncreased(previousState, nextState) {
  for (const nextPlayer of (nextState?.players || [])) {
    const previousPlayer = roomPlayerById(previousState, nextPlayer.id);
    if ((nextPlayer.money || 0) > (previousPlayer?.money || 0)) {
      return true;
    }
  }
  return false;
}

function anyPlayerStockChanged(previousState, nextState) {
  for (const nextPlayer of (nextState?.players || [])) {
    const previousPlayer = roomPlayerById(previousState, nextPlayer.id);
    for (const color of STOCK_COLORS) {
      if ((nextPlayer?.stocks?.[color] || 0) > (previousPlayer?.stocks?.[color] || 0)) {
        return true;
      }
    }
  }
  return false;
}

function playRoomEventSounds(previousState, nextState) {
  if (!previousState || !nextState || previousState.last_action === nextState.last_action) {
    return;
  }

  if (!previousState.pending_acquire && nextState.pending_acquire) {
    playAcquireImpactSound();
  }

  if (nextState.last_action?.includes(" founded the ")) {
    playCelebrateSound();
  }

  if (nextState.last_action?.includes(" bought ")) {
    playMoneyDeductSound();
  }

  if (
    previousState.pending_acquire
    && (anyPlayerMoneyIncreased(previousState, nextState) || anyPlayerStockChanged(previousState, nextState))
  ) {
    playMoneyIncomingSound();
  }
}

function applyRoomState(nextState, fallbackMessage = "Connected.") {
  const previousState = state.roomState;
  state.roomState = nextState;
  playRoomEventSounds(previousState, nextState);
  setStatus(nextState.last_action || fallbackMessage);
  renderGame();
}

function setPanelFocus(panel, isActive, variant) {
  panel.classList.toggle("panel-focus", isActive);
  panel.classList.toggle(`panel-focus--${variant}`, isActive);
}

function displayTile(tile) {
  return `${tile.slice(1)}${tile[0]}`;
}

function stockCell(stocks, color) {
  const count = stocks?.[color] || 0;
  return count ? String(count) : "";
}

function renderHoldings() {
  const players = state.roomState?.players || [];
  const bankStocks = state.roomState?.bank?.stocks || {};
  elements.holdingsBody.innerHTML = "";

  for (let index = 0; index < MAX_PLAYERS; index += 1) {
    const player = players[index];
    const row = document.createElement("tr");
    const isCurrent = player?.id === state.roomState?.current_turn_player_id;
    if (isCurrent) {
      row.classList.add("current-player-row");
    }
    const stockCells = STOCK_COLORS
      .map((color) => `<td>${stockCell(player?.stocks, color)}</td>`)
      .join("");

    row.innerHTML = `
      <td class="player-name-cell">${player?.name || ""}</td>
      <td>${player ? formatMoney(player.money) : ""}</td>
      ${stockCells}
    `;
    elements.holdingsBody.appendChild(row);
  }

  const bankRow = document.createElement("tr");
  bankRow.className = "bank-row";
  const bankStockCells = STOCK_COLORS
    .map((color) => `<td>${stockCell(bankStocks, color)}</td>`)
    .join("");
  bankRow.innerHTML = `
    <td>Bank</td>
    <td></td>
    ${bankStockCells}
  `;
  elements.holdingsBody.appendChild(bankRow);
}

function renderBuying() {
  const companiesFound = state.roomState?.companies_found || {};
  const bankStocks = state.roomState?.bank?.stocks || {};
  const sharePrices = state.roomState?.share_prices || {};
  const boughtThisTurn = state.roomState?.stocks_bought_this_turn || 0;
  const viewer = currentViewer();
  const isBuyingTurn = state.roomState?.pending_finish_player_id === state.playerId
    && !state.roomState?.pending_found_player_id
    && !state.roomState?.pending_acquire;

  if (!isBuyingTurn) {
    state.buySelection = {};
  }

  for (const color of STOCK_COLORS) {
    const available = bankStocks[color] || 0;
    const selected = state.buySelection[color] || 0;
    if (!companiesFound[color] || selected > available) {
      state.buySelection[color] = 0;
    }
  }

  const selectedCount = selectedBuyCount();
  const selectedTotal = STOCK_COLORS.reduce((total, color) => (
    total + ((state.buySelection[color] || 0) * (sharePrices[color] || 0))
  ), 0);
  const remainingTurnBuys = Math.max(0, 3 - boughtThisTurn - selectedCount);

  elements.buyingOptions.innerHTML = "";
  for (const color of STOCK_COLORS) {
    const price = sharePrices[color];
    const available = bankStocks[color] || 0;
    const selected = state.buySelection[color] || 0;
    const isAvailable = isBuyingTurn && companiesFound[color] && available > 0 && price;
    const canAdd = isAvailable
      && remainingTurnBuys > 0
      && selected < available
      && selectedTotal + price <= (viewer?.money || 0);

    const row = document.createElement("div");
    row.className = `buying-row${isAvailable ? "" : " disabled"}`;
    row.innerHTML = `
      <span class="buying-company"><span class="dot ${color}"></span></span>
      <span class="buying-price">${price ? formatMoney(price) : "--"}</span>
      <span class="buying-bank">Bank: ${available || ""}</span>
      <button class="buying-step" type="button" ${!isAvailable || selected <= 0 ? "disabled" : ""}>-</button>
      <span class="buying-quantity">${selected || ""}</span>
      <button class="buying-step" type="button" ${canAdd ? "" : "disabled"}>+</button>
    `;

    const [minusButton, plusButton] = row.querySelectorAll("button");
    minusButton.addEventListener("click", () => {
      state.buySelection[color] = Math.max(0, selected - 1);
      renderBuying();
    });
    plusButton.addEventListener("click", () => {
      state.buySelection[color] = selected + 1;
      renderBuying();
    });

    elements.buyingOptions.appendChild(row);
  }

  elements.buyingCount.textContent = `${boughtThisTurn + selectedCount} / 3`;
  elements.buyingTotal.textContent = `Total: ${formatMoney(selectedTotal)}`;
  elements.buyButton.disabled = !isBuyingTurn
    || selectedCount <= 0
    || boughtThisTurn + selectedCount > 3
    || selectedTotal > (viewer?.money || 0);
}

function resetTradeSelection() {
  state.tradeSelection = { sell: 0, trade: 0 };
}

function clampTradeSelection(owned) {
  state.tradeSelection.sell = Math.max(0, Math.min(state.tradeSelection.sell, owned));
  state.tradeSelection.trade = Math.max(0, state.tradeSelection.trade - (state.tradeSelection.trade % 2));
  if (state.tradeSelection.sell + state.tradeSelection.trade > owned) {
    state.tradeSelection.trade = owned - state.tradeSelection.sell;
    state.tradeSelection.trade -= state.tradeSelection.trade % 2;
  }
}

function renderTrade() {
  const pending = state.roomState?.pending_acquire;
  const viewer = currentViewer();
  const bankStocks = state.roomState?.bank?.stocks || {};
  const isActivePlayer = pending?.active_player_id === state.playerId && !pending?.ordering;
  const activeTarget = pending?.active_target;
  const survivor = pending?.survivor;
  const owned = isActivePlayer ? (viewer?.stocks?.[activeTarget] || 0) : 0;

  if (!pending || !isActivePlayer) {
    resetTradeSelection();
  } else {
    clampTradeSelection(owned);
  }

  const sell = state.tradeSelection.sell;
  const trade = state.tradeSelection.trade;
  const keep = Math.max(0, owned - sell - trade);
  const price = state.roomState?.share_prices?.[activeTarget] || 0;
  const saleMoney = sell * price;
  const survivorStock = trade / 2;
  const canAddSell = isActivePlayer && sell + trade < owned;
  const canAddTrade = isActivePlayer
    && sell + trade + 2 <= owned
    && bankStocks[survivor] > survivorStock;

  elements.tradePlayer.textContent = pending
    ? `${pending.active_player_name}'s decision`
    : "No Acquire";
  elements.tradeSurvivor.textContent = survivor
    ? `Survivor: ${survivor}`
    : "Survivor: --";
  elements.tradeOwned.textContent = `Owned: ${owned}`;
  elements.tradeCompanyOptions.innerHTML = "";

  for (const color of STOCK_COLORS) {
    const dotButton = document.createElement("button");
    dotButton.className = `trade-dot-button${color === activeTarget ? " active" : ""}`;
    dotButton.type = "button";
    dotButton.disabled = color !== activeTarget || !isActivePlayer;
    dotButton.innerHTML = `<span class="dot ${color}"></span>`;
    elements.tradeCompanyOptions.appendChild(dotButton);
  }

  elements.sellCount.textContent = String(sell);
  elements.tradeCount.textContent = String(trade);
  elements.keepCount.textContent = String(keep);
  elements.tradeResult.textContent = `${formatMoney(saleMoney)}, +${survivorStock} ${survivor || "stock"}`;

  elements.sellMinus.disabled = !isActivePlayer || sell <= 0;
  elements.sellPlus.disabled = !canAddSell;
  elements.tradeMinus.disabled = !isActivePlayer || trade <= 0;
  elements.tradePlus.disabled = !canAddTrade;
  elements.processTradeButton.disabled = !isActivePlayer;
}

function renderAcquireOrder() {
  const pending = state.roomState?.pending_acquire;
  const isOrdering = !!pending?.ordering;
  const isStarter = pending?.starter_id === state.playerId;
  const sizes = pending?.sizes || {};

  if (!isOrdering) {
    state.acquireOrder = [];
  } else if (
    state.acquireOrder.length !== pending.targets.length
    || state.acquireOrder.some((color) => !pending.targets.includes(color))
  ) {
    state.acquireOrder = [...pending.targets];
  }

  elements.acquireOrderList.innerHTML = "";
  if (!pending) {
    elements.acquireOrderNote.textContent = "No Acquire order needed.";
  } else if (isOrdering && isStarter) {
    elements.acquireOrderNote.textContent = `Choose the tied Acquire order for ${pending.survivor}.`;
  } else if (isOrdering) {
    elements.acquireOrderNote.textContent = (
      `Waiting for ${pending.active_player_name} to choose the tied order. `
      + `Survivor: ${pending.survivor || "--"}`
    );
  } else {
    elements.acquireOrderNote.textContent = `Survivor: ${pending.survivor || "--"}`;
  }

  const order = state.acquireOrder.length ? state.acquireOrder : (pending?.targets || []);
  for (const [index, color] of order.entries()) {
    const size = sizes[color] || 0;
    const previousColor = order[index - 1];
    const nextColor = order[index + 1];
    const canMoveUp = isOrdering && isStarter && previousColor && sizes[previousColor] === size;
    const canMoveDown = isOrdering && isStarter && nextColor && sizes[nextColor] === size;
    const row = document.createElement("div");
    row.className = `acquire-order-row${isOrdering ? "" : " disabled"}`;
    row.innerHTML = `
      <span class="dot ${color}"></span>
      <span>${color}</span>
      <span>Size ${size}</span>
      <button type="button" ${canMoveUp ? "" : "disabled"}>Up</button>
      <button type="button" ${canMoveDown ? "" : "disabled"}>Down</button>
    `;

    const [upButton, downButton] = row.querySelectorAll("button");
    upButton.addEventListener("click", () => {
      [state.acquireOrder[index - 1], state.acquireOrder[index]] = [
        state.acquireOrder[index],
        state.acquireOrder[index - 1],
      ];
      renderAcquireOrder();
    });
    downButton.addEventListener("click", () => {
      [state.acquireOrder[index], state.acquireOrder[index + 1]] = [
        state.acquireOrder[index + 1],
        state.acquireOrder[index],
      ];
      renderAcquireOrder();
    });

    elements.acquireOrderList.appendChild(row);
  }

  elements.acquireOrderButton.disabled = !isOrdering || !isStarter;
}

function renderActionPanels() {
  const pending = state.roomState?.pending_acquire;
  const isFoundActive = state.roomState?.pending_found_player_id === state.playerId
    && !state.roomState?.game_over;
  const isAcquireOrderActive = !!pending?.ordering
    && pending?.starter_id === state.playerId
    && !state.roomState?.game_over;
  const isBuyingActive = state.roomState?.pending_finish_player_id === state.playerId
    && !state.roomState?.pending_found_player_id
    && !state.roomState?.pending_acquire
    && !state.roomState?.game_over;
  const isTradeActive = pending?.active_player_id === state.playerId
    && !pending?.ordering
    && !state.roomState?.game_over;

  setPanelFocus(elements.foundPanel, isFoundActive, "found");
  setPanelFocus(elements.acquireOrderPanel, isAcquireOrderActive, "acquire");
  setPanelFocus(elements.buyingPanel, isBuyingActive, "buying");
  setPanelFocus(elements.tradePanel, isTradeActive, "trade");

  elements.foundNote.textContent = isFoundActive
    ? "Choose a company, then click Found."
    : "No founding decision waiting.";
  elements.buyingNote.textContent = isBuyingActive
    ? "You can buy up to 3 stocks before finishing this turn."
    : "Buy opens after your tile resolves.";
  elements.tradeNote.textContent = isTradeActive
    ? `Sell, trade, or keep ${pending.active_target} shares.`
    : "Trade decisions appear during Acquire.";
}

function renderEnding() {
  if (!state.roomState?.game_over) {
    elements.endingPanel.hidden = true;
    return;
  }

  elements.endingPanel.hidden = false;
  elements.endingWinner.textContent = state.roomState.winner
    ? `${state.roomState.winner} wins`
    : "Final ranking";
  elements.endingRankings.innerHTML = "";

  for (const [index, player] of (state.roomState.final_rankings || []).entries()) {
    const cashBeforeSales = player.cash_before_sales ?? player.money;
    const stockSaleTotal = player.stock_sale_total ?? 0;
    const finalTotal = player.final_total ?? player.money;
    const stockSales = player.stock_sales || [];
    const row = document.createElement("div");
    row.className = "ending-row";
    const salesMarkup = stockSales.length
      ? stockSales.map((sale) => `
        <div class="ending-detail-row">
          <span class="ending-detail-label">
            <span class="dot ${sale.color}"></span>
            Bank buys ${sale.shares} @ ${formatMoney(sale.price)}
          </span>
          <span>${formatMoney(sale.subtotal)}</span>
        </div>
      `).join("")
      : `
        <div class="ending-empty">No shares left to sell to the bank.</div>
      `;
    row.innerHTML = `
      <div class="ending-row-main">
        <span>#${index + 1}</span>
        <strong>${escapeHtml(player.name)}</strong>
        <span>${formatMoney(finalTotal)}</span>
      </div>
      <div class="ending-breakdown">
        <div class="ending-detail-row">
          <span>Cash on hand</span>
          <span>${formatMoney(cashBeforeSales)}</span>
        </div>
        ${salesMarkup}
        <div class="ending-detail-row ending-detail-total">
          <span>Stock sale total</span>
          <span>${formatMoney(stockSaleTotal)}</span>
        </div>
        <div class="ending-detail-row ending-detail-final">
          <span>Final total</span>
          <span>${formatMoney(finalTotal)}</span>
        </div>
      </div>
    `;
    elements.endingRankings.appendChild(row);
  }
}

function renderCompanies() {
  const companiesFound = state.roomState?.companies_found || {};
  const isActive = state.roomState?.pending_found_player_id === state.playerId;
  elements.companyOptions.innerHTML = "";

  if (!isActive || (state.selectedCompany && companiesFound[state.selectedCompany])) {
    state.selectedCompany = null;
  }

  for (const color of STOCK_COLORS) {
    const isFound = !!companiesFound[color];
    const optionId = `company-${color}`;
    const label = document.createElement("label");
    label.className = "company-option";
    label.htmlFor = optionId;
    label.innerHTML = `
      <input
        type="checkbox"
        id="${optionId}"
        value="${color}"
        ${isFound ? "checked" : ""}
        ${isFound || !isActive ? "disabled" : ""}
        ${state.selectedCompany === color ? "checked" : ""}
      >
      <span class="dot ${color}"></span>
    `;

    const checkbox = label.querySelector("input");
    checkbox.addEventListener("change", () => {
      if (!isActive) return;
      state.selectedCompany = checkbox.checked ? color : null;
      renderCompanies();
    });

    elements.companyOptions.appendChild(label);
  }

  elements.foundButton.disabled = !isActive;
}

function renderGame() {
  renderEnding();
  renderHoldings();
  renderBuying();
  renderTrade();
  renderAcquireOrder();
  renderCompanies();
  renderActionPanels();
  renderRack();
  renderBoard();
}

async function placeTile(tile) {
  if (!canPlaceTile(tile)) return;

  try {
    const data = await api(`/api/rooms/${state.roomId}/place_tile`, {
      method: "POST",
      body: JSON.stringify({ player_id: state.playerId, tile }),
    });
    state.selectedTile = null;
    applyRoomState(data, `${displayTile(tile)} placed.`);
  } catch (error) {
    setStatus(error.message, true);
  }
}

function subscribeToRoomState() {
  socket.emit("join_room_state", {
    room_id: state.roomId,
    player_id: state.playerId,
  });
}

socket.on("room_state", (data) => {
  applyRoomState(data, "Connected.");
});

function handlePlaceButton() {
  if (!state.selectedTile) return;
  placeTile(state.selectedTile);
}

async function handleFoundButton() {
  const isActive = state.roomState?.pending_found_player_id === state.playerId;
  if (!isActive) return;

  if (!state.selectedCompany) {
    const shouldContinue = window.confirm("Don't want to found a company?");
    if (!shouldContinue) return;
  }

  try {
    const data = await api(`/api/rooms/${state.roomId}/found_company`, {
      method: "POST",
      body: JSON.stringify({
        player_id: state.playerId,
        color: state.selectedCompany || null,
      }),
    });
    state.selectedCompany = null;
    applyRoomState(data, "Company founded.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function handleFinishButton() {
  if (!canFinishTurn()) return;

  try {
    const data = await api(`/api/rooms/${state.roomId}/finish_turn`, {
      method: "POST",
      body: JSON.stringify({ player_id: state.playerId }),
    });
    state.selectedTile = null;
    state.selectedCompany = null;
    applyRoomState(data, "Turn finished.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function handleBuyButton() {
  const purchases = Object.fromEntries(
    Object.entries(state.buySelection).filter(([, quantity]) => quantity > 0)
  );

  try {
    const data = await api(`/api/rooms/${state.roomId}/buy_stocks`, {
      method: "POST",
      body: JSON.stringify({ player_id: state.playerId, purchases }),
    });
    state.buySelection = {};
    applyRoomState(data, "Stocks bought.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function handleProcessTradeButton() {
  const pending = state.roomState?.pending_acquire;
  if (!pending || pending.active_player_id !== state.playerId) return;

  try {
    const data = await api(`/api/rooms/${state.roomId}/trade_stocks`, {
      method: "POST",
      body: JSON.stringify({
        player_id: state.playerId,
        target: pending.active_target,
        sell: state.tradeSelection.sell,
        trade: state.tradeSelection.trade,
      }),
    });
    resetTradeSelection();
    applyRoomState(data, "Trade processed.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function handleAcquireOrderButton() {
  const pending = state.roomState?.pending_acquire;
  if (!pending?.ordering || pending.starter_id !== state.playerId) return;

  try {
    const data = await api(`/api/rooms/${state.roomId}/set_acquire_order`, {
      method: "POST",
      body: JSON.stringify({
        player_id: state.playerId,
        order: state.acquireOrder,
      }),
    });
    state.acquireOrder = [];
    applyRoomState(data, "Acquire order set.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

function copyLinksText() {
  const baseUrl = `${window.location.origin}/game/${encodeURIComponent(state.roomId)}`;
  const players = state.roomState?.players || [];
  const lines = players.map((player) => (
    `${player.name}: ${baseUrl}?player_id=${encodeURIComponent(player.id)}`
  ));
  return [
    `Room ${state.roomId}`,
    ...lines,
  ].join("\n");
}

async function writeClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const helper = document.createElement("textarea");
  helper.value = text;
  helper.setAttribute("readonly", "");
  helper.style.position = "fixed";
  helper.style.opacity = "0";
  document.body.appendChild(helper);
  helper.select();
  document.execCommand("copy");
  document.body.removeChild(helper);
}

function showCopyLinkFeedback(label) {
  clearTimeout(state.copyLinkResetTimer);
  elements.copyLinkButton.textContent = label;
  state.copyLinkResetTimer = window.setTimeout(() => {
    elements.copyLinkButton.textContent = "Copy Link";
  }, 1500);
}

async function handleCopyLinkButton() {
  if (!state.roomId || !state.roomState?.players?.length) {
    showCopyLinkFeedback("No Links");
    return;
  }

  try {
    await writeClipboard(copyLinksText());
    showCopyLinkFeedback("Copied");
  } catch (error) {
    showCopyLinkFeedback("Copy Failed");
  }
}

elements.sellMinus.addEventListener("click", () => {
  state.tradeSelection.sell = Math.max(0, state.tradeSelection.sell - 1);
  renderTrade();
});
elements.sellPlus.addEventListener("click", () => {
  state.tradeSelection.sell += 1;
  renderTrade();
});
elements.tradeMinus.addEventListener("click", () => {
  state.tradeSelection.trade = Math.max(0, state.tradeSelection.trade - 2);
  renderTrade();
});
elements.tradePlus.addEventListener("click", () => {
  state.tradeSelection.trade += 2;
  renderTrade();
});
elements.copyLinkButton.addEventListener("click", handleCopyLinkButton);
window.addEventListener("pointerdown", unlockAudio, { passive: true });
window.addEventListener("keydown", unlockAudio);

renderBoard();
subscribeToRoomState();
elements.placeButton.addEventListener("click", handlePlaceButton);
elements.foundButton.addEventListener("click", handleFoundButton);
elements.finishButton.addEventListener("click", handleFinishButton);
elements.buyButton.addEventListener("click", handleBuyButton);
elements.processTradeButton.addEventListener("click", handleProcessTradeButton);
elements.acquireOrderButton.addEventListener("click", handleAcquireOrderButton);
