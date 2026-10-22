
import time
import warnings

import cv2
import numpy as np
import pyrealsense2 as rs

# 848x480 is the D435's optimal depth resolution (Intel tuning guide)
WIDTH, HEIGHT, FPS = 848, 480, 30
DECIMATION = 2

# Fuse the RGB camera with depth: colour fills in where depth has holes or
# is unsure, depth vetoes colour where it clearly sees the floor (shadows)
USE_COLOR = True

# Play area: anything outside this depth band is ignored
MIN_DEPTH_M = 0.3
MAX_DEPTH_M = 4.0

# Stop auto-exposure (and colour white balance) from shifting the image
# when a player walks in
LOCK_EXPOSURE = True

WARMUP_FRAMES = 30
BACKGROUND_FRAMES = 60

BLUR_KERNEL = (5, 5)
MORPH_KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

# A pixel turns on when it is K_SIGMA_ON noise sigmas closer than the
# background and only turns off below K_SIGMA_OFF (hysteresis = no flicker)
K_SIGMA_ON = 4.0
K_SIGMA_OFF = 2.5
MIN_THRESHOLD_MM = 25.0

# D435 stereo noise grows with distance squared:
# rms_mm = z_mm^2 * subpixel / (fx_px * baseline_mm)
# The filters remove part of it, so the model is only used as a floor.
D435_BASELINE_MM = 50.0
SUBPIXEL_RMS = 0.08
NOISE_MODEL_SCALE = 0.5

# Share of background frames in which a pixel had valid depth
STABLE_VALID_RATIO = 0.6
EMPTY_VALID_RATIO = 0.1

# Colour background (Horprasert et al. 1999): a change is split into
# brightness (alpha, 1 = same as the floor) and colour (chromaticity
# distortion, in noise units). A shadow on the grey floor only lowers
# alpha; a person usually changes the colour or is much darker/brighter.
COLOR_MIN_STD = 4.0
CD_ON = 7.0
CD_OFF = 4.5
DARK_ALPHA = 0.45
BRIGHT_ALPHA = 1.5

# Temporal vote on the fused mask: each pixel keeps a running foreground
# score; it turns on above MASK_ON and off below MASK_OFF. 1.0 disables.
MASK_SMOOTHING = 0.5
MASK_ON = 0.6
MASK_OFF = 0.3

# Holes inside a body smaller than this (depth dropouts) are filled
MAX_HOLE_PX = 150

# Slowly absorb drift into the background where nobody is standing
BG_LEARNING_RATE = 0.01

MIN_BLOB_AREA = 150

# Hand tracking (top-down view, whole body in frame). Hands are geodesic
# extrema: the body points farthest from the torso when walking along the
# body's surface (Plagemann et al., ICRA 2010). Each hand reports its z,
# the height above the background (floor).
NUM_HANDS = 2
# Height above the background (mm) mapped to z = 0..1 (waist -> overhead)
HAND_HEIGHT_RANGE_MM = (800.0, 2000.0)
# Extrema to look for per body: head, hands and feet, plus spares for
# elbows and shoulder corners, which are found too and then rejected
MAX_EXTREMA = 8
# Stop once the next extremum sticks out less than this from the rest
MIN_EXTREMUM_MM = 120.0
# Extrema closer to the torso than this are the head, shoulders or hands
# held against the body
MIN_HAND_REACH_MM = 350.0
# A hand already being tracked is still followed down to this share of
# MIN_HAND_REACH_MM, so it doesn't blink when pulled in a little
KEEP_REACH_FRACTION = 0.7
# A hand must be the far end of its limb, within this tolerance
TIP_TOLERANCE_MM = 40.0
# Extrema lower than this above the floor are feet
MIN_HAND_HEIGHT_MM = 300.0
# Part of the limb around the tip averaged into the hand position
HAND_LENGTH_MM = 150.0
# Depth steps bigger than this are walls for the geodesic walk, so an arm
# held over the body connects at the shoulder, not through the chest
# (0 disables)
DEPTH_JUMP_MM = 100.0
# Depth holes inside the body up to this many pixels across are bridged
MAX_DEPTH_FILL_PX = 20
# Torso = the thickest part of the body (share of the max thickness)
TORSO_CORE = 0.8
# A tracked hand may move at most this far between frames to keep its id
MAX_HAND_JUMP_PX = 60.0
# Keep the last z for a few frames when a hand drops out
HOLD_FRAMES = 5

