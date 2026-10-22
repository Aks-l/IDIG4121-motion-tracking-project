
# Hand tracking with the camera in front of the player, like a mirror.
#
# The RealSense depth is used to cut away everything outside a depth range
# (the unstable background), so MediaPipe's hand landmarker only sees the
# player. Depth then gives every hand its distance from the camera.

import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import pyrealsense2 as rs
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python import vision

from test_depth_camera import OneEuroFilter

WIDTH, HEIGHT, FPS = 848, 480, 30

# Show the image flipped, like a mirror. MediaPipe's handedness assumes a
# mirrored (selfie) image, so Left/Right also come out right this way.
MIRROR = True

# Depth range kept around the player; everything outside is cut out
NEAR_M = 0.3
FAR_M = 1.6
# Follow the player: the far cut sits this far behind their body, so the
# background is removed even when it is close behind them
AUTO_RANGE = True
BEHIND_BODY_M = 0.3
AUTO_RANGE_SMOOTHING = 0.05
# Step for the '[' and ']' keys that move the far cut
RANGE_STEP_M = 0.05

# Cut-out cleanup
MIN_REGION_PX = 1500
CLOSE_KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
# Depth holes (black) touching the player, e.g. the shadow along the edge
# of a hand, are kept within this many pixels
EDGE_HOLE_PX = 6
# Temporal vote on the cut-out mask, as in test_depth_camera.py
MASK_SMOOTHING = 0.5
MASK_ON = 0.6
MASK_OFF = 0.3
# Soft edge of the cut-out (Gaussian kernel, odd)
FEATHER_PX = 7
CUTOUT_GREY = 128

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/latest/hand_landmarker.task"
)
MODEL_PATH = Path(__file__).with_name("hand_landmarker.task")

NUM_HANDS = 2
MIN_DETECTION_CONFIDENCE = 0.5
MIN_PRESENCE_CONFIDENCE = 0.5
MIN_TRACKING_CONFIDENCE = 0.5

# Wrist and the four knuckles: the palm, which is flat and rarely hidden
PALM_IDS = [0, 5, 9, 13, 17]

# z = how far the hand is pushed out in front of the body:
# 0 = at the body, 1 = ARM_REACH_MM closer to the camera
ARM_REACH_MM = 600.0

# A tracked hand may move at most this far between frames to keep its id
MAX_HAND_JUMP_PX = 120.0
HOLD_FRAMES = 5

# 1€ filter: lower MIN_CUTOFF = less jitter, higher BETA = less lag
ONE_EURO_MIN_CUTOFF = 1.0
ONE_EURO_BETA = 20.0

HAND_COLORS = {"Left": (255, 128, 0), "Right": (0, 128, 255)}


def configure_sensor(depth_sensor):
    # Intel's "Hand" preset: tuned for hands and gestures, with good edges
    if depth_sensor.supports(rs.option.visual_preset):
        depth_sensor.set_option(
            rs.option.visual_preset, int(rs.rs400_visual_preset.hand)
        )

    if depth_sensor.supports(rs.option.emitter_enabled):
        depth_sensor.set_option(rs.option.emitter_enabled, 1)

    if depth_sensor.supports(rs.option.laser_power):
        laser_range = depth_sensor.get_option_range(rs.option.laser_power)
        depth_sensor.set_option(rs.option.laser_power, laser_range.max)


class FrontCamera:
    def __init__(self):
        self.pipeline = rs.pipeline()
        config = rs.config()
        config.enable_stream(rs.stream.depth, WIDTH, HEIGHT, rs.format.z16, FPS)
        config.enable_stream(rs.stream.color, WIDTH, HEIGHT, rs.format.bgr8, FPS)

        profile = self.pipeline.start(config)

        depth_sensor = profile.get_device().first_depth_sensor()
        configure_sensor(depth_sensor)
        self.depth_scale = depth_sensor.get_depth_scale()

        # Depth is mapped onto the colour image, since that is what
        # MediaPipe looks at: landmark (x, y) can then read its depth
        self.align = rs.align(rs.stream.color)

        self.spatial = rs.spatial_filter()
        self.temporal = rs.temporal_filter()
        # Persistency 3: reuse the last value if valid in 2 of the last 4
        self.temporal.set_option(rs.option.holes_fill, 3)

    def read(self):
        frames = self.align.process(self.pipeline.wait_for_frames())

        depth_frame = frames.get_depth_frame()
        color_frame = frames.get_color_frame()

        if not depth_frame or not color_frame:
            return None, None

        depth_frame = self.spatial.process(depth_frame)
        depth_frame = self.temporal.process(depth_frame)

        depth_mm = (
            np.asanyarray(depth_frame.get_data()).astype(np.float32)
            * self.depth_scale
            * 1000.0
        )
        color = np.asanyarray(color_frame.get_data())

        if MIRROR:
            depth_mm = depth_mm[:, ::-1]
            color = color[:, ::-1]

        return np.ascontiguousarray(depth_mm), np.ascontiguousarray(color)

    def stop(self):
        self.pipeline.stop()


