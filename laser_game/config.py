"""Every tunable number of the laser duel in one place: the camera (mount
height and tilt, background, splitting the two players) and the game.

World distances are in metres (m) or millimetres (mm) as named, screen
values in pixels (px) of the game window, times in seconds (s).
"""

# ------------------------------------------------------------------ camera
DEPTH_SIZE = (848, 480)      # the D435's best depth resolution
DEPTH_FPS = 30
DECIMATION = 2               # processed at 424x240: plenty for two players

# Hard depth band, applied by the camera's own threshold filter. NEAR_M low,
# so players up close aren't cut (the D435 measures from about 0.3 m)
NEAR_M = 0.3
FAR_M = 10.0

# Spatial smoothing costs ~1 ms; temporal smoothing adds lag, so it's off
USE_SPATIAL_FILTER = True
USE_TEMPORAL_FILTER = False

# Where the camera is: height of the lens above the floor and how far it is
# tilted down (negative = up). Turns camera coordinates into "height above
# the floor".
# AUTO_CALIBRATE: measure both from the floor every time the background is
# captured (at start and on B), so the camera may sit a little differently
# each run. The two values below are only used when no floor is found.
AUTO_CALIBRATE = True
CAMERA_HEIGHT_M = 1.08
CAMERA_PITCH_DEG = -3.4

# The camera looks out of the screen at the players, so its image is a
# mirror of what the audience sees. True = flip it, so Player 1 (left on
# the screen) is also on the left of the image.
MIRROR = True

# Show the real players (colour camera) inside their glowing silhouettes
SHOW_REAL_PLAYER = True
COLOR_SIZE = (848, 480)

# --------------------------------------------------------------- play zone
# Only this box of the room counts; everything the camera sees outside it
# is ignored. Tune it live with:  python -m laser_game.zone_debug
# Across, 0 = straight ahead of the camera, negative = Player 1's side
ZONE_X_M = (-2.1, 2.1)
# Distance ahead of the camera, along the floor. Keep the far end well
# inside FAR_M: the camera's depth is noisy right at its limit
ZONE_DEPTH_M = (0.5, 3.8)
# Height above the floor: the bottom cuts off the floor itself
ZONE_HEIGHT_M = (0.06, 2.4)

# -------------------------------------------------------------- background
BACKGROUND_DELAY_S = 3.0     # countdown before capturing, so people step out
BACKGROUND_FRAMES = 45
# A pixel is a player when it is this much closer than the background...
BG_MARGIN_MM = 80.0
# ...or BG_NOISE_K times the expected stereo noise there, whichever is more
BG_NOISE_K = 3.0
# Slowly re-learn the background where nobody is (lights, a moved chair)
BG_LEARNING_RATE = 0.005

# ----------------------------------------------------------------- players
MIN_PLAYER_AREA_PX = 1200    # at the processed resolution
# The divider between the players is searched in this band of the width
SPLIT_SEARCH = (0.25, 0.75)
# Moving the divider costs this much per px, so it doesn't jump around
SPLIT_STICKINESS = 0.5
# Each px away from straight ahead costs this much: among equally empty
# columns the divider takes the most central one
SPLIT_CENTRE_PULL = 0.05
SPLIT_SMOOTHING = 0.3
# A player's pixels further than this in front of or behind their body are
# artifacts (smeared edges, the floor at their feet, furniture)
PLAYER_DEPTH_BAND_M = 0.5
# Shave this many px off every player's outline: the camera makes near
# objects a little too big at their edges (0 = off)
EDGE_TRIM_PX = 1

# ------------------------------------------------------------------ screen
SCREEN_SIZE = (1280, 720)
FULLSCREEN = True
FPS = 60

# ------------------------------------------------------------------ bodies
# Each player's silhouette is a grid over the players' plane: x across the
# play space (0 = straight ahead of the camera), height above the floor.
# x: the full width the screen shows (the lanes are this wide too)
PLAY_X_RANGE_M = (-2.1, 2.1)
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
