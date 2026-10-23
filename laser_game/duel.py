"""Round rules: silhouettes in, lasers and the winner out.

No drawing and no camera here, so the rules can be tested with made-up
silhouettes. Times are time.perf_counter() seconds, the clock the tracker
stamps its frames with.

waiting   -> both players in view for JOIN_HOLD_S (or Enter: whoever is there)
countdown -> heights measured; anyone leaving goes back to waiting
playing   -> waves of lasers; a player is out when their lives run out or
             they leave the view for FORFEIT_S
over      -> last player standing wins (both out at once: a draw)
"""

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from . import config
from .lasers import Target, WaveSpawner

WAITING, COUNTDOWN, PLAYING, OVER = "waiting", "countdown", "playing", "over"

# Camera frames kept for looking back (s)
HISTORY_S = 2.0


@dataclass
class Player:
    pid: int
    lane: tuple                       # x range (m)
    seen_at: float                    # last time they were in view
    height: float = config.DEFAULT_PLAYER_HEIGHT_M
    lives: int = config.LIVES
    out_at: Optional[float] = None
    out_reason: str = ""
    hit_at: float = -math.inf         # last time a laser hit them
    height_samples: list = field(default_factory=list)

    @property
    def out(self):
        return self.out_at is not None


def make_lanes(spec):
    """{pid: x range (m)}: Player 1 left of the split, Player 2 right."""
    split = config.LANE_SPLIT_X_M
    return {1: (spec.x_range[0], split), 2: (split, spec.x_range[1])}


