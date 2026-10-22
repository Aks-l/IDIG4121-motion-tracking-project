"""Splitting the foreground into Player 1 / Player 2 and finding their anchors.

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


def find_split(mask, previous=None):
    """Column dividing the players: the emptiest column near the middle."""
    width = mask.shape[1]
    columns = (mask > 0).sum(axis=0).astype(np.float32)
    columns = np.convolve(columns, np.ones(9) / 9.0, mode="same")

    low, high = (int(width * f) for f in config.SPLIT_SEARCH)
    cost = columns[low:high].copy()

    # Staying put is cheaper than moving, so the divider doesn't jump
    if previous is not None:
        cost += config.SPLIT_STICKINESS * np.abs(np.arange(low, high) - previous)

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
    # Cut at the divider first, so two players touching hands still split
    left = mask.copy()
    left[:, split:] = 0
    right = mask.copy()
    right[:, :split] = 0
    return {1: largest_region(left), 2: largest_region(right)}


def _upper_body(player):
    # Hands are never in the lowest part of the body (legs, feet)
    rows = np.flatnonzero(player.any(axis=1))
    top, bottom = rows[0], rows[-1]
    cutoff = int(top + (1.0 - config.IGNORE_LOWER_FRACTION) * (bottom - top))

    upper = player.copy()
    upper[cutoff + 1:] = False
    return upper


def _centre_of_largest(candidates, depth):
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(
        candidates.astype(np.uint8), connectivity=8
    )
    if count < 2:
        return None

    best = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    region = labels == best
    distances = depth[region & (depth > 0)]
    if not distances.size:
        return None

    u, v = centroids[best]
    return float(u), float(v), float(np.median(distances))


def nearest_anchor(player, depth):
    """The player's surface closest to the camera (a hand held toward it)."""
    region = _upper_body(player) & (depth > 0)
    if not region.any():
        return None

    # A low percentile, not the minimum: single noisy pixels can't win
    nearest = np.percentile(depth[region], config.NEAREST_PERCENTILE)
    hand = region & (depth <= nearest + config.HAND_BAND_MM)
    return _centre_of_largest(hand, depth)


def reach_anchor(player, depth, toward_right):
    """The player's point reaching farthest toward the other player."""
    region = _upper_body(player) & (depth > 0)
    if not region.any():
        return None

    xs = np.nonzero(region)[1]
    columns = np.arange(region.shape[1])[None, :]

    if toward_right:
        edge = np.percentile(xs, 99)
        band = columns >= edge - config.REACH_BAND_PX
    else:
        edge = np.percentile(xs, 1)
        band = columns <= edge + config.REACH_BAND_PX

    return _centre_of_largest(region & band, depth)


def find_anchor(player, depth, player_id):
    """(u, v, depth_mm) of the player's anchor hand, or None."""
    if config.ANCHOR_MODE == "reach":
        # Player 1 (left) reaches right toward Player 2, and vice versa
        return reach_anchor(player, depth, toward_right=player_id == 1)
    return nearest_anchor(player, depth)