# 1€ filter: lower MIN_CUTOFF = less jitter, higher BETA = less lag
ONE_EURO_MIN_CUTOFF = 1.0
ONE_EURO_BETA = 20.0
ONE_EURO_D_CUTOFF = 1.0

# Windows are shown this many times bigger than the processed image
DISPLAY_SCALE = 2


def make_filters():
    # Recommended order from the librealsense post-processing docs
    decimation = rs.decimation_filter()
    decimation.set_option(rs.option.filter_magnitude, DECIMATION)

    threshold = rs.threshold_filter()
    threshold.set_option(rs.option.min_distance, MIN_DEPTH_M)
    threshold.set_option(rs.option.max_distance, MAX_DEPTH_M)

    to_disparity = rs.disparity_transform(True)

    spatial = rs.spatial_filter()
    spatial.set_option(rs.option.filter_magnitude, 2)
    spatial.set_option(rs.option.filter_smooth_alpha, 0.5)
    spatial.set_option(rs.option.filter_smooth_delta, 20)

    temporal = rs.temporal_filter()
    temporal.set_option(rs.option.filter_smooth_alpha, 0.4)
    temporal.set_option(rs.option.filter_smooth_delta, 20)
    # Persistency 3: reuse the last value if valid in 2 of the last 4 frames
    temporal.set_option(rs.option.holes_fill, 3)

    to_depth = rs.disparity_transform(False)

    # No hole_filling_filter: it invents depth from neighbours, which makes
    # holes look like real (noisy) surfaces and causes false detections
    return (
        decimation,
        threshold,
        to_disparity,
        spatial,
        temporal,
        to_depth,
    )


def configure_sensor(depth_sensor):
    # "High Density" is Intel's preset for background subtraction
    if depth_sensor.supports(rs.option.visual_preset):
        depth_sensor.set_option(
            rs.option.visual_preset,
            int(rs.rs400_visual_preset.high_density),
        )

    # The IR projector adds texture so flat walls/floors get valid depth
    if depth_sensor.supports(rs.option.emitter_enabled):
        depth_sensor.set_option(rs.option.emitter_enabled, 1)

    if depth_sensor.supports(rs.option.laser_power):
        laser_range = depth_sensor.get_option_range(rs.option.laser_power)
        depth_sensor.set_option(rs.option.laser_power, laser_range.max)


def downsample_color(color, shape):
    # Aligned colour is black where there was no depth to map it with
    # (and outside the narrower RGB field of view): average only real pixels
    h, w = shape
    valid = (color.max(axis=2) > 0).astype(np.float32)

    summed = cv2.resize(
        color.astype(np.float32), (w, h), interpolation=cv2.INTER_AREA
    )
    weight = cv2.resize(valid, (w, h), interpolation=cv2.INTER_AREA)

    small = np.zeros_like(summed)
    np.divide(
        summed, weight[..., None], out=small, where=weight[..., None] > 0.5
    )
    return small


