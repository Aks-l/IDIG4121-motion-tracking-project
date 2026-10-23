// A player's silhouette on a grid over the players' plane (the browser side
// of coop_game/vision/bodies.py): x across, height above the floor, cell 0
// at the top left, row by row. A body is a Uint8Array, 1 = body.

export class GridSpec {
  constructor({ x_range, height_range, cell }) {
    this.xRange = x_range;
    this.heightRange = height_range;
    this.cell = cell;
    this.rows = Math.round((height_range[1] - height_range[0]) / cell);
    this.cols = Math.round((x_range[1] - x_range[0]) / cell);
    this.size = this.rows * this.cols;

    // Centre (x, height) of every cell
    this.xs = new Float32Array(this.size);
    this.hs = new Float32Array(this.size);
    for (let row = 0; row < this.rows; row++) {
      for (let col = 0; col < this.cols; col++) {
        const i = row * this.cols + col;
        this.xs[i] = x_range[0] + (col + 0.5) * cell;
        this.hs[i] = height_range[1] - (row + 0.5) * cell;
      }
    }
  }
}

/** The server's base64 bits (numpy.packbits) -> a body. */
export function decodeBody(spec, base64) {
  const binary = atob(base64);
  const body = new Uint8Array(spec.size);
  for (let i = 0; i < spec.size; i++) {
    body[i] = (binary.charCodeAt(i >> 3) >> (7 - (i & 7))) & 1;
  }
  return body;
}

export function countCells(body) {
  let n = 0;
  for (let i = 0; i < body.length; i++) n += body[i];
  return n;
}

/** Indices of the cells whose centre is within thickness / 2 of a segment. */
export function segmentCells(spec, start, end, thickness) {
  const dx = end[0] - start[0];
  const dh = end[1] - start[1];
  const lengthSq = Math.max(dx * dx + dh * dh, 1e-9);
  const limit = (thickness / 2) ** 2;

  const cells = [];
  for (let i = 0; i < spec.size; i++) {
    // Closest point of the segment to the cell centre
    let t = ((spec.xs[i] - start[0]) * dx + (spec.hs[i] - start[1]) * dh) / lengthSq;
    t = Math.min(Math.max(t, 0), 1);
    const ex = spec.xs[i] - (start[0] + t * dx);
    const eh = spec.hs[i] - (start[1] + t * dh);
    if (ex * ex + eh * eh <= limit) cells.push(i);
  }
  return Int32Array.from(cells);
}
