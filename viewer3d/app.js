// AEGIS-LINK 3D simulation view. Thin client: draws whatever the server's /ws says.
// Sim coordinates (x east, y north, z up, metres) -> three.js (x, y up, -z north), centred on the arena.
import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';

const CX = 450, CY = 250;
const toV = (x, y, z = 0) => new THREE.Vector3(x - CX, z, -(y - CY));
const fromV = (v) => [v.x + CX, -v.z + CY];
const UNIT_SCALE = 14;                 // units are drawn ~7x real size so they read from 1 km away
const COL = { ok: 0x3ee08f, degraded: 0xf2c14e, down: 0xff5468 };
const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- renderer, camera, controls
const canvas = $('scene');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(50, 1, 2, 20000);
camera.position.set(-520, 250, 1180);
const controls = new OrbitControls(camera, canvas);
controls.target.set(-30, 30, -80);
controls.enableDamping = true;
controls.maxPolarAngle = Math.PI * 0.47;
controls.minDistance = 150;
controls.maxDistance = 4200;

// ---------------------------------------------------------------- noise + terrain height
function hash(x, y) { const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453; return s - Math.floor(s); }
function vnoise(x, y) {
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const a = hash(xi, yi), b = hash(xi + 1, yi), c = hash(xi, yi + 1), d = hash(xi + 1, yi + 1);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
function fbm(x, y, o = 5) { let s = 0, a = 0.5, f = 1; for (let i = 0; i < o; i++) { s += a * vnoise(x * f, y * f); a *= 0.5; f *= 2.03; } return s; }
const PLAY = { x0: -820, x1: 820, z0: -720, z1: 720 };   // flat play area (three coords), a bit larger than the arena
function playDist(x, z) {
  const dx = Math.max(PLAY.x0 - x, 0, x - PLAY.x1), dz = Math.max(PLAY.z0 - z, 0, z - PLAY.z1);
  return Math.hypot(dx, dz);
}
function terrainH(x, z) {
  const d = playDist(x, z);
  if (d <= 0) return 0;
  const t = Math.min(1, d / 450), blend = t * t * (3 - 2 * t);
  const rolling = (fbm(x / 520, z / 520) - 0.45) * 90;
  const r = Math.hypot(x, z);
  const m = Math.max(0, (r - 1900) / 1300);                // mountain ring further out
  const ridge = Math.pow(1 - Math.abs(fbm(x / 900 + 7, z / 900 + 3, 4) * 2 - 1), 2.2);
  return blend * (Math.max(rolling, -8) + 40) + Math.min(m, 1.6) * ridge * 620;
}

// ---------------------------------------------------------------- sky, stars, sun/moon, fog, lights
const skyU = { top: { value: new THREE.Color() }, bottom: { value: new THREE.Color() }, glowDir: { value: new THREE.Vector3(0.3, 0.4, -1).normalize() }, glowCol: { value: new THREE.Color() } };
const sky = new THREE.Mesh(new THREE.SphereGeometry(12000, 32, 16), new THREE.ShaderMaterial({
  side: THREE.BackSide, depthWrite: false, uniforms: skyU,
  vertexShader: 'varying vec3 vDir; void main(){ vDir = normalize(position); gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }',
  fragmentShader: `uniform vec3 top; uniform vec3 bottom; uniform vec3 glowDir; uniform vec3 glowCol; varying vec3 vDir;
    void main(){ float h = clamp(vDir.y*1.6+0.12,0.0,1.0); vec3 c = mix(bottom, top, h);
      float g = pow(max(dot(normalize(vDir), glowDir),0.0), 24.0); c += glowCol*g*0.9 + glowCol*pow(max(dot(normalize(vDir), glowDir),0.0),3.0)*0.15;
      gl_FragColor = vec4(c,1.0); }`,
}));
scene.add(sky);

const starGeo = new THREE.BufferGeometry();
{ const p = []; for (let i = 0; i < 2600; i++) { const th = Math.random() * Math.PI * 2, ph = Math.acos(Math.random() * 0.92); p.push(Math.sin(ph) * Math.cos(th) * 11000, Math.cos(ph) * 11000, Math.sin(ph) * Math.sin(th) * 11000); }
  starGeo.setAttribute('position', new THREE.Float32BufferAttribute(p, 3)); }
const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0xffffff, size: 2.2, sizeAttenuation: false, transparent: true, opacity: 0.9, depthWrite: false }));
scene.add(stars);

function glowTexture(inner, outer) {
  const c = document.createElement('canvas'); c.width = c.height = 128; const g = c.getContext('2d');
  const gr = g.createRadialGradient(64, 64, 0, 64, 64, 64); gr.addColorStop(0, inner); gr.addColorStop(0.25, inner); gr.addColorStop(1, outer);
  g.fillStyle = gr; g.fillRect(0, 0, 128, 128); const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
const orb = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture('rgba(255,255,255,1)', 'rgba(255,255,255,0)'), depthWrite: false, fog: false }));
orb.scale.set(900, 900, 1); scene.add(orb);

const hemi = new THREE.HemisphereLight(0x8899ff, 0x1a2a18, 0.6); scene.add(hemi);
const sun = new THREE.DirectionalLight(0xffffff, 1.0);
sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -1100, right: 1100, top: 1100, bottom: -1100, near: 10, far: 5000 });
sun.shadow.bias = -0.0005; scene.add(sun); scene.add(sun.target);
scene.fog = new THREE.Fog(0x000000, 2600, 9500);

