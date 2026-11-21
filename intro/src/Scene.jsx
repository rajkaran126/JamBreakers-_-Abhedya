// Live 3D backdrop for the mission deck. One <Canvas>; each slide's scene slides in from the side
// (the PPT-style horizontal move) while the previous one slides out. Every scene plays the same
// 12-second story: links clear → jammer switches on → AI responds → links restored.
import { useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { LOOK } from './slides.js';
import { blockMaterials } from './blocks.js';
import { B, SPAN, buildTerrain } from './terrain.js';

export const LOOP_S = 12;
export const phaseAt = (t) => { const u = t % LOOP_S; return u < 3 ? 0 : u < 6.5 ? 1 : u < 8.5 ? 2 : 3; };

// sky per time of day: dome top / horizon, fog, sun, ambient, how much of the stars and windows show
const SKY = {
  night: { top: '#070d26', hor: '#23345a', fog: '#1a2742', sun: '#c3d0ff', sunI: 0.75, amb: 0.55, hemi: '#7d8fc8', stars: 1, sunPos: [-60, 90, -120], sunCol: '#e8eeff' },
  dusk: { top: '#262a66', hor: '#c98a7e', fog: '#4a4566', sun: '#ffb27a', sunI: 0.95, amb: 0.5, hemi: '#9c86c9', stars: 0.35, sunPos: [120, 22, -160], sunCol: '#ffcf8a' },
  day: { top: '#3d7fd6', hor: '#bfe2ff', fog: '#a7cdee', sun: '#fff4dc', sunI: 1.5, amb: 0.65, hemi: '#cfe8ff', stars: 0, sunPos: [80, 140, -60], sunCol: '#fffbe6' },
  sunset: { top: '#4b4a8e', hor: '#e8a56c', fog: '#9c7258', sun: '#ff9257', sunI: 1.25, amb: 0.55, hemi: '#ffb88a', stars: 0, sunPos: [-140, 26, -150], sunCol: '#ffb36b' },
};

function rng(seed) {                    // mulberry32: same layout every time
  let a = seed >>> 0;
  return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

// ------------------------------------------------------------------ actors
function Drone({ id, reg, path, color = '#d8e2ee', led = '#5fe3ff', hostile = false, scale = 1 }) {
  const g = useRef(), rotors = useRef([]);
  scale = scale * 1.6;
  const prev = useMemo(() => new THREE.Vector3(), []);
  useFrame(({ clock }) => {
    const t = clock.elapsedTime, p = path(t);
    if (!g.current) return;
    prev.copy(g.current.position);
    g.current.position.set(p[0], p[1], p[2]);
    const dx = p[0] - prev.x, dz = p[2] - prev.z;
    if (dx * dx + dz * dz > 1e-6) g.current.rotation.y = Math.atan2(dx, dz);
    g.current.rotation.z = Math.sin(t * 1.7 + p[0]) * 0.06;
    rotors.current.forEach((r) => r && (r.rotation.y += 0.9));
    if (reg) reg.current[id] = g.current.position;
  });
  const arms = [[1, 1], [1, -1], [-1, 1], [-1, -1]];
  return (
    <group ref={g} scale={scale}>
      <mesh castShadow><boxGeometry args={[1.1, 0.34, 1.1]} /><meshStandardMaterial color={hostile ? '#3a0c0c' : '#2b3644'} metalness={0.6} roughness={0.35} /></mesh>
      <mesh position={[0, 0.2, 0]}><sphereGeometry args={[0.36, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2]} /><meshStandardMaterial color={color} metalness={0.3} roughness={0.3} /></mesh>
      {arms.map(([sx, sz], i) => (
        <group key={i}>
          <mesh position={[sx * 0.75, 0, sz * 0.75]} rotation={[0, Math.atan2(sx, sz), 0]}><boxGeometry args={[0.12, 0.08, 1.2]} /><meshStandardMaterial color="#1c232c" /></mesh>
          <mesh ref={(r) => (rotors.current[i] = r)} position={[sx * 1.2, 0.14, sz * 1.2]}>
            <cylinderGeometry args={[0.55, 0.55, 0.02, 20]} /><meshBasicMaterial color={hostile ? '#ff6b6b' : '#a9c6e8'} transparent opacity={0.28} />
          </mesh>
        </group>
      ))}
      <mesh position={[0, -0.22, 0.45]}><sphereGeometry args={[0.1, 8, 8]} /><meshBasicMaterial color={hostile ? '#ff3030' : led} /></mesh>
    </group>
  );
}

function Truck({ id, reg, curve, offset = 0, speed = 0.035, accent }) {
  const g = useRef();
  const look = useMemo(() => new THREE.Vector3(), []);
  useFrame(({ clock }) => {
    if (!g.current) return;
    const u = (clock.elapsedTime * speed + offset) % 1;
    const p = curve.getPointAt(u), q = curve.getPointAt(Math.min(0.999, u + 0.004));
    g.current.position.set(p.x, 1.25, p.z);
    look.set(q.x, 1.25, q.z);
    g.current.lookAt(look);
    if (reg) reg.current[id] = g.current.position;
  });
  return (
    <group ref={g} scale={1.6}>
      <mesh position={[0, 0.15, -0.6]} castShadow><boxGeometry args={[1.5, 1.2, 2.6]} /><meshStandardMaterial color="#4a5a3a" roughness={0.8} /></mesh>
      <mesh position={[0, -0.05, 1.15]} castShadow><boxGeometry args={[1.45, 0.95, 1.1]} /><meshStandardMaterial color="#3d4b30" roughness={0.7} /></mesh>
      <mesh position={[0, 0.12, 1.71]}><boxGeometry args={[1.2, 0.35, 0.02]} /><meshStandardMaterial color="#9fc6ff" emissive="#335" /></mesh>
      <mesh position={[0.45, 1.25, -1.2]}><cylinderGeometry args={[0.03, 0.03, 1.4]} /><meshStandardMaterial color="#222" /></mesh>
      <mesh position={[0.45, 1.98, -1.2]}><sphereGeometry args={[0.09, 8, 8]} /><meshBasicMaterial color={accent} /></mesh>
      {[-0.65, 0.4, 1.2].map((z) => [-0.78, 0.78].map((x) => (
        <mesh key={`${x}${z}`} position={[x, -0.55, z]} rotation={[0, 0, Math.PI / 2]}><cylinderGeometry args={[0.36, 0.36, 0.25, 14]} /><meshStandardMaterial color="#111" /></mesh>
      )))}
    </group>
  );
}

function CommandPost({ reg, accent, pos = [-24, 0, -2] }) {
  const dish = useRef(), led = useRef(), top = useMemo(() => new THREE.Vector3(pos[0], 8.2 * 1.4, pos[2]), [pos]);
  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    if (dish.current) dish.current.rotation.y = t * 0.4;
    if (led.current) led.current.material.opacity = 0.4 + 0.6 * (Math.sin(t * 4) > 0 ? 1 : 0);
    if (reg) reg.current.CP = top;
  });
  return (
    <group position={pos} scale={1.4}>
      <mesh position={[0, 0.9, 0]} castShadow><boxGeometry args={[4, 1.8, 3]} /><meshStandardMaterial color="#38433a" roughness={0.9} /></mesh>
      <mesh position={[0, 4.5, 0]}><cylinderGeometry args={[0.12, 0.2, 7.2, 8]} /><meshStandardMaterial color="#8c96a3" metalness={0.7} /></mesh>
      <group ref={dish} position={[0, 7.4, 0]}>
        <mesh rotation={[Math.PI / 2.6, 0, 0]}><sphereGeometry args={[0.9, 20, 8, 0, Math.PI * 2, 0, Math.PI / 3.2]} /><meshStandardMaterial color="#cfd6de" side={THREE.DoubleSide} metalness={0.4} /></mesh>
      </group>
      <mesh ref={led} position={[0, 8.3, 0]}><sphereGeometry args={[0.16, 10, 10]} /><meshBasicMaterial color={accent} transparent /></mesh>
      {/* sandbag ring */}
      {Array.from({ length: 14 }, (_, i) => { const a = (i / 14) * Math.PI * 2; return (
        <mesh key={i} position={[Math.cos(a) * 4.3, 0.35, Math.sin(a) * 4.3]} rotation={[0, -a, 0]}><boxGeometry args={[0.6, 0.7, 1.7]} /><meshLambertMaterial color="#8a7a52" /></mesh>); })}
    </group>
  );
}

