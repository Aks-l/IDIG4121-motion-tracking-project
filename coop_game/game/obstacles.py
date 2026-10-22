"""Obstacles scrolling in from the right, and the hit test against the object."""

import math
import random
from dataclasses import dataclass

import numpy as np
import pygame

from .. import config


@dataclass
class Obstacle:
    x: float
    y: float
    w: float
    h: float
    kind: str              # "block": on the ground, lift over it
                           # "beam": hangs from the top, stay under it
    hit: bool = False
    passed: bool = False

    def rect(self):
        return self.x, self.y, self.w, self.h

    def draw(self, surface):
        if self.hit:
            color = (250, 210, 80)
        elif self.kind == "block":
            color = (220, 90, 50)
        else:
            color = (140, 100, 70)

        rect = pygame.Rect(int(self.x), int(self.y), int(self.w), int(self.h))
        pygame.draw.rect(surface, color, rect, border_radius=8)
        pygame.draw.rect(surface, (60, 30, 20), rect, width=3, border_radius=8)


class ObstacleSpawner:
    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.timer = 2.5

    def update(self, dt, screen_width):
        self.timer -= dt
        if self.timer > 0:
            return []

        self.timer = self.rng.uniform(*config.SPAWN_GAP_S)
        x = screen_width + 10

        if self.rng.random() < 0.6:
            height = self.rng.uniform(90, 240)
            width = self.rng.uniform(60, 120)
            return [Obstacle(x, config.GROUND_Y - height, width, height, "block")]

        bottom = config.GROUND_Y - self.rng.uniform(250, 420)
        width = self.rng.uniform(80, 160)
        return [Obstacle(x, 0, width, bottom, "beam")]


def obb_overlaps_rect(center, half_extents, angle, rect):
    """Separating-axis test: rotated object box vs upright rectangle."""
    c, s = math.cos(angle), math.sin(angle)
    along, across = np.array([c, s]), np.array([-s, c])
    hx, hy = half_extents

    box = [
        center + sx * hx * along + sy * hy * across
        for sx in (-1, 1) for sy in (-1, 1)
    ]
    x, y, w, h = rect
    upright = [np.array(p) for p in ((x, y), (x + w, y), (x, y + h), (x + w, y + h))]

    for axis in (np.array([1.0, 0.0]), np.array([0.0, 1.0]), along, across):
        a = [p @ axis for p in box]
        b = [p @ axis for p in upright]
        if max(a) < min(b) or max(b) < min(a):
            return False
    return True
