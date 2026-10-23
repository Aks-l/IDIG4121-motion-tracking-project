// The 3D scene: a neon corridor running into the screen, lasers flying out
// of it at the players, and the players' glowing silhouettes at the front.
//
// three.js coordinates: x across (metres, as the tracker), y = height above
// the floor, z = -depth. The players' plane is z = 0 and fills the screen
// from the floor to the top of the grid: the screen is the players' mirror.

import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";

import { CONFIG } from "./config.js";
import { PLAYING } from "./duel.js";

export const PLAYER_COLORS = { 1: [60, 140, 255], 2: [60, 210, 100] };
const OUT_COLOR = [110, 110, 120];
const FLASH_COLOR = [255, 60, 60];

const BACKGROUND = 0x04060d;
const CORRIDOR_COLOR = 0x2b6ea8;
const CORRIDOR_HEIGHT_M = 2.7;
const RING_SPACING_M = 3.0;
const RING_SPEED_M_S = 6.0;
const HIT_FLASH_S = 0.6;
const SHAKE_S = 0.3;
const SHAKE_M = 0.04;

// Colours above 1 glow hardest under the bloom
const LASER_GLOW = new THREE.Color(2.2, 0.15, 0.35);
const LASER_CORE = new THREE.Color(3.0, 2.0, 2.3);
const HIT_GLOW = new THREE.Color(2.5, 1.8, 0.4);
const SPARK_COLOR = new THREE.Color(2.0, 1.4, 0.4);

const UP = new THREE.Vector3(0, 1, 0);