class Camera:
    def __init__(self):
        self.pipeline = rs.pipeline()
        config = rs.config()

        config.enable_stream(
            rs.stream.depth, WIDTH, HEIGHT, rs.format.z16, FPS
        )

        if USE_COLOR:
            config.enable_stream(
                rs.stream.color, WIDTH, HEIGHT, rs.format.bgr8, FPS
            )

        profile = self.pipeline.start(config)
        device = profile.get_device()

        self.depth_sensor = device.first_depth_sensor()
        configure_sensor(self.depth_sensor)
        self.depth_scale = self.depth_sensor.get_depth_scale()

        # Full-resolution focal length, used by the stereo noise model
        self.fx = (
            profile.get_stream(rs.stream.depth)
            .as_video_stream_profile()
            .get_intrinsics()
            .fx
        )

        self.color_sensor = device.first_color_sensor() if USE_COLOR else None

        # Reproject colour onto the depth image, so pixel (x, y) is the
        # same point of the scene in both
        self.align = rs.align(rs.stream.depth) if USE_COLOR else None

        self.filters = make_filters()

    def read(self):
        frames = self.pipeline.wait_for_frames()

        if self.align is not None:
            frames = self.align.process(frames)

        depth_frame = frames.get_depth_frame()

        if not depth_frame:
            return None, None, None

        color = None
        if self.align is not None:
            color_frame = frames.get_color_frame()
            if color_frame:
                color = np.asanyarray(color_frame.get_data())

        # Apply SDK filters in sequence
        for filter_ in self.filters:
            depth_frame = filter_.process(depth_frame)

        depth_frame = depth_frame.as_depth_frame()

        depth_mm = (
            np.asanyarray(depth_frame.get_data()).astype(np.float32)
            * self.depth_scale
            * 1000.0
        )

        if color is not None:
            color = downsample_color(color, depth_mm.shape)

        return depth_frame, depth_mm, color

    def set_auto(self, enabled):
        value = 1 if enabled else 0

        if self.depth_sensor.supports(rs.option.enable_auto_exposure):
            self.depth_sensor.set_option(rs.option.enable_auto_exposure, value)

        if self.color_sensor is not None:
            for option in (
                rs.option.enable_auto_exposure,
                rs.option.enable_auto_white_balance,
            ):
                if self.color_sensor.supports(option):
                    self.color_sensor.set_option(option, value)

    def lock(self):
        self._lock_depth()

        if self.color_sensor is not None:
            self._lock_color()

    def _lock_depth(self):
        if not self.depth_sensor.supports(rs.option.enable_auto_exposure):
            return

        depth_frame = self.pipeline.wait_for_frames().get_depth_frame()
        key = rs.frame_metadata_value.actual_exposure

        if not depth_frame or not depth_frame.supports_frame_metadata(key):
            print("Exposure metadata unavailable, keeping auto-exposure on.")
            return

        exposure_range = self.depth_sensor.get_option_range(rs.option.exposure)
        exposure = float(np.clip(
            depth_frame.get_frame_metadata(key),
            exposure_range.min,
            exposure_range.max,
        ))

        self.depth_sensor.set_option(rs.option.enable_auto_exposure, 0)
        self.depth_sensor.set_option(rs.option.exposure, exposure)
        print(f"Depth exposure locked at {exposure:.0f} us.")

    def _lock_color(self):
        # Keep the values auto mode settled on, then switch auto off
        for auto, manual in (
            (rs.option.enable_auto_exposure, rs.option.exposure),
            (rs.option.enable_auto_white_balance, rs.option.white_balance),
        ):
            sensor = self.color_sensor
            if not (sensor.supports(auto) and sensor.supports(manual)):
                continue

            value = sensor.get_option(manual)
            sensor.set_option(auto, 0)
            sensor.set_option(manual, value)

        print("Colour exposure and white balance locked.")

    def stop(self):
        self.pipeline.stop()


def preprocess_depth(depth_mm):
    # Normalised blur: holes (0) are left out of the average, otherwise
    # they drag nearby pixels closer and show up as fake foreground
    valid = (depth_mm > 0).astype(np.float32)

    summed = cv2.GaussianBlur(depth_mm, BLUR_KERNEL, 0)
    weight = cv2.GaussianBlur(valid, BLUR_KERNEL, 0)

    blurred = np.zeros_like(depth_mm)
    np.divide(summed, weight, out=blurred, where=weight > 1e-3)

    blurred[valid == 0] = 0
    return blurred


def fill_small_holes(mask):
    # Background pockets fully inside a body (depth dropouts on dark hair
    # or clothes) are filled; the big outside region is left alone
    holes = cv2.bitwise_not(mask)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        holes, connectivity=4
    )

    small = np.zeros(count, dtype=bool)
    small[1:] = stats[1:, cv2.CC_STAT_AREA] <= MAX_HOLE_PX

    filled = mask.copy()
    filled[small[labels]] = 255
    return filled


def find_blobs(mask, depth_mm, closer_mm, focal_px):
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=8
    )

    clean = np.zeros_like(mask)
    blobs = []

    for label in range(1, count):
        area = stats[label, cv2.CC_STAT_AREA]

        if area < MIN_BLOB_AREA:
            continue

        pixels = labels == label
        clean[pixels] = 255

        blob_depth = depth_mm[pixels & (depth_mm > 0)]
        median_depth = float(np.median(blob_depth)) if blob_depth.size else 0.0

        blob = {
            "bbox": tuple(stats[label, :4]),
            "center": tuple(centroids[label].astype(int)),
            "area": int(area),
            "depth_mm": median_depth,
            "torso": None,
            "extrema": [],
            "hands": [],
        }

        if median_depth > 0:
            # Size of one pixel at the body's distance from the camera
            mm_per_px = median_depth / focal_px
            find_extrema(
                blob, pixels, depth_mm, closer_mm, mm_per_px
            )

        blobs.append(blob)

    blobs.sort(key=lambda blob: blob["area"], reverse=True)
    return clean, blobs