// clouds: soft sprites
const cloudTex = (() => { const c = document.createElement('canvas'); c.width = 256; c.height = 128; const g = c.getContext('2d');
  for (let i = 0; i < 26; i++) { const x = 40 + Math.random() * 176, y = 40 + Math.random() * 48, r = 18 + Math.random() * 34;
    const gr = g.createRadialGradient(x, y, 0, x, y, r); gr.addColorStop(0, 'rgba(255,255,255,0.55)'); gr.addColorStop(1, 'rgba(255,255,255,0)'); g.fillStyle = gr; g.fillRect(0, 0, 256, 128); }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t; })();
const clouds = [];
for (let i = 0; i < 16; i++) {
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: cloudTex, transparent: true, opacity: 0.5, depthWrite: false }));
  const a = Math.random() * Math.PI * 2, r = 1500 + Math.random() * 3500;
  s.position.set(Math.cos(a) * r, 900 + Math.random() * 700, Math.sin(a) * r); s.scale.set(1400 + Math.random() * 1200, 550, 1);
  scene.add(s); clouds.push(s);
}

let night = true;
function applyTheme() {
  if (night) {
    skyU.top.value.set(0x050b22); skyU.bottom.value.set(0x1b2a55); skyU.glowCol.value.set(0x6f86c9);
    skyU.glowDir.value.set(0.55, 0.42, -0.72).normalize();
    scene.fog.color.set(0x16224a); hemi.color.set(0x8fa2ff); hemi.groundColor.set(0x22331f); hemi.intensity = 1.05;
    sun.color.set(0xb4c6ff); sun.intensity = 1.1; stars.visible = true;
    orb.material.color.set(0xdfe8ff); orb.scale.set(520, 520, 1); renderer.toneMappingExposure = 1.05;
    clouds.forEach((c) => c.material.color.set(0x4a5a86));
  } else {
    skyU.top.value.set(0x2f6fd6); skyU.bottom.value.set(0xbfd9f2); skyU.glowCol.value.set(0xffd9a0);
    skyU.glowDir.value.set(0.5, 0.33, -0.8).normalize();
    scene.fog.color.set(0xb9cfe6); hemi.color.set(0xdfeaff); hemi.groundColor.set(0x4d5b2c); hemi.intensity = 0.85;
    sun.color.set(0xffe7c2); sun.intensity = 2.1; stars.visible = false;
    orb.material.color.set(0xfff1cc); orb.scale.set(1100, 1100, 1); renderer.toneMappingExposure = 1.0;
    clouds.forEach((c) => c.material.color.set(0xffffff));
  }
  const d = skyU.glowDir.value; sun.position.set(d.x * 2600, d.y * 2600, d.z * 2600); orb.position.set(d.x * 10000, d.y * 10000, d.z * 10000);
  buildingMats.forEach((m) => { m.emissiveIntensity = night ? 1.0 : 0.0; });
}

// ---------------------------------------------------------------- ground
const ground = (() => {
  const size = 9000, seg = 220;
  const geo = new THREE.PlaneGeometry(size, size, seg, seg); geo.rotateX(-Math.PI / 2);
  const pos = geo.attributes.position, cols = [];
  const c = new THREE.Color();
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), z = pos.getZ(i), h = terrainH(x, z); pos.setY(i, h);
    const n = fbm(x / 140, z / 140, 3);
    const d = playDist(x, z);
    if (h > 260) c.setRGB(0.36 + n * 0.1, 0.38 + n * 0.1, 0.42 + n * 0.1);                 // rock
    else if (d > 60 && d < 900 && Math.floor((x + 3000) / 160) % 3 === 0 && fbm(x / 600, z / 600) > 0.5) {
      const stripe = Math.floor((z + 3000) / 22) % 2;                                       // farmland
      c.setRGB(0.42 + stripe * 0.1, 0.43 + stripe * 0.08, 0.18);
    } else c.setRGB(0.16 + n * 0.12, 0.34 + n * 0.16, 0.13 + n * 0.06);                     // grass
    cols.push(c.r, c.g, c.b);
  }
  geo.setAttribute('color', new THREE.Float32BufferAttribute(cols, 3));
  geo.computeVertexNormals();
  const m = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ vertexColors: true }));
  m.receiveShadow = true; scene.add(m); return m;
})();

// lake
{ const lake = new THREE.Mesh(new THREE.CircleGeometry(420, 48), new THREE.MeshPhongMaterial({ color: 0x1d4f7a, shininess: 90, transparent: true, opacity: 0.92 }));
  lake.rotation.x = -Math.PI / 2; lake.position.set(-1500, 6, -950); lake.scale.set(1.6, 1, 1); scene.add(lake); }

// roads (the vehicles' routes) as flat ribbons with dashed centre lines
function road(p0, p1) {
  const a = toV(p0[0], p0[1], 0.4), b = toV(p1[0], p1[1], 0.4), len = a.distanceTo(b);
  const m = new THREE.Mesh(new THREE.PlaneGeometry(len, 14), new THREE.MeshLambertMaterial({ color: 0x3b3f45 }));
  m.rotation.x = -Math.PI / 2; m.rotation.z = Math.atan2(-(b.z - a.z), b.x - a.x); m.position.copy(a).lerp(b, 0.5); m.receiveShadow = true; scene.add(m);
  const n = Math.floor(len / 40);
  for (let i = 0; i < n; i++) { const d = new THREE.Mesh(new THREE.PlaneGeometry(16, 1.6), new THREE.MeshBasicMaterial({ color: 0xd8d2b0 }));
    d.rotation.copy(m.rotation); d.position.copy(a).lerp(b, (i + 0.5) / n); d.position.y = 0.6; scene.add(d); }
}
road([-150, -250], [950, -250]);
road([60, 760], [1080, 140]);

