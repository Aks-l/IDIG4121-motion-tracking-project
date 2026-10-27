"""Run from the project folder:

    python -m laser_game             # with the RealSense D435
    python -m laser_game --sim       # keyboard: WASD = Player 1, arrows = Player 2
"""

import argparse

from . import config, settings
from .duel import make_lanes
from .game import LaserGame
from .sources import KeyboardBodySource, RealSenseBodySource
from .vision.bodies import GridSpec


def main():
    parser = argparse.ArgumentParser(description="Two-player laser dodging for the Intel RealSense D435")
    parser.add_argument("--sim", action="store_true", help="play with the keyboard instead of the camera")
    parser.add_argument("--seed", type=int, help="same seed = same lasers")
    args = parser.parse_args()

    message = settings.load()
    if message:
        print(message)

    spec = GridSpec(config.PLAY_X_RANGE_M, config.PLAY_HEIGHT_RANGE_M, config.CELL_M)
    if args.sim:
        source = KeyboardBodySource(spec, make_lanes(spec))
    else:
        source = RealSenseBodySource(spec)

    LaserGame(source, spec, args.seed).run()


if __name__ == "__main__":
    main()
