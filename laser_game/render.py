"""The 3D look, faked in 2D: a perspective corridor with lasers flying out of
the vanishing point toward the players' plane at the front of the screen.

Depth is metres behind the players' plane. At depth 0 a point (x, height)
lands exactly where the players see themselves (the screen is their mirror);
deeper points shrink toward the vanishing point at eye height.

Everything that glows is drawn on one black layer that is then added onto
the screen (BLEND_ADD), so overlapping light adds up like real light.
"""

import numpy as np
import pygame

from . import config
from .duel import PLAYING
from .vision.bodies import FINE

PLAYER_COLORS = {1: (60, 140, 255), 2: (60, 210, 100)}
LASER_COLOR = (255, 40, 70)
LASER_CORE = (255, 215, 225)
HIT_COLOR = (255, 225, 110)
CORRIDOR_COLOR = (40, 110, 170)
OUT_COLOR = (110, 110, 120)

CORRIDOR_HEIGHT_M = 2.7
RING_SPACING_M = 3.0
RING_SPEED_M_S = 6.0
HIT_FLASH_S = 0.6


def scaled(color, factor):
    return tuple(max(0, min(255, int(c * factor))) for c in color)


class View:
    def __init__(self, size, spec):
        self.size = size
        self.spec = spec
        self.floor_y = size[1] - config.FLOOR_MARGIN_PX
        h0, h1 = spec.height_range
        self.scale = self.floor_y / (h1 - h0)          # px per metre at depth 0
        self.cx = size[0] / 2
        self.horizon_y = self.floor_y - (config.EYE_HEIGHT_M - h0) * self.scale
        self.corridor_x = max(abs(x) for x in spec.x_range) + 0.4

    def factor(self, depth):
        """Screen px per metre at this depth."""
        z = max(config.VIEW_DISTANCE_M + depth, 0.1)
        return self.scale * config.VIEW_DISTANCE_M / z

    def project(self, x, height, depth=0.0):
        k = self.factor(depth)
        return self.cx + x * k, self.horizon_y + (config.EYE_HEIGHT_M - height) * k


