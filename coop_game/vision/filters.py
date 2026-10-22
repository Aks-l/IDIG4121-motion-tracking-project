"""1€ filter (Casiez et al. 2012): smooths hard when still, follows fast moves."""

import math

import numpy as np


class OneEuroFilter:
    # Works on floats and numpy arrays (each component filtered on its own)

    def __init__(self, min_cutoff, beta, d_cutoff=1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.reset()

    def reset(self):
        self.value = None
        self.speed = 0.0
        self.time = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, value, timestamp):
        # Own copy: the caller's array is never changed behind its back
        value = np.array(value, dtype=float)

        if self.value is None:
            self.value, self.time = value, timestamp
            return value.copy()

        dt = max(timestamp - self.time, 1e-3)
        self.time = timestamp

        speed = (value - self.value) / dt
        self.speed = self.speed + self._alpha(self.d_cutoff, dt) * (
            speed - self.speed
        )

        cutoff = self.min_cutoff + self.beta * np.abs(self.speed)
        self.value = self.value + self._alpha(cutoff, dt) * (value - self.value)
        return self.value.copy()
