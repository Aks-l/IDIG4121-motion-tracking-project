# Laser Duel (three.js)

The same game as `laser_game` (the pygame version), with real 3D in the
browser: a neon corridor in true perspective, glowing lasers (bloom), and
sparks when a laser hits. Two players stand side by side facing the
projection, each in their own lane, and dodge lasers flying at them. The
first to touch one loses.

Python only does the tracking. It streams each player's silhouette to the
browser, and the whole game runs there.

## Run

```bash
pip install -r coop_game/requirements.txt
python -m laser_web            # with the camera: opens the game in the browser
python -m laser_web --sim      # no camera: keyboard stick figures
```

Then press F in the browser window for fullscreen on the projector.
three.js loads from the internet (cdn.jsdelivr.net), so the computer
running the game needs a connection.

| Key | Action |
| --- | --- |
| Enter | Start now with whoever is in view (one player = solo) |
| R | Back to waiting for players |
| B | Re-capture the background (step out first) |
| Tab | Camera debug view |
| F | Fullscreen |
| (`--sim`) A D W S | Player 1: move, jump, duck |
| (`--sim`) arrow keys | Player 2: move, jump, duck |
| (`--sim`) 1 / 2 | That player steps out of / back into view |

URL options: `?sim` plays with the keyboard even when the camera server
is running; `?seed=7` sends the same lasers every round.

## How it fits together

```
Python (laser_web/server.py)
  coop_game vision pipeline   depth -> background -> Player 1 / 2 -> silhouettes
  GET /stream                 Server-Sent Events: each frame's silhouettes as
                              base64 bits, plus how old the frame is
  GET /debug.jpg, POST /command   debug view (Tab), re-capture background (B)

Browser (laser_web/static/js/)
  sources.js    camera stream, or keyboard stick figures
  duel.js       rounds and hit tests       (port of laser_game/duel.py)
  lasers.js     waves of lasers            (port of laser_game/lasers.py)
  scene.js      three.js: corridor, lasers, silhouettes, sparks, bloom
  hud.js        text over the scene (HTML)
  main.js       starts it all, keys, one update + render per screen refresh
```

Server-Sent Events are a one-way WebSocket, which is all this needs. They
are built into browsers and Python's standard library, so there is nothing
extra to install.

The players' plane (z = 0) fills the screen from the floor to the top of
the grid, seen from `VIEW_DISTANCE_M` in front of it, so each silhouette
appears exactly where its player stands: the screen is a mirror. Lasers
travel along z from `LASER_START_DEPTH_M` toward the players.

## Tuning

- Game: `laser_web/static/js/config.js`, with the same names as
  `laser_game/config.py` plus `BLOOM` for the glow. Edit and reload the page.
- Silhouette grid and server port: `laser_web/config.py`.
- Camera mount, background, player split: `coop_game/config.py` (shared).
  See `laser_game/README.md` for what to check on the real setup.