// Lines from the command post to every unit. Colour tells the story: cyan clear, red jammed,
// flashing hops while the AI responds, accent colour once restored.
function Links({ reg, accent, ids, phaseRef, friendly }) {
  const lines = useMemo(() => ids.map(() => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
    return new THREE.Line(geo, new THREE.LineBasicMaterial({ color: '#5fe3ff', transparent: true, opacity: 0.9 }));
  }), [ids]);
  const hops = useMemo(() => ['#5fe3ff', '#ffffff', accent, '#8affc1'], [accent]);
  useFrame(({ clock }) => {
    const t = clock.elapsedTime, ph = phaseRef.current, cp = reg.current.CP;
    lines.forEach((ln, i) => {
      const p = reg.current[ids[i]], a = ln.geometry.attributes.position.array;
      if (!cp || !p) { ln.visible = false; return; }
      ln.visible = true;
      a[0] = cp.x; a[1] = cp.y; a[2] = cp.z; a[3] = p.x; a[4] = p.y + 0.4; a[5] = p.z;
      ln.geometry.attributes.position.needsUpdate = true;
      const m = ln.material;
      if (ph === 0) { m.color.set('#5fe3ff'); m.opacity = 0.75; }
      else if (ph === 1) { m.color.set(friendly ? '#ffc04d' : '#ff4d4d'); m.opacity = Math.random() < 0.45 ? 0.08 : 0.85; }
      else if (ph === 2) { m.color.set(hops[Math.floor(t * 8 + i) % hops.length]); m.opacity = 0.95; }
      else { m.color.set(accent); m.opacity = 0.8 + 0.2 * Math.sin(t * 6 + i); }
    });
  });
  return <>{lines.map((l, i) => <primitive key={i} object={l} />)}</>;
}

// ------------------------------------------------------------------ jammers
function Dome({ pos, color, radius, phaseRef, gate = (ph) => ph > 0, pulse = 1.2 }) {
  const g = useRef();
  useFrame(({ clock }) => {
    if (!g.current) return;
    const on = gate(phaseRef.current, clock.elapsedTime);
    const target = on ? 1 + 0.06 * Math.sin(clock.elapsedTime * pulse * 3) : 0.001;
    const s = THREE.MathUtils.lerp(g.current.scale.x, target, 0.08);
    g.current.scale.setScalar(s);
  });
  return (
    <group ref={g} position={pos} scale={0.001}>
      <mesh><sphereGeometry args={[radius, 32, 16, 0, Math.PI * 2, 0, Math.PI / 2]} /><meshBasicMaterial color={color} transparent opacity={0.1} depthWrite={false} side={THREE.DoubleSide} /></mesh>
      <mesh><sphereGeometry args={[radius, 18, 8, 0, Math.PI * 2, 0, Math.PI / 2]} /><meshBasicMaterial color={color} wireframe transparent opacity={0.22} depthWrite={false} /></mesh>
    </group>
  );
}