class DepthCutout:
    # Keeps the pixels inside the depth range as a stable mask

    def __init__(self):
        self.far_m = FAR_M
        self.body_mm = None
        self.score = None
        self.mask = None

    def update(self, depth_mm, hand_boxes=()):
        near_mm, far_mm = NEAR_M * 1000.0, self.far_m * 1000.0

        if AUTO_RANGE:
            self._follow_body(depth_mm, near_mm, far_mm, hand_boxes)
            if self.body_mm is not None:
                far_mm = min(far_mm, self.body_mm + BEHIND_BODY_M * 1000.0)

        mask = self._solid_in_range(depth_mm, near_mm, far_mm)

        # Depth holes along the player's edges (the stereo shadow next to
        # a hand) belong to the player, not to the background. Only solid
        # regions grow, so background specks can't pull holes in.
        near_player = cv2.dilate(
            mask, cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (2 * EDGE_HOLE_PX + 1,) * 2
            )
        ) > 0
        mask[near_player & (depth_mm <= 0)] = 255

        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, CLOSE_KERNEL)

        # Temporal vote: single-frame dropouts don't flicker the cut-out
        if self.score is None:
            self.score = (mask > 0).astype(np.float32)
            self.mask = mask > 0

        self.score += MASK_SMOOTHING * ((mask > 0) - self.score)
        self.mask = (self.score > MASK_ON) | (
            self.mask & (self.score > MASK_OFF)
        )

        return self.mask, near_mm, far_mm

    def _solid_in_range(self, depth_mm, near_mm, far_mm):
        in_range = (depth_mm >= near_mm) & (depth_mm <= far_mm)
        mask = in_range.astype(np.uint8) * 255

        # Majority vote over 5x5: scattered pixels of a flickering
        # background fall away, the player (mostly in range) stays
        mask = cv2.medianBlur(mask, 5)
        return self._drop_small_regions(mask)

    def _follow_body(self, depth_mm, near_mm, far_mm, hand_boxes):
        # The body is the biggest solid region in the fixed range. Leave
        # the hands out so pushing them forward doesn't drag the range.
        solid = self._solid_in_range(depth_mm, near_mm, far_mm)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            solid, connectivity=8
        )

        if count < 2:
            return

        body = labels == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])

        for x0, y0, x1, y1 in hand_boxes:
            body[y0:y1, x0:x1] = False

        values = depth_mm[body & (depth_mm > 0)]
        if values.size < MIN_REGION_PX:
            return

        body_mm = float(np.median(values))

        if self.body_mm is None:
            self.body_mm = body_mm
        else:
            self.body_mm += AUTO_RANGE_SMOOTHING * (body_mm - self.body_mm)

    @staticmethod
    def _drop_small_regions(mask):
        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            mask, connectivity=8
        )

        keep = np.zeros(count, dtype=bool)
        keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= MIN_REGION_PX
        return np.where(keep[labels], 255, 0).astype(np.uint8)


def apply_cutout(color, mask):
    # Soft edge so MediaPipe doesn't see a hard, jagged outline
    alpha = cv2.GaussianBlur(
        mask.astype(np.float32), (FEATHER_PX, FEATHER_PX), 0
    )[..., None]
    grey = np.full_like(color, CUTOUT_GREY, dtype=np.float32)
    return (color * alpha + grey * (1.0 - alpha)).astype(np.uint8)


