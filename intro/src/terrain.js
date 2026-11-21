// Block terrain for each mission's biome. A world is 64 × 56 columns of 2-unit blocks (128 × 112 units),
// centred on its own origin; worlds sit side by side along x so the deck is one long landscape.
// Roads, the command post and the jammer site are flattened to ground level (surface y = 0).
import { rngSeed } from './blocks.js';

export const B = 2;                 // block size in scene units
export const SPAN = 128;            // world width (64 columns)
const NX = 64, Z0 = -34, Z1 = 22;   // column range in z (blocks): from far back to near the camera

function valueNoise(seed) {
  const r = rngSeed(seed), P = new Float32Array(512);
  for (let i = 0; i < 512; i++) P[i] = r();
  const h = (x, z) => P[((x * 73856093) ^ (z * 19349663)) & 511];
  const s = (t) => t * t * (3 - 2 * t);
  const n = (x, z) => {
    const xi = Math.floor(x), zi = Math.floor(z), xf = s(x - xi), zf = s(z - zi);
    const a = h(xi, zi), b = h(xi + 1, zi), c = h(xi, zi + 1), d = h(xi + 1, zi + 1);
    return a + (b - a) * xf + (c - a) * zf + (a - b - c + d) * xf * zf;
  };
  return (x, z, oct = 3) => { let v = 0, amp = 1, f = 1, tot = 0; for (let o = 0; o < oct; o++) { v += n(x * f, z * f) * amp; tot += amp; amp *= 0.5; f *= 2; } return v / tot; };
}

function distToPolyline(px, pz, pts) {
  let best = 1e9;
  for (let i = 0; i < pts.length - 1; i++) {
    const [ax, az] = pts[i], [bx, bz] = pts[i + 1], dx = bx - ax, dz = bz - az;
    const t = Math.max(0, Math.min(1, ((px - ax) * dx + (pz - az) * dz) / (dx * dx + dz * dz)));
    best = Math.min(best, Math.hypot(px - (ax + t * dx), pz - (az + t * dz)));
  }
  return best;
}

// biome: per-column height (in blocks, 0 = ground level), surface block and fill
const BIOME = {
  mountains: (n, x, z) => {
    const back = Math.max(0, (-z - 26) / 3.4), front = 0;
    const L = Math.round(n(x / 22, z / 22) * 2 + back * (0.7 + n(x / 12, z / 12)) + front * n(x / 10, z / 9) * 2);
    return { L, top: L >= 9 ? 'snow' : L >= 5 ? 'stone' : 'grass', fill: L >= 5 ? 'stone' : 'dirt' };
  },
  city: () => ({ L: 0, top: 'concrete', fill: 'stone' }),
  coast: (n, x, z) => {
    if (z < -12) return { L: -1, top: 'water', fill: 'sand' };
    if (z < -5) return { L: 0, top: 'sand', fill: 'sand' };
    const L = Math.max(0, Math.round((n(x / 18, z / 18) - 0.45) * 5));
    return { L, top: 'grass', fill: 'dirt' };
  },
  forest: (n, x, z) => {
    const L = Math.max(0, Math.round((n(x / 20, z / 20) - 0.35) * 5 + Math.max(0, (-z - 28) / 5)));
    return { L, top: 'grass', fill: 'dirt' };
  },
  airbase: (n, x, z) => ({ L: z < -38 ? Math.round(n(x / 15, z / 15) * 4 + (-z - 38) / 3) : 0, top: 'grass', fill: 'dirt' }),
  camp: (n, x, z) => ({ L: Math.max(0, Math.round((n(x / 25, z / 25) - 0.5) * 4 + Math.max(0, (-z - 30) / 4))), top: 'grass', fill: 'dirt' }),
  desert: (n, x, z) => {
    const L = Math.max(0, Math.round((n(x / 14, z / 9) - 0.4) * 5 + Math.max(0, (-z - 30) / 3.5)));
    return { L, top: L > 4 ? 'sandstone' : 'sand', fill: 'sandstone' };
  },
  arena: (n, x, z) => ({ L: Math.max(0, Math.round((n(x / 24, z / 24) - 0.45) * 4 + Math.max(0, (-z - 34) / 4))), top: 'grass', fill: 'dirt' }),
};

