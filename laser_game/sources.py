"""Where the game gets the players' silhouettes from: the camera, or the
keyboard for development."""

import math
import time
from dataclasses import dataclass

import numpy as np
import pygame


@dataclass
class BodyFrame:
    time: float              # time.perf_counter() when it was seen
    bodies: dict             # {1: body grid or None, 2: body grid or None}
    # The real players (vision.bodies.Picture), None without colour camera
    pictures: dict = None


class BodySource:
    def poll(self):
        """Latest BodyFrame, or None before the first one."""
        return None

    def on_key(self, key):
        pass

    def status(self):
        """Text to show the players (countdowns etc.), or None."""
        return None

    def debug_image(self):
        """BGR camera debug image, or None."""
        return None

    def camera_text(self):
        """Where the camera was measured to be, or None."""
        return None

    def set_debug(self, enabled):
        pass

    def request_background(self):
        pass

    def close(self):
        pass


class RealSenseBodySource(BodySource):
    CALIBRATION_SHOW_S = 4.0

    def __init__(self, spec):
        # Imported here so --sim works without pyrealsense2 installed
        from . import config
        from .vision.tracker import TrackerThread

        self.background_delay = config.BACKGROUND_DELAY_S
        self.thread = TrackerThread(body_spec=spec)
        self.thread.start()
        self.thread.request_background(self.background_delay)

    def poll(self):
        if self.thread.error is not None:
            raise RuntimeError(f"Camera stopped: {self.thread.error}")

        result = self.thread.latest()
        if result is None or result.bodies is None:
            return None
        return BodyFrame(result.time, result.bodies, result.pictures)

    def status(self):
        waiting = self.thread.background_status()
        if waiting is not None:
            if waiting > 0:
                return f"Step out of the play area: capturing the background in {waiting:.0f}"
            return "Capturing the background..."

        if self.thread.latest() is None:
            return "Waiting for the camera..."

        # Where the camera turned out to be, for a few seconds
        calibration = self.thread.calibration()
        if calibration is not None and time.perf_counter() - calibration[1] < self.CALIBRATION_SHOW_S:
            return calibration[0].message
        return None

    def debug_image(self):
        result = self.thread.latest()
        return None if result is None else result.debug

    def camera_text(self):
        calibration = self.thread.calibration()
        return None if calibration is None else calibration[0].message

    def set_debug(self, enabled):
        self.thread.want_debug = enabled

    def request_background(self):
        self.thread.request_background(self.background_delay)

    def close(self):
        self.thread.stop()


@dataclass
class SimPlayer:
    x: float                 # m
    height: float            # m, standing
    lane: tuple              # x range it may move in (m)
    in_view: bool = True
    jump_t: float = None     # seconds into the current jump
    ducking: bool = False


class KeyboardBodySource(BodySource):
    """Play without a camera, with stick-figure silhouettes.

    Player 1: A / D move, W jump, S duck. Player 2: the arrow keys.
    1 / 2: that player steps out of (or back into) view.
    """

    SPEED = 1.8              # m/s
    JUMP_S = 0.6
    JUMP_PEAK_M = 0.5
    FRAME_S = 1 / 30         # new frames as often as the camera

    BINDINGS = {
        1: (pygame.K_a, pygame.K_d, pygame.K_w, pygame.K_s),
        2: (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN),
    }

    def __init__(self, spec, lanes):
        self.spec = spec
        self.players = {
            1: SimPlayer(sum(lanes[1]) / 2, 1.75, lanes[1]),
            2: SimPlayer(sum(lanes[2]) / 2, 1.62, lanes[2]),
        }
        self.last = None
        self.frame = None

    def on_key(self, key):
        for pid, toggle in ((1, pygame.K_1), (2, pygame.K_2)):
            if key == toggle:
                self.players[pid].in_view = not self.players[pid].in_view

    def poll(self):
        now = time.perf_counter()
        dt = 0.0 if self.last is None else min(now - self.last, 0.05)
        self.last = now

        keys = pygame.key.get_pressed()
        for pid, player in self.players.items():
            self._move(player, keys, self.BINDINGS[pid], dt)

        if self.frame is None or now - self.frame.time >= self.FRAME_S:
            bodies = {
                pid: self._silhouette(player) if player.in_view else None
                for pid, player in self.players.items()
            }
            self.frame = BodyFrame(now, bodies)
        return self.frame

    def _move(self, player, keys, binding, dt):
        left, right, jump, duck = binding
        player.x += (keys[right] - keys[left]) * self.SPEED * dt
        player.x = min(max(player.x, player.lane[0] + 0.25), player.lane[1] - 0.25)
        player.ducking = bool(keys[duck])

        if player.jump_t is None and keys[jump]:
            player.jump_t = 0.0
        elif player.jump_t is not None:
            player.jump_t += dt
            if player.jump_t >= self.JUMP_S:
                player.jump_t = None

    def _silhouette(self, player):
        xs, heights = self.spec.centres
        lift = 0.0
        if player.jump_t is not None:
            lift = self.JUMP_PEAK_M * math.sin(math.pi * player.jump_t / self.JUMP_S)

        # Ducking squats everything lower, knees out
        squat = 0.62 if player.ducking else 1.0
        leg_half_width = 0.22 if player.ducking else 0.16

        def at(fraction):
            return lift + fraction * player.height * squat

        across = np.abs(xs - player.x)
        legs = (across <= leg_half_width) & (heights >= lift) & (heights <= at(0.47))
        torso = (across <= 0.21) & (heights >= at(0.47)) & (heights <= at(0.82))
        head_r = 0.095 * player.height
        head = (xs - player.x) ** 2 + (heights - at(0.91)) ** 2 <= head_r ** 2
        return legs | torso | head
