"""The play zone: a box in the room, in metres, where players can be.

Everything the camera sees outside it (walls, desks, people watching, the
floor, the noisy far edge of the depth range) is cut before looking for
players. Tune it with `python -m laser_game.zone_debug`.
"""

from .. import config
from .geometry import world_image


def world(depth, intrinsics):
    """x, height, forward (m) of every pixel, see geometry.world_image."""
    return world_image(
        depth, intrinsics, config.CAMERA_PITCH_DEG, config.CAMERA_HEIGHT_M
    )


def in_zone(x, height, forward, valid):
    """Pixels with depth that are inside the play zone."""
    (x0, x1), (h0, h1), (f0, f1) = config.ZONE_X_M, config.ZONE_HEIGHT_M, config.ZONE_DEPTH_M
    return (
        valid
        & (x >= x0) & (x <= x1)
        & (height >= h0) & (height <= h1)
        & (forward >= f0) & (forward <= f1)
    )
