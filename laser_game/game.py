"""Game loop: silhouettes in, lasers + players + HUD on screen."""

import math
import random
import time

import numpy as np
import pygame

from . import config, settings
from .duel import COUNTDOWN, OVER, PLAYING, WAITING, LaserDuel
from .render import PLAYER_COLORS, Renderer
from .sources import KeyboardBodySource

TEXT = (235, 235, 245)
DIM_TEXT = (150, 150, 170)


class LaserGame:
    def __init__(self, source, spec, seed=None):
        pygame.init()
        flags = pygame.SCALED | (pygame.FULLSCREEN if config.FULLSCREEN else 0)
        self.screen = pygame.display.set_mode(config.SCREEN_SIZE, flags)
        pygame.display.set_caption("Laser Duel")

        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont(None, 32)
        self.big_font = pygame.font.SysFont(None, 96)

        self.source = source
        self.duel = LaserDuel(spec, random.Random(seed))
        self.renderer = Renderer(config.SCREEN_SIZE, spec, self.duel.lanes)
        self.show_debug = False
        # With --sim, S is Player 1's duck: the settings open with F1 only
        sim = isinstance(source, KeyboardBodySource)
        self.settings_keys = (pygame.K_F1,) if sim else (pygame.K_s, pygame.K_F1)
        self.menu = SettingsMenu(self.source, "F1" if sim else "S")

    def run(self):
        try:
            running = True
            while running:
                self.clock.tick(config.FPS)
                now = time.perf_counter()
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.KEYDOWN:
                        running = self._on_key(event.key, now)

                self.duel.update(now, self.source.poll())
                self.draw(now)
                pygame.display.flip()
        finally:
            self.source.close()
            pygame.quit()

    def _on_key(self, key, now):
        # The settings screen takes the keys while it is open; the game
        # keeps running behind it
        if self.menu.open:
            if key in self.settings_keys or key == pygame.K_ESCAPE:
                self.menu.hide()
            else:
                self.menu.on_key(key, now)
            return True
        if key in self.settings_keys:
            self.menu.show()
            return True

        if key == pygame.K_ESCAPE:
            return False
        if key == pygame.K_r:
            self.duel.reset()
        elif key == pygame.K_RETURN and self.duel.state in (WAITING, OVER):
            self.duel.start(now)
        elif key == pygame.K_b:
            self.source.request_background()
        elif key == pygame.K_TAB:
            self.show_debug = not self.show_debug
            self.source.set_debug(self.show_debug)
        elif key == pygame.K_f:
            pygame.display.toggle_fullscreen()
        else:
            self.source.on_key(key)
        return True

    # ----------------------------------------------------------- drawing

    def draw(self, now):
        self.renderer.draw(self.screen, self.duel, now)
        self._draw_hud(now)
        if self.show_debug:
            self._draw_debug()
        if self.menu.open:
            self.menu.draw(self.screen, now)

    def _draw_hud(self, now):
        duel = self.duel
        w = config.SCREEN_SIZE[0]

        for pid, x in ((1, 20), (2, w - 200)):
            self._player_panel(pid, x, now)

        if duel.state == PLAYING:
            self._centered(
                f"{duel.elapsed(now):5.1f} s    wave {duel.spawner.waves}", 34, self.font
            )

        message = self.source.status()
        if message:
            self._centered(message, 80, self.font)

        if duel.state == WAITING:
            self._waiting_text()
        elif duel.state == COUNTDOWN:
            left = max(1, math.ceil(duel.countdown_end - now))
            self._centered(str(left), 260, self.big_font, (255, 90, 110))
            self._centered("Stand tall, arms down: measuring you", 330, self.font)
        elif duel.state == OVER:
            self._result_text(now)

    def _player_panel(self, pid, x, now):
        duel = self.duel
        player = duel.players.get(pid)
        in_view = duel.body(pid) is not None

        if player is not None and player.out:
            color, line = (90, 90, 100), "OUT"
        elif player is not None:
            lives = "life" if player.lives == 1 else "lives"
            color, line = PLAYER_COLORS[pid], f"{player.lives} {lives}"
        elif in_view:
            color, line = PLAYER_COLORS[pid], "ready"
        else:
            color, line = (70, 70, 80), "not in view"

        pygame.draw.rect(self.screen, color, (x, 16, 180, 40), border_radius=8)
        label = self.font.render(f"P{pid}  {line}", True, (255, 255, 255))
        self.screen.blit(label, (x + 12, 25))

        if player is not None and duel.state in (PLAYING, OVER):
            info = f"{player.height:.2f} m   {duel.survived(player, now):.1f} s"
            image = self.font.render(info, True, DIM_TEXT)
            self.screen.blit(image, (x + 4, 62))

    def _waiting_text(self):
        present = self.duel.present()
        if len(present) == 2:
            self._centered("Get ready...", 260, self.font)
            return

        self._centered("LASER DUEL", 230, self.big_font, (255, 90, 110))
        self._centered("Player 1: left lane    Player 2: right lane", 300, self.font)
        self._centered("Jump, duck and step aside. First to touch a laser loses!", 335, self.font, DIM_TEXT)
        key = "F1" if isinstance(self.source, KeyboardBodySource) else "S"
        self._centered(f"{key}: settings", config.SCREEN_SIZE[1] - 30, self.font, DIM_TEXT)
        if present:
            self._centered("Press Enter to play solo", 380, self.font, DIM_TEXT)

    def _result_text(self, now):
        duel = self.duel
        if len(duel.players) == 1:
            player = next(iter(duel.players.values()))
            title = f"{duel.survived(player, now):.1f} seconds!"
            detail = f"Player {player.pid} {player.out_reason}"
        elif duel.winner is None:
            title, detail = "Draw!", "Both out at the same time"
        else:
            loser = next(p for p in duel.players.values() if p.pid != duel.winner)
            title = f"Player {duel.winner} wins!"
            detail = f"Player {loser.pid} {loser.out_reason}"

        color = PLAYER_COLORS.get(duel.winner, (255, 90, 110))
        self._centered(title, 250, self.big_font, color)
        self._centered(detail, 320, self.font)
        self._centered("Enter: play again", 360, self.font, DIM_TEXT)

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
        self.screen.blit(surface, (x, 100))

    def _centered(self, text, y, font, color=TEXT):
        # Dark shadow: readable over lasers and silhouettes
        centre = (config.SCREEN_SIZE[0] // 2, y)
        shadow = font.render(text, True, (0, 0, 0))
        self.screen.blit(shadow, shadow.get_rect(center=(centre[0] + 2, centre[1] + 2)))
        image = font.render(text, True, color)
        self.screen.blit(image, image.get_rect(center=centre))


class SettingsMenu:
    """S: change settings while playing. Up / down choose, left / right
    change (hold to repeat), Enter saves to settings.json, D goes back to
    the default from config.py, S or Esc closes."""

    WIDTH = 600
    ROW = 23
    NOTE_S = 3.0

    def __init__(self, source, close_key):
        self.source = source
        self.close_key = close_key
        self.open = False
        self.selected = 0
        self.note = None          # (text, time)
        self.title_font = pygame.font.SysFont(None, 40)
        self.font = pygame.font.SysFont(None, 26)
        self.small = pygame.font.SysFont(None, 22)

    def show(self):
        self.open = True
        pygame.key.set_repeat(300, 60)

    def hide(self):
        self.open = False
        pygame.key.set_repeat()

    def on_key(self, key, now):
        setting = settings.ALL[self.selected]
        if key == pygame.K_UP:
            self.selected = (self.selected - 1) % len(settings.ALL)
        elif key == pygame.K_DOWN:
            self.selected = (self.selected + 1) % len(settings.ALL)
        elif key == pygame.K_LEFT:
            setting.nudge(-1)
        elif key == pygame.K_RIGHT:
            setting.nudge(+1)
        elif key == pygame.K_d:
            settings.reset(setting)
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            try:
                self.note = (settings.save(), now)
            except OSError as error:
                self.note = (f"Not saved: {error}", now)

    def draw(self, screen, now):
        w, h = config.SCREEN_SIZE
        x0, y0 = (w - self.WIDTH) // 2, 24
        panel = pygame.Surface((self.WIDTH, h - 2 * y0), pygame.SRCALPHA)
        panel.fill((8, 10, 24, 242))
        screen.blit(panel, (x0, y0))
        pygame.draw.rect(screen, (90, 110, 170), (x0, y0, self.WIDTH, h - 2 * y0), 2, border_radius=6)

        y = y0 + 12
        screen.blit(self.title_font.render("Settings", True, TEXT), (x0 + 20, y))
        camera = self.source.camera_text()
        if camera:
            image = self.small.render(camera, True, DIM_TEXT)
            screen.blit(image, (x0 + self.WIDTH - 20 - image.get_width(), y + 10))
        y += 42

        index = 0
        for title, section in settings.SECTIONS:
            screen.blit(self.small.render(title.upper(), True, (120, 150, 220)), (x0 + 20, y + 4))
            y += self.ROW + 2
            for setting in section:
                chosen = index == self.selected
                if chosen:
                    pygame.draw.rect(screen, (40, 60, 120), (x0 + 12, y - 2, self.WIDTH - 24, self.ROW), border_radius=4)
                color = TEXT if chosen else (200, 200, 215)
                screen.blit(self.font.render(setting.label, True, color), (x0 + 28, y))

                value = setting.text()
                if setting.get() != settings.DEFAULTS[setting]:
                    value += " *"
                value = f"< {value} >" if chosen else value
                image = self.font.render(value, True, (255, 220, 120) if chosen else color)
                screen.blit(image, (x0 + self.WIDTH - 28 - image.get_width(), y))
                y += self.ROW
                index += 1

        hints = f"Up/Down choose   Left/Right change   Enter save   D default   {self.close_key} close"
        lines = [hints, "* = changed from config.py"]
        if self.note and now - self.note[1] < self.NOTE_S:
            lines = [self.note[0]] + lines
        for i, text in enumerate(reversed(lines)):
            image = self.small.render(text, True, DIM_TEXT if i < 2 else (140, 230, 140))
            screen.blit(image, (x0 + 20, h - y0 - 26 - 22 * i))
