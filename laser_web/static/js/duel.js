// Round rules: silhouettes in, lasers and the winner out (a port of
// laser_game/duel.py). No drawing and no camera here, so the rules can be
// tested with made-up silhouettes. Times are seconds on the page's clock.
//
// waiting   -> both players in view for JOIN_HOLD_S (or Enter: whoever is there)
// countdown -> heights measured; anyone leaving goes back to waiting
// playing   -> waves of lasers; a player is out when their lives run out or
//              they leave the view for FORFEIT_S
// over      -> last player standing wins (both out at once: a draw)
//
// A frame is {time, bodies: {1: body or null, 2: ...}, counts: {1: n, 2: n}}.

import { CONFIG } from "./config.js";
import { WaveSpawner } from "./lasers.js";

export const WAITING = "waiting";
export const COUNTDOWN = "countdown";
export const PLAYING = "playing";
export const OVER = "over";

// Camera frames kept for looking back (s)
const HISTORY_S = 2.0;

export function makeLanes(spec) {
  const split = CONFIG.LANE_SPLIT_X_M;
  return { 1: [spec.xRange[0], split], 2: [split, spec.xRange[1]] };
}

class Player {
  constructor(pid, lane, seenAt) {
    this.pid = pid;
    this.lane = lane;
    this.seenAt = seenAt;           // last time they were in view
    this.height = CONFIG.DEFAULT_PLAYER_HEIGHT_M;
    this.lives = CONFIG.LIVES;
    this.outAt = null;
    this.outReason = "";
    this.hitAt = -Infinity;         // last time a laser hit them
    this.heightSamples = [];
  }

  get out() {
    return this.outAt !== null;
  }
}

export class LaserDuel {
  constructor(spec, random) {
    this.spec = spec;
    this.random = random;
    this.lanes = makeLanes(spec);
    this.frames = [];               // recent camera frames, oldest first
    this.reset();
  }

  reset() {
    this.state = WAITING;
    this.players = new Map();       // pid -> Player in this round
    this.lasers = [];
    this.spawner = new WaveSpawner(this.spec, this.random);
    this.bothSince = null;
    this.countdownEnd = null;
    this.startedAt = null;
    this.endedAt = null;
    this.winner = null;             // pid; null = draw (or solo)
  }

  // ------------------------------------------------------------- queries

  /** A player's latest silhouette, or null if they're not in view. */
  body(pid) {
    const frame = this.frames[this.frames.length - 1];
    if (!frame || !frame.bodies[pid] || frame.counts[pid] < CONFIG.MIN_BODY_CELLS) return null;
    return frame.bodies[pid];
  }

  present() {
    return [1, 2].filter((pid) => this.body(pid) !== null);
  }

  elapsed(now) {
    if (this.startedAt === null) return 0;
    return (this.endedAt === null ? now : this.endedAt) - this.startedAt;
  }

  survived(player, now) {
    if (player.outAt === null) return this.elapsed(now);
    return player.outAt - this.startedAt;
  }

  centreX(pid) {
    const body = this.body(pid);
    if (body === null) return (this.lanes[pid][0] + this.lanes[pid][1]) / 2;
    let sum = 0;
    let n = 0;
    for (let i = 0; i < body.length; i++) {
      if (body[i]) {
        sum += this.spec.xs[i];
        n++;
      }
    }
    return sum / n;
  }

  // --------------------------------------------------------------- input

  /** Start a round (countdown first) with these players, default: whoever
   *  is in view. False if nobody is there. */
  start(now, pids = null) {
    pids = pids ?? this.present();
    if (pids.length === 0) return false;

    this.reset();
    for (const pid of pids) this.players.set(pid, new Player(pid, this.lanes[pid], now));
    this.state = COUNTDOWN;
    this.countdownEnd = now + CONFIG.COUNTDOWN_S;
    return true;
  }

  /** Advance to time now. frame: the source's latest frame (or null); the
   *  same frame may come in several times. */
  update(now, frame) {
    const fresh = this.addFrame(now, frame);

    if (this.state === WAITING) this.wait(now);
    else if (this.state === COUNTDOWN) this.countDown(now, fresh);
    else if (this.state === PLAYING) this.play(now, fresh);
    else if (now - this.endedAt >= CONFIG.RESTART_S) this.reset();
    else {
      // Over: lasers still in the air fly on past the players
      this.lasers = this.lasers.filter((laser) => laser.depth(now) > -CONFIG.LASER_PAST_DEPTH_M);
    }
  }

