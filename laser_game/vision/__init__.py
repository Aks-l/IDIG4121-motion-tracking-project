"""Depth camera -> player masks -> one whole-body silhouette per player.

camera.py      Intel RealSense D435: depth stream and post-processing
background.py  learned depth of the empty play space
players.py     foreground -> Player 1 (left) / Player 2 (right)
geometry.py    pixel + depth -> metres above the floor
bodies.py      a player's pixels -> silhouette on a grid in metres
tracker.py     all of the above on a thread, off the game loop

Only camera.py imports pyrealsense2, so everything else runs (and can be
tested) without the camera.
"""
