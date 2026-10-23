"""Depth frames in, two smoothed hand anchors (metres) out."""

import threading
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from .. import config
from .background import BackgroundModel
from .bodies import body_grid
from .filters import OneEuroFilter
from .geometry import camera_to_world
from .players import clean_mask, find_anchor, find_split, split_players

PLAYER_COLORS_BGR = {1: (255, 140, 40), 2: (60, 200, 60)}


@dataclass
class Anchor:
    world: np.ndarray        # x right, y height above floor, z distance (m)
    pixel: tuple             # (u, v) in the processed depth image
    time: float
    stale: bool = False      # held over from an earlier frame


@dataclass
class TrackingResult:
    anchors: dict            # {1: Anchor or None, 2: Anchor or None}
    split: int
    debug: Optional[np.ndarray] = None
    # Only with a body grid (see bodies.py): {1: grid or None, 2: ...}
    bodies: Optional[dict] = None
    time: float = 0.0        # time.perf_counter() when the frame arrived


class PlayerTracker:
    def __init__(self, body_spec=None):
        # A bodies.GridSpec: also report each player's whole silhouette
        self.body_spec = body_spec
        self.background = BackgroundModel()
        self.split = None
        self.filters = {
            pid: OneEuroFilter(config.ONE_EURO_MIN_CUTOFF, config.ONE_EURO_BETA)
            for pid in (1, 2)
        }
        self.last = {1: None, 2: None}

    @staticmethod
    def orient(depth, intrinsics):
        """Flip into screen orientation (see config.MIRROR)."""
        if config.MIRROR:
            return np.ascontiguousarray(depth[:, ::-1]), intrinsics.mirrored()
        return depth, intrinsics

    def capture_background(self, frames, intrinsics):
        self.background.capture(frames, intrinsics.fx * config.DECIMATION)

    def process(self, depth, intrinsics, timestamp, debug=False):
        mask = clean_mask(self.background.foreground(depth))

        split = find_split(mask, self.split)
        if self.split is None:
            self.split = float(split)
        else:
            self.split += config.SPLIT_SMOOTHING * (split - self.split)

        players = split_players(mask, int(round(self.split)))

        anchors = {}
        for pid, player in players.items():
            found = None if player is None else find_anchor(player, depth, pid)

            world = pixel = None
            if found is not None:
                u, v, depth_mm = found
                point = intrinsics.deproject(u, v, depth_mm / 1000.0)
                world = camera_to_world(
                    point, config.CAMERA_PITCH_DEG, config.CAMERA_HEIGHT_M
                )
                pixel = (u, v)

            anchors[pid] = self._smooth(pid, world, pixel, timestamp)

        bodies = None
        if self.body_spec is not None:
            bodies = {
                pid: None if player is None
                else body_grid(player, depth, intrinsics, self.body_spec)
                for pid, player in players.items()
            }

        occupied = np.zeros(mask.shape, dtype=bool)
        for player in players.values():
            if player is not None:
                occupied |= player
        self.background.update(depth, occupied)

        image = self._debug_image(depth, players, anchors) if debug else None
        return TrackingResult(
            anchors, int(round(self.split)), image, bodies, timestamp
        )

    def _smooth(self, pid, world, pixel, timestamp):
        if world is None:
            # Missed for a moment: keep the last anchor briefly
            last = self.last[pid]
            if last is not None and timestamp - last.time <= config.ANCHOR_HOLD_S:
                return Anchor(last.world, last.pixel, last.time, stale=True)

            self.filters[pid].reset()
            self.last[pid] = None
            return None

        anchor = Anchor(self.filters[pid](world, timestamp), pixel, timestamp)
        self.last[pid] = anchor
        return anchor

    def _debug_image(self, depth, players, anchors):
        # Grey depth (near = bright), players tinted, anchors circled
        grey = np.clip(
            255 - depth * (255.0 / (config.FAR_M * 1000.0)), 0, 255
        ).astype(np.uint8)
        grey[depth <= 0] = 0
        image = cv2.cvtColor(grey, cv2.COLOR_GRAY2BGR)

        for pid, player in players.items():
            if player is not None:
                tint = np.array(PLAYER_COLORS_BGR[pid], dtype=np.float32)
                image[player] = (0.4 * image[player] + 0.6 * tint).astype(np.uint8)

        split = int(round(self.split))
        cv2.line(image, (split, 0), (split, image.shape[0]), (255, 255, 255), 1)

        for anchor in anchors.values():
            if anchor is not None:
                u, v = (int(round(c)) for c in anchor.pixel)
                cv2.circle(image, (u, v), 6, (255, 255, 255), 2)

        return image


class TrackerThread(threading.Thread):
    """Camera + tracking off the game loop: 60 fps rendering never waits
    for the 30 fps camera."""

    def __init__(self, body_spec=None):
        super().__init__(daemon=True)
        # Imported here so the rest of vision/ works without pyrealsense2
        from .camera import DepthCamera

        self.camera = DepthCamera()
        self.tracker = PlayerTracker(body_spec)
        self.want_debug = False
        self.error = None

        self._lock = threading.Lock()
        self._latest = None
        self._running = True
        self._capture_at = None
        self._frames = []

    def request_background(self, delay_s=0.0):
        with self._lock:
            self._frames = []
            self._capture_at = time.perf_counter() + delay_s

    def background_status(self):
        """Seconds until capture (>0), 0 while capturing, None otherwise."""
        with self._lock:
            if self._capture_at is None:
                return None
            return max(0.0, self._capture_at - time.perf_counter())

    def latest(self):
        with self._lock:
            return self._latest

    def run(self):
        try:
            while self._running:
                depth, intrinsics = self.camera.read()
                if depth is None:
                    continue

                depth, intrinsics = self.tracker.orient(depth, intrinsics)
                now = time.perf_counter()

                if self._take_background_frame(depth, intrinsics, now):
                    continue

                result = self.tracker.process(
                    depth, intrinsics, now, debug=self.want_debug
                )
                with self._lock:
                    self._latest = result
        except Exception as error:   # shown by the game, which then exits
            self.error = error
        finally:
            self.camera.stop()

    def _take_background_frame(self, depth, intrinsics, now):
        with self._lock:
            if self._capture_at is None or now < self._capture_at:
                return False

            self._frames.append(depth)
            if len(self._frames) < config.BACKGROUND_FRAMES:
                return True

            frames, self._frames = self._frames, []
            self._capture_at = None

        self.tracker.capture_background(frames, intrinsics)
        return True

    def stop(self):
        self._running = False
        self.join(timeout=2.0)
