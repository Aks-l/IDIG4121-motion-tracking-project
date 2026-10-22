"""Run from the project folder:

    python -m coop_game              # with the RealSense D435
    python -m coop_game --sim        # keyboard: WASD = Player 1, arrows = Player 2
"""

import argparse

from . import config
from .game.game import Game
from .game.mapping import ScreenMapper
from .game.objects import OBJECTS
from .game.sources import KeyboardSource, RealSenseSource


def main():
    parser = argparse.ArgumentParser(description="Co-op carry game for the Intel RealSense D435")
    parser.add_argument("--sim", action="store_true", help="play with the keyboard instead of the camera")
    parser.add_argument("--object", default="couch", choices=sorted(OBJECTS))
    args = parser.parse_args()

    if args.sim:
        # Start with both hands on the ends of the object, so it's picked up
        spec = OBJECTS[args.object]
        x, y = config.SCREEN_SIZE[0] / 2, config.GROUND_Y - spec.thickness / 2
        source = KeyboardSource((x - spec.length / 2, y), (x + spec.length / 2, y))
    else:
        source = RealSenseSource(ScreenMapper(config.SCREEN_SIZE[0], config.GROUND_Y))

    Game(source, args.object).run()


if __name__ == "__main__":
    main()
