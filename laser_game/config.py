"""Every tunable number of the laser duel in one place.

The camera itself (mount height and tilt, background, splitting the two
players) is set in coop_game/config.py: both games share that pipeline.

World distances are in metres (m), screen values in pixels (px) of the game
window, times in seconds (s).
"""

# ------------------------------------------------------------------ screen
SCREEN_SIZE = (1280, 720)
FULLSCREEN = False
FPS = 60

# ------------------------------------------------------------------ bodies
# Each player's silhouette is a grid over the players' plane: x across the
# play space (0 = straight ahead of the camera), height above the floor
PLAY_X_RANGE_M = (-1.8, 1.8)
PLAY_HEIGHT_RANGE_M = (0.0, 2.4)
CELL_M = 0.03
# Player 1's lane is left of this, Player 2's right of it
LANE_SPLIT_X_M = 0.0
# Fewer silhouette cells than this = nobody there
MIN_BODY_CELLS = 60

# -------------------------------------------------------------------- view
# The front of the 3D scene is the players' plane, shown like a mirror:
# the floor at the bottom of the screen, PLAY_HEIGHT_RANGE_M filling it
FLOOR_MARGIN_PX = 16
# Lasers come from the vanishing point at this height
EYE_HEIGHT_M = 1.2
# Virtual viewer distance from the players' plane: smaller = stronger 3D
VIEW_DISTANCE_M = 2.5
# How deep in the scene lasers appear
LASER_START_DEPTH_M = 30.0
# Lasers keep flying this far past the players before they vanish
LASER_PAST_DEPTH_M = 1.8

# ------------------------------------------------------------------ rounds
# Both players in view this long starts the countdown (Enter: start now)
JOIN_HOLD_S = 1.0
COUNTDOWN_S = 3.0
# Each player's height is measured during the countdown; lasers scale to it
DEFAULT_PLAYER_HEIGHT_M = 1.7
PLAYER_HEIGHT_LIMITS_M = (1.0, 2.1)
# 1 = the first player to touch a laser loses
LIVES = 1
# With more lives: safe this long after being hit
HIT_COOLDOWN_S = 1.0
# Out of view this long during a round = out
FORFEIT_S = 1.5
# Result screen, then back to waiting for players
RESTART_S = 10.0

# ------------------------------------------------------------------ lasers
FIRST_WAVE_DELAY_S = 1.0
# Seconds from appearing to reaching the players: first wave, then faster
TRAVEL_START_S = 2.4
TRAVEL_MIN_S = 1.0
TRAVEL_SPEEDUP_S = 0.05      # per wave
SPAWN_GAP_START_S = 2.2
SPAWN_GAP_MIN_S = 0.8
SPAWN_SPEEDUP_S = 0.06       # per wave
DIAGONAL_FROM_WAVE = 6
# Relative chance of each kind of laser
KIND_WEIGHTS = {"low": 3, "high": 3, "aimed": 2, "diagonal": 2}

# Beam heights as fractions of each player's own height, so it is equally
# hard for a tall and a short player
LOW_BEAM = 0.10              # jump over it
HIGH_BEAM = 0.78             # duck under it
DIAGONAL_BEAM = (0.12, 1.15) # from one side of the lane to the other
# Horizontal beams stop this far from the lane edges
LANE_INSET_M = 0.05

LASER_DRAW_WIDTH_M = 0.05
LASER_HIT_THICKNESS_M = 0.06

# -------------------------------------------------------------------- hits
# Forgiving on purpose: a laser only counts as a hit when it overlaps at
# least MIN_HIT_CELLS of the body in HIT_FRAMES camera frames around the
# moment it reaches the player
MIN_HIT_CELLS = 4
HIT_FRAMES = 2
HIT_WINDOW_S = 0.15
# Camera + projector delay: the frame the camera took this long after a
# laser arrived on screen shows what the player did when they saw it
DISPLAY_LAG_S = 0.08
# No camera frames at all for this long after the window: call it dodged
FRAME_TIMEOUT_S = 0.5