// trees: instanced, placed once (never more instances than allocated)
const TREE_MAX = 3200;
{ const cone = new THREE.ConeGeometry(1, 2.6, 7); cone.translate(0, 2.3, 0);
  const trunk = new THREE.CylinderGeometry(0.18, 0.24, 1.2, 5); trunk.translate(0, 0.6, 0);
  const leaves = new THREE.InstancedMesh(cone, new THREE.MeshLambertMaterial({ color: 0xffffff }), TREE_MAX);
  const wood = new THREE.InstancedMesh(trunk, new THREE.MeshLambertMaterial({ color: 0x4a3423 }), TREE_MAX);
  leaves.castShadow = true;
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3(), col = new THREE.Color();
  let n = 0, tries = 0;
  while (n < TREE_MAX && tries < 60000) {
    tries++;
    const x = (Math.random() - 0.5) * 6400, z = (Math.random() - 0.5) * 6400;
    const d = playDist(x, z), h = terrainH(x, z);
    const inside = d <= 0;
    if (h > 230) continue;
    if (inside && (Math.random() > 0.035 || Math.abs(x) < 120 && Math.abs(z) < 120)) continue;   // a few trees in the arena
    if (!inside && d < 280) continue;                                                           // open meadow around the arena
    if (!inside && fbm(x / 380 + 11, z / 380) < 0.42) continue;                                   // forests in clumps
    const sc = 7 + Math.random() * 9;
    p.set(x, h - 0.5, z); q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.random() * 6.3); s.set(sc, sc * (0.9 + Math.random() * 0.5), sc);
    m.compose(p, q, s); leaves.setMatrixAt(n, m); wood.setMatrixAt(n, m);
    col.setHSL(0.30 + Math.random() * 0.06, 0.42, 0.24 + Math.random() * 0.12); leaves.setColorAt(n, col);
    n++;
  }
  leaves.count = n; wood.count = n;
  scene.add(leaves, wood);
}

// ---------------------------------------------------------------- obstacles (from the server)
const buildingMats = [];
const obstacleGroup = new THREE.Group(); scene.add(obstacleGroup);
function windowTexture() {
  const c = document.createElement('canvas'); c.width = 64; c.height = 128; const g = c.getContext('2d');
  g.fillStyle = '#000'; g.fillRect(0, 0, 64, 128);
  for (let y = 6; y < 124; y += 10) for (let x = 5; x < 60; x += 9) if (Math.random() < 0.45) { g.fillStyle = `rgba(255,${200 + Math.random() * 40 | 0},140,${0.5 + Math.random() * 0.5})`; g.fillRect(x, y, 5, 5); }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
let obstaclesBuilt = false;
function buildObstacles(list) {
  if (obstaclesBuilt || !list?.length) return;
  obstaclesBuilt = true;
  for (const o of list) {
    if (o.kind === 'building') {
      const mat = new THREE.MeshLambertMaterial({ color: 0x8a909c, emissive: 0xffffff, emissiveMap: windowTexture(), emissiveIntensity: night ? 1 : 0 });
      buildingMats.push(mat);
      const b = new THREE.Mesh(new THREE.BoxGeometry(o.size[0], o.size[2], o.size[1]), mat);
      b.position.copy(toV(o.pos[0], o.pos[1], o.size[2] / 2)); b.castShadow = b.receiveShadow = true; obstacleGroup.add(b);
      const roof = new THREE.Mesh(new THREE.BoxGeometry(o.size[0] + 2, 1.5, o.size[1] + 2), new THREE.MeshLambertMaterial({ color: 0x4b505a }));
      roof.position.copy(toV(o.pos[0], o.pos[1], o.size[2] + 0.7)); obstacleGroup.add(roof);
      obstacleGroup.add(label(`${o.id} · ${o.size[2]} m`, '#c9d6f0', 0.016, toV(o.pos[0], o.pos[1], o.size[2] + 18)));
    } else {
      const hill = new THREE.Mesh(new THREE.SphereGeometry(1, 40, 20, 0, Math.PI * 2, 0, Math.PI / 2),
        new THREE.MeshLambertMaterial({ color: 0x4f8a42 }));
      hill.scale.set(o.size[0] / 2, o.size[2], o.size[1] / 2); hill.position.copy(toV(o.pos[0], o.pos[1], 0)); hill.receiveShadow = hill.castShadow = true;
      obstacleGroup.add(hill);
      obstacleGroup.add(label(`${o.id} · hill ${o.size[2]} m`, '#c9d6f0', 0.016, toV(o.pos[0], o.pos[1], o.size[2] + 18)));
    }
  }
}

// ---------------------------------------------------------------- labels (constant screen size)
function label(text, color = '#ffffff', size = 0.02, pos = null) {
  const c = document.createElement('canvas'), g = c.getContext('2d'); g.font = 'bold 44px Segoe UI, sans-serif';
  const w = Math.ceil(g.measureText(text).width) + 28; c.width = w; c.height = 64;
  g.font = 'bold 44px Segoe UI, sans-serif'; g.fillStyle = 'rgba(5,12,30,0.55)'; g.beginPath(); g.roundRect(0, 4, w, 56, 14); g.fill();
  g.fillStyle = color; g.textBaseline = 'middle'; g.fillText(text, 14, 33);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, depthTest: false, sizeAttenuation: false, transparent: true }));
  s.scale.set(size * w / 64, size, 1); s.renderOrder = 10; if (pos) s.position.copy(pos);
  s.userData.text = text; return s;
}
function relabel(sprite, text, color) {
  if (sprite.userData.text === text) return;
  const fresh = label(text, color, sprite.scale.y);
  sprite.material.map.dispose(); sprite.material.map = fresh.material.map; sprite.scale.copy(fresh.scale); sprite.userData.text = text;
}

