"""Where the camera is, measured from the floor it sees: its height above
the floor and how far it is tilted down.

Done on every background capture (the room is empty then), so the camera
can sit a little differently between runs. config.CAMERA_HEIGHT_M and
config.CAMERA_PITCH_DEG are the fallback when no floor is found.
"""

from dataclasses import dataclass

import numpy as np

from .. import config

# The floor is looked for in the bottom part of the image
SEARCH_FROM = 0.6            # fraction of the image height
INLIER_M = 0.02              # a point this close to the plane is on it
# A measurement is trusted only within these limits
MIN_FLOOR_SHARE = 0.15       # of the pixels searched
HEIGHT_LIMITS_M = (0.2, 4.0)
PITCH_LIMITS_DEG = (-45.0, 75.0)


@dataclass
class Calibration:
    ok: bool                 # measured and used; False = config values kept
    height: float            # m, camera above the floor
    pitch: float             # deg, tilted down (negative = up)
    roll: float = 0.0        # deg, tilted sideways (not corrected)
    message: str = ""


def fit_floor(depth, intrinsics, seed=0):
    """Measure the camera's height and downward tilt from the floor in the
    bottom of the image: (height m, pitch deg, sideways roll deg, share of
    those pixels that are floor), or None if no floor was found."""
    rng = np.random.default_rng(seed)
    top = int(depth.shape[0] * SEARCH_FROM)
    v, u = np.nonzero(depth[top:] > 0)
    v = v + top
    if len(v) < 500:
        return None
    pick = rng.choice(len(v), size=min(4000, len(v)), replace=False)
    points = intrinsics.deproject(u[pick], v[pick], depth[v[pick], u[pick]] / 1000.0).T

    # RANSAC: the plane through 3 random points that most points lie on
    best, best_count = None, 0
    for _ in range(300):
        a, b, c = points[rng.choice(len(points), 3, replace=False)]
        normal = np.cross(b - a, c - a)
        if np.linalg.norm(normal) < 1e-9:
            continue
        normal /= np.linalg.norm(normal)
        if normal[1] < 0:
            normal = -normal              # pointing down (camera y is down)
        if normal[1] < 0.5:
            continue                      # a wall, not the floor
        count = int((np.abs(points @ normal - a @ normal) < INLIER_M).sum())
        if count > best_count:
            best, best_count = (normal, a @ normal), count
    if best is None:
        return None

    # Refine on the floor points: least-squares plane
    normal, offset = best
    floor = points[np.abs(points @ normal - offset) < INLIER_M]
    centre = floor.mean(axis=0)
    normal = np.linalg.svd(floor - centre)[2][2]
    if normal[1] < 0:
        normal = -normal
    height = float(centre @ normal)
    pitch = float(np.degrees(np.arctan2(normal[2], normal[1])))
    roll = float(np.degrees(np.arcsin(np.clip(normal[0], -1, 1))))
    return height, pitch, roll, len(floor) / len(points)


def describe(height, pitch):
    tilt = "down" if pitch >= 0 else "up"
    return f"camera {height:.2f} m up, tilted {abs(pitch):.1f} deg {tilt}"


def calibrate(depth, intrinsics):
    """Measure the camera from the floor and, if the result is believable,
    use it (sets config.CAMERA_HEIGHT_M / CAMERA_PITCH_DEG)."""
    found = fit_floor(depth, intrinsics)
    if found is not None:
        height, pitch, roll, share = found
        if (
            share >= MIN_FLOOR_SHARE
            and HEIGHT_LIMITS_M[0] <= height <= HEIGHT_LIMITS_M[1]
            and PITCH_LIMITS_DEG[0] <= pitch <= PITCH_LIMITS_DEG[1]
        ):
            config.CAMERA_HEIGHT_M, config.CAMERA_PITCH_DEG = height, pitch
            message = f"Floor found: {describe(height, pitch)}"
            if abs(roll) > 3:
                message += f", {roll:.0f} deg sideways (straighten it)"
            return Calibration(True, height, pitch, roll, message)

    return Calibration(
        False, config.CAMERA_HEIGHT_M, config.CAMERA_PITCH_DEG, 0.0,
        "No floor found: using the camera height and tilt from config.py",
    )