CROSS_KERNEL = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
SQUARE_KERNEL = np.ones((3, 3), np.uint8)


def geodesic_distance(walkable, seeds, current=None):
    # Grow outward from the seeds one ring at a time, only over walkable
    # pixels. Alternating cross/square steps approximates true distance.
    # With `current`, growth stops where it cannot beat the old distance.
    dist = np.full(walkable.shape, np.inf, dtype=np.float32)

    front = seeds & walkable
    reached = front.copy()
    dist[front] = 0
    step = 0

    while True:
        step += 1
        kernel = CROSS_KERNEL if step % 2 else SQUARE_KERNEL

        # Grow from everything reached so far, not just the last ring, or
        # a pixel touching only diagonally is skipped on a cross step
        grown = cv2.dilate(reached.astype(np.uint8), kernel) > 0
        front = grown & walkable & ~reached

        if current is not None:
            front &= current > step

        if not front.any():
            return dist

        dist[front] = step
        reached |= front


def find_extrema(blob, pixels, depth_mm, closer_mm, mm_per_px):
    # Work on the blob's bounding box only, it is much faster
    x, y, w, h = blob["bbox"]
    body = pixels[y:y + h, x:x + w]
    depth = depth_mm[y:y + h, x:x + w]
    height = closer_mm[y:y + h, x:x + w]

    walkable = body.copy()

    if DEPTH_JUMP_MM > 0:
        # Fill depth holes inside the body (e.g. a black sleeve the colour
        # camera found but depth can't see) and the ring around the body
        # from neighbouring body depth, or they'd all count as jumps
        surface = np.where(body & (depth > 0), depth, 0).astype(np.float32)

        for _ in range(MAX_DEPTH_FILL_PX):
            grown = cv2.dilate(surface, SQUARE_KERNEL)
            surface = np.where(surface > 0, surface, grown)

            if not (body & (surface == 0)).any():
                break

        # One more ring so the body outline isn't a jump either
        surface = np.where(
            surface > 0, surface, cv2.dilate(surface, SQUARE_KERNEL)
        )

        jump = cv2.morphologyEx(surface, cv2.MORPH_GRADIENT, SQUARE_KERNEL)
        walkable &= jump < DEPTH_JUMP_MM

    # Torso and arms are the biggest connected piece. The head is cut off
    # by the jump at the neck and is left out, so it can't be the torso.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        walkable.astype(np.uint8), connectivity=8
    )

    if count < 2:
        return

    walkable = labels == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])

    # Seen from above, the torso is the thickest part of the body. Measured
    # on the walkable area so an arm lying over the chest is not counted.
    thickness = cv2.distanceTransform(
        walkable.astype(np.uint8), cv2.DIST_L2, 5
    )
    torso = walkable & (thickness >= TORSO_CORE * thickness.max())

    torso_y, torso_x = np.nonzero(torso)
    blob["torso"] = (float(torso_x.mean() + x), float(torso_y.mean() + y))

    from_torso = geodesic_distance(walkable, torso)
    dist = from_torso.copy()

    hand_steps = HAND_LENGTH_MM / mm_per_px

    for _ in range(MAX_EXTREMA):
        reachable = np.where(np.isfinite(dist), dist, -1.0)
        tip_index = np.argmax(reachable)
        tip_steps = reachable.flat[tip_index]

        # Nothing left that sticks out of the body
        if tip_steps * mm_per_px < MIN_EXTREMUM_MM:
            break

        # Every walkable pixel is reachable from the torso, but be safe
        if not np.isfinite(from_torso.flat[tip_index]):
            break

        tip = np.zeros(walkable.shape, dtype=bool)
        tip.flat[tip_index] = True

        # AGEX: the next extremum is the point farthest from the torso
        # AND from every extremum found so far
        from_tip = geodesic_distance(walkable, tip, current=dist)
        dist = np.minimum(dist, from_tip)

        region = from_tip <= hand_steps
        region_y, region_x = np.nonzero(region)
        region_height = height[region]
        region_height = region_height[region_height > 0]

        reach_mm = float(from_torso.flat[tip_index] * mm_per_px)
        height_mm = (
            float(np.median(region_height)) if region_height.size else None
        )

        # Nothing around a real tip reaches farther from the torso. The
        # middle of an arm fails this: the hand side reaches farther.
        farthest_mm = float(from_torso[region].max() * mm_per_px)
        is_tip = farthest_mm <= reach_mm + TIP_TOLERANCE_MM

        if reach_mm < MIN_HAND_REACH_MM:
            kind = "body"
        elif not is_tip:
            kind = "limb"
        elif height_mm is None or height_mm < MIN_HAND_HEIGHT_MM:
            kind = "foot"
        else:
            kind = "hand"

        extremum = {
            "point": (float(region_x.mean() + x), float(region_y.mean() + y)),
            "height_mm": height_mm,
            "reach_mm": reach_mm,
            "is_tip": is_tip,
            "kind": kind,
        }

        blob["extrema"].append(extremum)

        if kind == "hand":
            blob["hands"].append(extremum)