export class LaserScene {
  constructor(container, spec, lanes) {
    this.spec = spec;
    this.lanes = lanes;

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(BACKGROUND);
    this.scene.fog = new THREE.Fog(BACKGROUND, 6, CONFIG.LASER_START_DEPTH_M);

    // Looking straight at the middle of the players' plane, its full height
    // in view: then every point on the plane lands where it is in the room
    const [h0, h1] = spec.heightRange;
    this.eye = (h0 + h1) / 2;
    const fov = 2 * Math.atan((h1 - h0) / 2 / CONFIG.VIEW_DISTANCE_M) * (180 / Math.PI);
    this.camera = new THREE.PerspectiveCamera(fov, 1, 0.05, 100);
    this.cameraHome = new THREE.Vector3(0, this.eye, CONFIG.VIEW_DISTANCE_M);
    this.camera.position.copy(this.cameraHome);
    this.camera.lookAt(0, this.eye, 0);

    this.composer = new EffectComposer(this.renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), ...CONFIG.BLOOM);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());

    this.cylinder = new THREE.CylinderGeometry(1, 1, 1, 12, 1, true);
    this.lasers = new Map();       // laser id -> LaserMesh
    this.bursts = [];
    this.shakeUntil = -Infinity;
    this.lastNow = null;

    this.buildCorridor();
    this.silhouettes = { 1: new Silhouette(spec, this.scene), 2: new Silhouette(spec, this.scene) };

    this.resize();
    window.addEventListener("resize", () => this.resize());
  }

  resize() {
    const width = window.innerWidth;
    const height = window.innerHeight;
    this.renderer.setSize(width, height);
    this.composer.setSize(width, height);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  // ------------------------------------------------------------- scenery

  buildCorridor() {
    const far = -CONFIG.LASER_START_DEPTH_M;
    const near = CONFIG.VIEW_DISTANCE_M;
    const halfWidth = Math.max(...this.spec.xRange.map(Math.abs)) + 0.4;
    this.halfWidth = halfWidth;

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(2 * halfWidth, near - far),
      new THREE.MeshBasicMaterial({ color: 0x070b18 }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(0, 0, (near + far) / 2);
    this.scene.add(floor);

    // Each lane's floor, tinted in its player's colour
    for (const pid of [1, 2]) {
      const [x0, x1] = this.lanes[pid];
      const lane = new THREE.Mesh(
        new THREE.PlaneGeometry(x1 - x0, near - far),
        new THREE.MeshBasicMaterial({
          color: rgb(PLAYER_COLORS[pid], 1),
          transparent: true,
          opacity: 0.1,
          depthWrite: false,
        }),
      );
      lane.rotation.x = -Math.PI / 2;
      lane.position.set((x0 + x1) / 2, 0.002, (near + far) / 2);
      this.scene.add(lane);
    }

    // Floor lines and the corridor's edges, all running into the distance
    const lines = [];
    for (let x = -halfWidth; x <= halfWidth + 1e-6; x += 0.5) lines.push([x, 0.004]);
    const edges = [];
    for (const x of [-halfWidth, halfWidth]) for (const y of [0, CORRIDOR_HEIGHT_M]) edges.push([x, y]);

    const longLines = (points, color, opacity) => {
      const positions = points.flatMap(([x, y]) => [x, y, near, x, y, far]);
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
      const material = new THREE.LineBasicMaterial({ color, transparent: true, opacity });
      this.scene.add(new THREE.LineSegments(geometry, material));
    };
    longLines(lines, CORRIDOR_COLOR, 0.35);
    longLines(edges, CORRIDOR_COLOR, 1.0);
    longLines([[CONFIG.LANE_SPLIT_X_M, 0.006]], 0xc8c8e6, 1.0);

    // Frames of the corridor rushing toward the players: the sense of speed
    const frame = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-halfWidth, 0, 0),
      new THREE.Vector3(halfWidth, 0, 0),
      new THREE.Vector3(halfWidth, CORRIDOR_HEIGHT_M, 0),
      new THREE.Vector3(-halfWidth, CORRIDOR_HEIGHT_M, 0),
    ]);
    const ringMaterial = new THREE.LineBasicMaterial({ color: CORRIDOR_COLOR });
    this.rings = [];
    for (let depth = 0; depth < CONFIG.LASER_START_DEPTH_M; depth += RING_SPACING_M) {
      const ring = new THREE.LineLoop(frame, ringMaterial);
      this.scene.add(ring);
      this.rings.push(ring);
    }
  }

  moveRings(now) {
    const offset = (now * RING_SPEED_M_S) % RING_SPACING_M;
    this.rings.forEach((ring, i) => {
      ring.position.z = -((i + 1) * RING_SPACING_M - offset);
    });
  }

  // --------------------------------------------------------------- frame

  render(duel, now) {
    const dt = this.lastNow === null ? 0 : Math.min(now - this.lastNow, 0.1);
    this.lastNow = now;

    this.moveRings(now);
    this.updateLasers(duel, now);
    this.updateSilhouettes(duel, now);

    for (const burst of this.bursts) {
      burst.update(dt);
      if (burst.done) burst.dispose();
    }
    this.bursts = this.bursts.filter((burst) => !burst.done);

    // A hit shakes the view
    this.camera.position.copy(this.cameraHome);
    if (now < this.shakeUntil) {
      const strength = (SHAKE_M * (this.shakeUntil - now)) / SHAKE_S;
      this.camera.position.x += (Math.random() - 0.5) * 2 * strength;
      this.camera.position.y += (Math.random() - 0.5) * 2 * strength;
    }

    this.composer.render();
  }

  updateLasers(duel, now) {
    const alive = new Set();
    for (const laser of duel.lasers) {
      alive.add(laser.id);
      let mesh = this.lasers.get(laser.id);
      if (!mesh) {
        mesh = new LaserMesh(laser, this.cylinder, this.scene);
        this.lasers.set(laser.id, mesh);
      }
      mesh.update(laser, now, duel.state === PLAYING);

      if (laser.result === "hit" && !mesh.burst) {
        mesh.burst = true;
        if (laser.hitAt) this.bursts.push(new Burst(this.scene, laser.hitAt));
        this.shakeUntil = now + SHAKE_S;
      }
    }

    for (const [id, mesh] of this.lasers) {
      if (!alive.has(id)) {
        mesh.dispose();
        this.lasers.delete(id);
      }
    }
  }

  updateSilhouettes(duel, now) {
    const frame = duel.frames[duel.frames.length - 1];
    for (const pid of [1, 2]) {
      const body = frame ? frame.bodies[pid] : null;
      const player = duel.players.get(pid);

      let base = PLAYER_COLORS[pid];
      if (player && player.out) base = OUT_COLOR;
      else if (player && now - player.hitAt < HIT_FLASH_S && Math.floor(now * 12) % 2) base = FLASH_COLOR;

      this.silhouettes[pid].update(body, frame ? frame.time : null, base);
    }
  }
}

/** One laser: a bright core inside a glowing tube, plus a faint line on the
 *  players' plane showing where it will land. */
class LaserMesh {
  constructor(laser, cylinder, scene) {
    this.scene = scene;
    this.burst = false;

    const [x0, h0] = laser.start;
    const [x1, h1] = laser.end;
    const direction = new THREE.Vector3(x1 - x0, h1 - h0, 0);
    const length = direction.length();
    this.middle = [(x0 + x1) / 2, (h0 + h1) / 2];
    const turn = new THREE.Quaternion().setFromUnitVectors(UP, direction.normalize());

    const tube = (radius, color, opacity) => {
      const material = new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        toneMapped: false,
      });
      const mesh = new THREE.Mesh(cylinder, material);
      mesh.scale.set(radius, length, radius);
      mesh.quaternion.copy(turn);
      return mesh;
    };

    const radius = CONFIG.LASER_DRAW_WIDTH_M / 2;
    this.glow = tube(radius, LASER_GLOW, 0.55);
    this.core = tube(radius * 0.35, LASER_CORE, 1.0);
    this.beam = new THREE.Group();
    this.beam.add(this.glow, this.core);

    this.preview = tube(0.006, LASER_GLOW, 0.2);
    this.preview.position.set(this.middle[0], this.middle[1], 0);

    scene.add(this.beam, this.preview);
  }

  update(laser, now, playing) {
    const depth = laser.depth(now);
    this.beam.position.set(this.middle[0], this.middle[1], -depth);

    // Fog dims it far away; once past the players it fades out
    const fade = depth >= 0 ? 1 : Math.max(0, 1 + depth / CONFIG.LASER_PAST_DEPTH_M);
    this.beam.visible = fade > 0;
    this.glow.material.opacity = 0.55 * fade;
    this.core.material.opacity = fade;
    if (laser.result === "hit") this.glow.material.color.copy(HIT_GLOW);

    // Where it will land: brighter as it gets closer, blinking at the end
    this.preview.visible = playing && laser.result === null;
    const progress = Math.min(Math.max(1 - depth / CONFIG.LASER_START_DEPTH_M, 0), 1);
    const blink = laser.arrive - now > 0.5 || Math.floor(now * 10) % 2 ? 1 : 0.4;
    this.preview.material.opacity = (0.08 + 0.3 * progress) * blink;
  }

  dispose() {
    this.scene.remove(this.beam, this.preview);
    for (const mesh of [this.glow, this.core, this.preview]) mesh.material.dispose();
  }
}

