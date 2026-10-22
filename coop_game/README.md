# Co-op Carry

Two players stand side-on in front of the projected screen and carry a
virtual object (a couch, a plank, an aquarium...) between their hands,
lifting and tilting it past obstacles. An Intel RealSense D435 tracks one
hand ("anchor") per player.

## Run

```bash
pip install -r coop_game/requirements.txt
python -m coop_game            # with the camera
python -m coop_game --sim      # no camera: WASD = Player 1, arrows = Player 2
```

On start the camera captures the empty play area (3 s countdown: step out).

| Key | Action |
| --- | --- |
| B | Re-capture the background (step out first) |
| C | Calibrate: sweep your hands from the floor to above your head for 6 s |
| Tab | Camera debug view (players tinted, anchors circled) |
| 1-9 | Switch object |
| R | Restart |
| F | Fullscreen (projector) |
| Space | (`--sim`) let go of the object |

## Pipeline

```
DepthCamera (camera.py)         848x480 depth -> decimate -> depth band -> spatial
   -> orient (tracker.py)       mirror so Player 1 is on the left, like on screen
   -> BackgroundModel           per-pixel depth of the empty room: keep what's in front
   -> clean_mask / find_split   close holes, find the emptiest column between players
   -> split_players             largest region on each side = Player 1 / Player 2
   -> find_anchor               "nearest" (closest to camera) or "reach" (toward partner)
   -> deproject + camera_to_world   metres: x across, height above floor
   -> 1€ filter, short hold     smooth, survive one-frame dropouts
TrackerThread                   all of the above at 30 fps, off the game loop
RealSenseSource + ScreenMapper  metres -> screen px (floor = game ground)
Game (game.py)                  object physics, obstacles, HUD at 60 fps
```

`game/` never touches the camera, and `vision/` never touches pygame:
`KeyboardSource` replaces the camera for development.

## The object

Player 1's anchor holds the left end, Player 2's the right end:

- centre = midpoint of the anchors, tilt = `atan2(dy, dx)` of the line
  between them; the object springs toward that pose (heavier = slower);
- hands farther apart than `length x (1 + grip_tolerance)`, a hand lost for
  more than `GRIP_GRACE_S`, or (if set) a tilt over `max_tilt_deg` drops it;
- dropped, it is a rigid body: gravity, bounce, friction, tipping flat;
- hands near both ends pick it up again.

## Add an object

In `game/objects.py`:

```python
register(ObjectSpec(
    "piano", "piano", length=360, thickness=140, mass=6.0,
    color=(30, 30, 30), grip_tolerance=0.25, damping_ratio=1.0,
))
```

For a custom look, pass `draw=` a function returning an unrotated
`pygame.Surface` of `length x thickness`.

## Tuning

Everything is in `config.py`. First things to check on the real setup:

- `CAMERA_HEIGHT_M`, `CAMERA_PITCH_DEG`: where the camera is mounted.
- `ANCHOR_MODE`: `"reach"` (default) takes the point reaching farthest
  toward the partner. `"nearest"` takes the point closest to the camera,
  which only finds the hand when it is held out toward the camera; side-on
  players reaching for each other keep their hands at body depth.
- `MIRROR`: if Player 1 shows up on the right, flip it.
- Press C once players are in place to fit the play area to the screen.