class OneEuroFilter:
    # Casiez et al. 2012: smooths hard when still, follows fast moves
    def __init__(self, min_cutoff=ONE_EURO_MIN_CUTOFF, beta=ONE_EURO_BETA,
                 d_cutoff=ONE_EURO_D_CUTOFF):
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
        tau = 1.0 / (2.0 * np.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, value, timestamp):
        if self.value is None:
            self.value, self.time = value, timestamp
            return value

        dt = max(timestamp - self.time, 1e-3)
        self.time = timestamp

        speed = (value - self.value) / dt
        self.speed += self._alpha(self.d_cutoff, dt) * (speed - self.speed)

        cutoff = self.min_cutoff + self.beta * abs(self.speed)
        self.value += self._alpha(cutoff, dt) * (value - self.value)
        return self.value


class HandTracker:
    def __init__(self, hands=NUM_HANDS):
        self.hands = hands

        # Same smoothing for positions, scaled from 0..1 to pixels
        point_beta = ONE_EURO_BETA / (WIDTH / DECIMATION)

        self.z_filters = [OneEuroFilter() for _ in range(hands)]
        self.x_filters = [OneEuroFilter(beta=point_beta) for _ in range(hands)]
        self.y_filters = [OneEuroFilter(beta=point_beta) for _ in range(hands)]
        self.reset()

    def reset(self):
        for slot in range(self.hands):
            self._reset_filters(slot)

        self.z = [None] * self.hands
        self.height_mm = [None] * self.hands
        self.points = [None] * self.hands
        self.last_points = [None] * self.hands
        self.missing = [0] * self.hands

    def _reset_filters(self, slot):
        self.z_filters[slot].reset()
        self.x_filters[slot].reset()
        self.y_filters[slot].reset()

    def _assign(self, found, keep):
        slots = [None] * self.hands
        used = set()

        # Each hand keeps the id of the hand it was nearest to last frame,
        # so ids survive the player turning around
        pairs = []
        for slot, last in enumerate(self.last_points):
            if last is None:
                continue
            for hand in found + keep:
                gap = np.hypot(
                    hand["point"][0] - last[0], hand["point"][1] - last[1]
                )
                if gap <= MAX_HAND_JUMP_PX:
                    pairs.append((gap, slot, hand))

        for _, slot, hand in sorted(pairs, key=lambda pair: pair[0]):
            if slots[slot] is None and id(hand) not in used:
                slots[slot] = hand
                used.add(id(hand))

        # Only confident hands start a new id, filled left to right
        unmatched = [hand for hand in found if id(hand) not in used]
        unmatched.sort(key=lambda hand: hand["point"][0])
        for slot in range(self.hands):
            if slots[slot] is None and unmatched:
                slots[slot] = unmatched.pop(0)

        return slots

    def update(self, blobs, timestamp):
        extrema = [extremum for blob in blobs for extremum in blob["extrema"]]

        # Hands that reach farthest from their torso are the most reliable
        found = sorted(
            (e for e in extrema if e["kind"] == "hand"),
            key=lambda hand: hand["reach_mm"],
            reverse=True,
        )[:self.hands]

        # Near misses (a hand pulled in a little) can continue a track
        keep_reach = KEEP_REACH_FRACTION * MIN_HAND_REACH_MM
        keep = [
            e for e in extrema
            if e["kind"] == "body"
            and e["is_tip"]
            and e["reach_mm"] >= keep_reach
            and e["height_mm"] is not None
            and e["height_mm"] >= MIN_HAND_HEIGHT_MM
        ]

        low, high = HAND_HEIGHT_RANGE_MM

        for slot, hand in enumerate(self._assign(found, keep)):
            if hand is None:
                self.points[slot] = None
                self.missing[slot] += 1

                if self.missing[slot] > HOLD_FRAMES:
                    self.z[slot] = None
                    self.height_mm[slot] = None
                    self._reset_filters(slot)
                continue

            self.missing[slot] = 0

            point = (
                self.x_filters[slot](hand["point"][0], timestamp),
                self.y_filters[slot](hand["point"][1], timestamp),
            )
            self.points[slot] = point
            self.last_points[slot] = point
            self.height_mm[slot] = hand["height_mm"]

            z = (hand["height_mm"] - low) / (high - low)
            z = float(np.clip(z, 0.0, 1.0))

            self.z[slot] = self.z_filters[slot](z, timestamp)

        return list(self.z)