// ---------------------------------------------------------------- unit models
const matCache = {};
const mat = (hex, extra = {}) => (matCache[hex + JSON.stringify(extra)] ||= new THREE.MeshLambertMaterial({ color: hex, ...extra }));
function droneModel(relay) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.45, 1.4), mat(relay ? 0x7b5cff : 0x2b3442)); g.add(body);
  const rotors = [];
  for (const [x, z] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) {
    const arm = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.12, 0.16), mat(0x1c222c)); arm.position.set(x * 0.55, 0, z * 0.55); arm.rotation.y = Math.atan2(z, x) * -1 + Math.PI / 2 * 0; arm.lookAt(0, 0, 0); g.add(arm);
    const rotor = new THREE.Mesh(new THREE.CylinderGeometry(0.62, 0.62, 0.04, 16), new THREE.MeshBasicMaterial({ color: 0xbfd6ff, transparent: true, opacity: 0.35 }));
    rotor.position.set(x * 1.05, 0.28, z * 1.05); g.add(rotor); rotors.push(rotor);
    const blade = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.03, 0.1), mat(0xdde6f5)); blade.position.copy(rotor.position); g.add(blade); rotors.push(blade);
  }
  const led = new THREE.Mesh(new THREE.SphereGeometry(0.26, 10, 8), new THREE.MeshBasicMaterial({ color: COL.ok })); led.position.set(0, -0.32, 0); g.add(led);
  g.traverse((o) => { if (o.isMesh) o.castShadow = true; });
  g.scale.setScalar(UNIT_SCALE);
  g.userData = { rotors, led };
  return g;
}
function vehicleModel() {
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(2.4, 1.0, 1.3), mat(0x5b6b3a)); body.position.y = 0.8; g.add(body);
  const cab = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.8, 1.2), mat(0x4a5830)); cab.position.set(0.7, 1.6, 0); g.add(cab);
  for (const [x, z] of [[0.8, 0.7], [0.8, -0.7], [-0.8, 0.7], [-0.8, -0.7]]) { const w = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.35, 0.25, 12), mat(0x111111)); w.rotation.x = Math.PI / 2; w.position.set(x, 0.35, z); g.add(w); }
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 1.4), mat(0x222222)); mast.position.set(-0.8, 2.0, 0.4); g.add(mast);
  const led = new THREE.Mesh(new THREE.SphereGeometry(0.2, 10, 8), new THREE.MeshBasicMaterial({ color: COL.ok })); led.position.set(-0.8, 2.75, 0.4); g.add(led);
  g.traverse((o) => { if (o.isMesh) o.castShadow = true; });
  g.scale.setScalar(UNIT_SCALE * 0.95);
  g.userData = { led };
  return g;
}
function commandPostModel() {
  const g = new THREE.Group();
  const hut = new THREE.Mesh(new THREE.BoxGeometry(3.2, 1.6, 2.4), mat(0x6c7684)); hut.position.y = 0.8; g.add(hut);
  const roof = new THREE.Mesh(new THREE.BoxGeometry(3.4, 0.2, 2.6), mat(0x39404b)); roof.position.y = 1.7; g.add(roof);
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.1, 6), mat(0x9aa4b2)); mast.position.set(1, 4.6, 0.6); g.add(mast);
  const dish = new THREE.Mesh(new THREE.SphereGeometry(0.6, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2.4), mat(0xd0d6de, { side: THREE.DoubleSide })); dish.position.set(-0.8, 2.3, -0.4); dish.rotation.x = -0.9; g.add(dish);
  const led = new THREE.Mesh(new THREE.SphereGeometry(0.22, 10, 8), new THREE.MeshBasicMaterial({ color: 0x46d3ff })); led.position.set(1, 7.7, 0.6); g.add(led);
  g.traverse((o) => { if (o.isMesh) o.castShadow = true; });
  g.scale.setScalar(UNIT_SCALE);
  g.userData = { led, blink: true };
  return g;
}

// jammer dome: fresnel energy shield with scrolling bands
const domeVS = 'varying vec3 vN; varying vec3 vV; varying vec2 vUv; void main(){ vUv = uv; vec4 mv = modelViewMatrix*vec4(position,1.0); vN = normalize(normalMatrix*normal); vV = normalize(-mv.xyz); gl_Position = projectionMatrix*mv; }';
const domeFS = `uniform vec3 col; uniform float t; uniform float k; varying vec3 vN; varying vec3 vV; varying vec2 vUv;
  void main(){ float f = pow(1.0-abs(dot(vN,vV)), 2.4); float band = smoothstep(0.88,1.0, fract(vUv.y*14.0 - t*0.6));
    float pulse = 0.75 + 0.25*sin(t*3.0); float a = (0.045 + f*0.5*pulse + band*0.07) * k; gl_FragColor = vec4(col*(0.7+f), a); }`;
function heatTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 128; const g = c.getContext('2d');
  const gr = g.createRadialGradient(64, 64, 0, 64, 64, 64); gr.addColorStop(0, 'rgba(255,60,60,0.55)'); gr.addColorStop(0.5, 'rgba(255,90,40,0.22)'); gr.addColorStop(1, 'rgba(255,60,40,0)');
  g.fillStyle = gr; g.fillRect(0, 0, 128, 128); const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
