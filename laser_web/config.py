"""Settings of the Python side of the three.js version: the web server and
the silhouette grid it streams.

Game settings (lasers, rounds, hits, look) are in static/js/config.js;
camera settings are shared with the other games in coop_game/config.py.
"""

HOST = "localhost"
PORT = 8000
OPEN_BROWSER = True

# Each player's silhouette is a grid over the players' plane: x across the
# play space (0 = straight ahead of the camera), height above the floor
PLAY_X_RANGE_M = (-1.8, 1.8)
PLAY_HEIGHT_RANGE_M = (0.0, 2.4)
CELL_M = 0.03

# How often the stream looks for a new camera frame (s)
POLL_S = 0.004
# Status messages while no frames come (e.g. capturing the background) (s)
STATUS_EVERY_S = 0.25
# Debug image (Tab in the page): stop drawing it this long after the last request
DEBUG_IDLE_S = 2.0
DEBUG_JPEG_QUALITY = 70