class SceneBackground:
    def __init__(self, depth_mm, sigma_mm, valid_ratio, fx,
                 color_mean=None, color_std=None, color_valid=None):
        self.depth = depth_mm
        self.stable = valid_ratio >= STABLE_VALID_RATIO
        self.empty = valid_ratio < EMPTY_VALID_RATIO

        model_sigma = (
            NOISE_MODEL_SCALE
            * depth_mm ** 2
            * SUBPIXEL_RMS
            / (fx * D435_BASELINE_MM)
        )
        self.sigma = np.maximum(sigma_mm, model_sigma)

        self.on_mm = np.maximum(K_SIGMA_ON * self.sigma, MIN_THRESHOLD_MM)
        self.off_mm = self.on_mm * (K_SIGMA_OFF / K_SIGMA_ON)

        self.color_mean = color_mean
        self.color_std = color_std
        self.color_valid = color_valid

        self.mask = np.zeros(depth_mm.shape, dtype=bool)
        self.score = np.zeros(depth_mm.shape, dtype=np.float32)

        # Raw depth / colour decisions of the last frame, for the debug view
        self.depth_foreground = self.mask
        self.color_foreground = self.mask

        # Focal length at the decimated resolution, to turn pixels into mm
        self.focal_px = fx / DECIMATION

    @property
    def has_color(self):
        return self.color_mean is not None

    def _color_change(self, color):
        valid = self.color_valid & (color.max(axis=2) > 0)

        # Brightness alpha: how much of the floor colour explains the pixel
        weight = 1.0 / self.color_std ** 2
        expected = self.color_mean
        alpha = (color * expected * weight).sum(axis=2) / np.maximum(
            (expected ** 2 * weight).sum(axis=2), 1e-6
        )

        # Chromaticity distortion: what is left after scaling brightness
        residual = (color - alpha[..., None] * expected) / self.color_std
        distortion = np.sqrt((residual ** 2).sum(axis=2))

        # Undo global light/exposure changes: most of the floor is free
        free = valid & ~self.mask
        if np.count_nonzero(free) > 500:
            alpha = alpha / max(float(np.median(alpha[free])), 1e-3)

        return valid, alpha, distortion

    def segment(self, current, color=None):
        valid = current > 0
        compare = valid & self.stable

        # Only things closer than the background count: pixels that look
        # farther are stereo shadows/noise, not players
        closer = np.zeros(current.shape, dtype=np.float32)
        closer[compare] = self.depth[compare] - current[compare]

        depth_fg = compare & (
            (closer > self.on_mm)
            | (self.mask & (closer > self.off_mm))
        )

        if self.has_color and color is not None:
            color_valid, alpha, distortion = self._color_change(color)

            cd_limit = np.where(self.mask, CD_OFF, CD_ON)
            color_fg = color_valid & (
                (distortion > cd_limit)
                | (alpha < DARK_ALPHA)
                | (alpha > BRIGHT_ALPHA)
            )

            # Depth is sure this is still the floor: a shadow, not a person
            depth_floor = compare & (closer < self.off_mm)

            fused = depth_fg | (color_fg & ~depth_floor)
        else:
            color_fg = np.zeros_like(depth_fg)

            # Nothing was seen here during capture (e.g. beyond MAX_DEPTH_M),
            # so anything inside the play band now is new
            fused = depth_fg | (valid & self.empty)

        self.depth_foreground = depth_fg
        self.color_foreground = color_fg

        # Temporal vote: one-frame dropouts and speckles don't flip a pixel
        self.score += MASK_SMOOTHING * (fused - self.score)
        foreground = (self.score > MASK_ON) | (
            self.mask & (self.score > MASK_OFF)
        )

        # Close before open: opening first erodes away any body pixel that
        # has a depth dropout nearby, which shreds the mask
        mask = foreground.astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, MORPH_KERNEL)
        mask = fill_small_holes(mask)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, MORPH_KERNEL)

        mask, blobs = find_blobs(mask, current, closer, self.focal_px)
        self.mask = mask > 0

        return closer, mask, blobs

    def update(self, current, color=None):
        # Keep a margin around players so their edges never leak in
        protected = cv2.dilate(
            self.mask.astype(np.uint8), MORPH_KERNEL, iterations=3
        ) > 0

        learn = (current > 0) & self.stable & ~protected
        self.depth[learn] += BG_LEARNING_RATE * (
            current[learn] - self.depth[learn]
        )

        if self.has_color and color is not None:
            learn = self.color_valid & (color.max(axis=2) > 0) & ~protected
            self.color_mean[learn] += BG_LEARNING_RATE * (
                color[learn] - self.color_mean[learn]
            )