  // -------------------------------------------------------------- states

  addFrame(now, frame) {
    const last = this.frames[this.frames.length - 1];
    if (!frame || (last && frame.time <= last.time)) return [];

    this.frames.push(frame);
    while (this.frames.length > 1 && this.frames[0].time < now - HISTORY_S) this.frames.shift();
    return [frame];
  }

  wait(now) {
    if (this.present().length < 2) {
      this.bothSince = null;
      return;
    }
    if (this.bothSince === null) this.bothSince = now;
    if (now - this.bothSince >= CONFIG.JOIN_HOLD_S) this.start(now, [1, 2]);
  }

  countDown(now, fresh) {
    for (const [pid, player] of this.players) {
      if (this.body(pid) !== null) player.seenAt = now;
      else if (now - player.seenAt > CONFIG.FORFEIT_S) {
        // Walked off before it started: wait for players again
        this.reset();
        return;
      }

      for (const frame of fresh) {
        const top = this.top(frame, pid);
        if (top !== null) player.heightSamples.push(top);
      }
    }

    if (now < this.countdownEnd) return;

    const [low, high] = CONFIG.PLAYER_HEIGHT_LIMITS_M;
    for (const player of this.players.values()) {
      if (player.heightSamples.length) {
        player.height = Math.min(Math.max(median(player.heightSamples), low), high);
      }
    }

    this.state = PLAYING;
    this.startedAt = now;
    this.spawner.start(now);
  }

  play(now, fresh) {
    for (const [pid, player] of this.players) {
      if (player.out) continue;
      if (this.body(pid) !== null) player.seenAt = now;
      else if (now - player.seenAt > CONFIG.FORFEIT_S) this.knockOut(player, now, "left the arena");
    }

    const targets = new Map();
    for (const [pid, player] of this.players) {
      if (!player.out) {
        targets.set(pid, { lane: player.lane, height: player.height, centreX: this.centreX(pid) });
      }
    }
    this.lasers.push(...this.spawner.update(now, targets));

    for (const laser of this.lasers) {
      if (laser.result === null) this.judge(laser, now, fresh);
    }
    this.lasers = this.lasers.filter((laser) => !laser.gone(now));

    this.checkEnd(now);
  }

  // ---------------------------------------------------------------- hits

  judge(laser, now, fresh) {
    const [first, last] = laser.window();

    for (const frame of fresh) {
      if (frame.time > last) {
        laser.result = "dodged";
        return;
      }
      if (frame.time >= first) this.test(laser, frame);
    }

    if (laser.hitFrames >= CONFIG.HIT_FRAMES) this.hit(laser, now);
    else if (now > last + CONFIG.FRAME_TIMEOUT_S) laser.result = "dodged"; // the camera went quiet
  }

  test(laser, frame) {
    const body = frame.bodies[laser.pid];
    if (!body) return;

    let n = 0;
    let x = 0;
    let h = 0;
    for (const i of laser.cells) {
      if (body[i]) {
        n++;
        x += this.spec.xs[i];
        h += this.spec.hs[i];
      }
    }
    if (n >= CONFIG.MIN_HIT_CELLS) {
      laser.hitFrames++;
      laser.hitAt = [x / n, h / n];
    }
  }

  hit(laser, now) {
    const player = this.players.get(laser.pid);
    const safe = !player || player.out || now - player.hitAt < CONFIG.HIT_COOLDOWN_S;
    if (safe) {
      laser.result = "dodged";
      return;
    }

    laser.result = "hit";
    player.hitAt = now;
    player.lives -= 1;
    if (player.lives <= 0) this.knockOut(player, now, "was hit by a laser");
  }

  knockOut(player, now, reason) {
    player.outAt = now;
    player.outReason = reason;
  }

  checkEnd(now) {
    const alive = [...this.players.values()].filter((player) => !player.out);
    const duel = this.players.size > 1;
    const over = duel ? alive.length <= 1 : alive.length === 0;

    if (over) {
      this.state = OVER;
      this.endedAt = now;
      this.winner = duel && alive.length ? alive[0].pid : null;
    }
  }

  /** Height (m) of the top of a player's silhouette in a frame. */
  top(frame, pid) {
    const body = frame.bodies[pid];
    if (!body || frame.counts[pid] < CONFIG.MIN_BODY_CELLS) return null;
    const first = body.indexOf(1);
    const row = Math.floor(first / this.spec.cols);
    return this.spec.heightRange[1] - row * this.spec.cell;
  }
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = sorted.length >> 1;
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}
