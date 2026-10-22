
# Hand tracking with the camera in front of the players, like a mirror.
#
# MediaPipe's pose model finds every person and their hands in the colour
# image; only the centre of each hand is kept. Depth is read at just those
# few points (no full-frame alignment, masking or filtering) to get each
# hand's distance and to ignore anyone outside the play range.

import time
import urllib.request
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import pyrealsense2 as rs
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python import vision

from test_depth_camera import OneEuroFilter

WIDTH, HEIGHT, FPS = 848, 480, 30

# Output and display coordinates are flipped, like a mirror
MIRROR = True
# Drawing the window costs time too; turn off when a game reads the data
SHOW_WINDOW = True

# Players are tracked between these distances; anyone else is ignored
NEAR_M = 0.5
FAR_M = 2.6

MAX_PEOPLE = 4
# "lite" is the fastest; "full" is steadier at a distance
POSE_MODEL = "lite"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_{0}/float16/latest/pose_landmarker_{0}.task"
)
MIN_DETECTION_CONFIDENCE = 0.5
MIN_PRESENCE_CONFIDENCE = 0.5
MIN_TRACKING_CONFIDENCE = 0.5

# Pose landmarks: wrist, pinky, index, thumb of each hand (the hand centre
# is their average) and the shoulders/hips for the body centre
HAND_LANDMARKS = {"Left": (15, 17, 19, 21), "Right": (16, 18, 20, 22)}
TORSO_LANDMARKS = (11, 12, 23, 24)
MIN_VISIBILITY = 0.5

# Depth is the median of a small patch around each point
DEPTH_PATCH_PX = 3

# z = how far the hand is pushed out in front of the body:
# 0 = at the body, 1 = ARM_REACH_MM closer to the camera
ARM_REACH_MM = 600.0

# A person may move at most this far between frames to keep their id
MAX_PERSON_JUMP_PX = 150.0
HOLD_FRAMES = 5

# Consistency: people and hands are matched to where their last
# HISTORY_FRAMES positions predict them to be, not to the model's labels
HISTORY_FRAMES = 3
# Never extrapolate further than this (s) after a track was last seen
MAX_PREDICT_S = 0.2
# Hands whose two possible pairings are this close (px) are too close to
# call (hands together/crossing): keep the pairing of the recent frames
SWAP_MARGIN_PX = 25.0
# The model's Left/Right only renames a person's hands once it disagreed
# in this share of the last LABEL_VOTE_FRAMES frames
LABEL_VOTE_FRAMES = 15
LABEL_SWAP_SHARE = 0.8
# When matching people, every mm of difference in distance from the camera
# counts as this many px: two people crossing at different depths keep ids
PERSON_DEPTH_WEIGHT = 0.15

# 1€ filter: lower MIN_CUTOFF = less jitter, higher BETA = less lag
ONE_EURO_MIN_CUTOFF = 1.0
ONE_EURO_BETA = 20.0

PERSON_COLORS = [(0, 200, 255), (255, 0, 200), (0, 255, 0), (255, 200, 0)]