def robust_stats(stack):
    # Median + MAD: robust per-pixel value and noise, ignoring zeros
    valid = stack > 0
    stack = stack.astype(np.float32)
    stack[~valid] = np.nan

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        median = np.nanmedian(stack, axis=0)
        mad = np.nanmedian(np.abs(stack - median), axis=0)

    median = np.nan_to_num(median, nan=0.0).astype(np.float32)
    sigma = 1.4826 * np.nan_to_num(mad, nan=0.0).astype(np.float32)
    return median, sigma, valid.mean(axis=0)


def capture_background(camera, wait_for_user=True):
    print("Clear the scene and keep the camera still.")

    if wait_for_user:
        input("Press Enter to capture the background...")

    # Let auto-exposure and the temporal filter settle first
    camera.set_auto(True)

    for _ in range(WARMUP_FRAMES):
        camera.read()

    if LOCK_EXPOSURE:
        camera.lock()

        for _ in range(WARMUP_FRAMES // 2):
            camera.read()

    depth_samples = []
    color_samples = []

    for _ in range(BACKGROUND_FRAMES):
        _, depth_mm, color = camera.read()

        if depth_mm is None:
            continue

        depth_samples.append(preprocess_depth(depth_mm))

        if color is not None:
            color_samples.append(np.round(color).astype(np.uint8))

    if not depth_samples:
        raise RuntimeError("Could not capture depth background.")

    depth, sigma, valid_ratio = robust_stats(np.stack(depth_samples))

    color_mean = color_std = color_valid = None

    if len(color_samples) >= BACKGROUND_FRAMES // 2:
        stack = np.stack(color_samples)
        color_mean, color_std, _ = robust_stats(stack)
        color_std = np.maximum(color_std, COLOR_MIN_STD)

        seen = (stack.max(axis=3) > 0).mean(axis=0)
        color_valid = seen >= STABLE_VALID_RATIO

    background = SceneBackground(
        depth, sigma, valid_ratio, camera.fx,
        color_mean, color_std, color_valid,
    )

    message = (
        f"Background captured: {background.stable.mean():.0%} stable depth, "
        f"median noise {np.median(background.sigma[background.stable]):.1f} mm"
    )
    if background.has_color:
        message += f", colour covers {background.color_valid.mean():.0%}"
    print(message + ".")

    return background


def draw_blobs(image, blobs):
    for index, blob in enumerate(blobs):
        x, y, w, h = blob["bbox"]
        cx, cy = blob["center"]

        cv2.rectangle(image, (x, y), (x + w, y + h), (0, 255, 0), 1)
        cv2.circle(image, (cx, cy), 3, (0, 255, 0), -1)
        cv2.putText(
            image,
            f"#{index} {blob['depth_mm'] / 1000:.2f} m",
            (x, max(y - 4, 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (0, 255, 0),
            1,
        )

        if blob["torso"] is not None:
            tx, ty = (int(v) for v in blob["torso"])
            cv2.drawMarker(image, (tx, ty), (255, 255, 255),
                           cv2.MARKER_CROSS, 12, 2)

            # Every extremum, linked to the torso, to help tune the limits
            for extremum in blob["extrema"]:
                ex, ey = (int(v) for v in extremum["point"])
                color = (255, 255, 255) if extremum["kind"] == "hand" \
                    else (128, 128, 128)

                cv2.line(image, (tx, ty), (ex, ey), color, 1)
                cv2.circle(image, (ex, ey), 3, color, -1)

                if extremum["kind"] != "hand":
                    cv2.putText(
                        image,
                        extremum["kind"],
                        (ex + 5, ey + 4),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.35,
                        color,
                        1,
                    )


HAND_COLORS = [(0, 255, 255), (255, 0, 255), (255, 255, 0), (0, 128, 255)]


def draw_hands(image, tracker):
    h = image.shape[0]
    top, bottom = 50, h - 20

    for slot, z in enumerate(tracker.z):
        color = HAND_COLORS[slot % len(HAND_COLORS)]

        # z gauge along the left edge: empty = waist height, full = high
        x = 10 + slot * 22
        cv2.rectangle(image, (x, top), (x + 14, bottom), color, 1)

        if z is not None:
            level = int(bottom - z * (bottom - top))
            cv2.rectangle(image, (x, level), (x + 14, bottom), color, -1)

        point = tracker.points[slot]
        if point is None or z is None:
            continue

        px, py = int(point[0]), int(point[1])
        cv2.circle(image, (px, py), 6, color, -1)
        cv2.putText(
            image,
            f"H{slot} z={z:.2f} ({tracker.height_mm[slot]:.0f} mm)",
            (px + 8, max(py - 8, 14)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
        )


def mask_debug_view(background, mask):
    # Green = depth says person, red = colour says person, yellow = both;
    # white outline = final fused mask
    view = np.zeros(mask.shape + (3,), dtype=np.uint8)
    view[..., 1] = background.depth_foreground * 200
    view[..., 2] = background.color_foreground * 200

    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(view, contours, -1, (255, 255, 255), 1)
    return view


def show(name, image):
    cv2.imshow(name, cv2.resize(
        image, None, fx=DISPLAY_SCALE, fy=DISPLAY_SCALE,
        interpolation=cv2.INTER_NEAREST,
    ))


def main():
    camera = None

    try:
        camera = Camera()
        background = capture_background(camera)

        colorizer = rs.colorizer()
        tracker = HandTracker()

        print("Press 'b' to recapture the background, 'q' to quit.")

        names = ["Tracking", "Stable Depth", "Foreground Mask"]

        while True:
            depth_frame, current, color = camera.read()

            if depth_frame is None:
                continue

            blurred = preprocess_depth(current)
            _, mask, blobs = background.segment(blurred, color)
            background.update(blurred, color)

            hand_z = tracker.update(blobs, time.perf_counter())

            depth_view = np.asanyarray(
                colorizer.colorize(depth_frame).get_data()
            ).copy()

            if color is not None:
                tracking_view = np.clip(color, 0, 255).astype(np.uint8)
            else:
                tracking_view = depth_view.copy()

            for view in (tracking_view, depth_view):
                draw_blobs(view, blobs)
                draw_hands(view, tracker)

            hands_text = "  ".join(
                "--" if z is None else f"{z:.2f}" for z in hand_z
            )

            cv2.putText(
                tracking_view,
                f"Hands z: {hands_text}",
                (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )

            show("Tracking", tracking_view)
            show("Stable Depth", depth_view)
            show("Foreground Mask", mask_debug_view(background, mask))

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break

            if key == ord("b"):
                background = capture_background(camera, wait_for_user=False)
                tracker.reset()
                continue

            if any(
                cv2.getWindowProperty(
                    name, cv2.WND_PROP_VISIBLE
                ) < 1
                for name in names
            ):
                break

    except (RuntimeError, ValueError) as error:
        print(f"Camera error: {error}")

    finally:
        if camera is not None:
            camera.stop()

        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
