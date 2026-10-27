"""See what the camera sees and tune the play zone live.

    python -m laser_game.zone_debug

Step out of view for the first 3 s: the empty room is captured as the
background and the camera's height and tilt are measured from the floor,
exactly like in the game. Then six panels:

  camera    the colour camera, mirrored like the game
  depth     near = bright. Outside the play zone is dimmed. Red = something
            moving outside the zone (ignored), orange = cut as an artifact,
            blue / green = Player 1 / Player 2, white line = their divider
  game      what the game gets: the silhouettes and the real players
  above     the room seen from above, camera at the bottom: every depth
            point, the play zone in green. Move the sliders until the box
            holds where players stand and nothing else (walls, desks).
            Grey lines: what the depth camera sees, yellow: the colour
            camera (narrower). Up close the camera can't see all of you
  side      the room from the side, camera on the left. The floor must be a
            flat line on the "floor" mark: if it slopes, change the camera
            pitch; if it is above or below, the camera height
  info      numbers and keys

Keys:  f = measure the camera's height and tilt from the floor again (needs
           some empty floor in the bottom of the image), sets the sliders
       b = re-capture the background (step out first)
       w = save the zone and tracking settings to laser_game/settings.json
           (the game loads them at start, and can change them with S)
       p = print the settings, to paste into laser_game/config.py
       s = save a snapshot picture
       q / Esc = quit
"""

import time

import cv2
import numpy as np

from . import config, settings
from .vision.bodies import FINE, GridSpec
from .vision.camera import DepthCamera
from .vision.floor import describe, fit_floor
from .vision.tracker import PLAYER_COLORS_BGR, PlayerTracker
from .vision.zone import in_zone, world

PANEL = (512, 288)                      # w, h of each panel
SETTINGS = "settings"
WINDOW = "play zone (laser_game)"

# Sliders: (name, its start position from config, its maximum). Their
# positions go back into config in read_sliders
SLIDERS = [
    ("zone left cm",   lambda: config.ZONE_X_M[0] * 100 + 400, 800),
    ("zone right cm",  lambda: config.ZONE_X_M[1] * 100 + 400, 800),
    ("zone near cm",   lambda: config.ZONE_DEPTH_M[0] * 100, 800),
    ("zone far cm",    lambda: config.ZONE_DEPTH_M[1] * 100, 800),
    ("floor cut cm",   lambda: config.ZONE_HEIGHT_M[0] * 100, 50),
    ("zone top cm",    lambda: config.ZONE_HEIGHT_M[1] * 100, 300),
    ("cam height cm",  lambda: config.CAMERA_HEIGHT_M * 100, 400),
    ("cam pitch x10",  lambda: config.CAMERA_PITCH_DEG * 10 + 300, 900),   # -30..60 deg
    ("depth band cm",  lambda: config.PLAYER_DEPTH_BAND_M * 100, 150),
    ("edge trim px",   lambda: config.EDGE_TRIM_PX, 5),
]