function JammerMast({ pos, color = '#ff4d4d' }) {
  // a small block hut with an antenna
  const led = useRef();
  useFrame(({ clock }) => { if (led.current) led.current.scale.setScalar(0.8 + 0.4 * Math.abs(Math.sin(clock.elapsedTime * 5))); });
  return (
    <group position={pos}>
      <mesh position={[0, 0.6, 0]}><boxGeometry args={[1.6, 1.2, 1.6]} /><meshStandardMaterial color="#2a1a1a" /></mesh>
      <mesh position={[0, 3, 0]}><cylinderGeometry args={[0.08, 0.14, 4, 6]} /><meshStandardMaterial color="#555" /></mesh>
      <mesh ref={led} position={[0, 5.1, 0]}><sphereGeometry args={[0.22, 10, 10]} /><meshBasicMaterial color={color} /></mesh>
    </group>
  );
}

function SweepRings({ pos, phaseRef }) {
  const rings = useRef([]), beam = useRef();
  useFrame(({ clock }) => {
    const t = clock.elapsedTime, on = phaseRef.current > 0;
    rings.current.forEach((r, i) => {
      if (!r) return;
      const u = ((t * 0.45 + i / 3) % 1);
      r.scale.setScalar(on ? 2 + u * 26 : 0.001);
      r.material.opacity = on ? 0.55 * (1 - u) : 0;
    });
    if (beam.current) { beam.current.rotation.y = t * 1.4; beam.current.visible = on; }
  });
  return (
    <group position={pos}>
      {[0, 1, 2].map((i) => (
        <mesh key={i} ref={(r) => (rings.current[i] = r)} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.3, 0]}>
          <ringGeometry args={[0.96, 1, 64]} /><meshBasicMaterial color="#ff5a5a" transparent depthWrite={false} side={THREE.DoubleSide} />
        </mesh>
      ))}
      <group ref={beam} position={[0, 5, 0]}>
        <mesh position={[0, 0, 9]} rotation={[Math.PI / 2, 0, 0]}><coneGeometry args={[3, 18, 20, 1, true]} /><meshBasicMaterial color="#ff6b6b" transparent opacity={0.12} depthWrite={false} side={THREE.DoubleSide} /></mesh>
      </group>
    </group>
  );
}

function RandomFlashes({ center, phaseRef, count = 5, spread = 14, color = '#ff4d4d' }) {
  const refs = useRef([]), r = useMemo(() => rng(7), []);
  const last = useRef(0);
  useFrame(({ clock }) => {
    const t = clock.elapsedTime, on = phaseRef.current > 0;
    if (t - last.current > 0.35) {
      last.current = t;
      refs.current.forEach((m) => { if (!m) return; m.position.set(center[0] + (r() - 0.5) * spread, 2 + r() * 6, center[2] + (r() - 0.5) * spread); m.visible = on && r() > 0.3; });
    }
    refs.current.forEach((m) => m && m.scale.setScalar(1 + 0.6 * Math.sin(t * 20)));
  });
  return <>{Array.from({ length: count }, (_, i) => (
    <mesh key={i} ref={(m) => (refs.current[i] = m)}><sphereGeometry args={[0.7, 12, 12]} /><meshBasicMaterial color={color} transparent opacity={0.7} /></mesh>))}</>;
}

// fake "return to base" commands: violet ghost lines that turn grey once the AI rejects them
function GhostCommands({ pos, reg, ids, phaseRef }) {
  const lines = useMemo(() => ids.map(() => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
    const l = new THREE.Line(geo, new THREE.LineDashedMaterial({ color: '#c38bff', dashSize: 0.8, gapSize: 0.6, transparent: true }));
    return l;
  }), [ids]);
  useFrame(({ clock }) => {
    const ph = phaseRef.current;
    lines.forEach((ln, i) => {
      const p = reg.current[ids[i]], a = ln.geometry.attributes.position.array;
      if (!p || ph === 0) { ln.visible = false; return; }
      ln.visible = true;
      a[0] = pos[0]; a[1] = 5; a[2] = pos[2]; a[3] = p.x; a[4] = p.y; a[5] = p.z;
      ln.geometry.attributes.position.needsUpdate = true;
      ln.computeLineDistances();
      ln.material.color.set(ph >= 2 ? '#56606e' : '#c38bff');
      ln.material.opacity = ph >= 2 ? 0.35 : 0.6 + 0.4 * Math.sin(clock.elapsedTime * 10 + i);
    });
  });
  return <>{lines.map((l, i) => <primitive key={i} object={l} />)}</>;
}

function Ship({ pos }) {
  const g = useRef();
  useFrame(({ clock }) => { if (g.current) { g.current.rotation.z = Math.sin(clock.elapsedTime * 0.9) * 0.04; g.current.position.y = Math.sin(clock.elapsedTime * 0.8) * 0.1; } });
  return (
    <group position={pos}><group ref={g}>
      <mesh position={[0, 0.8, 0]}><boxGeometry args={[12, 1.6, 3.6]} /><meshStandardMaterial color="#333a44" /></mesh>
      <mesh position={[-1.5, 2.6, 0]}><boxGeometry args={[4, 2, 2.6]} /><meshStandardMaterial color="#4b5563" /></mesh>
      <mesh position={[-1.5, 5, 0]}><cylinderGeometry args={[0.1, 0.1, 3]} /><meshStandardMaterial color="#888" /></mesh>
      <mesh position={[-1.5, 6.6, 0]}><sphereGeometry args={[0.25, 10, 10]} /><meshBasicMaterial color="#ff4d4d" /></mesh>
    </group></group>
  );
}