def configure_sensor(depth_sensor):
    if depth_sensor.supports(rs.option.visual_preset):
        depth_sensor.set_option(
            rs.option.visual_preset,
            int(rs.rs400_visual_preset.high_density),
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
        self.depth_mm_per_unit = depth_sensor.get_depth_scale() * 1000.0

        # Calibration to map a colour pixel into the depth image
        depth_profile = (
            profile.get_stream(rs.stream.depth).as_video_stream_profile()
        )
        color_profile = (
            profile.get_stream(rs.stream.color).as_video_stream_profile()
        )
        self.depth_intrinsics = depth_profile.get_intrinsics()
        self.color_intrinsics = color_profile.get_intrinsics()
        self.color_to_depth = color_profile.get_extrinsics_to(depth_profile)

    def read(self):
        frames = self.pipeline.wait_for_frames()
        depth_frame = frames.get_depth_frame()
        color_frame = frames.get_color_frame()

        if not depth_frame or not color_frame:
            return None, None

        # No copies or conversions: depth stays raw, read only where needed
        return (
            np.asanyarray(depth_frame.get_data()),
            np.asanyarray(color_frame.get_data()),
        )

    def depth_at(self, depth_raw, color_xy, guess_mm):
        # The depth camera sits beside the colour one, so where a colour
        # pixel lands in the depth image depends on its distance. Guess,
        # look up, and refine once with the measured distance.
        distance_mm = guess_mm

        for _ in range(2):
            point = rs.rs2_deproject_pixel_to_point(
                self.color_intrinsics,
                [float(color_xy[0]), float(color_xy[1])],
                distance_mm / 1000.0,
            )
            point = rs.rs2_transform_point_to_point(self.color_to_depth, point)
            u, v = rs.rs2_project_point_to_pixel(self.depth_intrinsics, point)

            measured = patch_median(depth_raw, u, v)
            if measured is None:
                return None

            distance_mm = measured * self.depth_mm_per_unit

        return distance_mm

    def stop(self):
        self.pipeline.stop()


def patch_median(depth_raw, u, v):
    h, w = depth_raw.shape
    x, y = int(round(u)), int(round(v))

    if not (0 <= x < w and 0 <= y < h):
        return None

    r = DEPTH_PATCH_PX
    patch = depth_raw[max(y - r, 0):y + r + 1, max(x - r, 0):x + r + 1]
    values = patch[patch > 0]

    return float(np.median(values)) if values.size else None


def load_landmarker():
    model_path = Path(__file__).with_name(f"pose_landmarker_{POSE_MODEL}.task")

    if not model_path.exists():
        print(f"Downloading the MediaPipe pose model to {model_path} ...")
        urllib.request.urlretrieve(MODEL_URL.format(POSE_MODEL), model_path)

    options = vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=MAX_PEOPLE,
        min_pose_detection_confidence=MIN_DETECTION_CONFIDENCE,
        min_pose_presence_confidence=MIN_PRESENCE_CONFIDENCE,
        min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
        output_segmentation_masks=False,
    )
    return vision.PoseLandmarker.create_from_options(options)


def mean_point(landmarks, ids, width, height):
    seen = [
        landmarks[i] for i in ids
        if (landmarks[i].visibility or 0.0) >= MIN_VISIBILITY
    ]
    if not seen:
        return None

    x = sum(p.x for p in seen) / len(seen) * width
    y = sum(p.y for p in seen) / len(seen) * height

    if not (0 <= x < width and 0 <= y < height):
        return None
    return x, y


def to_output(x, y, width):
    return (width - 1 - x, y) if MIRROR else (x, y)


def read_people(result, camera, depth_raw, width, height):
    near_mm, far_mm = NEAR_M * 1000.0, FAR_M * 1000.0
    middle_mm = (near_mm + far_mm) / 2.0
    people = []

    for landmarks in result.pose_landmarks:
        center = mean_point(landmarks, TORSO_LANDMARKS, width, height)
        if center is None:
            continue

        body_mm = camera.depth_at(depth_raw, center, middle_mm)

        # Outside the play range (background people, posters, ...)
        if body_mm is None or not near_mm <= body_mm <= far_mm:
            continue

        hands = {}
        for side, ids in HAND_LANDMARKS.items():
            # The wrist must be seen, the finger points help centre it
            wrist = landmarks[ids[0]]
            point = mean_point(landmarks, ids, width, height)

            if (wrist.visibility or 0.0) < MIN_VISIBILITY or point is None:
                hands[side] = None
                continue

            hand_mm = camera.depth_at(depth_raw, point, body_mm)
            hands[side] = {
                "point": to_output(*point, width),
                "distance_mm": hand_mm,
            }

        people.append({
            "center": to_output(*center, width),
            "distance_mm": body_mm,
            "hands": hands,
        })

    return people


def predict(history, timestamp):
    # Constant velocity from the oldest to the newest recent position
    if not history:
        return None

    t1, p1 = history[-1]
    if len(history) == 1:
        return p1

    t0, p0 = history[0]
    velocity = (p1 - p0) / max(t1 - t0, 1e-3)
    return p1 + velocity * min(timestamp - t1, MAX_PREDICT_S)


