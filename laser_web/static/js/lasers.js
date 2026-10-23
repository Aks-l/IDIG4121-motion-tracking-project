// Lasers flying at the players, and the waves that send them.
//
// A wave sends the same pattern down every playing lane at once, fitted to
// that lane's player (beam heights are fractions of their height, aimed
// beams aim at where they stand), so neither player gets an easier laser.
//
// Positions are [x, height] in metres on the players' plane: where the
// laser will be when it reaches them.

import { CONFIG } from "./config.js";
import { segmentCells } from "./grid.js";

let nextId = 1;

export class Laser {
  constructor(pid, kind, start, end, arrive, travel, cells) {
    this.id = nextId++;
    this.pid = pid;            // whose lane it flies down
    this.kind = kind;          // "low", "high", "aimed" or "diagonal"
    this.start = start;
    this.end = end;
    this.arrive = arrive;      // time it reaches the players' plane
    this.travel = travel;      // seconds from appearing to arriving
    this.cells = cells;        // grid cells it burns on arrival
    this.result = null;        // "hit" or "dodged" once decided
    this.hitFrames = 0;
    this.hitAt = null;         // [x, height] where it touched
  }

  /** Metres behind the players' plane; negative once past them. */
  depth(now) {
    return (CONFIG.LASER_START_DEPTH_M * (this.arrive - now)) / this.travel;
  }

  /** Camera frame times that decide whether it hit. */
  window() {
    const middle = this.arrive + CONFIG.DISPLAY_LAG_S;
    const half = CONFIG.HIT_WINDOW_S / 2;
    return [middle - half, middle + half];
  }

  gone(now) {
    return this.result !== null && this.depth(now) < -CONFIG.LASER_PAST_DEPTH_M;
  }
}

/** [start, end] of a laser of this kind, fitted to one player. */
export function laserShape(kind, target, top, rising) {
  const left = target.lane[0] + CONFIG.LANE_INSET_M;
  const right = target.lane[1] - CONFIG.LANE_INSET_M;
  const height = target.height;

  if (kind === "low" || kind === "high") {
    const h = (kind === "low" ? CONFIG.LOW_BEAM : CONFIG.HIGH_BEAM) * height;
    return [[left, h], [right, h]];
  }
  if (kind === "aimed") {
    // Floor to ceiling where they stand: step aside
    const x = Math.min(Math.max(target.centreX, left + 0.15), right - 0.15);
    return [[x, 0], [x, top]];
  }
  const [low, high] = CONFIG.DIAGONAL_BEAM.map((f) => f * height);
  return rising ? [[left, low], [right, high]] : [[left, high], [right, low]];
}

export class WaveSpawner {
  constructor(spec, random) {
    this.spec = spec;
    this.random = random;
    this.waves = 0;
    this.nextAt = null;
  }

  start(now) {
    this.waves = 0;
    this.nextAt = now + CONFIG.FIRST_WAVE_DELAY_S;
  }

  /** New lasers to launch; targets: Map pid -> {lane, height, centreX}. */
  update(now, targets) {
    if (this.nextAt === null || now < this.nextAt || targets.size === 0) return [];

    const travel = Math.max(
      CONFIG.TRAVEL_MIN_S,
      CONFIG.TRAVEL_START_S - CONFIG.TRAVEL_SPEEDUP_S * this.waves,
    );
    const gap = Math.max(
      CONFIG.SPAWN_GAP_MIN_S,
      CONFIG.SPAWN_GAP_START_S - CONFIG.SPAWN_SPEEDUP_S * this.waves,
    );
    const kind = this.pickKind();
    const rising = this.random() < 0.5;
    this.waves += 1;
    this.nextAt = now + gap;

    const lasers = [];
    for (const [pid, target] of [...targets].sort((a, b) => a[0] - b[0])) {
      const [start, end] = laserShape(kind, target, this.spec.heightRange[1], rising);
      const cells = segmentCells(this.spec, start, end, CONFIG.LASER_HIT_THICKNESS_M);
      lasers.push(new Laser(pid, kind, start, end, now + travel, travel, cells));
    }
    return lasers;
  }

  pickKind() {
    const kinds = Object.keys(CONFIG.KIND_WEIGHTS).filter(
      (kind) => kind !== "diagonal" || this.waves >= CONFIG.DIAGONAL_FROM_WAVE,
    );
    const total = kinds.reduce((sum, kind) => sum + CONFIG.KIND_WEIGHTS[kind], 0);
    let pick = this.random() * total;
    for (const kind of kinds) {
      pick -= CONFIG.KIND_WEIGHTS[kind];
      if (pick < 0) return kind;
    }
    return kinds[kinds.length - 1];
  }
}