function FollowerAura({ path, phaseRef }) {
  const m = useRef();
  useFrame(({ clock }) => {
    if (!m.current) return;
    const p = path(clock.elapsedTime); m.current.position.set(p[0], p[1], p[2]);
    const on = phaseRef.current === 1 || phaseRef.current === 2;
    m.current.scale.setScalar(THREE.MathUtils.lerp(m.current.scale.x, on ? 1 + 0.15 * Math.sin(clock.elapsedTime * 8) : 0.35, 0.08));
  });
  return <mesh ref={m}><sphereGeometry args={[4, 20, 14]} /><meshBasicMaterial color="#ff4d4d" transparent opacity={0.13} depthWrite={false} /></mesh>;
}


// ------------------------------------------------------------------ block terrain
function Terrain({ props, look, seed, actors }) {
  const mats = useMemo(() => blockMaterials(), []);
  const meshes = useMemo(() => {
    const { blocks } = buildTerrain(props, look, seed, { actors });
    const box = new THREE.BoxGeometry(B, B, B), water = new THREE.BoxGeometry(B, B * 0.7, B), m4 = new THREE.Matrix4(), col = new THREE.Color();
    return Object.entries(blocks).map(([type, arr]) => {
      const count = arr.length / 4, mat = mats[type];
      if (!mat) return null;
      const mesh = new THREE.InstancedMesh(type === 'water' ? water : box, mat, count);
      for (let i = 0; i < count; i++) {
        m4.makeTranslation(arr[i * 4], arr[i * 4 + 1], arr[i * 4 + 2]);
        mesh.setMatrixAt(i, m4);
        const sh = arr[i * 4 + 3]; mesh.setColorAt(i, col.setRGB(sh, sh, sh));
      }
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      mesh.computeBoundingSphere();
      mesh.userData.type = type;
      return mesh;
    }).filter(Boolean);
  }, [props, look, seed, actors, mats]);
  useEffect(() => () => meshes.forEach((m) => m.dispose()), [meshes]);
  useFrame(({ clock }) => { if (mats.waterTex) mats.waterTex.offset.set(clock.elapsedTime * 0.02, clock.elapsedTime * 0.012); });
  return <>{meshes.map((m) => <primitive key={m.userData.type} object={m} />)}</>;
}

function Tent({ pos, red }) {
  return (
    <group position={pos} scale={1.5}>
      <mesh position={[0, 1.2, 0]} rotation={[0, Math.PI / 4, 0]}><coneGeometry args={[2.2, 2.4, 4]} /><meshLambertMaterial color="#e9ece1" flatShading /></mesh>
      {red ? <mesh position={[0, 1.4, 1.2]}><planeGeometry args={[0.9, 0.3]} /><meshBasicMaterial color="#e63946" /></mesh> : null}
    </group>
  );
}

function Hangar({ pos }) {
  return <mesh position={pos} rotation={[0, 0, 0]}><cylinderGeometry args={[5, 5, 12, 20, 1, false, -Math.PI / 2, Math.PI]} /><meshLambertMaterial color="#6b7482" side={THREE.DoubleSide} /></mesh>;
}

// ------------------------------------------------------------------ one mission's world
function World({ slide, phaseRef, seed }) {
  const look = LOOK[slide.id] || LOOK.arena;
  const reg = useRef({});
  const curve = useMemo(() => new THREE.CatmullRomCurve3(look.road.map(([x, z]) => new THREE.Vector3(x, 0.05, z))), [look]);
  const jp = look.jammerPos, J = slide.jammer;
  const droneIds = Array.from({ length: look.drones }, (_, i) => `D${i + 1}`);
  const truckIds = Array.from({ length: look.trucks }, (_, i) => `V${i + 1}`);
  const dronePath = (i) => (t) => {
    const a = t * (0.15 + i * 0.03) + i * 1.9, rx = 16 + i * 5, rz = 9 + i * 3;
    return [-4 + Math.cos(a) * rx, 17 + i * 2 + Math.sin(t * 1.3 + i) * 0.5, Math.sin(a) * rz];
  };
  const followerPath = (t) => { const p = dronePath(0)(t - 0.9); return [p[0] + 3, p[1] + 2, p[2] - 2]; };
  const lift = (p) => [p[0], (look.props === 'coast' && J === 'sweep') ? 0 : 0, p[2]];
  return (
    <group>
      <Terrain props={look.props} look={look} seed={seed} actors />
      {look.props === 'camp' && Array.from({ length: 12 }, (_, i) => <Tent key={i} pos={[-18 + (i % 6) * 8, 0, -16 + Math.floor(i / 6) * 9]} red={i === 3} />)}
      {look.props === 'airbase' && [-14, 0, 14].map((x) => <Hangar key={x} pos={[x, 0, -22]} />)}
      <CommandPost reg={reg} accent={look.accent} />
      {droneIds.map((id, i) => <Drone key={id} id={id} reg={reg} path={dronePath(i)} led={look.accent} />)}
      {truckIds.map((id, i) => <Truck key={id} id={id} reg={reg} curve={curve} offset={i * 0.09} accent={look.accent} />)}
      <Links reg={reg} accent={look.accent} ids={[...droneIds, ...truckIds]} phaseRef={phaseRef} friendly={J === 'accidental'} />

      {J === 'barrage' && <><JammerMast pos={jp} /><Dome pos={jp} color="#ff3b3b" radius={22} phaseRef={phaseRef} /></>}
      {J === 'random' && <><JammerMast pos={jp} /><RandomFlashes center={jp} phaseRef={phaseRef} /><Dome pos={jp} color="#ff5a3b" radius={12} phaseRef={phaseRef} pulse={3} /></>}
      {J === 'sweep' && <><Ship pos={lift(jp)} /><SweepRings pos={[jp[0] - 1.5, 0, jp[2]]} phaseRef={phaseRef} /></>}
      {J === 'reactive' && <><JammerMast pos={jp} /><Dome pos={jp} color="#ff3b3b" radius={20} phaseRef={phaseRef} gate={(ph, t) => ph > 0 && (t % 1.4) < 0.55} pulse={4} /></>}
      {J === 'deceptive' && <><JammerMast pos={jp} color="#c38bff" /><Dome pos={jp} color="#b48cff" radius={10} phaseRef={phaseRef} /><GhostCommands pos={jp} reg={reg} ids={droneIds} phaseRef={phaseRef} /></>}
      {J === 'accidental' && <><JammerMast pos={jp} color="#ffc04d" /><Dome pos={jp} color="#ffc04d" radius={9} phaseRef={phaseRef} pulse={0.6} /></>}
      {J === 'follower' && <><Drone id="X" path={followerPath} hostile scale={1.1} /><FollowerAura path={followerPath} phaseRef={phaseRef} /></>}
      {J === 'arena' && <>
        <JammerMast pos={[22, 0, -12]} /><Dome pos={[22, 0, -12]} color="#ff3b3b" radius={14} phaseRef={phaseRef} />
        <SweepRings pos={[-2, 0, -22]} phaseRef={phaseRef} />
        <RandomFlashes center={[10, 0, 14]} phaseRef={phaseRef} count={3} spread={10} color="#ffc04d" />
      </>}
    </group>
  );
}