/** A player's silhouette as a glowing picture on the players' plane: dim
 *  inside, bright outline, softened by the texture's smoothing. */
class Silhouette {
  constructor(spec, scene) {
    this.spec = spec;
    this.pixels = new Uint8Array(spec.size * 4);
    this.texture = new THREE.DataTexture(this.pixels, spec.cols, spec.rows, THREE.RGBAFormat);
    this.texture.magFilter = THREE.LinearFilter;
    this.texture.minFilter = THREE.LinearFilter;
    this.texture.colorSpace = THREE.SRGBColorSpace;

    const [x0, x1] = spec.xRange;
    const [h0, h1] = spec.heightRange;
    this.mesh = new THREE.Mesh(
      new THREE.PlaneGeometry(x1 - x0, h1 - h0),
      new THREE.MeshBasicMaterial({
        map: this.texture,
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        toneMapped: false,
      }),
    );
    this.mesh.position.set((x0 + x1) / 2, (h0 + h1) / 2, 0);
    scene.add(this.mesh);
    this.key = null;
  }

  update(body, time, base) {
    this.mesh.visible = body !== null;
    const key = `${time}|${base}`;
    if (!body || key === this.key) return;
    this.key = key;

    const { rows, cols } = this.spec;
    const fill = base.map((c) => Math.round(c * 0.35));
    const edge = base.map((c) => Math.min(255, Math.round(c * 1.2)));
    const pixels = this.pixels;
    pixels.fill(0);

    for (let row = 0; row < rows; row++) {
      // Texture rows run from the bottom up, grid rows from the top down
      const out = (rows - 1 - row) * cols;
      for (let col = 0; col < cols; col++) {
        const i = row * cols + col;
        if (!body[i]) continue;

        const inner =
          row > 0 && body[i - cols] && row < rows - 1 && body[i + cols] &&
          col > 0 && body[i - 1] && col < cols - 1 && body[i + 1];
        const color = inner ? fill : edge;
        const p = (out + col) * 4;
        pixels[p] = color[0];
        pixels[p + 1] = color[1];
        pixels[p + 2] = color[2];
        pixels[p + 3] = 255;
      }
    }
    this.texture.needsUpdate = true;
  }
}

/** Sparks flying out of the spot a laser touched, toward the players. */
class Burst {
  constructor(scene, [x, h]) {
    this.scene = scene;
    this.age = 0;
    this.lifetime = 0.9;
    const count = 140;

    this.velocities = new Float32Array(count * 3);
    const positions = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      positions.set([x, h, 0], i * 3);
      const direction = new THREE.Vector3().randomDirection();
      const speed = 0.8 + Math.random() * 2.2;
      this.velocities.set([direction.x * speed, direction.y * speed + 0.8, Math.abs(direction.z) * speed + 0.6], i * 3);
    }

    this.geometry = new THREE.BufferGeometry();
    this.geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    this.material = new THREE.PointsMaterial({
      color: SPARK_COLOR,
      size: 0.025,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      toneMapped: false,
    });
    this.points = new THREE.Points(this.geometry, this.material);
    scene.add(this.points);
  }

  get done() {
    return this.age >= this.lifetime;
  }

  update(dt) {
    this.age += dt;
    const positions = this.geometry.attributes.position.array;
    for (let i = 0; i < positions.length; i += 3) {
      this.velocities[i + 1] -= 4.0 * dt;      // gravity
      positions[i] += this.velocities[i] * dt;
      positions[i + 1] += this.velocities[i + 1] * dt;
      positions[i + 2] += this.velocities[i + 2] * dt;
    }
    this.geometry.attributes.position.needsUpdate = true;
    this.material.opacity = Math.max(0, 1 - this.age / this.lifetime);
  }

  dispose() {
    this.scene.remove(this.points);
    this.geometry.dispose();
    this.material.dispose();
  }
}

function rgb([r, g, b], factor) {
  return new THREE.Color().setRGB(
    (r / 255) * factor, (g / 255) * factor, (b / 255) * factor, THREE.SRGBColorSpace,
  );
}
