import React, { useRef, useState, useEffect } from 'react';
import { useStore, shownState, mode, send, toast, JAMMERS, CLASS_INFO } from '../store.js';
import { SIMPLE } from '../ui.jsx';

const MAIN = ['barrage', 'random', 'sweep', 'follower'];       // the four that show the AI best; the rest behind 'More types'

const LINK_C = { ok: '#23935f', degraded: '#c07d10', down: '#d23f4d' };
const reach = (p) => 60 + (p - 18) * 9.5;                     // same visual reach as the 3D view

export default function MapTab() {
  const S = useStore();
  const st = shownState(), scn = mode() === 'scenario';
  const [jt, setJt] = useState('random');
  const [taps, setTaps] = useState([]);
  const [all, setAll] = useState(false);
  const cv = useRef(null), view = useRef(null);

  // world -> screen transform fitted to the arena (and anything outside it)
  useEffect(() => {
    const c = cv.current; if (!c) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2.5), W = c.clientWidth, H = c.clientHeight;
    if (c.width !== Math.round(W * dpr)) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); }
    const g = c.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const b = S.hello?.bounds || { x: [-300, 1200], y: [-400, 900] };
    let [x0, x1] = b.x, [y0, y1] = b.y;
    for (const n of st?.nodes || []) { x0 = Math.min(x0, n.pos[0] - 40); x1 = Math.max(x1, n.pos[0] + 40); y0 = Math.min(y0, n.pos[1] - 40); y1 = Math.max(y1, n.pos[1] + 40); }
    for (const j of st?.jammers || []) { x0 = Math.min(x0, j.pos[0] - 40); x1 = Math.max(x1, j.pos[0] + 40); y0 = Math.min(y0, j.pos[1] - 40); y1 = Math.max(y1, j.pos[1] + 40); }
    const sc = Math.min((W - 16) / (x1 - x0), (H - 16) / (y1 - y0));
    const ox = (W - (x1 - x0) * sc) / 2, oy = (H - (y1 - y0) * sc) / 2;
    const X = (x) => ox + (x - x0) * sc, Y = (y) => H - oy - (y - y0) * sc;
    view.current = { X, Y, inv: (px, py) => [x0 + (px - ox) / sc, y0 + (H - oy - py) / sc], sc };

    // ground + grid
    g.fillStyle = '#fdf1e8'; g.fillRect(0, 0, W, H);
    g.fillStyle = '#ffffff'; g.fillRect(X(b.x[0]), Y(b.y[1]), (b.x[1] - b.x[0]) * sc, (b.y[1] - b.y[0]) * sc);
    g.strokeStyle = 'rgba(240,138,93,.08)'; g.lineWidth = 1;
    for (let x = Math.ceil(x0 / 100) * 100; x <= x1; x += 100) { g.beginPath(); g.moveTo(X(x), 0); g.lineTo(X(x), H); g.stroke(); }
    for (let y = Math.ceil(y0 / 100) * 100; y <= y1; y += 100) { g.beginPath(); g.moveTo(0, Y(y)); g.lineTo(W, Y(y)); g.stroke(); }

    // obstacles
    for (const o of st?.obstacles || S.hello?.obstacles || []) {
      const w = o.size[0] * sc, h = o.size[1] * sc;
      if (o.kind === 'hill') { g.fillStyle = 'rgba(90,120,70,.55)'; g.beginPath(); g.ellipse(X(o.pos[0]), Y(o.pos[1]), w / 2, h / 2, 0, 0, 7); g.fill(); }
      else { g.fillStyle = 'rgba(120,132,152,.75)'; g.fillRect(X(o.pos[0]) - w / 2, Y(o.pos[1]) - h / 2, w, h); }
    }
    if (!st) return;
    const pos = Object.fromEntries(st.nodes.map((n) => [n.id, n.pos]));
    // jammer reach + bodies
    for (const j of st.jammers) {
      const R = reach(j.power_dbm) * sc, x = X(j.pos[0]), y = Y(j.pos[1]), c = j.type === 'accidental' ? '255,190,80' : '255,79,102';
      if (j.active) { const gr = g.createRadialGradient(x, y, 0, x, y, R); gr.addColorStop(0, `rgba(${c},.28)`); gr.addColorStop(1, `rgba(${c},0)`);
        g.fillStyle = gr; g.beginPath(); g.arc(x, y, R, 0, 7); g.fill(); g.strokeStyle = `rgba(${c},.55)`; g.setLineDash([4, 4]); g.stroke(); g.setLineDash([]); }
    }
    // vehicle trips: a dashed line to where the truck is heading
    for (const n of st.nodes) {
      const t = n.trip; if (!t) continue;
      if (t.state === 'driving' || t.state === 'returning') {
        const to = t.to === t.dst ? t.dst_pos : t.src_pos;
        g.strokeStyle = 'rgba(217,102,58,.8)'; g.lineWidth = 1.6; g.setLineDash([5, 4]);
        g.beginPath(); g.moveTo(X(n.pos[0]), Y(n.pos[1])); g.lineTo(X(to[0]), Y(to[1])); g.stroke(); g.setLineDash([]);
      }
    }
    // links
    for (const l of st.links) {
      const a = pos[l.a], b2 = pos[l.b]; if (!a || !b2 || !l.routed) continue;     // only the links in use
      g.strokeStyle = LINK_C[l.status] || '#888'; g.globalAlpha = l.routed ? 0.95 : 0.35; g.lineWidth = l.routed ? 2.4 : 1.2;
      g.beginPath(); g.moveTo(X(a[0]), Y(a[1])); g.lineTo(X(b2[0]), Y(b2[1])); g.stroke();
    }
    g.globalAlpha = 1;
    // AI estimate rings
    for (const e of st.estimates || []) {
      const x = X(e.pos[0]), y = Y(e.pos[1]), r = Math.max(6, e.radius_m * sc);
      g.strokeStyle = '#d99a00'; g.lineWidth = 2; g.setLineDash([6, 4]); g.beginPath(); g.arc(x, y, r, 0, 7); g.stroke(); g.setLineDash([]);
      g.beginPath(); g.moveTo(x - 7, y); g.lineTo(x + 7, y); g.moveTo(x, y - 7); g.lineTo(x, y + 7); g.stroke();
      g.fillStyle = '#d99a00'; g.font = '600 10px system-ui'; g.fillText('AI guess', x + r + 4, y + 3);
    }
    // nodes
    for (const n of st.nodes) {
      const x = X(n.pos[0]), y = Y(n.pos[1]);
      const c = n.status === 'ok' ? '#3b2a22' : n.status === 'returning' || n.status === 'charging' ? '#d9663a' : n.status === 'degraded' || n.status === 'rejoining' ? '#c07d10' : '#d23f4d';
      g.fillStyle = n.kind === 'relay' ? '#3b2a22' : c; g.strokeStyle = '#ffffff'; g.lineWidth = 1.5;
      g.beginPath();
      if (n.kind === 'command_post') g.rect(x - 7, y - 7, 14, 14);
      else if (n.kind === 'vehicle') g.roundRect ? g.roundRect(x - 7, y - 5, 14, 10, 3) : g.rect(x - 7, y - 5, 14, 10);
      else { const h = ((n.heading_deg || 0) * Math.PI) / 180; g.moveTo(x + 8 * Math.cos(h), y - 8 * Math.sin(h)); g.lineTo(x + 6 * Math.cos(h + 2.4), y - 6 * Math.sin(h + 2.4)); g.lineTo(x + 6 * Math.cos(h - 2.4), y - 6 * Math.sin(h - 2.4)); g.closePath(); }
      g.fill(); g.stroke();
      g.fillStyle = '#3b2a22'; g.font = '600 10px system-ui'; g.fillText(n.id === 'CP' ? 'Base' : n.id, x + 9, y - 7);
    }
    for (const j of st.jammers) {
      const x = X(j.pos[0]), y = Y(j.pos[1]), c = j.type === 'accidental' ? '#c07d10' : '#d23f4d';
      g.fillStyle = j.active ? c : '#6a6f80'; g.strokeStyle = '#fff'; g.lineWidth = 1.5;
      g.beginPath(); g.moveTo(x, y - 9); g.lineTo(x + 8, y); g.lineTo(x, y + 9); g.lineTo(x - 8, y); g.closePath(); g.fill(); g.stroke();
      g.fillStyle = '#b0303f'; g.font = '600 10px system-ui'; g.fillText(`${CLASS_INFO[j.type]?.label || j.type}${j.owner ? ' · ' + j.owner : ''}`, x + 10, y + 4);
    }
    // tap ripples
    const now = performance.now();
    for (const t of taps) { const a = (now - t.t) / 900; if (a < 1) { g.strokeStyle = `rgba(217,102,58,${1 - a})`; g.lineWidth = 2; g.beginPath(); g.arc(t.x, t.y, 6 + a * 30, 0, 7); g.stroke(); } }
  });

  const onTap = (e) => {
    if (scn) { toast('A mission is running: its jammers are scripted. Exit the mission to launch your own.'); return; }
    const r = cv.current.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
    const [x, y] = view.current.inv(px, py), b = S.hello?.bounds || { x: [-300, 1200], y: [-400, 900] };
    if (x < b.x[0] || x > b.x[1] || y < b.y[0] || y > b.y[1]) { toast('Tap inside the arena (the lighter area).'); return; }
    if (send('launch_jammer', { jammer_type: jt, pos: [Math.round(x), Math.round(y)] })) {
      setTaps((ts) => [...ts.filter((t) => performance.now() - t.t < 900), { x: px, y: py, t: performance.now() }]);
      if (S.vibrate && navigator.vibrate) navigator.vibrate(30);
    }
  };
  const active = st?.jammers.filter((j) => j.active).length || 0;
  return (
    <div className="tab map">
      {scn ? <p className="hint">A mission is running, so its jammers are scripted. You can watch the map.</p> : (
        <>
          <p className="steps"><b>1</b> Pick a jammer <b>2</b> Tap the map</p>
          <div className="chips">
            {(all ? JAMMERS : MAIN).map((t) => (
              <button key={t} className={jt === t ? 'chip on' : 'chip'} style={{ '--c': CLASS_INFO[t].color }} onClick={() => setJt(t)}>{CLASS_INFO[t].label}</button>
            ))}
            <button className="chip more" onClick={() => setAll(!all)}>{all ? 'Fewer' : 'More types'}</button>
          </div>
          <p className="hint"><b style={{ color: CLASS_INFO[jt].color }}>{CLASS_INFO[jt].label}:</b> {SIMPLE[jt]?.[0]}</p>
        </>
      )}
      <canvas ref={cv} className="mapcv" onClick={onTap} />
      <div className="map-foot">
        <span className="legend"><i className="l-ok" />working <i className="l-deg" />weak <i className="l-down" />lost</span>
        {!scn && active > 0 && <button className="danger" onClick={() => send('clear_jammers')}>Remove {active > 1 ? `all ${active}` : 'jammer'}</button>}
      </div>
    </div>
  );
}