const HEAT = heatTexture();
function jammerReach(j) { return Math.max(70, 70 + (j.power_dbm - 18) * 12); }   // rough radius where it dominates our links
function jammerModel(j) {
  const g = new THREE.Group();
  const friendly = j.type === 'accidental';
  const color = friendly ? 0xffa64d : 0xff4a5c;
  const base = new THREE.Mesh(new THREE.BoxGeometry(2.2, 1.0, 1.6), mat(0x2a2f38)); base.position.y = 0.5;
  const ant = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 3.2), mat(0x777777)); ant.position.set(0.6, 2.4, 0);
  const tip = new THREE.Mesh(new THREE.SphereGeometry(0.28, 10, 8), new THREE.MeshBasicMaterial({ color })); tip.position.set(0.6, 4.1, 0);
  const unit = new THREE.Group(); unit.add(base, ant, tip); unit.scale.setScalar(UNIT_SCALE); unit.traverse((o) => { if (o.isMesh) o.castShadow = true; });
  g.add(unit);
  const R = jammerReach(j);
  const u = { col: { value: new THREE.Color(color) }, t: { value: 0 }, k: { value: friendly ? 0.6 : 1 } };
  const dome = new THREE.Mesh(new THREE.SphereGeometry(1, 48, 24, 0, Math.PI * 2, 0, Math.PI / 2),
    new THREE.ShaderMaterial({ uniforms: u, vertexShader: domeVS, fragmentShader: domeFS, transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending }));
  dome.scale.setScalar(R); g.add(dome);
  const heat = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: HEAT, transparent: true, depthWrite: false, color: friendly ? 0xffb070 : 0xffffff }));
  heat.rotation.x = -Math.PI / 2; heat.position.y = 1.2; heat.scale.setScalar(R * 2.2); g.add(heat);
  const tag = label(`${j.id} · ${j.type}${j.owner ? ' · ' + j.owner : ''}`, friendly ? '#ffc58a' : '#ff9aa6', 0.019); tag.position.y = 75; g.add(tag);
  g.userData = { uniforms: u, dome, heat, R };
  return g;
}

