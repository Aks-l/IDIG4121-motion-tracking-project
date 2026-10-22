
import cv2
import numpy as np
import pyrealsense2 as rs

WIDTH, HEIGHT, FPS = 640, 480, 30

BLUR_KERNEL = (7, 7)
THRESHOLD_MM = 30  # Detect depth changes greater than 3 cm
MORPH_KERNEL = np.ones((3, 3), np.uint8)


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

    # RealSense depth post-processing filters
    decimation = rs.decimation_filter()
    decimation.set_option(rs.option.filter_magnitude, 2)

    to_disparity = rs.disparity_transform(True)
    spatial = rs.spatial_filter()
    temporal = rs.temporal_filter()
    to_depth = rs.disparity_transform(False)
    hole_filling = rs.hole_filling_filter()

    filters = (
        decimation,
        to_disparity,
        spatial,
        temporal,
        to_depth,
        hole_filling,
    )

    return pipeline, profile, filters


def get_filtered_depth(pipeline, filters):
    frames = pipeline.wait_for_frames()
    depth_frame = frames.get_depth_frame()

    if not depth_frame:
        return None, None

    # Apply SDK filters in sequence
    for filter_ in filters:
        depth_frame = filter_.process(depth_frame)

    depth_mm = (
        np.asanyarray(depth_frame.get_data()).astype(np.float32)
        * depth_frame.get_units()
        * 1000.0
    )

    return depth_frame, depth_mm


def preprocess_depth(depth_mm):
    # Keep invalid depth pixels invalid
    valid = depth_mm > 0

    blurred = cv2.GaussianBlur(
        depth_mm,
        BLUR_KERNEL,
        0,
    )

    blurred[~valid] = 0
    return blurred


def capture_background(pipeline, filters):
    print("Clear the scene and keep the camera still.")
    input("Press Enter to capture the depth background...")

    samples = []

    # Let the temporal filter settle first
    for _ in range(15):
        get_filtered_depth(pipeline, filters)

    # Capture multiple filtered frames
    for _ in range(30):
        _, depth_mm = get_filtered_depth(pipeline, filters)

        if depth_mm is not None:
            samples.append(depth_mm)

    if not samples:
        raise RuntimeError("Could not capture depth background.")

    stack = np.stack(samples, axis=0)

    # Ignore invalid zero-depth samples
    stack[stack <= 0] = np.nan

    with np.errstate(invalid="ignore"):
        background = np.nanmedian(stack, axis=0)

    background = np.nan_to_num(
        background,
        nan=0.0,
    ).astype(np.float32)

    return preprocess_depth(background)


def create_mask(current, background):
    # Compare only pixels valid in both frames
    valid = (current > 0) & (background > 0)

    diff = np.zeros(current.shape, dtype=np.float32)
    diff[valid] = np.abs(current[valid] - background[valid])

    mask = (valid & (diff > THRESHOLD_MM)).astype(np.uint8) * 255

    mask = cv2.morphologyEx(
        mask, cv2.MORPH_OPEN, MORPH_KERNEL
    )
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, MORPH_KERNEL
    )

    return diff, mask


def main():
    pipeline = None

    try:
        pipeline, profile, filters = start_camera()

        # Get the depth scale from the sensor
        depth_sensor = profile.get_device().first_depth_sensor()
        depth_scale = depth_sensor.get_depth_scale()

        background = capture_background(pipeline, filters)

        colorizer = rs.colorizer()

        while True:
            depth_frame, current = get_filtered_depth(
                pipeline, filters
            )

            if depth_frame is None:
                continue

            blurred = preprocess_depth(current)
            diff, mask = create_mask(blurred, background)

            # Display filtered depth
            depth_view = np.asanyarray(
                colorizer.colorize(depth_frame).get_data()
            )

            # Visualize difference in millimeters
            diff_view = np.clip(
                diff * 255.0 / 200.0, 0, 255
            ).astype(np.uint8)

            h, w = current.shape
            distance_m = depth_frame.get_distance(w // 2, h // 2)

            cv2.putText(
                depth_view,
                f"Center: {distance_m:.2f} m",
                (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
            )

            cv2.imshow("Stable Depth", depth_view)
            cv2.imshow("Depth Difference", diff_view)
            cv2.imshow("Foreground Mask", mask)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

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
