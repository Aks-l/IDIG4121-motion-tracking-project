"""Pinhole camera maths: pixel + depth -> metres -> the players' world."""

import math
from dataclasses import dataclass, replace
from functools import lru_cache

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

    def project(self, point):
        """Camera point(s) (3, ...) -> pixel (u, v)."""
        x, y, z = point
        return self.fx * x / z + self.ppx, self.fy * y / z + self.ppy

    def mirrored(self):
        # Flipping the image left-right moves the principal point with it
        return replace(self, ppx=self.width - 1 - self.ppx)


@dataclass
class ColorFrame:
    """One colour image and how to find a depth-camera point in it."""
    image: np.ndarray        # BGR, as the colour camera sees it (never mirrored)
    intrinsics: Intrinsics
    rotation: np.ndarray     # 3x3, depth camera -> colour camera
    translation: np.ndarray  # m, depth camera -> colour camera

    def project(self, point, mirrored):
        """Point(s) (3, ...) in the depth camera's frame -> colour pixel.

        mirrored: the point comes from a mirrored depth image (x flipped).
        """
        x, y, z = point
        if mirrored:
            x = -x
        p = np.stack(np.broadcast_arrays(x, y, z))
        q = np.tensordot(self.rotation, p, axes=1)
        q += self.translation.reshape((3,) + (1,) * (q.ndim - 1))
        return self.intrinsics.project(q)


def camera_to_world(point, pitch_deg, height_m):
    """Camera point -> world: x right, y height above floor, z distance."""
    x, y_down, z = point
    pitch = math.radians(pitch_deg)
    c, s = math.cos(pitch), math.sin(pitch)

    # Undo the camera's downward tilt so "down" is really down
    level_down = y_down * c + z * s
    level_forward = -y_down * s + z * c
    return np.array([x, height_m - level_down, level_forward])


def world_to_camera(x, height, forward, pitch_deg, height_m):
    """The inverse of camera_to_world."""
    pitch = math.radians(pitch_deg)
    c, s = math.cos(pitch), math.sin(pitch)
    level_down = height_m - height
    return np.array([
        x,
        level_down * c - forward * s,
        level_down * s + forward * c,
    ])


@lru_cache(maxsize=4)
def _rays(intrinsics, pitch_deg):
    # Per pixel: world (x, level_down, forward) for 1 m of camera depth
    u = np.arange(intrinsics.width, dtype=np.float32)[None, :]
    v = np.arange(intrinsics.height, dtype=np.float32)[:, None]
    rx = (u - intrinsics.ppx) / intrinsics.fx
    ry = (v - intrinsics.ppy) / intrinsics.fy
    pitch = math.radians(pitch_deg)
    c, s = math.cos(pitch), math.sin(pitch)
    shape = (intrinsics.height, intrinsics.width)
    return (
        np.broadcast_to(rx, shape).astype(np.float32),
        (ry * c + s).astype(np.float32),
        (-ry * s + c).astype(np.float32),
    )


def world_image(depth, intrinsics, pitch_deg, height_m):
    """Every pixel of a depth image (mm) -> world x, height, forward (m),
    each shaped like the image. Pixels without depth come out at 0, 0, 0."""
    across, down, ahead = _rays(intrinsics, pitch_deg)
    z = depth * np.float32(0.001)
    height = height_m - down * z
    height[depth <= 0] = 0.0
    return across * z, height, ahead * z