// ---------------------------------------------------------------- per-world dynamic state
class WorldView {
  constructor(id) {
    this.id = id;
    this.group = new THREE.Group(); scene.add(this.group);
    this.nodes = new Map(); this.links = []; this.jammers = new Map(); this.packets = []; this.estimates = [];
    this.state = null; this.spectrum = null; this.gradcam = null;
    this.linkGeo = new THREE.CylinderGeometry(1, 1, 1, 6, 1, true); this.linkGeo.translate(0, 0.5, 0); this.linkGeo.rotateX(Math.PI / 2);
  }
  dispose() { scene.remove(this.group); }
  apply(s) {
    this.state = s;
    // nodes
    const seen = new Set();
    for (const n of s.nodes) {
      seen.add(n.id);
      let v = this.nodes.get(n.id);
      if (!v) {
        const model = n.kind === 'drone' ? droneModel(false) : n.kind === 'relay' ? droneModel(true) : n.kind === 'vehicle' ? vehicleModel() : commandPostModel();
        const name = n.kind === 'command_post' ? 'CMD' : n.id;
        const tag = label(name, n.kind === 'relay' ? '#c6b6ff' : '#ffffff', 0.019);
        const drop = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]), new THREE.LineBasicMaterial({ color: 0x9fb5d8, transparent: true, opacity: 0.35 }));
        const target = toV(...n.pos);
        model.position.copy(target);
        this.group.add(model, tag, drop);
        v = { model, tag, drop, target, kind: n.kind };
        this.nodes.set(n.id, v);
      }
      v.target = toV(...n.pos);
      v.heading = n.heading_deg || 0;
      v.status = n.status;
      if (v.model.userData.led && n.kind !== 'command_post') v.model.userData.led.material.color.setHex(COL[n.status] ?? COL.ok);
    }
    for (const [id, v] of this.nodes) if (!seen.has(id)) { this.group.remove(v.model, v.tag, v.drop); this.nodes.delete(id); }

    // links: reuse a pool of tubes
    const L = s.links;
    while (this.links.length < L.length) {
      const m = new THREE.Mesh(this.linkGeo, new THREE.MeshBasicMaterial({ color: COL.ok, transparent: true, opacity: 0.9, depthWrite: false }));
      this.group.add(m); this.links.push(m);
    }
    this.links.forEach((m, i) => {
      const l = L[i];
      m.visible = !!l;
      if (!l) return;
      m.userData = { a: l.a, b: l.b, routed: l.routed, status: l.status, delivery: l.delivery_pct };
      m.material.color.setHex(COL[l.status]);
      m.material.opacity = l.routed ? 0.95 : 0.22;
    });

    // jammers
    const js = new Set();
    for (const j of s.jammers) {
      js.add(j.id);
      if (!this.jammers.has(j.id)) { const g = jammerModel(j); g.position.copy(toV(j.pos[0], j.pos[1], 0)); g.userData.born = performance.now(); this.group.add(g); this.jammers.set(j.id, g); }
      this.jammers.get(j.id).userData.active = j.active;
    }
    for (const [id, g] of this.jammers) if (!js.has(id)) { this.group.remove(g); this.jammers.delete(id); }

    // estimate rings
    const ests = s.estimates || [];
    while (this.estimates.length < ests.length) {
      const ring = new THREE.Mesh(new THREE.RingGeometry(0.96, 1, 96), new THREE.MeshBasicMaterial({ color: 0xffd54a, transparent: true, opacity: 0.95, side: THREE.DoubleSide, depthWrite: false }));
      ring.rotation.x = -Math.PI / 2;
      const dot = new THREE.Mesh(new THREE.CylinderGeometry(6, 6, 2, 20), new THREE.MeshBasicMaterial({ color: 0xffd54a }));
      const tag = label('estimate', '#ffe27a', 0.017);
      const g = new THREE.Group(); g.add(ring, dot, tag); this.group.add(g); this.estimates.push({ g, ring, tag });
    }
    this.estimates.forEach((e, i) => {
      const est = ests[i]; e.g.visible = !!est; if (!est) return;
      e.target = toV(est.pos[0], est.pos[1], 3); if (!e.g.userData.placed) { e.g.position.copy(e.target); e.g.userData.placed = true; }
      e.radius = est.radius_m;
      relabel(e.tag, `AI estimate ±${Math.round(est.radius_m)} m`, '#ffe27a');
    });
  }
  frame(dt, t) {
    for (const v of this.nodes.values()) {
      v.model.position.lerp(v.target, Math.min(1, dt * 8));
      if (v.kind === 'vehicle' || v.kind === 'drone' || v.kind === 'relay') v.model.rotation.y = THREE.MathUtils.degToRad(90 - v.heading) - Math.PI / 2 * (v.kind === 'vehicle' ? 0 : 0);
      const p = v.model.position;
      v.tag.position.set(p.x, p.y + (v.kind === 'command_post' ? 115 : 40), p.z);
      const arr = v.drop.geometry.attributes.position; arr.setXYZ(0, p.x, p.y, p.z); arr.setXYZ(1, p.x, 0.5, p.z); arr.needsUpdate = true;
      v.drop.visible = p.y > 15;
      if (v.model.userData.rotors) v.model.userData.rotors.forEach((r, i) => { r.rotation.y += dt * (i % 2 ? 38 : -38); });
      if (v.model.userData.blink) v.model.userData.led.visible = (t % 1.2) < 0.6;
    }
    const pos = (id) => this.nodes.get(id)?.model.position;
    for (const m of this.links) {
      if (!m.visible) continue;
      const a = pos(m.userData.a), b = pos(m.userData.b); if (!a || !b) { m.visible = false; continue; }
      const len = a.distanceTo(b); const r = m.userData.routed ? 1.6 : 0.6;
      m.position.copy(a); m.scale.set(r, r, len); m.lookAt(b);
    }
    for (const g of this.jammers.values()) {
      const u = g.userData; u.uniforms.t.value = t;
      const age = Math.min(1, (performance.now() - u.born) / 900);   // dome grows in when launched
      u.dome.scale.setScalar(u.R * (0.15 + 0.85 * age)); u.heat.material.opacity = (u.active ? 1 : 0.35) * age;
    }
    for (const e of this.estimates) {
      if (!e.g.visible || !e.target) continue;
      e.g.position.lerp(e.target, Math.min(1, dt * 3));
      const cur = e.ring.scale.x || 1; const r = cur + ((e.radius || 100) - cur) * Math.min(1, dt * 3);
      e.ring.scale.set(r, r, 1); e.tag.position.set(0, 14, r * 0.9);
      e.ring.material.opacity = 0.65 + 0.3 * Math.sin(t * 4);
    }
    this.flowPackets(dt);
  }
  flowPackets(dt) {
    // small glowing packets travelling child -> parent along routed links; fewer when delivery is low
    const routed = this.links.filter((m) => m.visible && m.userData.routed);
    const want = Math.min(60, routed.length * 3);
    while (this.packets.length < want) {
      const p = new THREE.Mesh(new THREE.SphereGeometry(3.2, 8, 6), new THREE.MeshBasicMaterial({ color: 0x9be7ff }));
      p.userData = { link: null, u: Math.random() }; this.group.add(p); this.packets.push(p);
    }
    const st = this.state; if (!st) return;
    const parentOf = Object.fromEntries(st.nodes.map((n) => [n.id, n.parent]));
    this.packets.forEach((p, i) => {
      const m = routed[i % Math.max(routed.length, 1)];
      if (!m || i >= want) { p.visible = false; return; }
      const { a, b, delivery } = m.userData;
      const child = parentOf[a] === b ? a : b, parent = child === a ? b : a;
      const A = this.nodes.get(child)?.model.position, B = this.nodes.get(parent)?.model.position;
      if (!A || !B) { p.visible = false; return; }
      p.userData.u += dt * 0.55;
      if (p.userData.u > 1) { p.userData.u -= 1; p.userData.lost = Math.random() * 100 > (delivery ?? 100); }
      p.visible = true;
      p.position.copy(A).lerp(B, p.userData.u);
      p.material.color.setHex(p.userData.lost ? 0xff5468 : 0x9be7ff);
      if (p.userData.lost && p.userData.u > 0.5) p.visible = false;    // dropped halfway
    });
  }
}

// ---------------------------------------------------------------- app state + panels
const worlds = new Map();
let view = 'single', hello = null, ws = null;
function worldIds() { return view === 'side_by_side' ? ['ai_off', 'ai_on'] : ['main']; }
function ensureWorld(id) {
  if (!worlds.has(id)) worlds.set(id, new WorldView(id));
  return worlds.get(id);
}
function primary() { return worlds.get(view === 'side_by_side' ? 'ai_on' : 'main'); }

function toast(text, level = 'info') {
  const d = document.createElement('div'); d.className = 'toast ' + level; d.textContent = text; $('toasts').prepend(d);
  setTimeout(() => d.remove(), 4600);
  while ($('toasts').childElementCount > 3) $('toasts').lastChild.remove();
}
function addDecision(text, level) {
  const list = $('dec-list'); const d = document.createElement('div');
  d.innerHTML = `<span class="t">${new Date().toLocaleTimeString([], { hour12: false })}</span><span class="${level}"></span>`;
  d.lastChild.textContent = text; list.prepend(d);
  while (list.childElementCount > 9) list.lastChild.remove();
}

