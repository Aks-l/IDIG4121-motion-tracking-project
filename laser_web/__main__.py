"""Run from the project folder, then play in the browser window it opens:

    python -m laser_web              # with the RealSense D435
    python -m laser_web --sim        # keyboard: WASD = Player 1, arrows = Player 2
"""

import argparse

from . import config
from .server import serve


def main():
    parser = argparse.ArgumentParser(description="Laser Duel in the browser (three.js), tracked by the RealSense D435")
    parser.add_argument("--sim", action="store_true", help="no camera: play with the keyboard")
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    args = parser.parse_args()

    serve(sim=args.sim, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
