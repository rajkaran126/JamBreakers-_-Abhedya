import React from 'react';

export function Gauge({ value, label }) {
  const v = value == null ? 0 : Math.max(0, Math.min(100, value));
  const c = value == null ? '#e8cdbd' : v >= 90 ? '#23935f' : v >= 60 ? '#c07d10' : '#d23f4d';
  const R = 52, L = Math.PI * R;
  return (
    <div className="gauge">
      <svg viewBox="0 0 130 78">
        <path d="M13 70 A52 52 0 0 1 117 70" stroke="#f6dccb" strokeWidth="12" fill="none" strokeLinecap="round" />
        <path d="M13 70 A52 52 0 0 1 117 70" stroke={c} strokeWidth="12" fill="none" strokeLinecap="round"
          strokeDasharray={`${(v / 100) * L} ${L}`} style={{ transition: 'stroke-dasharray .4s, stroke .4s' }} />
      </svg>
      <b style={{ color: c }}>{value == null ? '—' : `${v.toFixed(0)}%`}</b>
      <span>{label}</span>
    </div>
  );
}

export function AiSwitch({ on, onChange, compact = false }) {
  return (
    <div className={`aiswitch ${compact ? 'compact' : ''}`} role="group" aria-label="AI defender">
      <button className={!on ? 'sel off' : ''} onClick={() => onChange(false)}>AI OFF<small>normal radio</small></button>
      <button className={on ? 'sel on' : ''} onClick={() => onChange(true)}>AI ON<small>ABHEDYA</small></button>
    </div>
  );
}

export function timeAgo(t) {
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  return s < 5 ? 'now' : s < 60 ? `${s}s` : `${Math.round(s / 60)}m`;
}

export function useCanvas(draw, deps) {
  const ref = React.useRef(null);
  React.useEffect(() => {
    const c = ref.current; if (!c) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2.5), w = c.clientWidth, h = c.clientHeight;
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
    const g = c.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    draw(g, w, h);
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  return ref;
}

export function inferno(t) {
  t = Math.max(0, Math.min(1, t));
  const s = [[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66], [245, 125, 21], [250, 193, 39], [252, 255, 164]];
  const x = t * (s.length - 1), i = Math.min(s.length - 2, Math.floor(x)), f = x - i;
  return s[i].map((a, k) => Math.round(a + (s[i + 1][k] - a) * f));
}

// Hides less important content until the user asks for it.
export function Reveal({ label = 'Show details', children, open = false }) {
  const [o, setO] = React.useState(open);
  return (
    <div className={`reveal ${o ? 'open' : ''}`}>
      {o && <div className="reveal-body">{children}</div>}
      <button className="reveal-btn" onClick={() => setO(!o)}>{o ? 'Hide' : label}<span>{o ? '▴' : '▾'}</span></button>
    </div>
  );
}

// One short line each: what the jammer does, and what the AI does about it.
export const SIMPLE = {
  clean: ['No jamming', 'Nothing to do'],
  barrage: ['Noise on every channel', 'Boosting power, sturdier signal'],
  random: ['Jumps between random channels', 'Blocking those channels'],
  sweep: ['Sweeps across all channels', 'Holding still, boosting power'],
  reactive: ['Fires when it hears us', 'Hopping fast and unpredictably'],
  deceptive: ['Sends fake commands', 'Rejecting fakes, moving away'],
  accidental: ['Friendly Wi-Fi, not an attack', 'Quietly avoiding it'],
  follower: ['Chases our channel', 'Secret hopping it cannot follow'],
  smart: ['Learns and changes tactics', 'Adapting move by move'],
  novel: ['A pattern never seen before', 'Trying safe moves, learning'],
  unknown: ['A pattern never seen before', 'Trying safe moves, learning'],
};
