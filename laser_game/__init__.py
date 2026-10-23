"""Laser Duel: two players dodge lasers flying at them out of the screen;
the first to touch one loses. Tracked by the Intel RealSense D435 through
coop_game's vision pipeline (whole-body silhouettes, see vision/bodies.py).

duel.py     round rules and hit tests (no pygame, no camera)
lasers.py   laser shapes and the waves that send them
render.py   fake-3D corridor, lasers and glowing silhouettes
sources.py  silhouettes from the camera, or the keyboard (--sim)
game.py     pygame loop and HUD
"""