class PersonTrack:
    def __init__(self, person_id, width, height):
        self.id = person_id
        self.width, self.height = width, height
        self.missing = 0
        self.center = None
        self.distance_mm = None
        self.hands = {side: None for side in HAND_LANDMARKS}
        self.hand_missing = {side: 0 for side in HAND_LANDMARKS}

        # Recent raw positions (timestamp, point) for the predictions
        self.center_history = deque(maxlen=HISTORY_FRAMES)
        self.hand_history = {
            side: deque(maxlen=HISTORY_FRAMES) for side in HAND_LANDMARKS
        }
        # Per frame: did the model's Left/Right come out swapped vs ours?
        self.label_votes = deque(maxlen=LABEL_VOTE_FRAMES)

        # Positions are in pixels, so scale beta from 0..1 units
        point_beta = ONE_EURO_BETA / width
        self.point_filters = {
            side: OneEuroFilter(ONE_EURO_MIN_CUTOFF, point_beta)
            for side in HAND_LANDMARKS
        }
        self.z_filters = {
            side: OneEuroFilter(ONE_EURO_MIN_CUTOFF, ONE_EURO_BETA)
            for side in HAND_LANDMARKS
        }

    def predicted_center(self, timestamp):
        return predict(self.center_history, timestamp)

    def _usually_swapped(self):
        return sum(self.label_votes) * 2 > len(self.label_votes)

    def _pair_hands(self, detected, timestamp):
        # Map the model's Left/Right onto this person's own hands by
        # position, so a label the model flips for a frame changes nothing
        straight = detected
        crossed = {"Left": detected["Right"], "Right": detected["Left"]}

        def gaps(pairing):
            result = []
            for side, hand in pairing.items():
                guess = predict(self.hand_history[side], timestamp)
                if hand is not None and guess is not None:
                    result.append(float(np.hypot(*(hand["point"] - guess))))
            return result

        keep, swap = gaps(straight), gaps(crossed)

        if keep and len(keep) == len(swap):
            if sum(swap) + SWAP_MARGIN_PX < sum(keep):
                swapped = True
            elif sum(keep) + SWAP_MARGIN_PX < sum(swap):
                swapped = False
            else:
                swapped = self._usually_swapped()
        else:
            # Nothing to compare (new hands): trust the recent frames, or
            # the model's labels for a brand new person
            swapped = self._usually_swapped()

        self.label_votes.append(swapped)

        # The model keeps disagreeing with us: our names were wrong, so
        # rename our hands to its labels
        if (
            len(self.label_votes) == LABEL_VOTE_FRAMES
            and sum(self.label_votes) >= LABEL_SWAP_SHARE * LABEL_VOTE_FRAMES
        ):
            self._rename_hands()
            return straight

        return crossed if swapped else straight

    def _rename_hands(self):
        for state in (
            self.hands, self.hand_missing, self.hand_history,
            self.point_filters, self.z_filters,
        ):
            state["Left"], state["Right"] = state["Right"], state["Left"]

        self.label_votes.clear()

    def update(self, person, timestamp):
        self.missing = 0
        self.center = np.array(person["center"], dtype=float)
        self.center_history.append((timestamp, self.center))
        self.distance_mm = person["distance_mm"]

        detected = {
            side: None if hand is None else {
                **hand, "point": np.array(hand["point"], dtype=float)
            }
            for side, hand in person["hands"].items()
        }

        for side, hand in self._pair_hands(detected, timestamp).items():
            if hand is None:
                self._lose_hand(side)
                continue

            self.hand_missing[side] = 0
            self.hand_history[side].append((timestamp, hand["point"]))

            # The filter updates its array in place: hand it a copy
            x, y = self.point_filters[side](
                hand["point"].copy(), timestamp
            ).tolist()

            # Push: how far the hand is in front of the body. Without
            # depth at the hand (a hole), keep the last value.
            z = None
            if hand["distance_mm"] is not None:
                z = (self.distance_mm - hand["distance_mm"]) / ARM_REACH_MM
                z = self.z_filters[side](float(np.clip(z, 0.0, 1.0)), timestamp)
            elif self.hands[side] is not None:
                z = self.hands[side]["z"]

            self.hands[side] = {
                "x": x / self.width,
                "y": y / self.height,
                "z": z,
                "distance_mm": hand["distance_mm"],
            }

    def lose(self):
        self.missing += 1
        for side in HAND_LANDMARKS:
            self._lose_hand(side)

    def _lose_hand(self, side):
        self.hand_missing[side] += 1

        if self.hand_missing[side] > HOLD_FRAMES:
            self.hands[side] = None
            self.hand_history[side].clear()
            self.point_filters[side].reset()
            self.z_filters[side].reset()


