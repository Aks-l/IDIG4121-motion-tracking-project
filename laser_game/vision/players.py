"""Splitting the foreground into Player 1 / Player 2.

Images here are in screen orientation (see config.MIRROR): Player 1 is on
the left, Player 2 on the right.
"""

import cv2
import numpy as np

from .. import config

CLOSE_KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
OPEN_KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))


def clean_mask(foreground):
    mask = foreground.astype(np.uint8) * 255
    # Close before open: opening first eats every pixel next to a depth hole
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, CLOSE_KERNEL)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, OPEN_KERNEL)


def find_split(mask, previous=None, centre=None):
    """Column dividing the players: the emptiest column near the middle.

    centre: the column straight ahead of the camera (default: the middle).
    """
    width = mask.shape[1]
    columns = (mask > 0).sum(axis=0).astype(np.float32)
    columns = np.convolve(columns, np.ones(9) / 9.0, mode="same")

    low, high = (int(width * f) for f in config.SPLIT_SEARCH)
    cost = columns[low:high].copy()
    candidates = np.arange(low, high)

    # Among equally empty columns, take the one nearest straight ahead.
    # Without this the first empty column from the left wins, and with
    # nobody at the far left the divider sticks to the edge of the search
    # band, putting both players on Player 2's side
    if centre is None:
        centre = (width - 1) / 2
    cost += config.SPLIT_CENTRE_PULL * np.abs(candidates - centre)

    # Staying put is cheaper than moving, so the divider doesn't jump
    if previous is not None:
        cost += config.SPLIT_STICKINESS * np.abs(candidates - previous)

    return int(low + np.argmin(cost))


def largest_region(mask):
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask, connectivity=8
    )
    if count < 2:
        return None

    best = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    if stats[best, cv2.CC_STAT_AREA] < config.MIN_PLAYER_AREA_PX:
        return None
    return labels == best


def split_players(mask, split):
    """{1: left player's pixels, 2: right player's}, None if nobody there."""
    # Cut at the divider first, so two players touching still split
    left = mask.copy()
    left[:, split:] = 0
    right = mask.copy()
    right[:, :split] = 0
    return {1: largest_region(left), 2: largest_region(right)}


def refine_player(player, valid, forward):
    """Strip what isn't the player: (cleaner mask, their distance in m),
    or None if nothing is left.

    The distance is the median of how far ahead of the camera their pixels
    are: the plane the player stands in.
    """
    distances = forward[player & valid]
    if not distances.size:
        return None
    distance = float(np.median(distances))

    # Pixels well in front of or behind the player are not the player:
    # "flying pixels" smeared between their edge and the wall, the floor
    # in front of their feet, furniture touching them in the image
    stray = valid & (np.abs(forward - distance) > config.PLAYER_DEPTH_BAND_M)
    kept = (player & ~stray).astype(np.uint8)

    # The D435 grows near objects a little at their edges: shave it off
    if config.EDGE_TRIM_PX > 0:
        size = 2 * config.EDGE_TRIM_PX + 1
        kept = cv2.erode(kept, np.ones((size, size), np.uint8))

    region = largest_region(kept)
    return None if region is None else (region, distance)
