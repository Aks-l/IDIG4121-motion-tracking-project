"""Physical play space (metres) -> game screen (px)."""

import numpy as np

from .. import config


class ScreenMapper:
    # x across the play space -> screen x; height above the floor -> screen
    # y, with the bottom of the height range on the game's ground line

    def __init__(self, screen_width, ground_y):
        self.width = screen_width
        self.ground_y = ground_y
        self.x_range = config.WORLD_X_RANGE_M
        self.height_range = config.WORLD_HEIGHT_RANGE_M
        self._samples = None

    def to_screen(self, world):
        (x0, x1), (h0, h1) = self.x_range, self.height_range
        sx = (world[0] - x0) / (x1 - x0) * self.width
        sy = self.ground_y - (world[1] - h0) / (h1 - h0) * self.ground_y

        # Hands outside the mapped space stay on the edge of the screen
        sx = min(max(sx, 0.0), self.width)
        sy = min(max(sy, 0.0), self.ground_y)
        return float(sx), float(sy)

    # Calibration: players sweep their hands over the whole space they can
    # reach; that becomes the full screen (lowest hands = the ground)

    def start_calibration(self):
        self._samples = []

    @property
    def calibrating(self):
        return self._samples is not None

    def add_sample(self, world):
        if self._samples is not None:
            self._samples.append(np.asarray(world[:2], dtype=float))

    def finish_calibration(self):
        samples, self._samples = self._samples, None
        if not samples or len(samples) < 30:
            return False

        points = np.array(samples)
        low = np.percentile(points, 2, axis=0)
        high = np.percentile(points, 98, axis=0)
        span = np.maximum(high - low, 0.5)
        pad = 0.08 * span

        self.x_range = (low[0] - pad[0], low[0] + span[0] + pad[0])
        self.height_range = (low[1], low[1] + span[1] + pad[1])
        return True
