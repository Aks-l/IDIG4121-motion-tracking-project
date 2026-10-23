"""One small web server for the three.js game:

GET  /            the game itself (static/)
GET  /stream      Server-Sent Events: a "hello" with the grid, then one
                  message per camera frame with both players' silhouettes
GET  /debug.jpg   the tracker's debug image (players tinted, split line)
POST /command     {"cmd": "background"}: re-capture the empty play area

Server-Sent Events are a one-way WebSocket, which is all the game needs:
browsers have them built in (EventSource) and Python needs nothing beyond
its standard library to send them.
"""

import base64
import json
import math
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config

STATIC = Path(__file__).parent / "static"


def grid_settings():
    return {
        "x_range": list(config.PLAY_X_RANGE_M),
        "height_range": list(config.PLAY_HEIGHT_RANGE_M),
        "cell": config.CELL_M,
    }


class CameraFeed:
    """The depth camera and tracker, shared by every open page."""

    def __init__(self):
        # Imported here so --sim needs neither numpy nor the camera
        import numpy as np
        from coop_game import config as camera_config
        from coop_game.vision.bodies import GridSpec
        from coop_game.vision.tracker import TrackerThread

        self.np = np
        spec = GridSpec(config.PLAY_X_RANGE_M, config.PLAY_HEIGHT_RANGE_M, config.CELL_M)
        self.background_delay = camera_config.BACKGROUND_DELAY_S
        self.thread = TrackerThread(body_spec=spec)
        self.thread.start()
        self.thread.request_background(self.background_delay)
        self.debug_wanted_at = -math.inf

    def latest(self):
        if self.thread.error is not None:
            raise RuntimeError(f"Camera stopped: {self.thread.error}")

        # Nobody has asked for the debug image lately: stop drawing it
        if time.perf_counter() - self.debug_wanted_at > config.DEBUG_IDLE_S:
            self.thread.want_debug = False
        return self.thread.latest()

    def status(self):
        waiting = self.thread.background_status()
        if waiting is not None:
            if waiting > 0:
                return f"Step out of the play area: capturing the background in {waiting:.0f}"
            return "Capturing the background..."
        if self.thread.latest() is None:
            return "Waiting for the camera..."
        return None

    def encode(self, result):
        """A tracker result as a stream message: silhouettes as base64 bits,
        row by row from the top, 1 = body."""
        bodies = {}
        for pid, grid in result.bodies.items():
            if grid is None:
                bodies[str(pid)] = None
            else:
                bits = self.np.packbits(grid, axis=None).tobytes()
                bodies[str(pid)] = base64.b64encode(bits).decode("ascii")

        return {
            "type": "frame",
            # Seconds since the camera saw it: the page turns it into its own clock
            "age": time.perf_counter() - result.time,
            "bodies": bodies,
            "status": self.status(),
        }

    def debug_jpeg(self):
        import cv2

        self.debug_wanted_at = time.perf_counter()
        self.thread.want_debug = True
        result = self.thread.latest()
        if result is None or result.debug is None:
            return None

        ok, data = cv2.imencode(
            ".jpg", result.debug, [cv2.IMWRITE_JPEG_QUALITY, config.DEBUG_JPEG_QUALITY]
        )
        return data.tobytes() if ok else None

    def request_background(self):
        self.thread.request_background(self.background_delay)

    def close(self):
        self.thread.stop()


class Handler(SimpleHTTPRequestHandler):
    # The server carries .feed (CameraFeed, or None in --sim) and .hello

    # Windows can map .js to text/plain in the registry, which browsers
    # refuse to run as a module
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".css": "text/css",
        ".html": "text/html",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def end_headers(self):
        # Always the latest files: edit, reload, see it
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_request(self, code="-", size="-"):
        # The debug image is fetched several times a second: don't flood
        if not self.path.startswith("/debug.jpg"):
            super().log_request(code, size)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/stream":
            self._stream()
        elif path == "/debug.jpg":
            self._debug_image()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path != "/command":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length") or 0)
        try:
            command = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self.send_error(400, "Not JSON")
            return

        feed = self.server.feed
        if command.get("cmd") == "background" and feed is not None:
            feed.request_background()
        self.send_response(204)
        self.end_headers()

    def _debug_image(self):
        feed = self.server.feed
        jpeg = None if feed is None else feed.debug_jpeg()
        if jpeg is None:
            self.send_error(404, "No debug image")
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(jpeg)))
        self.end_headers()
        self.wfile.write(jpeg)

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        feed = self.server.feed
        try:
            self._send(self.server.hello)
            if feed is None:
                return       # --sim: the page plays with the keyboard

            last = None
            quiet_since = time.perf_counter()
            while True:
                result = feed.latest()
                now = time.perf_counter()
                if result is not None and result.bodies is not None and result.time != last:
                    last = result.time
                    quiet_since = now
                    self._send(feed.encode(result))
                elif now - quiet_since > config.STATUS_EVERY_S:
                    quiet_since = now
                    self._send({"type": "status", "status": feed.status()})
                time.sleep(config.POLL_S)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass             # the page was closed or reloaded
        except RuntimeError as error:
            self._send({"type": "error", "message": str(error)})

    def _send(self, message):
        self.wfile.write(b"data: " + json.dumps(message).encode("utf-8") + b"\n\n")
        self.wfile.flush()


def serve(sim=False, port=config.PORT, open_browser=config.OPEN_BROWSER):
    feed = None if sim else CameraFeed()

    server = ThreadingHTTPServer((config.HOST, port), Handler)
    server.daemon_threads = True       # open streams don't block Ctrl+C
    server.feed = feed
    server.hello = {
        "type": "hello",
        "mode": "sim" if sim else "camera",
        "grid": grid_settings(),
    }

    url = f"http://{config.HOST}:{port}/"
    print(f"Laser Duel ({'keyboard' if sim else 'camera'}) at {url}  -  Ctrl+C to stop")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if feed is not None:
            feed.close()
