"""Pinhole camera maths: pixel + depth -> metres -> the players' world."""

import math
from dataclasses import dataclass, replace

import numpy as np


@dataclass(frozen=True)
class Intrinsics:
    width: int
    height: int
    fx: float
    fy: float
    ppx: float
    ppy: float

    def deproject(self, u, v, depth_m):
        # Camera coordinates: x right, y down, z forward (metres). The D435
        # depth stream has no lens distortion, so the plain pinhole is exact.
        return np.array([
            (u - self.ppx) / self.fx * depth_m,
            (v - self.ppy) / self.fy * depth_m,
            depth_m,
        ])

    def mirrored(self):
        # Flipping the image left-right moves the principal point with it
        return replace(self, ppx=self.width - 1 - self.ppx)


def camera_to_world(point, pitch_deg, height_m):
    """Camera point -> world: x right, y height above floor, z distance."""
    x, y_down, z = point
    pitch = math.radians(pitch_deg)
    c, s = math.cos(pitch), math.sin(pitch)

    # Undo the camera's downward tilt so "down" is really down
    level_down = y_down * c + z * s
    level_forward = -y_down * s + z * c
    return np.array([x, height_m - level_down, level_forward])