class LaserDuel:
    def __init__(self, spec, rng):
        self.spec = spec
        self.rng = rng
        self.lanes = make_lanes(spec)
        self.frames = deque()         # recent camera frames, oldest first
        self.reset()

    def reset(self):
        self.state = WAITING
        self.players = {}             # {pid: Player} in this round
        self.lasers = []
        self.spawner = WaveSpawner(self.spec, self.rng)
        self.both_since = None
        self.countdown_end = None
        self.started_at = None
        self.ended_at = None
        self.winner = None            # pid; None = draw (or solo)

    # ----------------------------------------------------------- queries

    def body(self, pid):
        """A player's latest silhouette, or None if they're not in view."""
        if not self.frames:
            return None
        grid = self.frames[-1].bodies.get(pid)
        if grid is None or grid.sum() < config.MIN_BODY_CELLS:
            return None
        return grid

    def present(self):
        return [pid for pid in (1, 2) if self.body(pid) is not None]

    def elapsed(self, now):
        if self.started_at is None:
            return 0.0
        end = now if self.ended_at is None else self.ended_at
        return end - self.started_at

    def survived(self, player, now):
        if player.out_at is None:
            return self.elapsed(now)
        return player.out_at - self.started_at

    def centre_x(self, pid):
        body = self.body(pid)
        if body is None:
            return sum(self.lanes[pid]) / 2
        return float(self.spec.centres[0][body].mean())

    # ------------------------------------------------------------- input

    def start(self, now, pids=None):
        """Start a round (countdown first) with these players, default:
        whoever is in view. False if nobody is there."""
        pids = self.present() if pids is None else pids
        if not pids:
            return False

        self.reset()
        self.players = {pid: Player(pid, self.lanes[pid], now) for pid in pids}
        self.state = COUNTDOWN
        self.countdown_end = now + config.COUNTDOWN_S
        return True

    def update(self, now, frame):
        """Advance to time now. frame: the source's latest frame (or None);
        the same frame may come in several times."""
        new = self._add_frame(now, frame)

        if self.state == WAITING:
            self._wait(now)
        elif self.state == COUNTDOWN:
            self._count_down(now, new)
        elif self.state == PLAYING:
            self._play(now, new)
        elif now - self.ended_at >= config.RESTART_S:
            self.reset()
        else:
            # Over: lasers still in the air fly on past the players
            self.lasers = [
                laser for laser in self.lasers
                if laser.depth(now) > -config.LASER_PAST_DEPTH_M
            ]

    # ------------------------------------------------------------ states

    def _add_frame(self, now, frame):
        if frame is None or (self.frames and frame.time <= self.frames[-1].time):
            return []

        self.frames.append(frame)
        while len(self.frames) > 1 and self.frames[0].time < now - HISTORY_S:
            self.frames.popleft()
        return [frame]

    def _wait(self, now):
        if len(self.present()) < 2:
            self.both_since = None
            return

        if self.both_since is None:
            self.both_since = now
        if now - self.both_since >= config.JOIN_HOLD_S:
            self.start(now, [1, 2])

    def _count_down(self, now, new):
        for pid, player in self.players.items():
            if self.body(pid) is not None:
                player.seen_at = now
            elif now - player.seen_at > config.FORFEIT_S:
                # Walked off before it started: wait for players again
                self.reset()
                return

            for frame in new:
                top = self._top(frame.bodies.get(pid))
                if top is not None:
                    player.height_samples.append(top)

        if now < self.countdown_end:
            return

        low, high = config.PLAYER_HEIGHT_LIMITS_M
        for player in self.players.values():
            if player.height_samples:
                player.height = min(max(float(np.median(player.height_samples)), low), high)

        self.state = PLAYING
        self.started_at = now
        self.spawner.start(now)

    def _play(self, now, new):
        for pid, player in self.players.items():
            if player.out:
                continue
            if self.body(pid) is not None:
                player.seen_at = now
            elif now - player.seen_at > config.FORFEIT_S:
                self._knock_out(player, now, "left the arena")

        targets = {
            pid: Target(player.lane, player.height, self.centre_x(pid))
            for pid, player in self.players.items() if not player.out
        }
        self.lasers += self.spawner.update(now, targets)

        for laser in self.lasers:
            if laser.result is None:
                self._judge(laser, now, new)
        self.lasers = [laser for laser in self.lasers if not laser.gone(now)]

        self._check_end(now)

    # -------------------------------------------------------------- hits

    def _judge(self, laser, now, new):
        first, last = laser.window

        for frame in new:
            if frame.time > last:
                laser.result = "dodged"
                return
            if frame.time >= first:
                self._test(laser, frame)

        if laser.hit_frames >= config.HIT_FRAMES:
            self._hit(laser, now)
        elif now > last + config.FRAME_TIMEOUT_S:
            laser.result = "dodged"     # the camera went quiet

    def _test(self, laser, frame):
        body = frame.bodies.get(laser.pid)
        if body is None:
            return

        touching = body & laser.cells
        if touching.sum() >= config.MIN_HIT_CELLS:
            laser.hit_frames += 1
            xs, heights = self.spec.centres
            laser.hit_at = np.array([xs[touching].mean(), heights[touching].mean()])

    def _hit(self, laser, now):
        player = self.players.get(laser.pid)
        safe = player is None or player.out or now - player.hit_at < config.HIT_COOLDOWN_S
        if safe:
            laser.result = "dodged"
            return

        laser.result = "hit"
        player.hit_at = now
        player.lives -= 1
        if player.lives <= 0:
            self._knock_out(player, now, "was hit by a laser")

    def _knock_out(self, player, now, reason):
        player.out_at = now
        player.out_reason = reason

    def _check_end(self, now):
        alive = [player for player in self.players.values() if not player.out]
        if len(self.players) > 1:
            over = len(alive) <= 1
        else:
            over = not alive

        if over:
            self.state = OVER
            self.ended_at = now
            self.winner = alive[0].pid if alive and len(self.players) > 1 else None

    def _top(self, grid):
        """Height (m) of the top of a silhouette."""
        if grid is None or grid.sum() < config.MIN_BODY_CELLS:
            return None
        top_row = np.flatnonzero(grid.any(axis=1))[0]
        return self.spec.height_range[1] - top_row * self.spec.cell
