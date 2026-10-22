"""Carryable objects: a data-driven spec, and one physics body that uses it.

To add an object, register a new ObjectSpec (optionally with its own draw
function). The physics and the game loop need no changes.

The object is a rigid bar: Player 1's hand holds its left end, Player 2's
the right end. Held, it springs toward the line between the hands (centre
= midpoint, tilt = angle of the line). Dropped, it falls under gravity,
bounces and settles on the ground as a real rigid body.
"""

import math
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pygame

from .. import config


@dataclass(frozen=True)
class ObjectSpec:
    name: str
    title: str                  # HUD: "Move the {title} together!"
    length: float               # px, end to end (the hands hold the ends)
    thickness: float            # px
    mass: float = 1.0           # heavier = follows the hands more slowly
    color: tuple = (90, 130, 200)
    # How it follows the hands: natural frequency (1/s) at mass 1, and
    # damping ratio (1 = no overshoot, lower = wobblier)
    responsiveness: float = 14.0
    damping_ratio: float = 0.8
    # Held while the hands are at most (1 + this) x length apart
    grip_tolerance: float = 0.4
    # Slips out when tilted more than this (degrees); None = never
    max_tilt_deg: Optional[float] = None
    restitution: float = 0.2    # bounce on the ground
    friction: float = 0.7
    draw: Optional[Callable] = None   # spec -> unrotated pygame.Surface


OBJECTS = {}


def register(spec):
    OBJECTS[spec.name] = spec
    return spec


def shade(color, factor):
    return tuple(max(0, min(255, int(c * factor))) for c in color)


def draw_box(spec):
    surface = pygame.Surface((int(spec.length), int(spec.thickness)), pygame.SRCALPHA)
    rect = surface.get_rect()
    pygame.draw.rect(surface, spec.color, rect, border_radius=6)
    pygame.draw.rect(surface, shade(spec.color, 0.6), rect, width=3, border_radius=6)
    return surface


