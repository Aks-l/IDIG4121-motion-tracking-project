"""Where the game gets the two anchors from, already in screen px."""

import time

import numpy as np
import pygame

from .. import config


class AnchorSource:
    def poll(self):
        """{1: (x, y) or None, 2: (x, y) or None} in screen px."""
        return {1: None, 2: None}

    def status(self):
        """Text to show the players (countdowns etc.), or None."""
        return None

    def debug_image(self):
        """BGR camera debug image, or None."""
        return None

    def set_debug(self, enabled):
        pass

    def request_background(self):
        pass

    def calibrate(self):
        pass

    def close(self):
        pass


class KeyboardSource(AnchorSource):
    """Play without a camera: WASD moves Player 1's hand, the arrow keys
    Player 2's. Hold SPACE to let go of the object."""

    SPEED = 420.0   # px/s

    def __init__(self, p1_start, p2_start):
        self.points = {1: np.array(p1_start, float), 2: np.array(p2_start, float)}
        self.last = None

    def poll(self):
        now = time.perf_counter()
        dt = 0.0 if self.last is None else min(now - self.last, 0.05)
        self.last = now

        keys = pygame.key.get_pressed()
        bindings = {
            1: (pygame.K_a, pygame.K_d, pygame.K_w, pygame.K_s),
            2: (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN),
        }
        for pid, (left, right, up, down) in bindings.items():
            move = np.array([keys[right] - keys[left], keys[down] - keys[up]], float)
            self.points[pid] += move * self.SPEED * dt
            np.clip(
                self.points[pid], (0, 0),
                (config.SCREEN_SIZE[0], config.GROUND_Y), out=self.points[pid],
            )

        if keys[pygame.K_SPACE]:
            return {1: None, 2: None}
        return {pid: tuple(point) for pid, point in self.points.items()}


class RealSenseSource(AnchorSource):
    def __init__(self, mapper):
        # Imported here so --sim works without pyrealsense2 installed
        from ..vision.tracker import TrackerThread

        self.mapper = mapper
        self.thread = TrackerThread()
        self.thread.start()
        self.thread.request_background(config.BACKGROUND_DELAY_S)
        self.calibrate_until = None

    def poll(self):
        if self.thread.error is not None:
            raise RuntimeError(f"Camera stopped: {self.thread.error}")

        result = self.thread.latest()
        if result is None:
            return {1: None, 2: None}

        anchors = {}
        for pid, anchor in result.anchors.items():
            if anchor is None:
                anchors[pid] = None
                continue
            self.mapper.add_sample(anchor.world)
            anchors[pid] = self.mapper.to_screen(anchor.world)

        if self.calibrate_until is not None and time.perf_counter() >= self.calibrate_until:
            self.calibrate_until = None
            self.mapper.finish_calibration()

        return anchors

    def status(self):
        waiting = self.thread.background_status()
        if waiting is not None:
            if waiting > 0:
                return f"Step out of the play area: capturing the background in {waiting:.0f}"
            return "Capturing the background..."

        if self.calibrate_until is not None:
            left = self.calibrate_until - time.perf_counter()
            return f"Calibrating: sweep your hands from the floor to above your head ({left:.0f})"

        if self.thread.latest() is None:
            return "Waiting for the camera..."
        return None

    def debug_image(self):
        result = self.thread.latest()
        return None if result is None else result.debug

    def set_debug(self, enabled):
        self.thread.want_debug = enabled

    def request_background(self):
        self.thread.request_background(config.BACKGROUND_DELAY_S)

    def calibrate(self):
        self.mapper.start_calibration()
        self.calibrate_until = time.perf_counter() + config.CALIBRATION_S

    def close(self):
        self.thread.stop()