class Renderer:
    def __init__(self, size, spec, lanes):
        self.view = View(size, spec)
        self.spec = spec
        self.lanes = lanes
        self.layer = pygame.Surface(size)
        self.backdrop = self._make_backdrop(size)
        self._silhouettes = {}     # pid -> (key, surface)
        self._pictures = {}        # pid -> (frame time, surface, topleft)

    # ----------------------------------------------------------- scenery

    def _make_backdrop(self, size):
        view = self.view
        w, h = size
        backdrop = pygame.Surface(size)

        horizon = int(view.horizon_y)
        for y in range(h):
            if y < horizon:
                t = y / max(horizon, 1)
                color = (int(6 + 10 * t), int(8 + 14 * t), int(22 + 40 * t))
            else:
                t = (y - horizon) / max(h - horizon, 1)
                color = (int(14 - 8 * t), int(18 - 10 * t), int(50 - 30 * t))
            pygame.draw.line(backdrop, color, (0, y), (w, y))

        far = config.LASER_START_DEPTH_M

        # Each lane's floor, tinted in its player's colour
        for pid, (x0, x1) in self.lanes.items():
            quad = [
                view.project(x0, 0, 0), view.project(x1, 0, 0),
                view.project(x1, 0, far), view.project(x0, 0, far),
            ]
            pygame.draw.polygon(backdrop, scaled(PLAYER_COLORS[pid], 0.12), quad)

        # Floor lines and the corridor's edges, all running into the distance
        dim = scaled(CORRIDOR_COLOR, 0.45)
        x = -view.corridor_x
        while x <= view.corridor_x + 1e-6:
            pygame.draw.line(backdrop, dim, view.project(x, 0, 0), view.project(x, 0, far), 1)
            x += 0.5
        for cx in (-view.corridor_x, view.corridor_x):
            for ch in (0.0, CORRIDOR_HEIGHT_M):
                pygame.draw.line(
                    backdrop, CORRIDOR_COLOR,
                    view.project(cx, ch, 0), view.project(cx, ch, far), 2,
                )

        split = config.LANE_SPLIT_X_M
        pygame.draw.line(
            backdrop, (200, 200, 230),
            view.project(split, 0, 0), view.project(split, 0, far), 3,
        )
        return backdrop

    def _draw_rings(self, layer, now):
        # Corridor frames rushing toward the players: the sense of speed
        view = self.view
        offset = (now * RING_SPEED_M_S) % RING_SPACING_M
        depth = RING_SPACING_M - offset
        while depth < config.LASER_START_DEPTH_M:
            fade = 1.0 - depth / config.LASER_START_DEPTH_M
            corners = [
                view.project(-view.corridor_x, 0, depth),
                view.project(view.corridor_x, 0, depth),
                view.project(view.corridor_x, CORRIDOR_HEIGHT_M, depth),
                view.project(-view.corridor_x, CORRIDOR_HEIGHT_M, depth),
            ]
            pygame.draw.lines(layer, scaled(CORRIDOR_COLOR, 0.8 * fade), True, corners, 2)
            depth += RING_SPACING_M

    # ------------------------------------------------------------- frame

    def draw(self, screen, duel, now):
        screen.blit(self.backdrop, (0, 0))
        # The real players under the glow: their silhouettes light them up
        self._draw_pictures(screen, duel)

        layer = self.layer
        layer.fill((0, 0, 0))
        self._draw_rings(layer, now)

        # Painter's order: far lasers, the players, then lasers at or past them
        lasers = sorted(duel.lasers, key=lambda laser: -laser.depth(now))
        if duel.state == PLAYING:
            for laser in lasers:
                if laser.result is None:
                    self._draw_preview(layer, laser, now)
        for laser in lasers:
            if laser.depth(now) > 0.3:
                self._draw_laser(layer, laser, now)

        self._draw_silhouettes(layer, duel, now)

        for laser in lasers:
            if laser.depth(now) <= 0.3:
                self._draw_laser(layer, laser, now)
            if laser.result == "hit":
                self._draw_spark(layer, laser, now)

        screen.blit(layer, (0, 0), special_flags=pygame.BLEND_ADD)

    def _draw_laser(self, layer, laser, now):
        view = self.view
        depth = laser.depth(now)
        a = view.project(*laser.start, depth)
        b = view.project(*laser.end, depth)
        width = config.LASER_DRAW_WIDTH_M * view.factor(depth)

        if depth >= 0:
            # Dimmer far away, full brightness on arrival
            fade = 1.0 - 0.6 * depth / config.LASER_START_DEPTH_M
        else:
            fade = max(0.0, 1.0 + depth / config.LASER_PAST_DEPTH_M)
        if fade <= 0:
            return

        color = HIT_COLOR if laser.result == "hit" else LASER_COLOR
        for spread, brightness in ((3.5, 0.16), (1.8, 0.45), (1.0, 1.0)):
            pygame.draw.line(
                layer, scaled(color, brightness * fade), a, b,
                max(1, round(width * spread)),
            )
        pygame.draw.line(layer, scaled(LASER_CORE, fade), a, b, max(1, round(width * 0.35)))

    def _draw_preview(self, layer, laser, now):
        # Where it will be when it arrives, brighter as it gets closer
        progress = 1.0 - max(laser.depth(now), 0.0) / config.LASER_START_DEPTH_M
        to_go = laser.arrive - now
        blink = 1.0 if to_go > 0.5 or int(now * 10) % 2 else 0.5
        a = self.view.project(*laser.start, 0)
        b = self.view.project(*laser.end, 0)
        pygame.draw.line(layer, scaled(LASER_COLOR, (0.1 + 0.3 * progress) * blink), a, b, 3)

    def _draw_spark(self, layer, laser, now):
        if laser.hit_at is None:
            return
        age = now - laser.arrive
        if not 0 <= age < HIT_FLASH_S:
            return
        t = age / HIT_FLASH_S
        centre = self.view.project(*laser.hit_at, 0)
        for radius, brightness in ((20 + 120 * t, 0.5), (10 + 60 * t, 1.0)):
            pygame.draw.circle(layer, scaled(HIT_COLOR, brightness * (1 - t)), centre, radius, 4)

    # ------------------------------------------------------- silhouettes

    def _draw_pictures(self, screen, duel):
        if not config.SHOW_REAL_PLAYER or not duel.frames or not duel.frames[-1].pictures:
            return
        frame = duel.frames[-1]
        view = self.view
        cell = self.spec.cell / FINE

        for pid in (1, 2):
            picture = frame.pictures.get(pid)
            if picture is None:
                continue

            cached = self._pictures.get(pid)
            if cached is None or cached[0] != frame.time:
                h, w = picture.rgba.shape[:2]
                surface = pygame.image.frombuffer(picture.rgba, (w, h), "RGBA")
                size = (max(1, round(w * cell * view.scale)), max(1, round(h * cell * view.scale)))
                topleft = view.project(
                    self.spec.x_range[0] + picture.col * cell,
                    self.spec.height_range[1] - picture.row * cell,
                )
                cached = (frame.time, pygame.transform.smoothscale(surface, size), topleft)
                self._pictures[pid] = cached
            screen.blit(cached[1], cached[2])

    def _draw_silhouettes(self, layer, duel, now):
        if not duel.frames:
            return
        frame = duel.frames[-1]
        view = self.view
        x0, h1 = self.spec.x_range[0], self.spec.height_range[1]
        rows, cols = self.spec.shape
        size = (round(cols * self.spec.cell * view.scale), round(rows * self.spec.cell * view.scale))
        topleft = view.project(x0, h1, 0)

        for pid in (1, 2):
            grid = frame.bodies.get(pid)
            if grid is None or not grid.any():
                continue

            fill, edge = self._body_colors(duel, pid, now)
            key = (frame.time, fill, edge)
            cached = self._silhouettes.get(pid)
            if cached is None or cached[0] != key:
                cached = (key, silhouette_surface(grid, fill, edge, size))
                self._silhouettes[pid] = cached
            layer.blit(cached[1], topleft, special_flags=pygame.BLEND_ADD)

    def _body_colors(self, duel, pid, now):
        player = duel.players.get(pid)
        if player is not None and player.out:
            base = OUT_COLOR
        elif player is not None and now - player.hit_at < HIT_FLASH_S and int(now * 12) % 2:
            base = (255, 60, 60)
        else:
            base = PLAYER_COLORS[pid]
        return scaled(base, 0.35), scaled(base, 1.2)


def silhouette_surface(grid, fill, edge, size):
    """A body grid as a soft glowing shape: dim inside, bright outline."""
    inner = grid.copy()
    inner[1:] &= grid[:-1]
    inner[:-1] &= grid[1:]
    inner[:, 1:] &= grid[:, :-1]
    inner[:, :-1] &= grid[:, 1:]

    rgb = np.zeros(grid.shape + (3,), dtype=np.uint8)
    rgb[grid] = edge
    rgb[inner] = fill

    surface = pygame.surfarray.make_surface(np.ascontiguousarray(rgb.transpose(1, 0, 2)))
    return pygame.transform.smoothscale(surface, size)
