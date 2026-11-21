// Motion graphics for the mission deck: the "signal burst" transition between slides, the decoding text
// effect, and the ABHEDYA boot splash. Framer Motion + SVG/CSS only.
import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';

const GLYPHS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%/<>=+*';

// Text that "decodes" like a received signal: random glyphs settle into the real letters, left to right.
export function Decode({ text = '', play, delay = 0, speed = 28, className, as: Tag = 'span' }) {
  const [out, setOut] = useState(text);
  useEffect(() => {
    if (!play) { setOut(text); return undefined; }
    let frame = 0, timer = null;
    const total = text.length + 8;
    const start = setTimeout(() => {
      timer = setInterval(() => {
        frame += 1;
        const settled = Math.floor(frame * 0.9);
        setOut(text.split('').map((ch, i) => (ch === ' ' || i < settled ? ch : GLYPHS[(Math.random() * GLYPHS.length) | 0])).join(''));
        if (settled >= total) { clearInterval(timer); setOut(text); }
      }, speed);
    }, delay);
    return () => { clearTimeout(start); clearInterval(timer); };
  }, [text, play, delay, speed]);
  return <Tag className={className} aria-label={text}>{out}</Tag>;
}

// Signal arcs like the ones on the logo's "A": three arcs that ripple outwards.
function Arcs({ color, size = 520 }) {
  return (
    <svg viewBox="-60 -60 120 70" width={size} height={size * 0.58} className="arcs">
      {[18, 32, 46].map((r, i) => (
        <motion.path key={r} d={`M ${-r} 0 A ${r} ${r} 0 0 1 ${r} 0`} fill="none" stroke={color} strokeWidth={5 - i} strokeLinecap="round"
          initial={{ pathLength: 0, opacity: 0, scale: 0.6 }}
          animate={{ pathLength: [0, 1, 1], opacity: [0, 1, 0], scale: [0.6, 1, 1.35] }}
          transition={{ duration: 1.1, delay: 0.06 + i * 0.1, ease: 'easeOut', times: [0, 0.45, 1] }} />
      ))}
    </svg>
  );
}

// The transition overlay: a short glitch as we leave, then the destination's label under the spinning globe.
const COORD = [[32, -150], [16, -100], [-6, -52], [44, -6], [20, 42], [-18, 88], [26, 134], [6, 178]];
const fmt = ([la, lo]) => `${Math.abs(la).toFixed(1)}° ${la >= 0 ? 'N' : 'S'} · ${Math.abs(lo).toFixed(1)}° ${lo >= 0 ? 'E' : 'W'}`;
export function Burst({ burst }) {
  return (
    <AnimatePresence>
      {burst && (
        <motion.div key={burst.id} className="burst" style={{ '--accent': burst.accent }}
          initial={{ opacity: 1 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: { duration: 0.3 } }}>
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <motion.i key={i} className="glitch" style={{ top: `${8 + ((i * 37 + burst.id) % 84)}%`, height: `${2 + ((i * 13) % 7)}px` }}
              initial={{ opacity: 0, x: 0 }} animate={{ opacity: [0, 1, 0, 1, 0], x: [0, (i % 2 ? 1 : -1) * 40, 0, (i % 2 ? -1 : 1) * 18, 0] }}
              transition={{ duration: 0.34, delay: i * 0.025 }} />
          ))}
          <motion.div className="edge" initial={{ opacity: 0 }} animate={{ opacity: [0, 0.7, 0] }} transition={{ duration: 0.8 }} />
          {/* targeting brackets round the globe */}
          <motion.div className="reticle" initial={{ opacity: 0, scale: 1.4 }} animate={{ opacity: [0, 1, 1, 0], scale: [1.4, 1, 1, 0.8] }}
            transition={{ duration: burst.dur * 0.62, delay: burst.dur * 0.2, times: [0, 0.2, 0.8, 1] }}><i /><i /><i /><i /></motion.div>
          <motion.div className="dest" initial={{ opacity: 0, y: 14 }} animate={{ opacity: [0, 1, 1, 0], y: [14, 0, 0, -10] }}
            transition={{ duration: burst.dur * 0.55, delay: burst.dur * 0.26, times: [0, 0.2, 0.8, 1] }}>
            <small>Next mission · {burst.num}</small>
            <Decode as="b" text={burst.title.toUpperCase()} play delay={burst.dur * 300} speed={30} />
            <span>{fmt(COORD[(burst.coord ?? 0) % COORD.length])}</span>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// Boot splash: the ABHEDYA logo arrives with its signal arcs, then the deck takes over.
export function Splash({ onDone }) {
  const done = useRef(false);
  const finish = () => { if (!done.current) { done.current = true; onDone(); } };
  useEffect(() => { const t = setTimeout(finish, 2600); return () => clearTimeout(t); });
  return (
    <motion.div className="splash" onClick={finish} initial={{ opacity: 1 }} exit={{ opacity: 0, scale: 1.08, filter: 'blur(10px)', transition: { duration: 0.7, ease: 'easeIn' } }}>
      <div className="splash-arcs"><Arcs color="#b3232f" size={760} /></div>
      <motion.img src="abhedya_logo.png" alt="ABHEDYA" className="splash-logo"
        initial={{ opacity: 0, letterSpacing: 0, clipPath: 'inset(0 100% 0 0)', filter: 'blur(8px)' }}
        animate={{ opacity: 1, clipPath: 'inset(0 0% 0 0)', filter: 'blur(0px)' }}
        transition={{ duration: 1.1, delay: 0.35, ease: [0.22, 1, 0.36, 1] }} />
      <motion.div className="splash-line" initial={{ scaleX: 0 }} animate={{ scaleX: 1 }} transition={{ duration: 1.2, delay: 0.6, ease: [0.65, 0, 0.35, 1] }} />
      <motion.small initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 1.2, duration: 0.6 }}>
        AI anti-jamming · Team JamBreakers
      </motion.small>
    </motion.div>
  );
}
