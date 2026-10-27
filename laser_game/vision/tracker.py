"""Depth frames in, each player's whole-body silhouette (metres) out, plus a
cut-out picture of them from the colour camera."""

import threading
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from .. import config
from .background import BackgroundModel
from .bodies import body_grid, body_picture
from .floor import calibrate
from .players import clean_mask, find_split, refine_player, split_players
from .zone import in_zone, world

PLAYER_COLORS_BGR = {1: (255, 140, 40), 2: (60, 200, 60)}
# Debug image: seen moving but outside the play zone / cut as an artifact
OUTSIDE_BGR = (60, 60, 200)
ARTIFACT_BGR = (0, 160, 255)


@dataclass
class TrackingResult:
    bodies: dict             # {1: body grid or None, 2: ...} (see bodies.py)
    split: int
    debug: Optional[np.ndarray] = None
    time: float = 0.0        # time.perf_counter() when the frame arrived
    # {1: bodies.Picture or None, 2: ...}, None without the colour camera
    pictures: Optional[dict] = None
    distances: Optional[dict] = None   # {pid: m ahead of the camera}


class PlayerTracker:
    def __init__(self, body_spec):
        # A bodies.GridSpec: the grid every silhouette is drawn on
        self.body_spec = body_spec
        self.background = BackgroundModel()
        self.split = None
        # floor.Calibration from the last background capture, or None
        self.calibration = None

    @staticmethod
    def orient(depth, intrinsics):
        """Flip into screen orientation (see config.MIRROR)."""
        if config.MIRROR:
            return np.ascontiguousarray(depth[:, ::-1]), intrinsics.mirrored()
        return depth, intrinsics

    def capture_background(self, frames, intrinsics):
        self.background.capture(frames, intrinsics.fx * config.DECIMATION)
        # The room is empty now: measure where the camera is from the floor
        # (on the averaged background, steadier than any single frame)
        if config.AUTO_CALIBRATE:
            self.calibration = calibrate(self.background.depth, intrinsics)

    def process(self, depth, intrinsics, timestamp, color=None, debug=False):
        """depth: oriented (see orient). color: a geometry.ColorFrame or None."""
        valid = depth > 0
        x, height, forward = world(depth, intrinsics)
        zone = in_zone(x, height, forward, valid)

        foreground = self.background.foreground(depth)
        mask = clean_mask(foreground & zone)

        split = find_split(mask, self.split, intrinsics.ppx)
        if self.split is None:
            self.split = float(split)
        else:
            self.split += config.SPLIT_SMOOTHING * (split - self.split)

        raw = split_players(mask, int(round(self.split)))

        players, distances = {}, {}
        for pid, player in raw.items():
            refined = None if player is None else refine_player(player, valid, forward)
            players[pid], distances[pid] = refined if refined else (None, None)

        bodies, pictures = {}, ({} if color is not None else None)
        for pid, player in players.items():
            bodies[pid] = None
            if pictures is not None:
                pictures[pid] = None
            if player is None:
                continue

            grid, fine = body_grid(player, distances[pid], intrinsics, self.body_spec)
            bodies[pid] = grid
            if pictures is not None:
                pictures[pid] = body_picture(
                    fine, distances[pid], color, config.MIRROR, self.body_spec
                )

        # Learn the background away from everything that might be a player
        occupied = np.zeros(mask.shape, dtype=bool)
        for player in raw.values():
            if player is not None:
                occupied |= player
        self.background.update(depth, occupied)

        image = None
        if debug:
            image = self._debug_image(depth, zone, foreground & valid, players)
        return TrackingResult(
            bodies, int(round(self.split)), image, timestamp, pictures, distances
        )

    def _debug_image(self, depth, zone, foreground, players):
        """Grey depth (near = bright), outside the play zone dimmed; red =
        moving but outside the zone, orange = cut as an artifact, players
        tinted, the divider in white."""
        grey = np.clip(
            255 - depth * (255.0 / (config.FAR_M * 1000.0)), 0, 255
        ).astype(np.uint8)
        grey[depth <= 0] = 0
        image = cv2.cvtColor(grey, cv2.COLOR_GRAY2BGR)
        image[~zone] //= 3

        image[foreground & ~zone] = OUTSIDE_BGR
        kept = np.zeros(zone.shape, dtype=bool)
        for player in players.values():
            if player is not None:
                kept |= player
        image[foreground & zone & ~kept] = ARTIFACT_BGR

        for pid, player in players.items():
            if player is not None:
                tint = np.array(PLAYER_COLORS_BGR[pid], dtype=np.float32)
                image[player] = (0.4 * image[player] + 0.6 * tint).astype(np.uint8)

        split = int(round(self.split))
        cv2.line(image, (split, 0), (split, image.shape[0]), (255, 255, 255), 1)
        return image


class TrackerThread(threading.Thread):
    """Camera + tracking off the game loop: 60 fps rendering never waits
    for the 30 fps camera."""

    def __init__(self, body_spec):
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
        self.calibrated_at = None

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
                depth, intrinsics, color = self.camera.read()
                if depth is None:
                    continue

                depth, intrinsics = self.tracker.orient(depth, intrinsics)
                now = time.perf_counter()

                if self._take_background_frame(depth, intrinsics, now):
                    continue

                result = self.tracker.process(
                    depth, intrinsics, now, color, debug=self.want_debug
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
            requested = self._capture_at

        self.tracker.capture_background(frames, intrinsics)
        if self.tracker.calibration is not None:
            print(self.tracker.calibration.message)
        with self._lock:
            # Only now: the game keeps showing "capturing" until calibrated.
            # (Unless B asked for a new capture meanwhile: keep that one)
            if self._capture_at == requested:
                self._capture_at = None
            self.calibrated_at = time.perf_counter()
        return True

    def calibration(self):
        """(floor.Calibration, when) of the last background capture, or None."""
        with self._lock:
            if self.tracker.calibration is None or self.calibrated_at is None:
                return None
            return self.tracker.calibration, self.calibrated_at

    def stop(self):
        self._running = False
        self.join(timeout=2.0)