// ------------------------------------------------------------------ sky, clouds, stars
function SkyDome({ skyRef }) {
  const mat = useMemo(() => new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: { top: { value: new THREE.Color() }, hor: { value: new THREE.Color() } },
    vertexShader: 'varying float h; void main(){ h = normalize(position).y; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
    fragmentShader: 'uniform vec3 top; uniform vec3 hor; varying float h; void main(){ float t = smoothstep(-0.02, 0.32, h); gl_FragColor = vec4(mix(hor, top, t), 1.0); }',
  }), []);
  const g = useRef();
  useFrame(({ camera }) => { const s = skyRef.current; mat.uniforms.top.value.copy(s.top); mat.uniforms.hor.value.copy(s.hor); if (g.current) g.current.position.copy(camera.position); });
  return <mesh ref={g} material={mat} renderOrder={-10}><sphereGeometry args={[420, 32, 16]} /></mesh>;
}

function SunMoon({ skyRef }) {
  const m = useRef();
  useFrame(({ camera }) => {
    const s = skyRef.current; if (!m.current) return;
    m.current.position.set(camera.position.x + s.sunPos.x, s.sunPos.y, camera.position.z + s.sunPos.z);
    m.current.lookAt(camera.position);
    m.current.material.color.copy(s.sunCol);
    m.current.visible = (s.hidden || 0) < 0.15;
  });
  return <mesh ref={m}><planeGeometry args={[16, 16]} /><meshBasicMaterial fog={false} toneMapped={false} /></mesh>;
}

function Clouds({ count, xFrom, xTo, skyRef }) {
  const mesh = useMemo(() => {
    const r = rng(5), geo = new THREE.BoxGeometry(1, 1, 1);
    const mat = new THREE.MeshLambertMaterial({ color: '#ffffff', transparent: true, opacity: 0.85, emissive: '#8892a6', emissiveIntensity: 0.25 });
    const cells = [];
    const n = (x, z) => Math.sin(x * 0.11) * Math.cos(z * 0.13) + Math.sin(x * 0.037 + z * 0.05) * 0.8;
    for (let x = xFrom; x < xTo; x += 6) for (let z = -200; z < 40; z += 6) if (n(x, z) + r() * 0.5 > 1.0) cells.push([x, z]);
    const im = new THREE.InstancedMesh(geo, mat, cells.length), m4 = new THREE.Matrix4();
    cells.forEach(([x, z], i) => { m4.compose(new THREE.Vector3(x, 78 + (i % 3), z), new THREE.Quaternion(), new THREE.Vector3(6, 2.4, 6)); im.setMatrixAt(i, m4); });
    im.instanceMatrix.needsUpdate = true; im.frustumCulled = false;
    return im;
  }, [count, xFrom, xTo]);
  const g = useRef();
  useFrame(({ clock }) => { if (!g.current) return; g.current.position.x = (clock.elapsedTime * 1.2) % 6; const h = skyRef?.current?.hidden || 0; mesh.material.opacity = 0.85 * Math.max(0, 1 - h * 2.5); g.current.visible = h < 0.4; });
  return <group ref={g}><primitive object={mesh} /></group>;
}

function Stars({ skyRef }) {
  const geo = useMemo(() => {
    const r = rng(11), n = 900, a = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) { const th = r() * Math.PI * 2, ph = 0.08 + r() * 0.45 * Math.PI, R = 380; a[i * 3] = R * Math.cos(th) * Math.cos(ph); a[i * 3 + 1] = R * Math.sin(ph); a[i * 3 + 2] = R * Math.sin(th) * Math.cos(ph); }
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(a, 3)); return g;
  }, []);
  const p = useRef();
  useFrame(({ camera }) => { if (!p.current) return; p.current.position.copy(camera.position); p.current.material.opacity = Math.min(1, 0.9 * skyRef.current.stars); p.current.visible = skyRef.current.stars > 0.02; });
  return <points ref={p} geometry={geo}><pointsMaterial size={1.4} color="#e6eeff" transparent fog={false} sizeAttenuation={false} /></points>;
}