def load_landmarker():
    if not MODEL_PATH.exists():
        print(f"Downloading the MediaPipe hand model to {MODEL_PATH} ...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)

    options = vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=NUM_HANDS,
        min_hand_detection_confidence=MIN_DETECTION_CONFIDENCE,
        min_hand_presence_confidence=MIN_PRESENCE_CONFIDENCE,
        min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
    )
    return vision.HandLandmarker.create_from_options(options)


def palm_depth(depth_mm, palm, mask):
    # Median depth inside the palm polygon: robust to holes and fingers
    region = np.zeros(depth_mm.shape, dtype=np.uint8)
    cv2.fillConvexPoly(region, cv2.convexHull(palm.astype(np.int32)), 1)

    values = depth_mm[(region > 0) & mask & (depth_mm > 0)]
    return float(np.median(values)) if values.size else None


def read_hands(result, depth_mm, mask):
    h, w = depth_mm.shape
    hands = []

    for landmarks, handedness in zip(result.hand_landmarks, result.handedness):
        points = np.array([[p.x * w, p.y * h] for p in landmarks])
        palm = points[PALM_IDS]
        distance_mm = palm_depth(depth_mm, palm, mask)

        # A "hand" with no depth inside the kept range is something in the
        # cut-out background (or a false detection): ignore it
        if distance_mm is None:
            continue

        best = handedness[0]
        hands.append({
            "label": best.category_name,
            "label_score": best.score,
            "points": points,
            "center": palm.mean(axis=0),
            "distance_mm": distance_mm,
        })

    return hands


class FrontHandTracker:
    def __init__(self, hands=NUM_HANDS):
        self.hands = hands

        # Landmarks are in pixels, so scale beta from 0..1 units
        point_beta = ONE_EURO_BETA / WIDTH

        self.point_filters = [
            OneEuroFilter(ONE_EURO_MIN_CUTOFF, point_beta)
            for _ in range(hands)
        ]
        self.z_filters = [
            OneEuroFilter(ONE_EURO_MIN_CUTOFF, ONE_EURO_BETA)
            for _ in range(hands)
        ]
        self.reset()

    def reset(self):
        for slot in range(self.hands):
            self.point_filters[slot].reset()
            self.z_filters[slot].reset()

        self.state = [None] * self.hands
        self.last_center = [None] * self.hands
        self.label_votes = [{} for _ in range(self.hands)]
        self.missing = [0] * self.hands

    def _assign(self, found):
        slots = [None] * self.hands
        used = set()

        # Each hand keeps the id of the hand it was nearest to last frame
        pairs = []
        for slot, last in enumerate(self.last_center):
            if last is None:
                continue
            for index, hand in enumerate(found):
                gap = float(np.hypot(*(hand["center"] - last)))
                if gap <= MAX_HAND_JUMP_PX:
                    pairs.append((gap, slot, index))

        for _, slot, index in sorted(pairs):
            if slots[slot] is None and index not in used:
                slots[slot] = found[index]
                used.add(index)

        # New hands go to the slot of their side (0 = Left, 1 = Right) if
        # it is free, otherwise to any free slot
        for index, hand in enumerate(found):
            if index in used:
                continue

            preferred = 0 if hand["label"] == "Left" else 1
            free = [s for s in range(self.hands) if slots[s] is None]
            if not free:
                break

            slot = preferred if preferred in free else free[0]
            slots[slot] = hand
            used.add(index)

        return slots

    def update(self, hands, body_mm, width, height, timestamp):
        for slot, hand in enumerate(self._assign(hands)):
            if hand is None:
                self.missing[slot] += 1

                if self.missing[slot] > HOLD_FRAMES:
                    self.state[slot] = None
                    self.label_votes[slot] = {}
                    self.point_filters[slot].reset()
                    self.z_filters[slot].reset()
                continue

            self.missing[slot] = 0

            # The filter updates its array in place: hand it a copy
            points = self.point_filters[slot](
                hand["points"].copy(), timestamp
            ).copy()
            center = points[PALM_IDS].mean(axis=0)
            self.last_center[slot] = center

            # Handedness can flicker for a frame or two: keep a running vote
            votes = self.label_votes[slot]
            votes[hand["label"]] = votes.get(hand["label"], 0) + hand["label_score"]
            label = max(votes, key=votes.get)

            # Push: how far the palm is in front of the body
            reference = body_mm if body_mm is not None else hand["distance_mm"]
            z = (reference - hand["distance_mm"]) / ARM_REACH_MM
            z = self.z_filters[slot](float(np.clip(z, 0.0, 1.0)), timestamp)

            self.state[slot] = {
                "label": label,
                "points": points,
                "x": float(center[0] / width),
                "y": float(center[1] / height),
                "z": z,
                "distance_mm": hand["distance_mm"],
            }

        return list(self.state)

    def hand_boxes(self, margin=40):
        boxes = []
        for hand in self.state:
            if hand is None:
                continue
            x0, y0 = hand["points"].min(axis=0) - margin
            x1, y1 = hand["points"].max(axis=0) + margin
            boxes.append((
                max(int(x0), 0), max(int(y0), 0), int(x1), int(y1)
            ))
        return boxes


