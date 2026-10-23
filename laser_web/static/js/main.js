// Starts the game: finds the camera stream (or falls back to the keyboard),
// then runs rules -> 3D scene -> HUD once per screen refresh.
//
// URL options: ?sim = keyboard even with the camera server, ?seed=7 = the
// same lasers every round.

import { CONFIG } from "./config.js";
import { LaserDuel, OVER, WAITING, makeLanes } from "./duel.js";
import { GridSpec } from "./grid.js";
import { Hud } from "./hud.js";
import { LaserScene } from "./scene.js";
import { CameraSource, KeyboardSource, connectToServer } from "./sources.js";

const DEBUG_REFRESH_MS = 150;

async function main() {
  window.laserDuelStarted = true;
  const params = new URLSearchParams(location.search);
  const keys = new Set();

  const server = params.has("sim") ? null : await connectToServer();
  let spec;
  let source;
  if (server && server.hello.mode === "camera") {
    spec = new GridSpec(server.hello.grid);
    source = new CameraSource(spec, server.events);
  } else {
    if (server) server.events.close();
    spec = new GridSpec(CONFIG.GRID);
    source = new KeyboardSource(spec, makeLanes(spec), keys);
  }

  const seed = params.get("seed");
  const random = seed === null ? Math.random : seededRandom(Number(seed));
  const duel = new LaserDuel(spec, random);
  const scene = new LaserScene(document.getElementById("stage"), spec, duel.lanes);
  const hud = new Hud(source.mode);
  const debug = new DebugImage(source);

  window.addEventListener("keydown", (event) => {
    if (["Tab", "Space", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.code)) {
      event.preventDefault();       // no focus jumps or scrolling
    }
    if (event.repeat) return;
    keys.add(event.code);
    const now = performance.now() / 1000;

    if (event.code === "Enter" && (duel.state === WAITING || duel.state === OVER)) duel.start(now);
    else if (event.code === "KeyR") duel.reset();
    else if (event.code === "KeyB") source.requestBackground();
    else if (event.code === "Tab") debug.toggle();
    else if (event.code === "KeyF") toggleFullscreen();
    else source.onKey(event.code);
  });
  window.addEventListener("keyup", (event) => keys.delete(event.code));
  window.addEventListener("blur", () => keys.clear());

  function frame() {
    const now = performance.now() / 1000;
    duel.update(now, source.poll(now));
    scene.render(duel, now);
    hud.update(duel, now, source.status());
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  // Handy from the browser console
  window.laserDuel = { duel, scene, hud, source };
}

/** The tracker's debug image (Tab), refreshed a few times a second. */
class DebugImage {
  constructor(source) {
    this.url = source.debugImageUrl();
    this.image = document.getElementById("debug");
    this.timer = null;
    // The first requests can come back empty while the tracker starts drawing it
    this.image.onload = () => { this.image.hidden = this.timer === null; };
  }

  toggle() {
    if (!this.url) return;
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
      this.image.hidden = true;
      return;
    }
    const refresh = () => { this.image.src = `${this.url}?t=${Date.now()}`; };
    refresh();
    this.timer = setInterval(refresh, DEBUG_REFRESH_MS);
  }
}

function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen();
}

// mulberry32: small, fast, good enough for picking lasers
function seededRandom(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

main();
