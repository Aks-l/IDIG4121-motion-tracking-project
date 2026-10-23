"""Laser Duel, three.js version: the game runs in the browser, Python only
tracks the players and streams their silhouettes to it.

server.py        web server: game files, silhouette stream, commands
static/js/       the game: rules (duel.js, lasers.js), 3D scene (scene.js),
                 HUD, camera / keyboard sources

Same rules and tuning as laser_game (the pygame version), ported to
JavaScript so the 3D can be real: perspective, glow (bloom), particles.
"""