def make_sliders():
    cv2.namedWindow(SETTINGS, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(SETTINGS, 520, 40 * len(SLIDERS))
    for name, value, top in SLIDERS:
        cv2.createTrackbar(name, SETTINGS, int(round(value())), top, lambda _: None)


def set_camera_sliders():
    """Camera height and tilt from config -> their sliders."""
    cv2.setTrackbarPos("cam height cm", SETTINGS, int(round(config.CAMERA_HEIGHT_M * 100)))
    cv2.setTrackbarPos("cam pitch x10", SETTINGS, int(round(config.CAMERA_PITCH_DEG * 10)) + 300)


def read_sliders():
    """Slider positions -> config, so the whole pipeline uses them live."""
    get = lambda name: cv2.getTrackbarPos(name, SETTINGS)
    config.ZONE_X_M = ((get("zone left cm") - 400) / 100, (get("zone right cm") - 400) / 100)
    config.ZONE_DEPTH_M = (get("zone near cm") / 100, get("zone far cm") / 100)
    config.ZONE_HEIGHT_M = (get("floor cut cm") / 100, get("zone top cm") / 100)
    config.CAMERA_HEIGHT_M = get("cam height cm") / 100
    config.CAMERA_PITCH_DEG = (get("cam pitch x10") - 300) / 10
    config.PLAYER_DEPTH_BAND_M = get("depth band cm") / 100
    config.EDGE_TRIM_PX = get("edge trim px")


def settings_text():
    return "\n".join([
        "# Fallback only: measured from the floor at every start",
        f"CAMERA_HEIGHT_M = {config.CAMERA_HEIGHT_M:.2f}",
        f"CAMERA_PITCH_DEG = {config.CAMERA_PITCH_DEG:.1f}",
        f"ZONE_X_M = ({config.ZONE_X_M[0]:.2f}, {config.ZONE_X_M[1]:.2f})",
        f"ZONE_DEPTH_M = ({config.ZONE_DEPTH_M[0]:.2f}, {config.ZONE_DEPTH_M[1]:.2f})",
        f"ZONE_HEIGHT_M = ({config.ZONE_HEIGHT_M[0]:.2f}, {config.ZONE_HEIGHT_M[1]:.2f})",
        f"PLAYER_DEPTH_BAND_M = {config.PLAYER_DEPTH_BAND_M:.2f}",
        f"EDGE_TRIM_PX = {config.EDGE_TRIM_PX}",
    ])


# ------------------------------------------------------------------ panels

def fit(image):
    """Scale an image into a panel, keeping its shape (black bars)."""
    w, h = PANEL
    panel = np.zeros((h, w, 3), np.uint8)
    if image is None:
        return panel
    scale = min(w / image.shape[1], h / image.shape[0])
    size = (max(1, int(image.shape[1] * scale)), max(1, int(image.shape[0] * scale)))
    small = cv2.resize(image, size, interpolation=cv2.INTER_NEAREST if scale > 1 else cv2.INTER_AREA)
    y, x = (h - size[1]) // 2, (w - size[0]) // 2
    panel[y:y + size[1], x:x + size[0]] = small
    return panel


def label(panel, text):
    cv2.putText(panel, text, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(panel, text, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return panel


class Plot:
    """A panel showing metres: a (horizontal) and b (vertical, up)."""

    def __init__(self, a_range, b_range):
        w, h = PANEL
        self.a0, self.b1 = a_range[0], b_range[1]
        self.scale = min(w / (a_range[1] - a_range[0]), h / (b_range[1] - b_range[0]))
        self.image = np.zeros((h, w, 3), np.uint8)

    def px(self, a, b):
        return (
            np.round((np.asarray(a) - self.a0) * self.scale).astype(int),
            np.round((self.b1 - np.asarray(b)) * self.scale).astype(int),
        )

    def points(self, a, b, color):
        u, v = self.px(a, b)
        h, w = self.image.shape[:2]
        ok = (u >= 0) & (u < w) & (v >= 0) & (v < h)
        self.image[v[ok], u[ok]] = color

    def box(self, a_range, b_range, color):
        p0 = tuple(int(c) for c in self.px(a_range[0], b_range[1]))
        p1 = tuple(int(c) for c in self.px(a_range[1], b_range[0]))
        cv2.rectangle(self.image, p0, p1, color, 2)

    def line(self, a0, b0, a1, b1, color, thickness=1):
        p0 = tuple(int(c) for c in self.px(a0, b0))
        p1 = tuple(int(c) for c in self.px(a1, b1))
        cv2.line(self.image, p0, p1, color, thickness)


def room_views(depth, intrinsics, result, color=None):
    valid = depth > 0
    x, height, forward = world(depth, intrinsics)
    zone = in_zone(x, height, forward, valid)

    # Every other pixel is plenty, and quicker
    step = (slice(None, None, 2), slice(None, None, 2))
    x, height, forward = x[step], height[step], forward[step]
    valid, zone = valid[step], zone[step]
    outside = valid & ~zone

    above = Plot((-3.5, 3.5), (-0.2, 6.0))
    side = Plot((-0.2, 6.0), (-0.4, 3.0))
    for plot, a, b in ((above, x, forward), (side, forward, height)):
        plot.points(a[outside], b[outside], (90, 90, 90))
        plot.points(a[zone], b[zone], (230, 230, 230))

    # Players at the distance the tracker found them
    for pid, distance in (result.distances or {}).items():
        if distance is not None:
            tint = PLAYER_COLORS_BGR[pid]
            above.line(config.ZONE_X_M[0], distance, config.ZONE_X_M[1], distance, tint, 2)
            side.line(distance, 0, distance, config.ZONE_HEIGHT_M[1], tint, 2)

    # What each camera can see: grey = depth, yellow = colour
    cameras = [(intrinsics, (130, 130, 130))]
    if color is not None:
        cameras.append((color.intrinsics, (0, 220, 255)))
    far = 6.0
    for camera, line_color in cameras:
        left = np.arctan(camera.ppx / camera.fx)
        right = np.arctan((camera.width - camera.ppx) / camera.fx)
        for angle in (-left, right):
            above.line(0, 0, far * np.clip(np.tan(angle), -20, 20), far, line_color)
        up = np.arctan(camera.ppy / camera.fy)
        down = np.arctan((camera.height - camera.ppy) / camera.fy)
        for angle in (np.radians(config.CAMERA_PITCH_DEG) - up, np.radians(config.CAMERA_PITCH_DEG) + down):
            side.line(0, config.CAMERA_HEIGHT_M, far, config.CAMERA_HEIGHT_M - far * np.clip(np.tan(angle), -20, 20), line_color)

    green = (60, 220, 60)
    above.box(config.ZONE_X_M, config.ZONE_DEPTH_M, green)
    side.box(config.ZONE_DEPTH_M, config.ZONE_HEIGHT_M, green)

    # The camera and the floor
    cv2.circle(above.image, tuple(int(c) for c in above.px(0, 0)), 6, (0, 200, 255), -1)
    side.line(-0.2, 0, 6.0, 0, (0, 200, 255), 1)
    cv2.putText(side.image, "floor", tuple(int(c) for c in side.px(5.4, 0.05)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 255), 1)
    cv2.circle(side.image, tuple(int(c) for c in side.px(0, config.CAMERA_HEIGHT_M)), 6, (0, 200, 255), -1)

    for plot, ticks, along in ((above, range(-3, 4), "x"), (side, range(0, 7), "f")):
        for t in ticks:
            u, v = (int(c) for c in (plot.px(t, -0.1) if along == "x" else plot.px(t, -0.3)))
            cv2.putText(plot.image, f"{t}m", (u - 8, min(v, PANEL[1] - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (150, 150, 150), 1)
    return above.image, side.image


def game_view(result, spec):
    """What the game receives: real players inside their silhouettes."""
    rows, cols = spec.shape
    canvas = np.full((rows * FINE, cols * FINE, 3), 20, np.uint8)

    for pid in (1, 2):
        picture = (result.pictures or {}).get(pid)
        if picture is not None:
            h, w = picture.rgba.shape[:2]
            alpha = picture.rgba[..., 3:].astype(np.float32) / 255
            area = canvas[picture.row:picture.row + h, picture.col:picture.col + w]
            bgr = picture.rgba[..., 2::-1].astype(np.float32)
            area[:] = (alpha * bgr + (1 - alpha) * area).astype(np.uint8)

        grid = result.bodies.get(pid)
        if grid is not None:
            big = cv2.resize(grid.astype(np.uint8), (cols * FINE, rows * FINE), interpolation=cv2.INTER_NEAREST)
            edge = big - cv2.erode(big, np.ones((3, 3), np.uint8))
            canvas[edge > 0] = PLAYER_COLORS_BGR[pid]
    return canvas


# -------------------------------------------------------------------- main

def main():
    spec = GridSpec(config.PLAY_X_RANGE_M, config.PLAY_HEIGHT_RANGE_M, config.CELL_M)
    camera = DepthCamera(color=True)
    tracker = PlayerTracker(spec)

    message = settings.load()
    if message:
        print(message)
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    make_sliders()

    capture_at, frames = time.perf_counter() + config.BACKGROUND_DELAY_S, []
    fps, last = 0.0, time.perf_counter()
    floor_text = ""
    print(__doc__)

    try:
        while True:
            depth, intrinsics, color = camera.read()
            if depth is None:
                continue
            depth, intrinsics = tracker.orient(depth, intrinsics)
            read_sliders()

            now = time.perf_counter()
            fps += 0.1 * (1.0 / max(now - last, 1e-3) - fps)
            last = now

            status = "background ready (b = capture again)"
            if capture_at is not None:
                if now < capture_at:
                    status = f"STEP OUT: capturing the background in {capture_at - now:.0f}"
                else:
                    frames.append(depth)
                    status = "capturing the background..."
                    if len(frames) >= config.BACKGROUND_FRAMES:
                        tracker.capture_background(frames, intrinsics)
                        capture_at, frames = None, []
                        if tracker.calibration is not None:
                            floor_text = tracker.calibration.message
                            print(floor_text)
                            set_camera_sliders()

            started = time.perf_counter()
            result = tracker.process(depth, intrinsics, now, color, debug=True)
            took_ms = (time.perf_counter() - started) * 1000

            camera_image = None
            if color is not None:
                camera_image = color.image[:, ::-1] if config.MIRROR else color.image
            above, side = room_views(depth, intrinsics, result, color)

            info = np.zeros((PANEL[1], PANEL[0], 3), np.uint8)
            lines = [status, f"{fps:4.1f} fps, tracking {took_ms:4.1f} ms", ""]
            for pid in (1, 2):
                grid, distance = result.bodies.get(pid), (result.distances or {}).get(pid)
                if grid is None:
                    lines.append(f"Player {pid}: not seen")
                else:
                    lines.append(f"Player {pid}: {distance:.2f} m away, {int(grid.sum())} cells")
            lines += ["", "f: measure camera height + tilt from the floor",
                      "b: background   w: save settings   p: print",
                      "s: snapshot     q / Esc: quit"]
            if floor_text:
                lines += ["", floor_text]
            for i, text in enumerate(lines):
                cv2.putText(info, text, (10, 50 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1, cv2.LINE_AA)

            mosaic = np.vstack([
                np.hstack([label(fit(camera_image), "camera"),
                           label(fit(result.debug), "depth: red = outside zone, orange = cut"),
                           label(fit(game_view(result, spec)), "game")]),
                np.hstack([label(above, "above (green: play zone)"),
                           label(side, "side (floor flat on the line?)"),
                           label(info, "info")]),
            ])
            cv2.imshow(WINDOW, mosaic)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("f"):
                floor = fit_floor(depth, intrinsics)
                if floor is None:
                    floor_text = "no floor found: point the camera at some floor"
                else:
                    height, pitch, roll, _ = floor
                    config.CAMERA_HEIGHT_M, config.CAMERA_PITCH_DEG = height, pitch
                    set_camera_sliders()
                    floor_text = f"floor: {describe(height, pitch)}"
                    if abs(roll) > 3:
                        floor_text += f", {roll:.0f} deg sideways!"
                print(floor_text)
            elif key == ord("b"):
                capture_at, frames = time.perf_counter() + config.BACKGROUND_DELAY_S, []
            elif key == ord("w"):
                print(settings.save())
            elif key == ord("p"):
                print("\n# --- paste into laser_game/config.py ---")
                print(settings_text())
            elif key == ord("s"):
                name = time.strftime("zone_snapshot_%Y%m%d_%H%M%S.png")
                cv2.imwrite(name, mosaic)
                print("saved", name)
    finally:
        camera.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