// ------------------------------------------------------------------ globe transition
// Changing slide pulls the camera up into space, a planet spins to the next mission's pin while a signal
// arc draws between the two pins, then the camera dives back down into the new world.
export const GLOBE_S = 2.7;
export const flightTime = () => GLOBE_S;
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const sstep = (a, b, x) => { const t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
const SPACE = new THREE.Color('#02040b');
const GLOBE_R = 30, GLOBE_D = 140;
// where each mission sits on the planet (lat, lon in degrees): spread round the world so the spin reads
const PINS = [[32, -150], [16, -100], [-6, -52], [44, -6], [20, 42], [-18, 88], [26, 134], [6, 178]];
const toRad = (d) => (d * Math.PI) / 180;
const dirOf = (lat, lon) => new THREE.Vector3(Math.cos(toRad(lat)) * Math.sin(toRad(lon)), Math.sin(toRad(lat)), Math.cos(toRad(lat)) * Math.cos(toRad(lon)));

function globeTexture() {
  const W = 192, H = 96, c = document.createElement('canvas'); c.width = W; c.height = H;
  const g = c.getContext('2d'), img = g.createImageData(W, H), r = rng(77);
  const P = Array.from({ length: 256 }, () => r());
  const h = (x, y) => P[((x * 73) ^ (y * 151)) & 255];
  const n = (x, y) => { const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi; const s = (t) => t * t * (3 - 2 * t);
    const a = h(xi, yi), b = h(xi + 1, yi), c2 = h(xi, yi + 1), d = h(xi + 1, yi + 1); return a + (b - a) * s(xf) + (c2 - a) * s(yf) + (a - b - c2 + d) * s(xf) * s(yf); };
  const fbm = (x, y) => (n(x, y) + 0.5 * n(x * 2, y * 2) + 0.25 * n(x * 4, y * 4)) / 1.75;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const lat = 90 - (y / H) * 180, lon = (x / W) * 360;
    // wrap noise round the sphere so there is no seam
    const a = toRad(lon), v = fbm(Math.cos(a) * 3 + 10, y / 9) * 0.6 + fbm(Math.sin(a) * 3 + 20, y / 9 + 5) * 0.4;
    let col;
    const pole = Math.abs(lat) > 68;
    if (v < 0.47) col = v < 0.4 ? [24, 66, 140] : [40, 102, 178];
    else if (pole) col = [235, 242, 248];
    else if (v > 0.64) col = [128, 128, 132];
    else if (Math.abs(lat) < 28 && v < 0.55) col = [214, 196, 132];
    else col = v > 0.57 ? [52, 112, 44] : [92, 150, 58];
    if (pole && v < 0.47) col = [214, 228, 240];
    const j = 0.9 + r() * 0.18, i = (y * W + x) * 4;
    img.data[i] = Math.min(255, col[0] * j); img.data[i + 1] = Math.min(255, col[1] * j); img.data[i + 2] = Math.min(255, col[2] * j); img.data[i + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c); t.magFilter = THREE.NearestFilter; t.minFilter = THREE.LinearMipmapLinearFilter; t.colorSpace = THREE.SRGBColorSpace; t.wrapS = THREE.RepeatWrapping;
  return t;
}

function Globe({ tr, slides }) {
  const g = useRef(), spin = useRef(), clouds = useRef(), arc = useRef(), ring = useRef(), pinRefs = useRef([]);
  const tex = useMemo(() => globeTexture(), []);
  const planet = useMemo(() => new THREE.ShaderMaterial({
    transparent: true, fog: false, uniforms: { map: { value: tex }, opacity: { value: 0 } },
    vertexShader: 'varying vec2 vUv; varying vec3 vN; void main(){ vUv = uv; vN = normalize(normalMatrix * normal); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
    fragmentShader: 'uniform sampler2D map; uniform float opacity; varying vec2 vUv; varying vec3 vN; void main(){ vec3 L = normalize(vec3(-0.5,0.6,0.65)); float d = max(dot(vN,L),0.0); vec3 c = texture2D(map,vUv).rgb; c = c*(0.18+0.95*d) + vec3(0.25,0.45,0.9)*pow(1.0-max(vN.z,0.0),3.0)*0.6; gl_FragColor = vec4(c, opacity); }',
  }), [tex]);
  const atmo = useMemo(() => new THREE.ShaderMaterial({
    transparent: true, fog: false, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.BackSide, uniforms: { opacity: { value: 0 } },
    vertexShader: 'varying vec3 vN; void main(){ vN = normalize(normalMatrix * normal); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
    fragmentShader: 'uniform float opacity; varying vec3 vN; void main(){ float f = pow(0.72 - dot(vN, vec3(0.0,0.0,1.0)), 3.0); gl_FragColor = vec4(vec3(0.35,0.65,1.0)*f*2.4, opacity*clamp(f*2.0,0.0,1.0)); }',
  }), []);
  const cloudMat = useMemo(() => {
    const c = document.createElement('canvas'); c.width = 128; c.height = 64; const x = c.getContext('2d'), r = rng(9);
    for (let i = 0; i < 70; i++) { x.fillStyle = `rgba(255,255,255,${0.35 + r() * 0.4})`; const w = 3 + r() * 9, hh = 1 + r() * 3; x.fillRect(Math.floor(r() * 128), Math.floor(8 + r() * 48), Math.floor(w), Math.floor(hh)); }
    const t = new THREE.CanvasTexture(c); t.magFilter = THREE.NearestFilter;
    return new THREE.MeshBasicMaterial({ map: t, transparent: true, opacity: 0, depthWrite: false, fog: false });
  }, []);
  const arcLine = useMemo(() => { const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(64 * 3), 3)); geo.setDrawRange(0, 0);
    return new THREE.Line(geo, new THREE.LineBasicMaterial({ color: '#ffffff', transparent: true, opacity: 0, fog: false, depthTest: false })); }, []);
  const qa = useMemo(() => new THREE.Quaternion(), []), qb = useMemo(() => new THREE.Quaternion(), []);
  const fwd = useMemo(() => new THREE.Vector3(), []);
  const X = useMemo(() => new THREE.Vector3(1, 0, 0), []), Y = useMemo(() => new THREE.Vector3(0, 1, 0), []);

  useFrame(({ camera, clock }) => {
    const T = tr.current, vis = T.hidden;
    if (!g.current) return;
    g.current.visible = vis > 0.01;
    if (!g.current.visible) return;
    camera.getWorldDirection(fwd);
    g.current.position.copy(camera.position).addScaledVector(fwd, GLOBE_D);
    g.current.quaternion.copy(camera.quaternion);
    const scale = T.p < 0.5 ? 0.35 + 0.65 * sstep(0.04, 0.34, T.p) : 1 + 3.2 * Math.pow(sstep(0.7, 1, T.p), 2);
    g.current.scale.setScalar(scale);
    planet.uniforms.opacity.value = vis; atmo.uniforms.opacity.value = vis; cloudMat.opacity = 0.75 * vis;
    // spin: longitude and latitude ease from the old pin to the new one, plus one extra turn in the travel direction
    const [la0, lo0] = PINS[T.from % PINS.length], [la1, lo1] = PINS[T.to % PINS.length];
    let dLon = lo1 - lo0; dLon = ((dLon % 360) + 540) % 360 - 180;
    const e = ease(sstep(0.18, 0.74, T.p));
    const lon = lo0 + (dLon + 360 * (T.dir || 1)) * e, lat = la0 + (la1 - la0) * e;
    qa.setFromAxisAngle(X, toRad(lat)); qb.setFromAxisAngle(Y, -toRad(lon));
    spin.current.quaternion.copy(qa.multiply(qb));
    if (clouds.current) clouds.current.rotation.y = clock.elapsedTime * 0.05;
    // pins: the target pulses, the others glow faintly
    pinRefs.current.forEach((m, i) => { if (!m) return; const on = i === T.to; m.scale.setScalar(on ? 1.25 + 0.35 * Math.sin(clock.elapsedTime * 9) : 0.8); m.children.forEach((c) => c.material && (c.material.opacity = vis * (on ? 1 : 0.55))); });
    // signal arc: a great-circle path from the old pin to the new one, drawn while the globe turns
    const a = dirOf(la0, lo0), b = dirOf(la1, lo1), pos = arcLine.geometry.attributes.position.array;
    const draw = Math.floor(64 * sstep(0.3, 0.72, T.p));
    for (let k = 0; k < 64; k++) {
      const u = k / 63, v = new THREE.Vector3().copy(a).lerp(b, u).normalize().multiplyScalar(GLOBE_R * (1.02 + 0.22 * Math.sin(Math.PI * u)));
      pos[k * 3] = v.x; pos[k * 3 + 1] = v.y; pos[k * 3 + 2] = v.z;
    }
    arcLine.geometry.attributes.position.needsUpdate = true; arcLine.geometry.setDrawRange(0, draw);
    arcLine.material.color.set(T.accent || '#ffffff'); arcLine.material.opacity = vis;
    if (ring.current) { const d = dirOf(la1, lo1); ring.current.position.copy(d).multiplyScalar(GLOBE_R * 1.01); ring.current.lookAt(d.multiplyScalar(100)); const u = (clock.elapsedTime * 1.4) % 1; ring.current.scale.setScalar(1 + u * 3); ring.current.material.opacity = vis * (1 - u); ring.current.material.color.set(T.accent || '#fff'); }
  });

  return (
    <group ref={g} visible={false} renderOrder={5}>
      <group ref={spin}>
        <mesh material={planet}><sphereGeometry args={[GLOBE_R, 64, 32]} /></mesh>
        <mesh ref={clouds} material={cloudMat}><sphereGeometry args={[GLOBE_R * 1.03, 48, 24]} /></mesh>
        <primitive object={arcLine} />
        <mesh ref={ring}><ringGeometry args={[1.1, 1.5, 32]} /><meshBasicMaterial transparent depthWrite={false} fog={false} side={THREE.DoubleSide} /></mesh>
        {slides.map((s, i) => {
          const d = dirOf(...PINS[i % PINS.length]), col = (LOOK[s.id] || LOOK.arena).accent;
          const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), d);
          return (
            <group key={s.id} position={d.clone().multiplyScalar(GLOBE_R)} quaternion={q}>
              <group ref={(m) => (pinRefs.current[i] = m)}>
                <mesh position={[0, 1.6, 0]}><boxGeometry args={[0.9, 3.2, 0.9]} /><meshBasicMaterial color={col} transparent fog={false} /></mesh>
                <mesh position={[0, 3.6, 0]}><boxGeometry args={[1.5, 1.5, 1.5]} /><meshBasicMaterial color="#ffffff" transparent fog={false} /></mesh>
              </group>
            </group>
          );
        })}
      </group>
      <mesh material={atmo} scale={1.12}><sphereGeometry args={[GLOBE_R, 48, 24]} /></mesh>
    </group>
  );
}

