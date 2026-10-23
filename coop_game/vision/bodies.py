"""Player masks -> whole-body silhouettes on a grid in metres.

The grid is a flat picture of the players' plane: x across the play space,
height above the floor, one cell = GridSpec.cell metres square. Row 0 is the
top of the grid (like an image), column 0 its left edge.
"""

from dataclasses import dataclass
from functools import cached_property

import cv2
import numpy as np

from .. import config
from .geometry import camera_to_world

CLOSE_KERNEL = np.ones((3, 3), np.uint8)


@dataclass(frozen=True)
class GridSpec:
    x_range: tuple           # m, left to right edge
    height_range: tuple      # m, floor to top
    cell: float              # m

    @property
    def shape(self):
        (x0, x1), (h0, h1) = self.x_range, self.height_range
        return round((h1 - h0) / self.cell), round((x1 - x0) / self.cell)

    @cached_property
    def centres(self):
        """(x, height) of every cell's centre, each shaped like the grid."""
        rows, cols = self.shape
        xs = self.x_range[0] + (np.arange(cols) + 0.5) * self.cell
        heights = self.height_range[1] - (np.arange(rows) + 0.5) * self.cell
        return np.meshgrid(xs, heights)

    def rasterize(self, xs, heights):
        """Grid with every cell holding at least one of the points set."""
        rows, cols = self.shape
        col = np.floor((xs - self.x_range[0]) / self.cell).astype(int)
        row = np.floor((self.height_range[1] - heights) / self.cell).astype(int)
        inside = (col >= 0) & (col < cols) & (row >= 0) & (row < rows)

        grid = np.zeros((rows, cols), dtype=bool)
        grid[row[inside], col[inside]] = True
        return grid


def body_grid(player, depth, intrinsics, spec):
    """One player's mask (image pixels) -> their silhouette on the grid."""
    v, u = np.nonzero(player)
    distances = depth[v, u]
    valid = distances > 0
    if not valid.any():
        return None

    # Holes closed by clean_mask have no depth: put them at the body's depth
    distances = np.where(valid, distances, np.median(distances[valid])) / 1000.0

    points = intrinsics.deproject(u, v, distances)
    world = camera_to_world(points, config.CAMERA_PITCH_DEG, config.CAMERA_HEIGHT_M)
    grid = spec.rasterize(world[0], world[1])

    # Far from the camera neighbouring pixels can land a cell apart: pinholes
    # (zero border: the default would grow anything touching the grid's edge)
    closed = cv2.morphologyEx(
        grid.astype(np.uint8), cv2.MORPH_CLOSE, CLOSE_KERNEL,
        borderType=cv2.BORDER_CONSTANT, borderValue=0,
    )
    return closed > 0