function updatePanels() {
  const w = primary(); if (!w?.state) return;
  const s = w.state, k = s.kpis;
  $('k-delivery').textContent = k.delivery_pct.toFixed(1);
  $('k-links').textContent = `${k.healthy_links}/${k.total_links}`;
  $('k-latency').textContent = k.hop_latency_ms == null ? '—' : k.hop_latency_ms.toFixed(0);
  $('k-outage').textContent = (k.outage_ms / 1000).toFixed(1);
  $('k-decision').textContent = k.decision_time_ms == null ? '—' : k.decision_time_ms.toFixed(1);
  $('k-hops').textContent = k.hops;
  $('k-delivery').style.color = k.delivery_pct >= 90 ? 'var(--ok)' : k.delivery_pct >= 60 ? 'var(--deg)' : 'var(--down)';
  $('sec-ver').textContent = k.frames_verified.toLocaleString(); $('sec-rej').textContent = k.frames_rejected; $('sec-forged').textContent = k.frames_forged;
  const ai = view === 'side_by_side' ? true : s.ai_enabled;
  $('pill-ai').textContent = view === 'side_by_side' ? 'AI OFF vs ON' : ai ? `AI ON · ${s.defender}` : 'AI OFF · fixed hopping';
  $('pill-ai').className = 'pill ' + (ai ? '' : 'off');
  $('b-ai-on').classList.toggle('active', view === 'single' && s.ai_enabled);
  $('b-ai-off').classList.toggle('active', view === 'single' && !s.ai_enabled);
  $('b-split').classList.toggle('active', view === 'side_by_side');
  if (view === 'side_by_side') for (const id of ['ai_off', 'ai_on']) {
    const x = worlds.get(id)?.state; if (!x) continue;
    const kk = x.kpis; const c = kk.delivery_pct >= 90 ? 'var(--ok)' : kk.delivery_pct >= 60 ? 'var(--deg)' : 'var(--down)';
    $('strip-' + id).innerHTML = `delivered <b style="color:${c}">${kk.delivery_pct.toFixed(1)}%</b> · outage ${(kk.outage_ms / 1000).toFixed(1)} s · hops ${kk.hops}` +
      (kk.hop_latency_ms != null ? ` · hop ${kk.hop_latency_ms.toFixed(0)} ms` : '') + ` · ${x.hop_mode}${x.nodes[0]?.modulation === 'BPSK' ? ' · BPSK' : ''}${x.nodes[0] && x.nodes[0].tx_power_dbm > 27 ? ' · +' + (x.nodes[0].tx_power_dbm - 27) + ' dB' : ''}`;
  }
}

function heat(v) {
  const stops = [[8, 16, 46], [70, 34, 120], [190, 50, 90], [250, 140, 40], [255, 238, 150]];
  const x = Math.max(0, Math.min(0.999, v)) * (stops.length - 1), i = Math.floor(x), f = x - i, a = stops[i], b = stops[i + 1];
  return `rgb(${a[0] + (b[0] - a[0]) * f | 0},${a[1] + (b[1] - a[1]) * f | 0},${a[2] + (b[2] - a[2]) * f | 0})`;
}
function drawSpectrum(m) {
  const c = $('spec'), g = c.getContext('2d'); g.clearRect(0, 0, c.width, c.height);
  const bw = c.width / m.bins.length, cur = primary()?.state?.nodes?.[0]?.channel;
  m.bins.forEach((p, i) => { const h = Math.max(0, (p + 112) / 70) * (c.height - 12); g.fillStyle = p > -80 ? '#ff5468' : p > -95 ? '#f2c14e' : '#3d7bff'; g.fillRect(i * bw, c.height - h, bw - 0.6, h); });
  g.font = '10px Segoe UI'; for (let ch = 0; ch < 8; ch++) { g.fillStyle = ch === cur ? '#46d3ff' : '#6c80a6'; g.fillText('ch' + ch + (ch === cur ? ' ◀' : ''), ch * c.width / 8 + 3, 10); }
  const wf = $('waterfall'), wg = wf.getContext('2d');
  wg.drawImage(wf, 0, 0, wf.width, wf.height - 1, 0, 1, wf.width, wf.height - 1);
  m.bins.forEach((p, i) => { wg.fillStyle = heat((p + 112) / 55); wg.fillRect(i * (wf.width / m.bins.length), 0, wf.width / m.bins.length + 0.5, 1); });
}
function drawCnn(m) {
  const bars = $('cnn-bars'), v = $('cnn-verdict');
  if (!m.probs) { bars.innerHTML = '<span class="muted">switch AI ON to see what the CNN sees</span>'; v.textContent = ''; return; }
  bars.innerHTML = Object.entries(m.probs).map(([n, p]) =>
    `<div class="r"><span class="n">${n}</span><span class="b ${n === m.verdict ? (n === 'clean' ? 'clean' : 'top') : ''}" style="width:${Math.max(2, p * 90)}px"></span><span>${(p * 100).toFixed(0)}%</span></div>`).join('');
  v.textContent = `${m.verdict} ${(m.confidence * 100).toFixed(0)}%`; v.className = 'tag' + (m.verdict === 'clean' ? ' clean' : '');
  const c = $('gradcam'), g = c.getContext('2d');
  g.fillStyle = '#0a1430'; g.fillRect(0, 0, c.width, c.height);
  if (m.gradcam) { const cw = c.width / 32, chh = c.height / 12; m.gradcam.forEach((row, r) => row.forEach((x, k) => { g.fillStyle = heat(x); g.fillRect(k * cw, r * chh, cw + 0.5, chh + 0.5); })); }
  else { g.fillStyle = '#6c80a6'; g.font = '12px Segoe UI'; g.fillText('band clean: nothing to explain', 70, 64); }
}

