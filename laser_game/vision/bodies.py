"""Player masks -> whole-body silhouettes on a grid in metres, and a picture
of the real player from the colour camera on the same grid.

The grid is a flat picture of the players' plane: x across the play space,
height above the floor, one cell = GridSpec.cell metres square. Row 0 is the
top of the grid (like an image), column 0 its left edge.

Each player is treated as standing in a flat plane at their own distance
from the camera: every pixel of theirs is placed where its camera ray
crosses that plane. A pixel with a wrong depth (common on body edges) then
still lands next to the body instead of being smeared outward, and the
camera image maps onto the grid in one warp (a homography) with no holes.
"""

from dataclasses import dataclass
from functools import cached_property, lru_cache

import cv2
import numpy as np

from .. import config
from .geometry import world_to_camera

# The picture of the real player is this many times finer than the grid
FINE = 3


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


@dataclass
class Picture:
    """The real player, cut out: RGBA on the fine grid (alpha = their shape),
    cropped to them. Its top-left cell is (row, col) of the fine grid."""
    rgba: np.ndarray
    row: int
    col: int


def _plane_warp(spec, distance, project):
    """Homography: fine-grid pixel -> image pixel, for the plane `distance`
    m ahead of the camera. project: camera point(s) -> image (u, v)."""
    rows, cols = spec.shape
    rows, cols, cell = rows * FINE, cols * FINE, spec.cell / FINE

    grid = np.array([(0, 0), (cols - 1, 0), (cols - 1, rows - 1), (0, rows - 1)], np.float32)
    x = spec.x_range[0] + (grid[:, 0] + 0.5) * cell
    height = spec.height_range[1] - (grid[:, 1] + 0.5) * cell
    point = world_to_camera(
        x, height, np.full(4, distance), config.CAMERA_PITCH_DEG, config.CAMERA_HEIGHT_M
    )
    u, v = project(point)
    image = np.stack([u, v], axis=1).astype(np.float32)
    return cv2.getPerspectiveTransform(grid, image), (cols, rows)


def body_grid(player, distance, intrinsics, spec):
    """One player's mask (image pixels) -> (silhouette on the grid, their
    shape on the fine grid as 0..255 with soft edges)."""
    warp, size = _plane_warp(spec, distance, intrinsics.project)
    fine = cv2.warpPerspective(
        player.astype(np.uint8) * 255, warp, size,
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
    )
    # A cell is body when at least half of it is
    rows, cols = spec.shape
    coverage = cv2.resize(fine, (cols, rows), interpolation=cv2.INTER_AREA)
    return coverage >= 128, fine


def body_picture(fine, distance, color, mirrored, spec):
    """The colour camera's view of one player, cut out by their shape."""
    rows = np.flatnonzero(fine.any(axis=1))
    cols = np.flatnonzero(fine.any(axis=0))
    if not rows.size:
        return None
    r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1

    warp, size = _plane_warp(spec, distance, lambda p: color.project(p, mirrored))
    # Only the player's box: shift the output by its top-left corner
    shift = np.array([[1, 0, c0], [0, 1, r0], [0, 0, 1]], np.float64)
    box = (c1 - c0, r1 - r0)
    flags = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
    bgr = cv2.warpPerspective(color.image, warp @ shift, box, flags=flags)

    # The colour camera sees less than the depth camera: where it can't see
    # the player, leave the picture see-through (fading out), so their
    # glowing silhouette shows there instead of a hard black block
    seen = cv2.warpPerspective(_coverage(color.image.shape[:2]), warp @ shift, box, flags=flags)

    alpha = np.minimum(fine[r0:r1, c0:c1], seen)
    rgba = np.dstack([bgr[..., ::-1], alpha])
    return Picture(np.ascontiguousarray(rgba), int(r0), int(c0))


@lru_cache(maxsize=2)
def _coverage(shape, fade_px=24):
    """255 inside the colour image, fading to 0 over its outer fade_px."""
    rows, cols = shape
    edge = np.minimum.outer(
        np.minimum(np.arange(rows), np.arange(rows)[::-1]),
        np.minimum(np.arange(cols), np.arange(cols)[::-1]),
    )
    return (np.clip(edge / fade_px, 0, 1) * 255).astype(np.uint8)
