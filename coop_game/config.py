"""Every tunable number of the game in one place.

Distances are in metres (m) or millimetres (mm) as named, screen values in
pixels (px) of the game window, times in seconds (s).
"""

# ------------------------------------------------------------------ camera
DEPTH_SIZE = (848, 480)      # the D435's best depth resolution
DEPTH_FPS = 30
DECIMATION = 2               # processed at 424x240: plenty for two players

# Hard depth band, applied by the camera's own threshold filter
NEAR_M = 0.5
FAR_M = 4.5

# Spatial smoothing costs ~1 ms; temporal smoothing adds lag, so it's off
USE_SPATIAL_FILTER = True
USE_TEMPORAL_FILTER = False

# Where the camera is: height of the lens above the floor and how far it is
# tilted down. Turns camera coordinates into "height above the floor".
CAMERA_HEIGHT_M = 2.2
CAMERA_PITCH_DEG = 15.0

# The camera looks out of the screen at the players, so its image is a
# mirror of what the audience sees. True = flip it, so Player 1 (left on
# the screen) is also on the left of the image.
MIRROR = True

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
SPLIT_SMOOTHING = 0.3

# ----------------------------------------------------------------- anchors
# "reach":   each player's point reaching farthest toward the other player.
#            Works whether hands are held sideways or toward the camera.
# "nearest": each player's point closest to the camera. Only finds the hand
#            when it is held out toward the camera: side-on players reaching
#            for each other keep their hands at body depth.
ANCHOR_MODE = "reach"
# Ignore the lowest part of each player (legs, feet) when looking for hands
IGNORE_LOWER_FRACTION = 0.35
# nearest: the hand is everything within HAND_BAND_MM of the nearest depth
NEAREST_PERCENTILE = 1.0
HAND_BAND_MM = 80.0
# reach: the hand is everything within REACH_BAND_PX of the inner edge
REACH_BAND_PX = 10
# A lost anchor is held this long before it is reported missing
ANCHOR_HOLD_S = 0.25
# 1€ filter on anchor positions (metres): lower cutoff = less jitter,
# higher beta = less lag on fast moves
ONE_EURO_MIN_CUTOFF = 1.5
ONE_EURO_BETA = 8.0

# ------------------------------------------------------------ screen, game
SCREEN_SIZE = (1280, 720)
FULLSCREEN = False
FPS = 60
GROUND_Y = 620               # px: the floor line of the game world

# Physical area mapped onto the screen: x across the play space, height
# above the floor. The bottom of the height range maps onto the ground.
WORLD_X_RANGE_M = (-1.6, 1.6)
WORLD_HEIGHT_RANGE_M = (0.0, 2.0)
CALIBRATION_S = 6.0

# Physics
GRAVITY = 2400.0             # px/s^2
PHYSICS_SUBSTEPS = 4
# An anchor may vanish this long before the players lose their grip
GRIP_GRACE_S = 0.35
# Hands this close to the ends of a dropped object pick it up again
REGRAB_RADIUS_PX = 80.0

# Obstacles
SCROLL_SPEED = 240.0         # px/s at the start
SCROLL_SPEEDUP = 6.0         # px/s faster for every obstacle passed
SPAWN_GAP_S = (2.0, 3.4)
LIVES = 3
HIT_COOLDOWN_S = 1.0
