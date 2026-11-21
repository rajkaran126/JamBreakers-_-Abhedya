// Minecraft-style pixel textures, drawn in code (16 × 16, no image files), and the block types built from them.
import * as THREE from 'three';

function rng(seed) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
const mix = (c, f) => c.map((v) => Math.max(0, Math.min(255, Math.round(v * f))));

function canvasTex(draw, seed, { alpha = false } = {}) {
  const c = document.createElement('canvas'); c.width = c.height = 16;
  const g = c.getContext('2d'), img = g.createImageData(16, 16), r = rng(seed);
  const put = (x, y, col, a = 255) => { const i = (y * 16 + x) * 4; img.data[i] = col[0]; img.data[i + 1] = col[1]; img.data[i + 2] = col[2]; img.data[i + 3] = a; };
  draw(put, r);
  g.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c);
  t.magFilter = THREE.NearestFilter; t.minFilter = THREE.NearestMipmapLinearFilter;
  t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  if (alpha) t.premultiplyAlpha = false;
  return t;
}

// speckle: base colour with random lighter / darker pixels
const speckle = (base, spread = 0.12, seedExtra = 0) => (put, r) => {
  const b = hex(base);
  for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) put(x, y, mix(b, 1 - spread + r() * spread * 2 + seedExtra * 0));
};

const DRAW = {
  grass_top: speckle('#5d9b38', 0.16),
  dirt: speckle('#86603f', 0.16),
  stone: (put, r) => { const b = hex('#7f7f80'); for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) { let f = 0.86 + r() * 0.2; if (r() < 0.07) f = 0.68; put(x, y, mix(b, f)); } },
  sand: speckle('#dccf91', 0.07),
  sandstone: (put, r) => { const b = hex('#d9c48a'); for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) put(x, y, mix(b, (y % 5 === 0 ? 0.86 : 0.97) + r() * 0.06)); },
  snow: speckle('#f1f5f9', 0.04),
  water: (put, r) => { const b = hex('#2c5aa6'); for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) put(x, y, mix(b, 0.9 + r() * 0.12 + ((x + y * 3) % 9 === 0 ? 0.25 : 0)), 200); },
  leaves: (put, r) => { const b = hex('#3c7a2a'); for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) put(x, y, mix(b, r() < 0.18 ? 0.55 : 0.85 + r() * 0.3)); },
  spruce: (put, r) => { const b = hex('#2d5a35'); for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) put(x, y, mix(b, r() < 0.2 ? 0.55 : 0.85 + r() * 0.25)); },
  log_side: (put, r) => { const a = hex('#6b5130'), b = hex('#4c3a22'); for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) put(x, y, mix(x % 4 === 0 || (x % 4 === 2 && r() < 0.3) ? b : a, 0.92 + r() * 0.12)); },
  log_top: (put, r) => { const a = hex('#a3824e'), b = hex('#6b5130'); for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) { const d = Math.max(Math.abs(x - 7.5), Math.abs(y - 7.5)); put(x, y, mix(d > 6.5 ? b : Math.floor(d) % 2 ? a : mix(a, 0.85), 0.95 + r() * 0.08)); } },
  plank: (put, r) => { const b = hex('#a5824e'); for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) put(x, y, mix(b, y % 4 === 3 ? 0.68 : (x === (y < 8 ? 5 : 11) && y % 4 !== 3 ? 0.75 : 0.92 + r() * 0.1))); },
  brick: (put, r) => { const b = hex('#94473a'), m = hex('#b9ad9f'); for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) { const row = Math.floor(y / 4), off = row % 2 ? 4 : 0; const mortar = y % 4 === 3 || (x + off) % 8 === 7; put(x, y, mortar ? mix(m, 0.95 + r() * 0.05) : mix(b, 0.88 + r() * 0.16)); } },
  concrete: speckle('#8e9399', 0.05),
  concrete_dark: speckle('#585e66', 0.06),
  window_lit: (put, r) => { const f = hex('#4a4f57'), l = hex('#ffcf7a'); for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) put(x, y, x < 2 || x > 13 || y < 2 || y > 13 || x === 7 || x === 8 ? mix(f, 0.9 + r() * 0.1) : mix(l, 0.85 + r() * 0.2)); },
  window_dark: (put, r) => { const f = hex('#4a4f57'), l = hex('#1d2a3a'); for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) put(x, y, x < 2 || x > 13 || y < 2 || y > 13 || x === 7 || x === 8 ? mix(f, 0.9 + r() * 0.1) : mix(l, 0.9 + r() * 0.2 + (x - y === 3 ? 0.6 : 0))); },
  asphalt: (put, r) => { const b = hex('#3b3e43'); for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) put(x, y, mix(b, 0.88 + r() * 0.2)); },
  path: (put, r) => { const b = hex('#93784b'); for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) put(x, y, mix(b, r() < 0.1 ? 0.75 : 0.92 + r() * 0.14)); },
  cactus: (put, r) => { const b = hex('#3f8b3b'); for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) put(x, y, mix(b, x % 5 === 0 ? 0.7 : 0.9 + r() * 0.14)); },
  marking: speckle('#e9e6dc', 0.04),
  hay: (put, r) => { const b = hex('#c9a43a'); for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) put(x, y, mix(b, y % 3 === 0 ? 0.8 : 0.92 + r() * 0.12)); },
};

// side texture with a top strip of another (grass on dirt, snow on dirt)
function stripTex(top, body, rows, seed) {
  return canvasTex((put, r) => {
    const t = hex(top), b = hex(body);
    const depth = Array.from({ length: 16 }, () => rows + (r() < 0.5 ? 1 : 0) + (r() < 0.2 ? 1 : 0));
    for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) put(x, y, y < depth[x] ? mix(t, 0.85 + r() * 0.25) : mix(b, 0.85 + r() * 0.25));
  }, seed);
}

let CACHE = null;
export function blockMaterials() {
  if (CACHE) return CACHE;
  const T = {};
  let s = 1;
  for (const [k, d] of Object.entries(DRAW)) T[k] = canvasTex(d, s++);
  T.grass_side = stripTex('#5d9b38', '#86603f', 3, 91);
  T.snow_side = stripTex('#f1f5f9', '#7f7f80', 4, 92);
  const lam = (map, extra = {}) => new THREE.MeshLambertMaterial({ map, ...extra });
  const six = (side, top, bottom) => [lam(side), lam(side), lam(top), lam(bottom), lam(side), lam(side)];
  CACHE = {
    grass: six(T.grass_side, T.grass_top, T.dirt),
    dirt: lam(T.dirt), stone: lam(T.stone), sand: lam(T.sand), sandstone: lam(T.sandstone),
    snow: six(T.snow_side, T.snow, T.stone),
    water: lam(T.water, { transparent: true, opacity: 0.82, depthWrite: false }),
    leaves: lam(T.leaves), spruce: lam(T.spruce),
    log: six(T.log_side, T.log_top, T.log_top),
    plank: lam(T.plank), brick: lam(T.brick), concrete: lam(T.concrete), concrete_dark: lam(T.concrete_dark),
    window_lit: lam(T.window_lit, { emissive: new THREE.Color('#ffb347'), emissiveMap: T.window_lit, emissiveIntensity: 0.9 }),
    window_dark: lam(T.window_dark),
    asphalt: lam(T.asphalt), path: lam(T.path), cactus: lam(T.cactus), marking: lam(T.marking), hay: six(T.hay, T.hay, T.hay),
  };
  CACHE.waterTex = T.water;
  return CACHE;
}

export const rngSeed = rng;