export function buildTerrain(props, look, seed, { actors = true } = {}) {
  const n = valueNoise(seed), r = rngSeed(seed * 7 + 1);
  const biome = BIOME[props] || BIOME.arena;
  const road = look.road;
  const flat = [[-24, -2, 11], ...(actors ? [[look.jammerPos[0], look.jammerPos[2], 6]] : [])];
  const roadBlock = props === 'city' || props === 'airbase' ? 'asphalt' : props === 'desert' ? 'sandstone' : 'path';
  const W = NX, D = Z1 - Z0;
  const L = new Int16Array(W * D), top = new Array(W * D), fill = new Array(W * D), roadCol = new Uint8Array(W * D);
  const idx = (i, k) => k * W + i;
  for (let k = 0; k < D; k++) for (let i = 0; i < W; i++) {
    const x = (i - W / 2 + 0.5) * B, z = (k + Z0 + 0.5) * B;
    let c = biome(n, x + seed * 37, z);
    // edges blend to ground level so neighbouring worlds join without a cliff
    const edge = Math.min(1, (SPAN / 2 - Math.abs(x)) / 18);
    let h = c.L > 0 ? Math.round(c.L * Math.max(0, edge)) : c.L;
    const dRoad = actors ? distToPolyline(x, z, road) : 1e9;
    if (dRoad < 3.4) { h = Math.min(h, 0) === -1 && props === 'coast' ? 0 : 0; c = { ...c, top: roadBlock }; roadCol[idx(i, k)] = 1; }
    else if (dRoad < 6 && h > 0) h = 0;
    for (const [fx, fz, rad] of flat) if (Math.hypot(x - fx, z - fz) < rad) { h = Math.max(h, 0) > 0 ? 0 : Math.max(h, 0); if (c.top === 'water') c = { ...c, top: 'sand' }; }
    if (props === 'coast' && Math.hypot(x - look.jammerPos[0], z - look.jammerPos[2]) < 10) { h = -1; c = { L: -1, top: 'water', fill: 'sand' }; }
    L[idx(i, k)] = h; top[idx(i, k)] = c.top; fill[idx(i, k)] = c.fill;
  }
  const blocks = {};
  const add = (type, x, y, z, shade = 0.88 + r() * 0.17) => { (blocks[type] ||= []).push(x, y, z, shade); };
  const colAt = (x, z) => { const i = Math.floor(x / B + W / 2), k = Math.floor(z / B - Z0); return i >= 0 && i < W && k >= 0 && k < D ? idx(i, k) : -1; };
  const groundY = (x, z) => { const c = colAt(x, z); return c < 0 ? 0 : Math.max(0, L[c]) * B; };

  // terrain columns: draw only blocks that can be seen (the top, and sides above the lowest neighbour)
  for (let k = 0; k < D; k++) for (let i = 0; i < W; i++) {
    const c = idx(i, k), h = L[c], x = (i - W / 2 + 0.5) * B, z = (k + Z0 + 0.5) * B;
    if (top[c] === 'water') { add('water', x, -B / 2 - 0.3, z, 1); add('sand', x, -B * 1.5, z); continue; }
    let lo = h;
    for (const [di, dk] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const ii = i + di, kk = k + dk;
      lo = Math.min(lo, ii >= 0 && ii < W && kk >= 0 && kk < D ? L[idx(ii, kk)] + 1 : h - 1);
    }
    lo = Math.max(lo, h - 8);
    for (let lvl = h; lvl >= Math.min(lo, h); lvl--) {
      const y = (lvl - 0.5) * B;
      let t = lvl === h ? top[c] : (top[c] === 'grass' && lvl >= h - 2 ? 'dirt' : fill[c]);
      if (lvl === h && roadCol[c] && roadBlock === 'asphalt' && props === 'city' && r() < 0.1) t = 'marking';
      add(t, x, y, z);
    }
  }

  // decorations
  const free = (x, z, rad = 7) => {
    if (!actors) return Math.abs(x) < SPAN / 2 - 3;
    if (distToPolyline(x, z, road) < rad - 1) return false;
    for (const [fx, fz, fr] of flat) if (Math.hypot(x - fx, z - fz) < fr + 2) return false;
    return Math.abs(x) < SPAN / 2 - 3;
  };
  const snap = (v) => (Math.floor(v / B) + 0.5) * B;
  const tree = (x, z, kind = 'oak') => {
    x = snap(x); z = snap(z);
    const c = colAt(x, z); if (c < 0 || top[c] === 'water' || top[c] === 'snow' || top[c] === 'stone' || top[c] === 'sand' && kind !== 'cactus') return;
    const g = Math.max(0, L[c]) * B;
    if (kind === 'cactus') { const hgt = 2 + Math.floor(r() * 2); for (let j = 0; j < hgt; j++) add('cactus', x, g + (j + 0.5) * B, z); return; }
    const trunk = kind === 'spruce' ? 4 + Math.floor(r() * 2) : 3 + Math.floor(r() * 2);
    for (let j = 0; j < trunk; j++) add('log', x, g + (j + 0.5) * B, z);
    const leaf = kind === 'spruce' ? 'spruce' : 'leaves';
    if (kind === 'spruce') {
      const layers = [[trunk - 3, 2], [trunk - 2, 1], [trunk - 1, 2], [trunk, 1], [trunk + 1, 0]];
      for (const [ly, rad] of layers) for (let a = -rad; a <= rad; a++) for (let b2 = -rad; b2 <= rad; b2++) {
        if (Math.abs(a) + Math.abs(b2) > rad + (rad > 1 ? 1 : 0) || (a === 0 && b2 === 0 && ly < trunk)) continue;
        add(leaf, x + a * B, g + (ly + 0.5) * B, z + b2 * B);
      }
    } else {
      for (let ly = trunk - 1; ly <= trunk + 1; ly++) {
        const rad = ly === trunk + 1 ? 1 : 2;
        for (let a = -rad; a <= rad; a++) for (let b2 = -rad; b2 <= rad; b2++) {
          if ((Math.abs(a) === rad && Math.abs(b2) === rad && (rad === 2 || r() < 0.6)) || (a === 0 && b2 === 0 && ly < trunk)) continue;
          add(leaf, x + a * B, g + (ly + 0.5) * B, z + b2 * B);
        }
      }
    }
  };
  const building = (x, z, w, d, h, wall = 'concrete', lit = 0.5) => {
    x = snap(x); z = snap(z);
    const g = groundY(x, z);
    for (let a = 0; a < w; a++) for (let b2 = 0; b2 < d; b2++) for (let j = 0; j < h; j++) {
      const edgeA = a === 0 || a === w - 1, edgeB = b2 === 0 || b2 === d - 1;
      if (!(edgeA || edgeB || j === h - 1)) continue;
      const corner = edgeA && edgeB;
      const win = !corner && j > 0 && j < h - 1 && (a + b2) % 2 === 1;
      add(win ? (r() < lit ? 'window_lit' : 'window_dark') : wall, x + a * B, g + (j + 0.5) * B, z + b2 * B);
    }
  };
  const house = (x, z) => {
    x = snap(x); z = snap(z); const g = groundY(x, z);
    for (let a = 0; a < 3; a++) for (let b2 = 0; b2 < 3; b2++) for (let j = 0; j < 2; j++) if (a !== 1 || b2 !== 1) add(j === 1 && (a + b2) % 2 ? 'window_lit' : 'plank', x + a * B, g + (j + 0.5) * B, z + b2 * B);
    for (let a = -1; a <= 3; a++) for (let b2 = 0; b2 < 3; b2++) add('brick', x + a * B, g + 2.5 * B + (b2 === 1 ? B : 0), z + b2 * B);
  };

  const scatter = (count, fn, tries = 4) => { for (let i = 0; i < count; i++) for (let t = 0; t < tries; t++) { const x = (r() - 0.5) * (SPAN - 8), z = Z0 * B + 4 + r() * (24 - Z0 * B - 4); if (free(x, z)) { fn(x, z); break; } } };
  if (props === 'mountains') scatter(40, (x, z) => z < -10 && tree(x, z, 'spruce'));
  if (props === 'forest') scatter(150, (x, z) => tree(x, z, r() < 0.7 ? 'spruce' : 'oak'));
  if (props === 'arena') scatter(28, (x, z) => (z < -8 || z > 22) && tree(x, z, 'oak'));
  if (props === 'camp') {
    scatter(18, (x, z) => (z > 14 || z < -26) && tree(x, z, 'oak'));
    for (let i = 0; i < 4; i++) add('hay', snap(10 + i * 2.2), B / 2, snap(-14), 1);
  }
  if (props === 'airbase') { scatter(14, (x, z) => z > 22 && tree(x, z, 'oak')); }
  if (props === 'coast') { scatter(12, (x, z) => z > 4 && tree(x, z, 'oak')); for (let i = 0; i < 6; i++) house(-34 + i * 9, 6 + (i % 2) * 6); }
  if (props === 'desert') { scatter(26, (x, z) => tree(x, z, 'cactus')); house(30, 2); house(38, -6); }
  if (props === 'city') {
    for (let gx = -6; gx <= 6; gx++) for (let gz = -5; gz <= 2; gz++) {
      const x = gx * 9 + 1, z = gz * 9 - 4, w = 2 + Math.floor(r() * 2), d = 2 + Math.floor(r() * 2);
      if (!free(x + w, z + d, 8) || !free(x, z, 8) || r() < 0.15) continue;
      building(x, z, w, d, 3 + Math.floor(r() * (gz < -2 ? 9 : 5)), r() < 0.35 ? 'brick' : r() < 0.5 ? 'concrete_dark' : 'concrete', 0.55);
    }
  }
  if (props === 'airbase' && actors) {
    for (let a = -30; a < 30; a++) for (let b2 = -2; b2 <= 2; b2++) {
      const x = snap(a * B + 4), z = snap(-4 + b2 * B);
      add(b2 === 0 && a % 3 !== 0 ? 'marking' : 'asphalt', x, B * -0.5 + 0.06, z);
    }
    building(22, 4, 2, 2, 5, 'concrete', 0.8);
  }
  if (props === 'coast' && actors) { for (let j = 0; j < 6; j++) add(j % 2 ? 'brick' : 'concrete', snap(6), (j + 0.5) * B, snap(-4)); add('window_lit', snap(6), 6.5 * B, snap(-4), 1); }
  return { blocks, groundY };
}
