"""Lasers flying at the players, and the waves that send them.

A wave sends the same pattern down every playing lane at once, fitted to
that lane's player (beam heights are fractions of their height, aimed beams
aim at where they stand), so neither player gets an easier laser.

Positions are (x, height) in metres on the players' plane: where the laser
will be when it reaches them.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np

from . import config


@dataclass
class Target:
    """What a wave needs to know about one lane's player."""
    lane: tuple              # x range of the lane (m)
    height: float            # standing height (m)
    centre_x: float          # where they stand right now (m)


@dataclass
class Laser:
    pid: int                 # whose lane it flies down
    kind: str                # "low", "high", "aimed" or "diagonal"
    start: np.ndarray        # (x, height) of one end
    end: np.ndarray
    arrive: float            # time it reaches the players' plane
    travel: float            # seconds from appearing to arriving
    cells: np.ndarray        # body-grid cells it burns on arrival
    result: Optional[str] = None     # "hit" or "dodged" once decided
    hit_frames: int = 0
    hit_at: Optional[np.ndarray] = None   # (x, height) where it touched

    def depth(self, now):
        """Metres behind the players' plane; negative once past them."""
        return config.LASER_START_DEPTH_M * (self.arrive - now) / self.travel

    @property
    def window(self):
        """Camera frame times that decide whether it hit."""
        middle = self.arrive + config.DISPLAY_LAG_S
        half = config.HIT_WINDOW_S / 2
        return middle - half, middle + half

    def gone(self, now):
        return self.result is not None and self.depth(now) < -config.LASER_PAST_DEPTH_M


def segment_cells(spec, start, end, thickness):
    """Grid cells whose centre is within thickness / 2 of the segment."""
    xs, heights = spec.centres
    direction = end - start
    length_sq = max(float(direction @ direction), 1e-9)

    # Closest point of the segment to every cell centre
    t = ((xs - start[0]) * direction[0] + (heights - start[1]) * direction[1]) / length_sq
    t = np.clip(t, 0.0, 1.0)
    dx = xs - (start[0] + t * direction[0])
    dh = heights - (start[1] + t * direction[1])
    return dx * dx + dh * dh <= (thickness / 2) ** 2


def laser_shape(kind, target, top, rising):
    """(start, end) of a laser of this kind, fitted to one player."""
    left = target.lane[0] + config.LANE_INSET_M
    right = target.lane[1] - config.LANE_INSET_M
    height = target.height

    if kind == "low":
        h = config.LOW_BEAM * height
        return (left, h), (right, h)
    if kind == "high":
        h = config.HIGH_BEAM * height
        return (left, h), (right, h)
    if kind == "aimed":
        # Floor to ceiling where they stand: step aside
        x = min(max(target.centre_x, left + 0.15), right - 0.15)
        return (x, 0.0), (x, top)

    low, high = (f * height for f in config.DIAGONAL_BEAM)
    if rising:
        return (left, low), (right, high)
    return (left, high), (right, low)


class WaveSpawner:
    def __init__(self, spec, rng):
        self.spec = spec
        self.rng = rng
        self.waves = 0
        self.next_at = None

    def start(self, now):
        self.waves = 0
        self.next_at = now + config.FIRST_WAVE_DELAY_S

    def update(self, now, targets):
        """New lasers to launch: targets is {pid: Target} of who is still in."""
        if self.next_at is None or now < self.next_at or not targets:
            return []

        travel = max(
            config.TRAVEL_MIN_S,
            config.TRAVEL_START_S - config.TRAVEL_SPEEDUP_S * self.waves,
        )
        gap = max(
            config.SPAWN_GAP_MIN_S,
            config.SPAWN_GAP_START_S - config.SPAWN_SPEEDUP_S * self.waves,
        )
        kind = self._pick_kind()
        rising = self.rng.random() < 0.5
        self.waves += 1
        self.next_at = now + gap

        lasers = []
        for pid, target in sorted(targets.items()):
            start, end = (
                np.array(p, dtype=float)
                for p in laser_shape(kind, target, self.spec.height_range[1], rising)
            )
            cells = segment_cells(self.spec, start, end, config.LASER_HIT_THICKNESS_M)
            lasers.append(Laser(pid, kind, start, end, now + travel, travel, cells))
        return lasers

    def _pick_kind(self):
        kinds = [
            kind for kind in config.KIND_WEIGHTS
            if kind != "diagonal" or self.waves >= config.DIAGONAL_FROM_WAVE
        ]
        weights = [config.KIND_WEIGHTS[kind] for kind in kinds]
        return self.rng.choices(kinds, weights)[0]