function Flight({ index, skies, skyRef, lights, wide, tr, slides }) {
  const { camera, scene } = useThree();
  const look = useMemo(() => new THREE.Vector3(), []);
  const tmp = useMemo(() => ({ a: new THREE.Color(), b: new THREE.Color() }), []);
  useEffect(() => { scene.fog = new THREE.Fog('#000', 150, 400); }, [scene]);
  useEffect(() => {
    const T = tr.current;
    if (index === T.to) return;
    T.from = T.p < 0.5 && T.p < 1 && T.t0 >= 0 ? T.from : T.to;  // a new jump mid-spin keeps spinning from where we left
    T.to = index; T.dir = index > T.from ? 1 : -1; T.t0 = -1;
    T.accent = (LOOK[slides[index].id] || LOOK.arena).accent;
  }, [index, tr, slides]);
  useFrame(({ clock, pointer }) => {
    const T = tr.current, t = clock.elapsedTime;
    if (T.t0 < 0) T.t0 = t;
    T.p = T.from === T.to ? 1 : Math.min(1, (t - T.t0) / GLOBE_S);
    const out = sstep(0, 0.3, T.p), back = sstep(0.7, 1, T.p);
    T.hidden = T.from === T.to ? 0 : out * (1 - back);
    const cur = (T.p < 0.5 ? T.from : T.to) * SPAN;
    T.cur = cur;
    const off = wide ? -16 : -3, fx = cur + off, H = T.hidden;
    // climb away from the land on the way out, dive back in on the way down
    const climb = T.p < 0.5 ? out : 1 - back;
    camera.position.set(fx + 30 + Math.sin(t * 0.08) * 4 + pointer.x * 4 * (1 - H), 60 + 150 * climb * climb + pointer.y * 4 * (1 - H), 102 + 120 * climb);
    look.set(fx, 0 + 40 * climb, -12);
    camera.fov = 40 + 14 * Math.sin(Math.PI * Math.min(1, T.p * 1.0)) * (T.from === T.to ? 0 : 1);
    camera.updateProjectionMatrix();
    const roll = 0.08 * Math.sin(Math.PI * T.p) * (T.dir || 0) * (T.from === T.to ? 0 : 1);
    camera.up.set(Math.sin(roll), Math.cos(roll), 0);
    camera.lookAt(look);
    // sky of the world we are over, fading to space while the globe is up
    const i0 = Math.max(0, Math.min(skies.length - 1, Math.round(cur / SPAN)));
    const A = SKY[skies[i0]], sk = skyRef.current;
    const Hc = Math.min(1, H * 1.8);
    const setC = (key, out2) => out2.set(A[key]).lerp(SPACE, key === 'sun' || key === 'hemi' || key === 'sunCol' ? 0 : Hc);
    setC('top', sk.top); setC('hor', sk.hor); setC('fog', sk.fog); setC('sun', sk.sun); setC('hemi', sk.hemi); setC('sunCol', sk.sunCol);
    sk.stars = Math.max(A.stars, H);
    sk.hidden = H;
    sk.sunPos.set(...A.sunPos);
    scene.fog.color.copy(sk.fog);
    scene.fog.near = 150 * (1 - H) + 2 * H; scene.fog.far = 400 * (1 - H) + 30 * H;   // the land dissolves into space
    const L = lights.current;
    if (L.amb) L.amb.intensity = A.amb;
    if (L.sun) { L.sun.intensity = A.sunI; L.sun.color.copy(sk.sun); L.sun.position.set(camera.position.x + sk.sunPos.x * 0.5, Math.max(30, sk.sunPos.y), sk.sunPos.z * 0.3 + 40); L.sun.target.position.set(camera.position.x, 0, 0); L.sun.target.updateMatrixWorld(); }
    if (L.hemi) L.hemi.color.copy(sk.hemi);
    const ws = lights.worlds;
    if (ws) ws.forEach((w, i) => { if (w) w.visible = H < 0.8 && Math.abs((i - 1) * SPAN - cur) < SPAN * 1.6; });
    void tmp;
  });
  return null;
}