CONNECTIONS = [
    (c.start, c.end)
    for c in vision.HandLandmarksConnections.HAND_CONNECTIONS
]


def draw_hands(image, tracked):
    for slot, hand in enumerate(tracked):
        if hand is None:
            continue

        color = HAND_COLORS.get(hand["label"], (255, 255, 255))
        points = [tuple(point) for point in hand["points"].astype(int).tolist()]

        for start, end in CONNECTIONS:
            cv2.line(image, points[start], points[end], color, 2)
        for point in points:
            cv2.circle(image, point, 3, (255, 255, 255), -1)

        cx, cy = (int(v) for v in hand["points"][PALM_IDS].mean(axis=0))
        cv2.putText(
            image,
            f"{hand['label']} z={hand['z']:.2f} ({hand['distance_mm']:.0f} mm)",
            (cx - 60, cy + 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            2,
        )

        # z gauge: empty = at the body, full = arm stretched to the camera
        x = 10 + slot * 22
        top, bottom = 60, image.shape[0] - 20
        cv2.rectangle(image, (x, top), (x + 14, bottom), color, 1)
        level = int(bottom - hand["z"] * (bottom - top))
        cv2.rectangle(image, (x, level), (x + 14, bottom), color, -1)


def main():
    camera = None
    landmarker = None

    try:
        landmarker = load_landmarker()
        camera = FrontCamera()

        cutout = DepthCutout()
        tracker = FrontHandTracker()
        last_ms = -1

        print("Press '[' / ']' to move the far cut, 'q' to quit.")

        names = ["Hands", "What MediaPipe sees"]

        while True:
            depth_mm, color = camera.read()

            if depth_mm is None:
                continue

            mask, near_mm, far_mm = cutout.update(
                depth_mm, tracker.hand_boxes()
            )
            cut = apply_cutout(color, mask)

            # VIDEO mode needs strictly increasing timestamps in ms
            now = time.perf_counter()
            timestamp_ms = max(int(now * 1000), last_ms + 1)
            last_ms = timestamp_ms

            rgb = cv2.cvtColor(cut, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = landmarker.detect_for_video(image, timestamp_ms)

            hands = read_hands(result, depth_mm, mask)
            tracked = tracker.update(
                hands, cutout.body_mm, WIDTH, HEIGHT, now
            )

            view = color.copy()
            # Dim what was cut out, so the kept range is visible
            view[~mask] = (view[~mask] * 0.35).astype(np.uint8)
            draw_hands(view, tracked)

            body_text = (
                "--" if cutout.body_mm is None
                else f"{cutout.body_mm / 1000:.2f} m"
            )
            cv2.putText(
                view,
                f"Range {near_mm / 1000:.2f}-{far_mm / 1000:.2f} m  "
                f"body {body_text}",
                (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2,
            )

            cv2.imshow("Hands", view)
            cv2.imshow("What MediaPipe sees", cut)

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break
            if key == ord("]"):
                cutout.far_m = min(cutout.far_m + RANGE_STEP_M, 4.0)
            if key == ord("["):
                cutout.far_m = max(cutout.far_m - RANGE_STEP_M, NEAR_M + 0.1)

            if any(
                cv2.getWindowProperty(name, cv2.WND_PROP_VISIBLE) < 1
                for name in names
            ):
                break

    except (RuntimeError, ValueError) as error:
        print(f"Camera error: {error}")

    finally:
        if camera is not None:
            camera.stop()

        if landmarker is not None:
            landmarker.close()

        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
