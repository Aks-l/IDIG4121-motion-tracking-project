
import warnings

import cv2
import numpy as np
import pyrealsense2 as rs

# 848x480 is the D435's optimal depth resolution (Intel tuning guide)
WIDTH, HEIGHT, FPS = 848, 480, 30

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
    decimation.set_option(rs.option.filter_magnitude, 2)

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


def find_blobs(mask, depth_mm):
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
            "area": int(area),
            "depth_mm": float(np.median(blob_depth)) if blob_depth.size else 0.0,
        })

    blobs.sort(key=lambda blob: blob["area"], reverse=True)
    return clean, blobs


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

        mask, blobs = find_blobs(mask, current)
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

            # Display filtered depth
            depth_view = np.asanyarray(
                colorizer.colorize(depth_frame).get_data()
            )
            draw_blobs(depth_view, blobs)

            # Visualize how much closer than the background, in millimeters
            diff_view = np.clip(
                closer * 255.0 / 200.0, 0, 255
            ).astype(np.uint8)

            h, w = current.shape
            distance_m = current[h // 2, w // 2] / 1000.0

            cv2.putText(
                depth_view,
                f"Center: {distance_m:.2f} m  Blobs: {len(blobs)}",
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