// ---------------------------------------------------------------- websocket
function send(obj) { if (ws?.readyState === 1) ws.send(JSON.stringify({ type: 'cmd', player: $('player').value.trim() || undefined, ...obj })); }
function connect() {
  ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  ws.onopen = () => { $('pill-conn').textContent = 'live'; $('pill-conn').className = 'pill'; };
  ws.onclose = () => { $('pill-conn').textContent = 'reconnecting'; $('pill-conn').className = 'pill bad'; setTimeout(connect, 1000); };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    switch (m.type) {
      case 'hello':
        hello = m;
        $('pill-src').textContent = m.world_source === 'sim' ? 'live simulation' : 'placeholder world';
        $('banner-backend').textContent = m.signal_backend === 'gnuradio' ? 'GNU Radio' : 'NumPy';
        $('sec-fp').textContent = m.key_fingerprint || '—';
        $('jtype').innerHTML = m.jammer_types.map((t) => `<option>${t}</option>`).join('');
        buildObstacles(m.obstacles);
        break;
      case 'state': {
        if (m.view !== view) {
          view = m.view;
          document.body.classList.toggle('split', view === 'side_by_side');
          $('split').classList.toggle('hidden', view !== 'side_by_side');
        }
        for (const [id, w] of worlds) if (!worldIds().includes(id)) { w.dispose(); worlds.delete(id); }
        buildObstacles(m.obstacles);
        ensureWorld(m.world).apply(m);
        break;
      }
      case 'spectrum': {
        const w = ensureWorld(m.world); w.spectrum = m;
        if (w === primary()) { drawSpectrum(m); drawCnn(m); }
        break;
      }
      case 'decision': {
        if (view === 'side_by_side' && m.world === 'ai_off') break;
        const lat = m.latency_ms != null ? ` · ${m.latency_ms.toFixed(0)} ms` : '';
        addDecision(`${m.reason}${lat}`, m.class === 'accidental' || m.class === 'clean' ? 'info' : 'good');
        break;
      }
      case 'event':
        if (m.world === 'ai_off') break;
        if (m.level === 'alert' || m.level === 'warn') toast(m.text, m.level);
        else if (!m.world) toast(m.text, m.level);
        if (m.text.startsWith('Jammer located') || m.text.startsWith('Relay')) addDecision(m.text, 'info');
        break;
      case 'security':
        $('sec-result').textContent = `${m.test}: ${m.accepted ? 'ACCEPTED' : 'rejected'} · ${m.reason}`;
        break;
      case 'error':
        if (m.code === 'not_implemented') { $('sec-result').textContent = m.message; toast(m.message, 'warn'); }
        else toast(m.message, 'warn');
        break;
    }
  };
}

// ---------------------------------------------------------------- controls
$('b-ai-on').onclick = () => { if (view !== 'single') send({ action: 'set_view', view: 'single' }); send({ action: 'toggle_ai', enabled: true }); };
$('b-ai-off').onclick = () => { if (view !== 'single') send({ action: 'set_view', view: 'single' }); send({ action: 'toggle_ai', enabled: false }); };
$('b-split').onclick = () => send({ action: 'set_view', view: view === 'side_by_side' ? 'single' : 'side_by_side' });
$('b-clear').onclick = () => send({ action: 'clear_jammers' });
$('b-bench').onclick = () => send({ action: 'run_benchmark' });
$('b-reset').onclick = () => send({ action: 'restart' });
$('b-theme').onclick = () => { night = !night; applyTheme(); };
document.querySelectorAll('[data-sec]').forEach((b) => b.onclick = () => send({ action: 'security_test', test: b.dataset.sec }));

// click the ground to launch (a drag is a camera move, not a click)
const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(), groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
let down = null;
canvas.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
canvas.addEventListener('pointerup', (e) => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
  const r = canvas.getBoundingClientRect();
  let x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
  if (view === 'side_by_side') x = (x % 0.5) * 2;                         // either half maps to the same world
  ndc.set(x * 2 - 1, -(y * 2 - 1));
  ray.setFromCamera(ndc, camera);
  const hit = new THREE.Vector3(); if (!ray.ray.intersectPlane(groundPlane, hit)) return;
  const [sx, sy] = fromV(hit);
  const b = hello?.bounds || { x: [-300, 1200], y: [-400, 900] };
  if (sx < b.x[0] || sx > b.x[1] || sy < b.y[0] || sy > b.y[1]) { toast('Launch inside the arena (the flat area).', 'warn'); return; }
  send({ action: 'launch_jammer', jammer_type: $('jtype').value, pos: [Math.round(sx), Math.round(sy)] });
});

// ---------------------------------------------------------------- render loop (one renderer, one or two viewports)
function resize() {
  const w = window.innerWidth, h = window.innerHeight; renderer.setSize(w, h, false);
}
window.addEventListener('resize', resize); resize();
const clock = new THREE.Clock();
function render() {
  const dt = Math.min(clock.getDelta(), 0.1), t = clock.elapsedTime;
  controls.update();
  for (const w of worlds.values()) w.frame(dt, t);
  clouds.forEach((c, i) => { c.position.x += dt * (4 + i % 3); if (c.position.x > 5200) c.position.x = -5200; });
  const W = window.innerWidth, H = window.innerHeight;
  const ids = worldIds();
  renderer.setScissorTest(true);
  ids.forEach((id, i) => {
    const vx = ids.length === 2 ? i * W / 2 : 0, vw = ids.length === 2 ? W / 2 : W;
    for (const [wid, w] of worlds) w.group.visible = wid === id;
    camera.aspect = vw / H; camera.fov = ids.length === 2 ? 66 : 50; camera.updateProjectionMatrix();
    renderer.setViewport(vx, 0, vw, H); renderer.setScissor(vx, 0, vw, H);
    renderer.render(scene, camera);
  });
  renderer.setScissorTest(false);
  updatePanels();
  requestAnimationFrame(render);
}
applyTheme();
connect();
render();
