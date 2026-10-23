# Laser Duel

Two players stand side by side facing the projected screen, each in their
own lane. Lasers fly at them out of the depth of a 3D corridor: jump over
low beams, duck under high ones, step away from beams aimed at you, and
squeeze past diagonals. The first player to touch a laser loses.

The screen is a mirror: each player sees their own glowing silhouette at
the front of the corridor, so they can see where a laser will cross them.
A thin line on the players' plane shows where each laser is going to land.

## Run

```bash
pip install -r coop_game/requirements.txt
python -m laser_game            # with the camera
python -m laser_game --sim      # no camera: keyboard stick figures
```

On start the camera captures the empty play area (3 s countdown: step out).
When both players are in view for a second, a 3 s countdown measures their
heights and the round starts.

| Key | Action |
| --- | --- |
| Enter | Start now with whoever is in view (one player = solo) |
| R | Back to waiting for players |
| B | Re-capture the background (step out first) |
| Tab | Camera debug view |
| F | Fullscreen (projector) |
| (`--sim`) A D W S | Player 1: move, jump, duck |
| (`--sim`) arrow keys | Player 2: move, jump, duck |
| (`--sim`) 1 / 2 | That player steps out of / back into view |

## How it works

```
coop_game vision pipeline     depth -> background -> split into Player 1 / 2
   -> body_grid (bodies.py)   every player pixel to metres: a silhouette on
                              a grid of 3 cm cells (x across, height)
RealSenseBodySource           the latest silhouettes, stamped with their time
LaserDuel (duel.py)           rounds, waves of lasers, hit tests
Renderer (render.py)          fake 3D: perspective maths on 2D pygame lines
```

- **Fair waves.** Every wave sends the same laser down both lanes at the
  same moment. Beam heights are fractions of each player's own height
  (measured in the countdown), and aimed beams aim at each player.
- **Forgiving hits.** A laser counts only if it overlaps at least
  `MIN_HIT_CELLS` of your silhouette in `HIT_FRAMES` camera frames within
  `HIT_WINDOW_S` of reaching you, shifted by `DISPLAY_LAG_S` for the camera
  and projector delay.
- **Leaving doesn't save you.** Out of view for `FORFEIT_S` during a round
  counts as out.

## Tuning

Laser game settings are in `laser_game/config.py`; camera settings
(`CAMERA_HEIGHT_M`, `CAMERA_PITCH_DEG`, `MIRROR`, background) are shared
with the carry game in `coop_game/config.py`.

First things to check on the real setup:

- Tab: both players should be tinted in their own colour. If the split
  between them wanders, stand a bit further apart.
- `LANE_SPLIT_X_M`: where the two lanes meet (0 = straight ahead of the
  camera). Move it if the camera isn't centred between the players.
- `CAMERA_HEIGHT_M` / `CAMERA_PITCH_DEG`: if the silhouettes float above or
  sink below the floor line, these are off. The measured heights in the
  player panels should match the players' real heights.
- Hits too strict or too easy: `MIN_HIT_CELLS`, `HIT_FRAMES`,
  `HIT_WINDOW_S`, `LASER_HIT_THICKNESS_M`.
- Too hard or too easy: `TRAVEL_*`, `SPAWN_GAP_*`, `LOW_BEAM`, `HIGH_BEAM`,
  `LIVES`.