def draw_couch(spec):
    w, h = int(spec.length), int(spec.thickness)
    surface = pygame.Surface((w, h), pygame.SRCALPHA)

    arm = int(w * 0.09)
    legs = max(4, h // 8)
    body = h - legs

    for x in (arm // 2, w - arm // 2 - 6):
        pygame.draw.rect(surface, (70, 50, 40), (x, body, 6, legs))

    # Backrest, two seat cushions, then the armrests on top
    pygame.draw.rect(
        surface, shade(spec.color, 0.8),
        (arm - 6, 0, w - 2 * arm + 12, int(body * 0.6)), border_radius=12,
    )
    seat_y = int(body * 0.45)
    cushion = (w - 2 * arm) / 2
    for i in range(2):
        pygame.draw.rect(
            surface, spec.color,
            (int(arm + i * cushion + 2), seat_y, int(cushion - 4), body - seat_y),
            border_radius=10,
        )
    for x in (0, w - arm):
        pygame.draw.rect(
            surface, shade(spec.color, 0.9),
            (x, int(body * 0.25), arm, body - int(body * 0.25)), border_radius=12,
        )
    return surface


def draw_plank(spec):
    surface = draw_box(spec)
    w, h = surface.get_size()
    for y in range(6, h - 4, 7):
        pygame.draw.line(surface, shade(spec.color, 0.8), (8, y), (w - 8, y), 1)
    return surface


def draw_aquarium(spec):
    w, h = int(spec.length), int(spec.thickness)
    surface = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(surface, (*spec.color, 170), (0, int(h * 0.2), w, int(h * 0.8)))
    pygame.draw.rect(surface, (220, 240, 255), (0, 0, w, h), width=4, border_radius=4)
    for x, y in ((0.3, 0.55), (0.65, 0.7)):
        pygame.draw.ellipse(surface, (255, 150, 40), (int(w * x), int(h * y), 26, 14))
    return surface


register(ObjectSpec(
    "couch", "couch", length=420, thickness=80, mass=3.0,
    color=(70, 120, 200), grip_tolerance=0.45, restitution=0.1,
    friction=0.9, draw=draw_couch,
))
register(ObjectSpec(
    "plank", "plank", length=380, thickness=26, mass=1.0,
    color=(190, 140, 80), responsiveness=18.0, damping_ratio=0.6,
    grip_tolerance=0.3, restitution=0.35, draw=draw_plank,
))
register(ObjectSpec(
    "aquarium", "aquarium", length=300, thickness=110, mass=2.5,
    color=(60, 150, 220), grip_tolerance=0.35, max_tilt_deg=25.0,
    restitution=0.05, draw=draw_aquarium,
))


def wrap_angle(angle):
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


class CarriedObject:
    def __init__(self, spec, position):
        self.spec = spec
        self.pos = np.array(position, dtype=float)
        self.vel = np.zeros(2)
        self.angle = 0.0             # radians, screen coordinates (y down)
        self.spin = 0.0              # radians/s
        self.held = False
        self.drop_reason = None
        self._grip_lost_for = 0.0
        self._target = None
        self.inertia = spec.mass * (spec.length ** 2 + spec.thickness ** 2) / 12.0
        self._image = (spec.draw or draw_box)(spec)

    @property
    def half_extents(self):
        return np.array([self.spec.length / 2.0, self.spec.thickness / 2.0])

    def _axes(self):
        c, s = math.cos(self.angle), math.sin(self.angle)
        return np.array([c, s]), np.array([-s, c])

    def ends(self):
        """(Player 1's end, Player 2's end) in screen px."""
        along, _ = self._axes()
        half = along * self.spec.length / 2.0
        return self.pos - half, self.pos + half

    def corners(self):
        along, across = self._axes()
        hx, hy = self.half_extents
        return [
            self.pos + sx * hx * along + sy * hy * across
            for sx in (-1, 1) for sy in (-1, 1)
        ]

    def update(self, p1, p2, dt):
        """Advance by dt with the two hand anchors (screen px or None)."""
        if self.held:
            self._follow(p1, p2, dt)
        elif p1 is not None and p2 is not None:
            self._try_grab(np.asarray(p1, float), np.asarray(p2, float))

        if not self.held:
            self._fall(dt)

    def _drop(self, reason):
        # Keeps its current velocity, so it flies off the way it was moving
        self.held = False
        self.drop_reason = reason
        self._target = None

    def _follow(self, p1, p2, dt):
        if p1 is None or p2 is None:
            # A hand flickered out: keep going toward the last target briefly
            self._grip_lost_for += dt
            if self._grip_lost_for > config.GRIP_GRACE_S or self._target is None:
                self._drop("Lost grip")
                return
        else:
            self._grip_lost_for = 0.0
            p1, p2 = np.asarray(p1, float), np.asarray(p2, float)
            span = p2 - p1

            if np.hypot(*span) > self.spec.length * (1.0 + self.spec.grip_tolerance):
                self._drop("Too far apart")
                return

            target_angle = math.atan2(span[1], span[0])
            tilt = abs(wrap_angle(target_angle))
            tilt = min(tilt, math.pi - tilt)
            if (
                self.spec.max_tilt_deg is not None
                and math.degrees(tilt) > self.spec.max_tilt_deg
            ):
                self._drop("Tilted too far")
                return

            self._target = ((p1 + p2) / 2.0, target_angle)

        # Damped spring toward the hands; heavier objects lag more
        target_pos, target_angle = self._target
        omega = self.spec.responsiveness / math.sqrt(self.spec.mass)
        zeta = self.spec.damping_ratio
        h = dt / config.PHYSICS_SUBSTEPS

        for _ in range(config.PHYSICS_SUBSTEPS):
            accel = omega ** 2 * (target_pos - self.pos) - 2 * zeta * omega * self.vel
            self.vel += accel * h
            self.pos += self.vel * h

            error = wrap_angle(target_angle - self.angle)
            spin_accel = omega ** 2 * error - 2 * zeta * omega * self.spin
            self.spin += spin_accel * h
            self.angle += self.spin * h

        # Even held, it can't go through the floor
        depth = max(c[1] for c in self.corners()) - config.GROUND_Y
        if depth > 0:
            self.pos[1] -= depth
            self.vel[1] = min(self.vel[1], 0.0)

    def _try_grab(self, p1, p2):
        reach = config.REGRAB_RADIUS_PX
        end_a, end_b = self.ends()

        if np.hypot(*(p1 - end_a)) < reach and np.hypot(*(p2 - end_b)) < reach:
            self.held = True
        elif np.hypot(*(p1 - end_b)) < reach and np.hypot(*(p2 - end_a)) < reach:
            # Picked up from the other side: turn it so P1 holds its left end
            self.angle += math.pi
            self.held = True

        if self.held:
            self.drop_reason = None
            self._grip_lost_for = 0.0

    def _fall(self, dt):
        h = dt / config.PHYSICS_SUBSTEPS
        for _ in range(config.PHYSICS_SUBSTEPS):
            self.vel[1] += config.GRAVITY * h
            self.pos += self.vel * h
            self.angle += self.spin * h
            self._ground_contact()

        # Settled: stop tiny jitters
        on_ground = max(c[1] for c in self.corners()) >= config.GROUND_Y - 1.0
        if on_ground and np.hypot(*self.vel) < 15.0 and abs(self.spin) < 0.1:
            self.vel[:] = 0.0
            self.spin = 0.0

    def _ground_contact(self):
        # Impulses at every corner below the floor (rigid body: bounce,
        # friction and the torque that tips it flat)
        corners = self.corners()
        depth = max(c[1] for c in corners) - config.GROUND_Y
        if depth <= 0:
            return

        normal = np.array([0.0, -1.0])
        tangent = np.array([1.0, 0.0])
        mass, inertia = self.spec.mass, self.inertia

        for corner in corners:
            if corner[1] < config.GROUND_Y:
                continue

            r = corner - self.pos
            velocity = self.vel + self.spin * np.array([-r[1], r[0]])
            approach = velocity @ normal
            if approach >= 0:
                continue

            # No bounce for slow contacts, or it never comes to rest
            bounce = self.spec.restitution if approach < -80.0 else 0.0
            rn = cross(r, normal)
            impulse = -(1 + bounce) * approach / (1 / mass + rn * rn / inertia)
            self.vel += impulse * normal / mass
            self.spin += rn * impulse / inertia

            velocity = self.vel + self.spin * np.array([-r[1], r[0]])
            rt = cross(r, tangent)
            slide = -(velocity @ tangent) / (1 / mass + rt * rt / inertia)
            limit = self.spec.friction * impulse
            slide = max(-limit, min(limit, slide))
            self.vel += slide * tangent / mass
            self.spin += rt * slide / inertia

        self.pos[1] -= depth

    def draw(self, surface):
        rotated = pygame.transform.rotate(self._image, -math.degrees(self.angle))
        surface.blit(rotated, rotated.get_rect(center=(int(self.pos[0]), int(self.pos[1]))))
