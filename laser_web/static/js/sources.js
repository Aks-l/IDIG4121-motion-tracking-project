// Where the game gets the players' silhouettes from: the camera (streamed by
// the Python server), or the keyboard for development.

import { countCells, decodeBody } from "./grid.js";

export function makeFrame(time, bodies) {
  const counts = {};
  for (const pid of [1, 2]) counts[pid] = bodies[pid] ? countCells(bodies[pid]) : 0;
  return { time, bodies, counts };
}

/** Open the server's stream and wait for its hello: {events, hello}, or
 *  null when there is no server (the page was opened some other way). */
export function connectToServer(timeoutMs = 2000) {
  return new Promise((resolve) => {
    const events = new EventSource("/stream");
    const done = (result) => {
      clearTimeout(timer);
      events.onmessage = events.onerror = null;
      if (!result) events.close();
      resolve(result);
    };
    const timer = setTimeout(() => done(null), timeoutMs);

    events.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "hello") done({ events, hello: message });
    };
    events.onerror = () => done(null);
  });
}

export class CameraSource {
  constructor(spec, events) {
    this.mode = "camera";
    this.spec = spec;
    this.frame = null;
    this.statusText = "Waiting for the camera...";

    events.onmessage = (event) => this.onMessage(JSON.parse(event.data));
    // EventSource reconnects by itself; say so until it does
    events.onerror = () => {
      this.statusText = "Lost the camera server: is python -m laser_web still running?";
    };
  }

  onMessage(message) {
    if (message.type === "frame") {
      const bodies = {};
      for (const pid of [1, 2]) {
        const bits = message.bodies[pid];
        bodies[pid] = bits ? decodeBody(this.spec, bits) : null;
      }
      // The server says how old the frame is: put it on this page's clock
      this.frame = makeFrame(performance.now() / 1000 - message.age, bodies);
      this.statusText = message.status;
    } else if (message.type === "status") {
      this.statusText = message.status;
    } else if (message.type === "error") {
      this.statusText = message.message;
    } else if (message.type === "hello") {
      this.statusText = null;          // reconnected
    }
  }

  poll() {
    return this.frame;
  }

  status() {
    return this.statusText;
  }

  onKey() {}

  requestBackground() {
    fetch("/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cmd: "background" }),
    });
  }

  debugImageUrl() {
    return "/debug.jpg";
  }
}

const SPEED = 1.8;            // m/s
const JUMP_S = 0.6;
const JUMP_PEAK_M = 0.5;
const FRAME_S = 1 / 30;       // new frames as often as the camera

const BINDINGS = {
  1: ["KeyA", "KeyD", "KeyW", "KeyS"],
  2: ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"],
};

/** Play without a camera, with stick-figure silhouettes.
 *  Player 1: A / D move, W jump, S duck. Player 2: the arrow keys.
 *  1 / 2: that player steps out of (or back into) view. */
export class KeyboardSource {
  constructor(spec, lanes, keys) {
    this.mode = "keyboard";
    this.spec = spec;
    this.keys = keys;              // Set of KeyboardEvent.code held down
    this.players = {
      1: { x: (lanes[1][0] + lanes[1][1]) / 2, height: 1.75, lane: lanes[1] },
      2: { x: (lanes[2][0] + lanes[2][1]) / 2, height: 1.62, lane: lanes[2] },
    };
    for (const player of Object.values(this.players)) {
      Object.assign(player, { inView: true, jumpT: null, ducking: false });
    }
    this.last = null;
    this.frame = null;
  }

  onKey(code) {
    if (code === "Digit1") this.players[1].inView = !this.players[1].inView;
    if (code === "Digit2") this.players[2].inView = !this.players[2].inView;
  }

  poll(now) {
    const dt = this.last === null ? 0 : Math.min(now - this.last, 0.05);
    this.last = now;

    for (const pid of [1, 2]) this.move(this.players[pid], BINDINGS[pid], dt);

    if (!this.frame || now - this.frame.time >= FRAME_S) {
      const bodies = {};
      for (const pid of [1, 2]) {
        const player = this.players[pid];
        bodies[pid] = player.inView ? this.silhouette(player) : null;
      }
      this.frame = makeFrame(now, bodies);
    }
    return this.frame;
  }

  move(player, [left, right, jump, duck], dt) {
    const held = (code) => (this.keys.has(code) ? 1 : 0);
    player.x += (held(right) - held(left)) * SPEED * dt;
    player.x = Math.min(Math.max(player.x, player.lane[0] + 0.25), player.lane[1] - 0.25);
    player.ducking = this.keys.has(duck);

    if (player.jumpT === null && this.keys.has(jump)) player.jumpT = 0;
    else if (player.jumpT !== null) {
      player.jumpT += dt;
      if (player.jumpT >= JUMP_S) player.jumpT = null;
    }
  }

  silhouette(player) {
    const { xs, hs, size } = this.spec;
    const lift = player.jumpT === null ? 0 : JUMP_PEAK_M * Math.sin((Math.PI * player.jumpT) / JUMP_S);

    // Ducking squats everything lower, knees out
    const squat = player.ducking ? 0.62 : 1;
    const legHalfWidth = player.ducking ? 0.22 : 0.16;
    const at = (fraction) => lift + fraction * player.height * squat;
    const hip = at(0.47);
    const shoulder = at(0.82);
    const headH = at(0.91);
    const headR = 0.095 * player.height;

    const body = new Uint8Array(size);
    for (let i = 0; i < size; i++) {
      const dx = xs[i] - player.x;
      const h = hs[i];
      const across = Math.abs(dx);
      const legs = across <= legHalfWidth && h >= lift && h <= hip;
      const torso = across <= 0.21 && h >= hip && h <= shoulder;
      const head = dx * dx + (h - headH) ** 2 <= headR * headR;
      body[i] = legs || torso || head ? 1 : 0;
    }
    return body;
  }

  status() {
    return null;
  }

  requestBackground() {}

  debugImageUrl() {
    return null;
  }
}
