"""Learned per-pixel depth of the empty play space (the uneven background).

A pixel belongs to a player when it is clearly in front of what was there
when the space was empty. Because every pixel has its own threshold, walls,
furniture and plants at different distances all drop out.
"""

import warnings

import cv2
import numpy as np

from .. import config

# D435 stereo noise grows with distance squared (Intel tuning guide):
# rms_mm = z_mm^2 * subpixel / (fx_px * baseline_mm)
SUBPIXEL = 0.08
BASELINE_MM = 50.0

LEARN_GUARD = np.ones((9, 9), np.uint8)


class BackgroundModel:
    def __init__(self):
        self.depth = None      # mm per pixel, 0 = never saw anything there
        self.margin = None     # mm a pixel must be in front of it

    @property
    def ready(self):
        return self.depth is not None

    def capture(self, frames, fx_full):
        stack = np.stack(frames).astype(np.float32)
        stack[stack <= 0] = np.nan

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            median = np.nanmedian(stack, axis=0)

        self.depth = np.nan_to_num(median, nan=0.0).astype(np.float32)

        noise = self.depth ** 2 * SUBPIXEL / (fx_full * BASELINE_MM)
        self.margin = np.maximum(
            config.BG_MARGIN_MM, config.BG_NOISE_K * noise
        ).astype(np.float32)

    def foreground(self, depth):
        valid = depth > 0

        # No background yet: only the camera's depth band applies
        if not self.ready:
            return valid

        # Nothing was there when empty, so anything there now is new
        nothing_behind = self.depth <= 0
        in_front = depth < self.depth - self.margin
        return valid & (nothing_behind | in_front)

    def update(self, depth, players):
        if not self.ready:
            return

        # Learn only well away from the players, so they never fade in
        near_players = cv2.dilate(players.astype(np.uint8), LEARN_GUARD) > 0
        learn = ~near_players & (depth > 0) & (self.depth > 0)
        self.depth[learn] += config.BG_LEARNING_RATE * (
            depth[learn] - self.depth[learn]
        )
