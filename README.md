# Acquire Board Game

![Acquire room lobby](image_login.png)
![Acquire game board](image_game.png)


This repository is a private, browser-based multiplayer board game inspired by hotel-merger gameplay. It is intentionally small:

- Python `Flask` backend
- WebSocket updates with `Flask-SocketIO`
- Plain `HTML`, `CSS`, and `JavaScript` frontend
- In-memory room state
- SQLite game recordings for debugging
- browser-based replays with action-by-action navigation
- Turn-based shared board with tile dealing

Current features include:

- use a lobby page to create, join, or spectate a password-protected room
- list active rooms and the players waiting in each room
- validate player names as 1-10 letters or numbers
- prevent duplicate player names within a room
- offer Classic rooms for 2-5 players and Expanded rooms for 2-8 players
- initialize games from a supplied or automatically generated reproducible seed
- allow only the room creator to start the game
- move players and waiting spectators to the board page after start
- show all player tiles in a read-only spectator interface
- show a live list of connected spectators on the board page
- place tiles on a 9x12 Classic board or an 11x14 Expanded board
- push room updates instantly with WebSockets
- found companies and expand company groups
- buy up to 3 stocks after tile placement resolves
- resolve acquisitions with survivor/order choices for tied company sizes
- pay shareholder rewards during acquisitions and final scoring
- sell, trade, or keep stocks after an acquired company is resolved
- detect invalid tiles that would connect two super companies
- show final rankings with a closable score panel
- record a full, hashed state snapshot after each successful game action
- retain the newest 10 game recordings automatically

## 1. Run locally

Open PowerShell in this folder and run:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Then open:

```text
http://127.0.0.1:5050
```

### Create a room

Enter the fields on the left side of the lobby:

1. Your player name (1-10 letters or numbers)
2. Invitation code: `evanston`
3. A room password of your choice
4. A game mode:
   - **Classic**: 2-5 players on the original 9x12 board
   - **Expanded**: 2-8 players on an 11x14 board
5. An optional numeric seed from `0` through `4294967295`

Leave the seed blank to generate one automatically. The effective seed is shown in the room card and on the game page. Using the same seed, mode, player join order, and application version reproduces the initial player order, tile racks, and remaining deck.

For a visual seed check, create one room with a short seed such as `12345` and confirm the narrow seed field, room card, and game-page mode badge all show that value. Create another room with the field blank and confirm a generated seed appears instead.

Click **Create Room**. The new room appears under **Existing Rooms** with its mode, board size, and capacity. The creator cannot Join or Spectate their own room; after at least 2 players have joined, the creator clicks **Start Game**.

### Join a room

Joining does not require the invitation code. Enter your name at the left, enter the room password inside the desired room card, and click **Join**. You will wait in the lobby until the creator starts the game.

### Spectate a room

Spectating also requires only your name and the room password. Click **Spectate** on the desired room. You will wait in the lobby and automatically move to the read-only game interface when the creator starts.

The room disappears from **Existing Rooms** when no players are connected. Spectators do not keep a room alive.

## 2. What the files do

- `app.py`: backend routes and in-memory game state
- `templates/index.html`: main page
- `templates/game.html`: board page
- `static/style.css`: page styling
- `static/app.js`: lobby logic and WebSocket updates
- `static/game.js`: board-page logic and WebSocket updates
- `recording_store.py`: SQLite recording, retention, hashing, export, and verification
- `scripts/game_recordings.py`: local recording inspection CLI
- `requirements.txt`: Python packages for local use and Render

## 3. Game recordings

A recording begins when a room successfully starts. Every successful game action stores its event metadata and the complete resulting state. Lobby-only rooms are not recorded.

The lobby lists the ten retained recordings under **Recent Replays**. Open one to view the game through the spectator interface, then use the left and right arrows to move between recorded actions. Replays are read-only, redact reusable player identifiers, and show the final score panel when a completed game reaches its last action.

By default, recordings are stored at:

```text
instance/game_recordings.sqlite3
```

Override the location with the `GAME_RECORDINGS_DB` environment variable. The store retains at most 10 games; starting an eleventh recording deletes the oldest game and all of its snapshots. An evicted game can continue in memory, but further recording for that room is disabled.

List retained games:

```powershell
python scripts/game_recordings.py list
```

Inspect or verify a recording:

```powershell
python scripts/game_recordings.py inspect RECORDING_ID
python scripts/game_recordings.py verify RECORDING_ID
```

Export a recording with player and spectator IDs redacted:

```powershell
python scripts/game_recordings.py export RECORDING_ID
```

Exports are written beneath `recording-exports/` by default. Use `--raw-ids` only for trusted local debugging. A single restorable state can be printed with:

```powershell
python scripts/game_recordings.py snapshot RECORDING_ID --sequence 3
```

Room passwords, WebSocket session IDs, connection maps, and cleanup timers are never recorded. The exact shuffled deck is stored, so snapshots remain the authoritative reproduction data even if a future Python or application version changes shuffle behavior.

## 4. Push to GitHub

Create an empty repository on GitHub first. GitHub's docs say not to initialize it with extra files if you are pushing an existing local project.

Then run:

```powershell
git init
git add .
git commit -m "Initial multiplayer prototype"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPO.git
git push -u origin main
```

## 5. Deploy to Render

Create a `Web Service` on Render, not a static site, because this app has a Python backend.

Use these settings:

- Language: `Python 3`
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn -w 1 --threads 100 --timeout 0 --keep-alive 75 app:app`
- Health Check Path: `/health`
- Instances: `1`

After deployment, Render will give you an `onrender.com` URL. Share that URL with your friend.

This repo also includes `render.yaml`, so you can deploy it as a Render Blueprint instead of typing the settings manually.

## 6. Important limitations

Active room state is still stored only in server memory. SQLite recordings are intended for debugging and export, not automatic game resumption. That means:

- restarting the service clears all active rooms
- free-tier spin-down can clear active state
- Render's ephemeral filesystem can also clear SQLite recordings unless a persistent disk or external database is configured
- running more than one web instance will split game state across instances, so keep Render at `1` instance
- recorded snapshots can be reconstructed locally, but there is no player-facing resume flow yet

For a real version, the next steps are:

1. restore active room state from recorded snapshots
2. add a player-facing saved-game resume flow
3. add private invite links and reconnection support
4. add stronger production monitoring and persistence
