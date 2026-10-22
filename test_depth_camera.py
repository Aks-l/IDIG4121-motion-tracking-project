
import time
import warnings

import cv2
import numpy as np
import pyrealsense2 as rs

# 848x480 is the D435's optimal depth resolution (Intel tuning guide)
WIDTH, HEIGHT, FPS = 848, 480, 30
DECIMATION = 2

# Play area: anything outside this depth band is ignored
MIN_DEPTH_M = 0.3
MAX_DEPTH_M = 4.0

# Stop auto-exposure from shifting the depth when a player walks in
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

# Slowly absorb drift into the background where nobody is standing
BG_LEARNING_RATE = 0.01

MIN_BLOB_AREA = 150

# Hand tracking (top-down view): every blob can hold several hands, the
# image is split into vertical lanes, one hand per lane, and only the
# hand's y position is reported (0 = top)
NUM_LANES = 2
# Remap this part of the image height to the full 0..1 range
PLAY_Y_RANGE = (0.1, 0.9)
INVERT_Y = False
# Pixels this close to the image edge mean the arm enters the frame there
BORDER_MARGIN_PX = 4
# Real hand length (wrist to fingertip); converted to pixels per depth
HAND_LENGTH_MM = 180.0
# Palm centre = average of points at least this share of the widest spot
PALM_PEAK_RATIO = 0.85
# Something must stick this far into the frame to count as a hand
MIN_REACH_MM = 80.0
# A second hand in the same blob (e.g. both arms joined through the body)
# must stick out at least this far from the rest of the blob
MIN_BRANCH_MM = 200.0
MAX_HANDS_PER_BLOB = 4
# Keep the last y for a few frames when a hand drops out
HOLD_FRAMES = 5

# 1€ filter: lower MIN_CUTOFF = less jitter, higher BETA = less lag
ONE_EURO_MIN_CUTOFF = 1.0
ONE_EURO_BETA = 20.0
ONE_EURO_D_CUTOFF = 1.0


def start_camera():
    pipeline = rs.pipeline()
    config = rs.config()

    config.enable_stream(
        rs.stream.depth,
        WIDTH,
        HEIGHT,
        rs.format.z16,
        FPS,
    )

    profile = pipeline.start(config)
    depth_sensor = profile.get_device().first_depth_sensor()
    configure_sensor(depth_sensor)

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
    filters = (
        decimation,
        threshold,
        to_disparity,
        spatial,
        temporal,
        to_depth,
    )

    return pipeline, profile, depth_sensor, filters


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


def set_auto_exposure(depth_sensor, enabled):
    if depth_sensor.supports(rs.option.enable_auto_exposure):
        depth_sensor.set_option(
            rs.option.enable_auto_exposure, 1 if enabled else 0
        )


def lock_exposure(pipeline, depth_sensor):
    if not depth_sensor.supports(rs.option.enable_auto_exposure):
        return

    depth_frame = pipeline.wait_for_frames().get_depth_frame()
    key = rs.frame_metadata_value.actual_exposure

    if not depth_frame or not depth_frame.supports_frame_metadata(key):
        print("Exposure metadata unavailable, keeping auto-exposure on.")
        return

    exposure_range = depth_sensor.get_option_range(rs.option.exposure)
    exposure = float(np.clip(
        depth_frame.get_frame_metadata(key),
        exposure_range.min,
        exposure_range.max,
    ))

    set_auto_exposure(depth_sensor, False)
    depth_sensor.set_option(rs.option.exposure, exposure)
    print(f"Exposure locked at {exposure:.0f} us.")


def get_filtered_depth(pipeline, filters, depth_scale):
    frames = pipeline.wait_for_frames()
    depth_frame = frames.get_depth_frame()

    if not depth_frame:
        return None, None

    # Apply SDK filters in sequence
    for filter_ in filters:
        depth_frame = filter_.process(depth_frame)

    depth_frame = depth_frame.as_depth_frame()

    depth_mm = (
        np.asanyarray(depth_frame.get_data()).astype(np.float32)
        * depth_scale
        * 1000.0
    )

    return depth_frame, depth_mm


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


def find_blobs(mask, depth_mm, fx):
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

        blobs.append({
            "bbox": tuple(stats[label, :4]),
            "center": tuple(centroids[label].astype(int)),
            "hands": find_hands(pixels, depth_mm, fx),
            "area": int(area),
            "depth_mm": float(np.median(blob_depth)) if blob_depth.size else 0.0,
        })

    blobs.sort(key=lambda blob: blob["area"], reverse=True)
    return clean, blobs


