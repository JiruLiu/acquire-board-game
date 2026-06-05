# Acquire Board Game

![alt text](image.png)


This repository is a private, browser-based multiplayer board game inspired by hotel-merger gameplay. It is intentionally small:

- Python `Flask` backend
- WebSocket updates with `Flask-SocketIO`
- Plain `HTML`, `CSS`, and `JavaScript` frontend
- In-memory room state
- Turn-based shared board with tile dealing

Current features include:

- use a lobby page to create or join a room
- validate player names as 1-10 letters or numbers
- prevent duplicate player names within a room
- allow only 2-5 players in a room
- allow only the room creator to start the game
- move to a separate board page after start
- place tiles on a 9x12 shared board
- push room updates instantly with WebSockets
- found companies and expand company groups
- buy up to 3 stocks after tile placement resolves
- resolve acquisitions with survivor/order choices for tied company sizes
- pay shareholder rewards during acquisitions and final scoring
- sell, trade, or keep stocks after an acquired company is resolved
- detect invalid tiles that would connect two super companies
- show final rankings with a closable score panel

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
http://127.0.0.1:5000
```

Open that URL in two browser windows, create a room in one, and join it from the other.

## 2. What the files do

- `app.py`: backend routes and in-memory game state
- `templates/index.html`: main page
- `templates/game.html`: board page
- `static/style.css`: page styling
- `static/app.js`: lobby logic and WebSocket updates
- `static/game.js`: board-page logic and WebSocket updates
- `requirements.txt`: Python packages for local use and Render

## 3. Push to GitHub

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

## 4. Deploy to Render

Create a `Web Service` on Render, not a static site, because this app has a Python backend.

Use these settings:

- Language: `Python 3`
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn -w 1 --threads 100 app:app`
- Health Check Path: `/`
- Instances: `1`

After deployment, Render will give you an `onrender.com` URL. Share that URL with your friend.

This repo also includes `render.yaml`, so you can deploy it as a Render Blueprint instead of typing the settings manually.

## 5. Important limitation

Right now the game state is stored only in server memory. That means:

- restarting the service clears all rooms
- free-tier spin-down can clear active state
- running more than one web instance will split game state across instances, so keep Render at `1` instance
- no saved games yet

For a real version, the next steps are:

1. move room state into a database
2. add saved games
3. add private invite links and reconnection support
4. add stronger production monitoring and persistence