function PhaseClock({ phaseRef, onPhase }) {
  const last = useRef(-1);
  useFrame(({ clock }) => {
    const ph = phaseAt(clock.elapsedTime);
    phaseRef.current = ph;
    if (ph !== last.current) { last.current = ph; onPhase(ph); }
  });
  return null;
}

export default function Stage({ slides, index, onPhase, onClick }) {
  const phaseRef = useRef(0);
  const skies = useMemo(() => slides.map((s) => (LOOK[s.id] || LOOK.arena).sky), [slides]);
  const skyRef = useRef({ top: new THREE.Color(), hor: new THREE.Color(), fog: new THREE.Color(), sun: new THREE.Color(), hemi: new THREE.Color(), sunCol: new THREE.Color(), stars: 0, sunPos: new THREE.Vector3() });
  const lights = useRef({ worlds: [] });
  const tr = useRef({ from: index, to: index, p: 1, t0: 0, hidden: 0, dir: 1, accent: '#fff', cur: index * SPAN });
  const wide = typeof window !== 'undefined' && window.innerWidth > 700;
  const first = LOOK[slides[0].id], last = LOOK[slides[slides.length - 1].id] || LOOK.arena;
  return (
    <Canvas className="stage" dpr={[1, 1.6]} camera={{ fov: 40, position: [index * SPAN, 60, 102], near: 0.5, far: 900 }}
      gl={{ antialias: true }} onClick={onClick}>
      <Flight index={index} skies={skies} skyRef={skyRef} lights={lights} wide={wide} tr={tr} slides={slides} />
      <Globe tr={tr} slides={slides} />
      <PhaseClock phaseRef={phaseRef} onPhase={onPhase} />
      <SkyDome skyRef={skyRef} />
      <SunMoon skyRef={skyRef} />
      <Stars skyRef={skyRef} />
      <Clouds xFrom={-SPAN * 1.5} xTo={SPAN * (slides.length + 0.5)} skyRef={skyRef} />
      <ambientLight ref={(l) => (lights.current.amb = l)} />
      <hemisphereLight ref={(l) => (lights.current.hemi = l)} args={['#ffffff', '#3a2f22', 0.45]} />
      <directionalLight ref={(l) => (lights.current.sun = l)} />
      {/* an extra stretch of land before the first and after the last mission, so the edges are never empty */}
      <group ref={(g) => (lights.current.worlds[0] = g)} position={[-SPAN, 0, 0]}><Terrain props={first.props} look={first} seed={101} actors={false} /></group>
      {slides.map((s, i) => (
        <group key={s.id} ref={(g) => (lights.current.worlds[i + 1] = g)} position={[i * SPAN, 0, 0]}>
          <World slide={s} phaseRef={phaseRef} seed={i + 3} />
        </group>
      ))}
      <group ref={(g) => (lights.current.worlds[slides.length + 1] = g)} position={[slides.length * SPAN, 0, 0]}><Terrain props={last.props} look={last} seed={202} actors={false} /></group>
    </Canvas>
  );
}
