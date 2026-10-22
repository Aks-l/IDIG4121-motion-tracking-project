"""Game loop: anchors in, carried object + obstacles + HUD on screen."""

import math
import random

import numpy as np
import pygame

from .. import config
from .objects import OBJECTS, CarriedObject
from .obstacles import ObstacleSpawner, obb_overlaps_rect

PLAYER_COLORS = {1: (60, 140, 255), 2: (60, 200, 90)}


class Game:
    def __init__(self, source, object_name="couch", seed=None):
        pygame.init()
        flags = pygame.SCALED | (pygame.FULLSCREEN if config.FULLSCREEN else 0)
        self.screen = pygame.display.set_mode(config.SCREEN_SIZE, flags)
        pygame.display.set_caption("Co-op Carry")

        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont(None, 32)
        self.big_font = pygame.font.SysFont(None, 64)

        self.source = source
        self.object_names = list(OBJECTS)
        self.object_name = object_name
        self.rng = random.Random(seed)
        self.backdrop = self._make_backdrop()
        self.show_debug = False
        self.time = 0.0
        self.reset()

    def reset(self):
        spec = OBJECTS[self.object_name]
        start = (config.SCREEN_SIZE[0] / 2, config.GROUND_Y - spec.thickness / 2)
        self.obj = CarriedObject(spec, start)
        self.obstacles = []
        self.spawner = ObstacleSpawner(self.rng)
        self.score = 0
        self.lives = config.LIVES
        self.speed = config.SCROLL_SPEED
        self.hit_cooldown = 0.0
        self.game_over = False
        self.anchors = {1: None, 2: None}

    # ------------------------------------------------------------- logic

    def step(self, dt, anchors):
        """Advance the game by dt seconds; anchors in screen px (or None)."""
        self.time += dt
        self.anchors = anchors
        if self.game_over:
            return

        self.obj.update(anchors.get(1), anchors.get(2), dt)
        self.hit_cooldown = max(0.0, self.hit_cooldown - dt)

        self.obstacles += self.spawner.update(dt, config.SCREEN_SIZE[0])
        left_end = min(end[0] for end in self.obj.ends())

        for obstacle in self.obstacles:
            obstacle.x -= self.speed * dt

            if (
                not obstacle.hit
                and self.hit_cooldown == 0.0
                and obb_overlaps_rect(
                    self.obj.pos, self.obj.half_extents, self.obj.angle,
                    obstacle.rect(),
                )
            ):
                obstacle.hit = True
                self.lives -= 1
                self.hit_cooldown = config.HIT_COOLDOWN_S
                self.game_over = self.lives <= 0

            if not obstacle.passed and obstacle.x + obstacle.w < left_end:
                obstacle.passed = True
                if not obstacle.hit:
                    self.score += 1
                    self.speed += config.SCROLL_SPEEDUP

        self.obstacles = [o for o in self.obstacles if o.x + o.w > -50]

    def run(self):
        try:
            running = True
            while running:
                dt = min(self.clock.tick(config.FPS) / 1000.0, 0.05)
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.KEYDOWN:
                        running = self._on_key(event.key)

                self.step(dt, self.source.poll())
                self.draw()
                pygame.display.flip()
        finally:
            self.source.close()
            pygame.quit()

    def _on_key(self, key):
        if key == pygame.K_ESCAPE:
            return False
        if key == pygame.K_r:
            self.reset()
        elif key == pygame.K_b:
            self.source.request_background()
        elif key == pygame.K_c:
            self.source.calibrate()
        elif key == pygame.K_TAB:
            self.show_debug = not self.show_debug
            self.source.set_debug(self.show_debug)
        elif key == pygame.K_f:
            pygame.display.toggle_fullscreen()
        elif pygame.K_1 <= key <= pygame.K_9:
            index = key - pygame.K_1
            if index < len(self.object_names):
                self.object_name = self.object_names[index]
                self.reset()
        return True

    # ----------------------------------------------------------- drawing

    def _make_backdrop(self):
        w, h = config.SCREEN_SIZE
        backdrop = pygame.Surface((w, h))

        for y in range(config.GROUND_Y):
            t = y / config.GROUND_Y
            color = (int(120 + 90 * t), int(180 + 50 * t), int(240 - 10 * t))
            pygame.draw.line(backdrop, color, (0, y), (w, y))

        hills = [(0, config.GROUND_Y)]
        for x in range(0, w + 80, 80):
            hills.append((x, config.GROUND_Y - 120 - 50 * math.sin(x / 170.0)))
        hills.append((w, config.GROUND_Y))
        pygame.draw.polygon(backdrop, (120, 160, 120), hills)

        pygame.draw.rect(backdrop, (190, 160, 110), (0, config.GROUND_Y, w, h))
        pygame.draw.line(backdrop, (120, 90, 60), (0, config.GROUND_Y), (w, config.GROUND_Y), 4)
        return backdrop

    def draw(self):
        self.screen.blit(self.backdrop, (0, 0))
        for obstacle in self.obstacles:
            obstacle.draw(self.screen)

        self._draw_grips()
        self.obj.draw(self.screen)
        self._draw_anchors()
        self._draw_hud()

        if self.show_debug:
            self._draw_debug()

    def _draw_grips(self):
        ends = self.obj.ends()

        if self.obj.held:
            for pid, end in zip((1, 2), ends):
                anchor = self.anchors.get(pid)
                if anchor is not None:
                    pygame.draw.line(
                        self.screen, PLAYER_COLORS[pid],
                        _ints(anchor), _ints(end), 3,
                    )
            return

        # Dropped: pulsing rings show where to grab it again
        pulse = 0.5 + 0.5 * math.sin(self.time * 6.0)
        radius = int(config.REGRAB_RADIUS_PX * (0.6 + 0.4 * pulse))
        for pid, end in zip((1, 2), ends):
            pygame.draw.circle(self.screen, PLAYER_COLORS[pid], _ints(end), radius, 2)

    def _draw_anchors(self):
        for pid, anchor in self.anchors.items():
            if anchor is None:
                continue
            pygame.draw.circle(self.screen, (255, 255, 255), _ints(anchor), 16)
            pygame.draw.circle(self.screen, PLAYER_COLORS[pid], _ints(anchor), 16, 4)
            pygame.draw.circle(self.screen, PLAYER_COLORS[pid], _ints(anchor), 6)

    def _draw_hud(self):
        w = config.SCREEN_SIZE[0]

        for pid, x in ((1, 20), (2, w - 140)):
            connected = self.anchors.get(pid) is not None
            color = PLAYER_COLORS[pid] if connected else (150, 150, 150)
            pygame.draw.rect(self.screen, color, (x, 16, 120, 34), border_radius=8)
            label = self.font.render(f"P{pid}", True, (255, 255, 255))
            self.screen.blit(label, (x + 10, 22))

        title = f"Move the {self.obj.spec.title} together!"
        self._centered(title, 34, self.font)
        self._centered(f"Score {self.score}    Lives {self.lives}", 70, self.font)

        message = self.source.status()
        if message is None and not self.obj.held and not self.game_over:
            reason = f"{self.obj.drop_reason}! " if self.obj.drop_reason else ""
            message = f"{reason}Put your hands on both ends to pick it up"
        if message:
            self._centered(message, 120, self.font, (40, 40, 40))

        if self.game_over:
            self._centered("Game over", 300, self.big_font, (180, 30, 30))
            self._centered(f"Score {self.score}  -  press R to play again", 360, self.font)

    def _draw_debug(self):
        image = self.source.debug_image()
        if image is None:
            return

        rgb = np.ascontiguousarray(image[..., ::-1].transpose(1, 0, 2))
        surface = pygame.surfarray.make_surface(rgb)
        surface = pygame.transform.smoothscale(
            surface, (360, int(360 * image.shape[0] / image.shape[1]))
        )
        x = config.SCREEN_SIZE[0] - surface.get_width() - 20
        self.screen.blit(surface, (x, 160))

    def _centered(self, text, y, font, color=(20, 20, 20)):
        image = font.render(text, True, color)
        self.screen.blit(image, image.get_rect(center=(config.SCREEN_SIZE[0] // 2, y)))


def _ints(point):
    return int(point[0]), int(point[1])