def geodesic_distance(blob, seeds):
    # Grow from the entry one ring at a time, staying inside the blob, so a
    # bent arm is measured along the arm and not straight across the gap.
    # Alternating cross/square kernels gives a near-round distance.
    blob = blob.astype(np.uint8)
    reached = (seeds & (blob > 0)).astype(np.uint8)
    dist = np.full(blob.shape, -1.0, dtype=np.float32)
    dist[reached > 0] = 0.0

    kernels = (
        cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3)),
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
    )
    step = 0

    while True:
        grown = cv2.dilate(reached, kernels[step % 2]) & blob
        new = (grown > 0) & (reached == 0)

        if not new.any():
            return dist

        step += 1
        dist[new] = step
        reached = grown


def component_at(mask, y, x):
    _, labels = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
    return labels == labels[y, x]


def find_hands(pixels, depth_mm, fx):
    h, w = pixels.shape
    m = BORDER_MARGIN_PX

    # Work on the blob's bounding box only, it is much faster
    ys, xs = np.nonzero(pixels)
    y0, y1 = ys.min(), ys.max() + 1
    x0, x1 = xs.min(), xs.max() + 1
    blob = pixels[y0:y1, x0:x1]
    depth = depth_mm[y0:y1, x0:x1]

    valid = blob & (depth > 0)
    blob_z = float(np.median(depth[valid])) if valid.any() else 1500.0
    z = np.where(depth > 0, depth, blob_z)

    # The D435 has no depth in a band on the left edge (wider for closer
    # objects), so an arm from the left stops short of the image border
    rows = np.arange(y0, y1)[:, None]
    cols = np.arange(x0, x1)[None, :]
    left_band = fx * D435_BASELINE_MM / z
    entry = blob & (
        (cols < m + left_band) | (cols >= w - m)
        | (rows < m) | (rows >= h - m)
    )

    # Distance to the blob edge: peaks in the middle of the palm
    inside = cv2.distanceTransform(blob.astype(np.uint8), cv2.DIST_L2, 5)

    if not entry.any():
        # Nothing comes in from outside (a lone hand, or a whole person in
        # view), so measure from the thickest part instead
        entry = blob & (inside >= inside.max())

    reach = geodesic_distance(blob, entry)

    # Hands are the tips that stick out. Walk from the farthest point down:
    # a tip only counts if, going MIN_BRANCH_MM back towards the entry, it
    # does not join something that reaches farther. So fingers, elbows and
    # the sides of the body are skipped, but a second arm is kept.
    hands = []
    todo = blob & (reach >= 0)

    while todo.any() and len(hands) < MAX_HANDS_PER_BLOB:
        ty, tx = np.unravel_index(
            np.where(todo, reach, -1.0).argmax(), reach.shape
        )
        top = reach[ty, tx]
        px_per_mm = fx / z[ty, tx]

        # Everything left is shorter, so nothing more sticks in far enough
        if top < MIN_REACH_MM * px_per_mm:
            break

        branch = component_at(
            blob & (reach >= top - MIN_BRANCH_MM * px_per_mm), ty, tx
        )
        todo &= ~branch

        if reach[branch].max() > top:
            continue

        hand = component_at(
            blob & (reach >= top - HAND_LENGTH_MM * px_per_mm), ty, tx
        )
        tip_y, tip_x = np.nonzero(hand & (reach >= top - 2.0))

        # Palm centre: the widest spot of the hand, averaged for stability
        palm_dist = np.where(hand, inside, 0.0)
        best = palm_dist.max()
        palm_y, palm_x = np.nonzero(palm_dist >= best * PALM_PEAK_RATIO)

        hands.append({
            "palm": (float(palm_x.mean() + x0), float(palm_y.mean() + y0)),
            "tip": (float(tip_x.mean() + x0), float(tip_y.mean() + y0)),
            "radius": float(best),
        })

    return hands


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
    def __init__(self, lanes=NUM_LANES):
        self.lanes = lanes
        self.filters = [OneEuroFilter() for _ in range(lanes)]
        self.y = [None] * lanes
        self.raw_points = [None] * lanes
        # Last hand each lane followed, kept through short dropouts
        self.last = [None] * lanes
        self.missing = [0] * lanes
        # Every hand seen this frame, also the ones no lane picked
        self.hands = []

    def reset(self):
        for lane in range(self.lanes):
            self.filters[lane].reset()
            self.y[lane] = None
            self.raw_points[lane] = None
            self.last[lane] = None
            self.missing[lane] = 0
        self.hands = []

    def pick(self, lane, candidates):
        if not candidates:
            return None

        # Stick with the hand nearest to last frame's, so a second hand
        # entering the lane does not steal it
        last = self.last[lane]
        if last is None:
            return candidates[0]

        return min(
            candidates,
            key=lambda hand: np.hypot(
                hand["palm"][0] - last["palm"][0],
                hand["palm"][1] - last["palm"][1],
            ),
        )

    def update(self, blobs, width, height, timestamp):
        lane_width = width / self.lanes
        self.hands = [hand for blob in blobs for hand in blob["hands"]]

        in_lane = [[] for _ in range(self.lanes)]
        for hand in self.hands:
            lane = min(int(hand["palm"][0] // lane_width), self.lanes - 1)
            in_lane[lane].append(hand)

        found = [self.pick(lane, in_lane[lane]) for lane in range(self.lanes)]

        low, high = PLAY_Y_RANGE

        for lane, point in enumerate(found):
            self.raw_points[lane] = point

            if point is None:
                self.missing[lane] += 1

                if self.missing[lane] > HOLD_FRAMES:
                    self.y[lane] = None
                    self.last[lane] = None
                    self.filters[lane].reset()
                continue

            self.missing[lane] = 0
            self.last[lane] = point

            y = point["palm"][1] / (height - 1)
            y = float(np.clip((y - low) / (high - low), 0.0, 1.0))

            if INVERT_Y:
                y = 1.0 - y

            self.y[lane] = self.filters[lane](y, timestamp)

        return list(self.y)


class DepthBackground:
    def __init__(self, depth_mm, sigma_mm, valid_ratio, fx):
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

        # The depth image is decimated, so its focal length shrinks too
        self.fx_px = fx / DECIMATION

        self.mask = np.zeros(depth_mm.shape, dtype=bool)

    def segment(self, current):
        valid = current > 0
        compare = valid & self.stable

        # Only things closer than the background count: pixels that look
        # farther are stereo shadows/noise, not players
        closer = np.zeros(current.shape, dtype=np.float32)
        closer[compare] = self.depth[compare] - current[compare]

        foreground = compare & (
            (closer > self.on_mm)
            | (self.mask & (closer > self.off_mm))
        )

        # Nothing was seen here during capture (e.g. beyond MAX_DEPTH_M),
        # so anything inside the play band now is new
        foreground |= valid & self.empty

        mask = foreground.astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, MORPH_KERNEL)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, MORPH_KERNEL)

        mask, blobs = find_blobs(mask, current, self.fx_px)
        self.mask = mask > 0

        return closer, mask, blobs

    def update(self, current):
        # Keep a margin around players so their edges never leak in
        protected = cv2.dilate(
            self.mask.astype(np.uint8), MORPH_KERNEL, iterations=3
        ) > 0

        learn = (current > 0) & self.stable & ~protected
        self.depth[learn] += BG_LEARNING_RATE * (
            current[learn] - self.depth[learn]
        )