class PeopleTracker:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.tracks = []
        self.next_id = 1

    def update(self, people, timestamp):
        # Each person keeps the id of the track predicted nearest to them,
        # counting both position on screen and distance from the camera
        pairs = []
        for t_index, track in enumerate(self.tracks):
            guess = track.predicted_center(timestamp)
            for p_index, person in enumerate(people):
                gap = float(np.hypot(*(np.array(person["center"]) - guess)))
                gap += PERSON_DEPTH_WEIGHT * abs(
                    person["distance_mm"] - track.distance_mm
                )
                if gap <= MAX_PERSON_JUMP_PX:
                    pairs.append((track.missing, gap, t_index, p_index))

        # People seen last frame are matched first: the predicted spot of
        # someone hidden behind another player sweeps right through them
        # and must not steal their detection
        used_tracks, used_people = set(), set()
        for _, _, t_index, p_index in sorted(pairs):
            if t_index in used_tracks or p_index in used_people:
                continue
            self.tracks[t_index].update(people[p_index], timestamp)
            used_tracks.add(t_index)
            used_people.add(p_index)

        for t_index, track in enumerate(self.tracks):
            if t_index not in used_tracks:
                track.lose()

        for p_index, person in enumerate(people):
            if p_index not in used_people:
                track = PersonTrack(self.next_id, self.width, self.height)
                track.update(person, timestamp)
                self.tracks.append(track)
                self.next_id += 1

        self.tracks = [t for t in self.tracks if t.missing <= HOLD_FRAMES]
        return self.tracks


def draw_people(image, tracks):
    for track in tracks:
        color = PERSON_COLORS[(track.id - 1) % len(PERSON_COLORS)]
        cx, cy = (int(v) for v in track.center)

        cv2.drawMarker(image, (cx, cy), color, cv2.MARKER_CROSS, 16, 2)
        cv2.putText(
            image,
            f"P{track.id} {track.distance_mm / 1000:.2f} m",
            (cx - 40, cy - 12),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            2,
        )

        for side, hand in track.hands.items():
            if hand is None:
                continue

            x = int(hand["x"] * track.width)
            y = int(hand["y"] * track.height)
            z_text = "--" if hand["z"] is None else f"{hand['z']:.2f}"

            cv2.circle(image, (x, y), 10, color, -1)
            cv2.putText(
                image,
                f"{side[0]} z={z_text}",
                (x + 12, y + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2,
            )


def main():
    camera = None
    landmarker = None

    try:
        landmarker = load_landmarker()
        camera = FrontCamera()
        tracker = PeopleTracker(WIDTH, HEIGHT)
        last_ms = -1

        print("Press 'q' to quit.")

        while True:
            depth_raw, color = camera.read()

            if depth_raw is None:
                continue

            # VIDEO mode needs strictly increasing timestamps in ms
            now = time.perf_counter()
            timestamp_ms = max(int(now * 1000), last_ms + 1)
            last_ms = timestamp_ms

            # The model runs on the unflipped image (its left/right assume
            # a normal camera view); only the output is mirrored
            rgb = cv2.cvtColor(color, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = landmarker.detect_for_video(image, timestamp_ms)

            people = read_people(result, camera, depth_raw, WIDTH, HEIGHT)
            tracks = tracker.update(people, now)

            # A game would read `tracks` here: per person an id, a
            # distance and Left/Right hands with x, y (0..1) and z

            if not SHOW_WINDOW:
                continue

            view = cv2.flip(color, 1) if MIRROR else color.copy()
            draw_people(view, tracks)
            cv2.imshow("Hands", view)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if cv2.getWindowProperty("Hands", cv2.WND_PROP_VISIBLE) < 1:
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