def capture_background(pipeline, filters, depth_sensor, depth_scale, fx,
                       wait_for_user=True):
    print("Clear the scene and keep the camera still.")

    if wait_for_user:
        input("Press Enter to capture the depth background...")

    # Let auto-exposure and the temporal filter settle first
    set_auto_exposure(depth_sensor, True)

    for _ in range(WARMUP_FRAMES):
        get_filtered_depth(pipeline, filters, depth_scale)

    if LOCK_EXPOSURE:
        lock_exposure(pipeline, depth_sensor)

        for _ in range(WARMUP_FRAMES // 2):
            get_filtered_depth(pipeline, filters, depth_scale)

    samples = []

    for _ in range(BACKGROUND_FRAMES):
        _, depth_mm = get_filtered_depth(pipeline, filters, depth_scale)

        if depth_mm is not None:
            samples.append(preprocess_depth(depth_mm))

    if not samples:
        raise RuntimeError("Could not capture depth background.")

    stack = np.stack(samples, axis=0)

    valid = stack > 0
    valid_ratio = valid.mean(axis=0)

    # Ignore invalid zero-depth samples
    stack[~valid] = np.nan

    # Median + MAD: robust per-pixel depth and noise estimate
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        median = np.nanmedian(stack, axis=0)
        mad = np.nanmedian(np.abs(stack - median), axis=0)

    median = np.nan_to_num(median, nan=0.0).astype(np.float32)
    sigma = 1.4826 * np.nan_to_num(mad, nan=0.0).astype(np.float32)

    background = DepthBackground(median, sigma, valid_ratio, fx)

    print(
        f"Background captured: {background.stable.mean():.0%} stable, "
        f"{background.empty.mean():.0%} empty, "
        f"median noise {np.median(background.sigma[background.stable]):.1f} mm."
    )

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


def draw_hands(image, tracker):
    h, w = image.shape[:2]
    lane_width = w / tracker.lanes
    low, high = PLAY_Y_RANGE

    for lane in range(1, tracker.lanes):
        x = int(lane * lane_width)
        cv2.line(image, (x, 0), (x, h), (255, 255, 255), 1)

    # Every detected hand: palm outline, palm centre and fingertip.
    # Hands a lane uses are red, extra hands are grey.
    for hand in tracker.hands:
        used = any(hand is point for point in tracker.raw_points)
        color = (0, 0, 255) if used else (160, 160, 160)

        palm = tuple(int(v) for v in hand["palm"])
        tip = tuple(int(v) for v in hand["tip"])

        cv2.circle(image, palm, max(int(hand["radius"]), 3), color, 1)
        cv2.circle(image, palm, 4, color, -1)
        cv2.circle(image, tip, 3, (255, 0, 255), -1)
        cv2.line(image, palm, tip, (255, 0, 255), 1)

    for lane, y in enumerate(tracker.y):
        x0 = int(lane * lane_width)
        x1 = int((lane + 1) * lane_width)

        if y is None:
            continue

        # Convert the smoothed 0..1 value back to a row for display
        shown = 1.0 - y if INVERT_Y else y
        row = int((low + shown * (high - low)) * (h - 1))

        cv2.line(image, (x0 + 4, row), (x1 - 4, row), (0, 255, 255), 3)
        cv2.putText(
            image,
            f"y={y:.2f}",
            (x0 + 8, max(row - 8, 14)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 255),
            1,
        )


def main():
    pipeline = None

    try:
        pipeline, profile, depth_sensor, filters = start_camera()

        # Get the depth scale from the sensor
        depth_scale = depth_sensor.get_depth_scale()

        # Full-resolution focal length, used by the stereo noise model
        fx = (
            profile.get_stream(rs.stream.depth)
            .as_video_stream_profile()
            .get_intrinsics()
            .fx
        )

        background = capture_background(
            pipeline, filters, depth_sensor, depth_scale, fx
        )

        colorizer = rs.colorizer()
        tracker = HandTracker()

        print("Press 'b' to recapture the background, 'q' to quit.")

        while True:
            depth_frame, current = get_filtered_depth(
                pipeline, filters, depth_scale
            )

            if depth_frame is None:
                continue

            blurred = preprocess_depth(current)
            closer, mask, blobs = background.segment(blurred)
            background.update(blurred)

            h, w = current.shape

            hand_y = tracker.update(blobs, w, h, time.perf_counter())

            # Display filtered depth
            depth_view = np.asanyarray(
                colorizer.colorize(depth_frame).get_data()
            )
            draw_blobs(depth_view, blobs)
            draw_hands(depth_view, tracker)

            # Visualize how much closer than the background, in millimeters
            diff_view = np.clip(
                closer * 255.0 / 200.0, 0, 255
            ).astype(np.uint8)

            hands_text = "  ".join(
                "--" if y is None else f"{y:.2f}" for y in hand_y
            )

            cv2.putText(
                depth_view,
                f"Hands y: {hands_text}",
                (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )

            cv2.imshow("Stable Depth", depth_view)
            cv2.imshow("Depth Difference", diff_view)
            cv2.imshow("Foreground Mask", mask)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break

            if key == ord("b"):
                background = capture_background(
                    pipeline, filters, depth_sensor, depth_scale, fx,
                    wait_for_user=False,
                )
                tracker.reset()
                continue

            names = [
                "Stable Depth",
                "Depth Difference",
                "Foreground Mask",
            ]

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
        if pipeline is not None:
            pipeline.stop()

        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
