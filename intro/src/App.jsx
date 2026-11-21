// ABHEDYA mission deck: eight slides that move horizontally like a presentation.
// ← / → (or swipe, scroll, the dock) to browse; click the emblem, the 3D scene or "Launch" to start
// that simulation in the 3D viewer.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import Stage, { flightTime } from './Scene.jsx';
import Emblem from './Emblem.jsx';
import { Burst, Decode, Splash } from './fx.jsx';
import { ARENA, FALLBACK, LOOK, STORY } from './slides.js';

const VIEWER = '/viewer/';
const THEME_NAME = { mountain_pass: 'Mountain pass', city: 'City', coast: 'Coast', forest: 'Forest', airbase: 'Airbase', camp: 'Camp', desert: 'Desert', open_field: 'Open field' };
const PHASE_DOT = ['ok', 'bad', 'ai', 'won'];

const item = {
  hidden: { opacity: 0, x: 40, filter: 'blur(8px)', transition: { duration: 0.35, ease: 'easeIn' } },
  show: (i) => ({ opacity: 1, x: 0, filter: 'blur(0px)', transition: { delay: 2.25 + i * 0.07, duration: 0.7, ease: [0.22, 1, 0.36, 1] } }),
};

function shortAi(s = '') {           // first two sentences, so the card stays short
  const parts = s.match(/[^.!?]+[.!?]+(\s|$)/g) || [s];
  let out = parts[0];
  if (parts[1] && (out + parts[1]).length < 190) out += parts[1];
  return out.trim();
}

export default function App() {
  const [scenarios, setScenarios] = useState(FALLBACK);
  const [index, setIndex] = useState(() => {
    const want = new URLSearchParams(location.search).get('slide');
    const i = [...FALLBACK.map((s) => s.id), 'arena'].indexOf(want);
    return i >= 0 ? i : 0;
  });
  const [dir, setDir] = useState(1);
  const [steps, setSteps] = useState(1);
  const [phase, setPhase] = useState(0);
  const [launch, setLaunch] = useState(null);       // { slide, x, y }
  const busy = useRef(false);
  const [burst, setBurst] = useState(null);
  const [splash, setSplash] = useState(() => {
    const deep = new URLSearchParams(location.search).has('slide');
    try { return !deep && !sessionStorage.getItem('abhedya-splash'); } catch { return !deep; }
  });
  const endSplash = useCallback(() => { try { sessionStorage.setItem('abhedya-splash', '1'); } catch { /* private mode */ } setSplash(false); }, []);

  useEffect(() => {
    fetch('/api/scenarios').then((r) => r.json()).then((d) => {
      const list = (d.scenarios || d).slice().sort((a, b) => (a.order || 0) - (b.order || 0));
      if (list.length) setScenarios(list);
    }).catch(() => {});
  }, []);

  const slides = useMemo(() => [...scenarios, ARENA], [scenarios]);
  const slide = slides[Math.min(index, slides.length - 1)];
  const look = LOOK[slide.id] || LOOK.arena;
  const story = STORY[slide.jammer] || STORY.arena;

  const go = useCallback((to) => {
    if (busy.current || launch) return;
    const n = slides.length, next = (to + n) % n;
    if (next === index) return;
    busy.current = true; setTimeout(() => (busy.current = false), 450);
    const d = next > index ? 1 : -1, dur = flightTime(next - index), nx = slides[next];
    setDir(d); setSteps(next - index); setIndex(next);
    const id = Date.now();
    setBurst({ id, dir: d, dur, coord: next, accent: (LOOK[nx.id] || LOOK.arena).accent, num: String(next + 1).padStart(2, '0'), title: nx.title });
    setTimeout(() => setBurst((b) => (b && b.id === id ? null : b)), dur * 1000 + 200);
  }, [index, slides.length, launch]);

  const start = useCallback((s, ev) => {
    if (launch) return;
    const x = ev?.clientX ?? window.innerWidth / 2, y = ev?.clientY ?? window.innerHeight / 2;
    setLaunch({ slide: s, x, y });
    setTimeout(() => { location.href = `${VIEWER}?start=${encodeURIComponent(s.id)}`; }, 1150);
  }, [launch]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'ArrowRight' || e.key === 'PageDown') go(index + 1);
      else if (e.key === 'ArrowLeft' || e.key === 'PageUp') go(index - 1);
      else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); start(slide); }
      else if (/^[1-8]$/.test(e.key)) go(Number(e.key) - 1);
    };
    let acc = 0;
    const onWheel = (e) => { acc += Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY; if (Math.abs(acc) > 60) { go(index + Math.sign(acc)); acc = 0; } };
    let x0 = null;
    const down = (e) => (x0 = e.touches ? e.touches[0].clientX : null);
    const up = (e) => { if (x0 === null) return; const dx = e.changedTouches[0].clientX - x0; if (Math.abs(dx) > 50) go(index + (dx < 0 ? 1 : -1)); x0 = null; };
    window.addEventListener('keydown', onKey); window.addEventListener('wheel', onWheel, { passive: true });
    window.addEventListener('touchstart', down, { passive: true }); window.addEventListener('touchend', up);
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('wheel', onWheel); window.removeEventListener('touchstart', down); window.removeEventListener('touchend', up); };
  }, [go, index, slide, start]);

  const num = (i) => String(i + 1).padStart(2, '0');
  const env = slide.id === 'arena' ? 'Free play · any jammer · any time' : `${THEME_NAME[slide.theme] || slide.theme} · ${slide.time_of_day} · ${slide.duration_s} s`;

  return (
    <div className="deck" style={{ '--accent': look.accent }}>
      <Stage slides={slides} index={index} onPhase={setPhase} onClick={(e) => start(slide, e)} />
      <div className="vignette" />
      <Burst burst={burst} />

      <header className="top">
        <div className="brand"><img className="brand-logo" src="abhedya_logo.png" alt="ABHEDYA" /><small>Mission deck · Team JamBreakers</small></div>
        <div className="hint">← → browse · Enter launch · 1–8 jump</div>
      </header>

      {/* the horizontal track: every slide's text panel sits side by side and the track slides */}
      <motion.div className="track" initial={false} animate={{ x: `${-index * 100}vw` }} transition={{ duration: 0.9, delay: 0.7, ease: [0.65, 0, 0.35, 1] }}>
        {slides.map((s, i) => {
          const L = LOOK[s.id] || LOOK.arena, on = i === index;
          return (
            <section className="slide" key={s.id} style={{ '--accent': L.accent }} aria-hidden={!on}>
              <motion.div className="panel" initial="hidden" animate={on ? 'show' : 'hidden'}
                variants={{ hidden: { clipPath: 'inset(0% 0% 0% 0% round 22px)', opacity: 0.25, scale: 0.96, transition: { duration: 0.4 } },
                  show: { clipPath: 'inset(0% 0% 0% 0% round 22px)', opacity: 1, scale: 1, transition: { duration: 0.6, delay: 2.1 } } }}>
                <motion.i className="scanline" key={`scan${on}`} initial={{ top: '-10%', opacity: 0 }} animate={on ? { top: ['-10%', '110%'], opacity: [0, 1, 0] } : {}} transition={{ duration: 1.1, delay: 2.2, ease: 'easeInOut' }} />
                <motion.div className="count" custom={0} variants={item}><b>{num(i)}</b><span>/ {num(slides.length - 1)}</span><i>{s.id === 'arena' ? 'Free play' : 'Guided mission'}</i></motion.div>
                <motion.div className="eyebrow" custom={1} variants={item}>{i === index ? <Decode text={env} play={on} delay={2250} speed={22} /> : ''}</motion.div>
                <motion.h1 custom={2} variants={item}><Decode text={s.title} play={on} delay={2350} speed={34} /></motion.h1>
                <motion.p className="sub" custom={3} variants={item}>{s.subtitle}</motion.p>
                <motion.p className="story" custom={4} variants={item}>{s.story}</motion.p>
                <motion.div className="ai" custom={5} variants={item}>
                  <span className="tag">AI response</span>{shortAi(s.ai_response)}
                </motion.div>
                {s.expected ? <motion.div className="expect" custom={6} variants={item}>{s.expected}</motion.div> : null}
                <motion.div className="actions" custom={7} variants={item}>
                  <button className="launch" onClick={(e) => start(s, e)}><span>Launch simulation</span><svg viewBox="0 0 24 24"><path d="M8 5l11 7-11 7z" /></svg></button>
                  <span className="or">or click the emblem / the scene</span>
                </motion.div>
              </motion.div>
            </section>
          );
        })}
      </motion.div>

      {/* big emblem + live status chip on the scene side */}
      <AnimatePresence mode="wait">
        <motion.div key={slide.id} className="hero-emblem"
          style={{ perspective: 600 }}
          initial={{ opacity: 0, rotateY: dir * 180, scale: 0.5, filter: 'blur(6px)' }} animate={{ opacity: 1, rotateY: 0, scale: 1, filter: 'blur(0px)' }}
          exit={{ opacity: 0, rotateY: -dir * 120, scale: 0.6, filter: 'blur(6px)', transition: { duration: 0.35 } }} transition={{ duration: 1.0, ease: [0.22, 1, 0.36, 1], delay: 2.3 }}>
          <motion.span className="emblem-ring" key={`ring${slide.id}`} initial={{ scale: 0.6, opacity: 0.9 }} animate={{ scale: 2.2, opacity: 0 }} transition={{ duration: 1.1, delay: 2.6, ease: 'easeOut' }} />
          <Emblem kind={look.emblem} accent={look.accent} size={132} onClick={(e) => start(slide, e)} title={`Launch ${slide.title}`} />
          <span className="emblem-cap">Click to launch</span>
        </motion.div>
      </AnimatePresence>

      <div className="status">
        <AnimatePresence mode="wait">
          <motion.div key={`${slide.id}${phase}`} className={`chip ${PHASE_DOT[phase]}`}
            initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }} transition={{ duration: 0.3 }}>
            <i />{story[phase]}
          </motion.div>
        </AnimatePresence>
        <div className="steps">{story.map((_, k) => <span key={k} className={k <= phase ? 'on' : ''} />)}</div>
      </div>

      <button className="nav prev" onClick={() => go(index - 1)} aria-label="Previous">‹</button>
      <button className="nav next" onClick={() => go(index + 1)} aria-label="Next">›</button>

      {/* dock: every mission's logo. Click selects it; click the selected one again to launch. */}
      <nav className="dock">
        {slides.map((s, i) => {
          const L = LOOK[s.id] || LOOK.arena;
          return (
            <motion.div key={s.id} className={`dock-item ${i === index ? 'on' : ''}`} style={{ '--accent': L.accent }}
              whileHover={{ y: -6 }} layout>
              <Emblem kind={L.emblem} accent={L.accent} size={i === index ? 50 : 40} active={i === index}
                onClick={(e) => (i === index ? start(s, e) : go(i))} title={i === index ? `Launch ${s.title}` : s.title} />
              <span>{s.title}</span>
              {i === index && <motion.div layoutId="dockbar" className="dock-bar" />}
            </motion.div>
          );
        })}
      </nav>

      <AnimatePresence>{splash && <Splash onDone={endSplash} />}</AnimatePresence>

      <AnimatePresence>
        {launch && (
          <motion.div className="launching" style={{ '--accent': (LOOK[launch.slide.id] || LOOK.arena).accent }}
            initial={{ clipPath: `circle(0px at ${launch.x}px ${launch.y}px)` }}
            animate={{ clipPath: `circle(${Math.hypot(window.innerWidth, window.innerHeight)}px at ${launch.x}px ${launch.y}px)` }}
            transition={{ duration: 0.8, ease: [0.65, 0, 0.35, 1] }}>
            <motion.div className="launch-inner" initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: 0.35 }}>
              <img className="launch-logo" src="abhedya_logo.png" alt="ABHEDYA" />
              <Emblem kind={(LOOK[launch.slide.id] || LOOK.arena).emblem} accent="#05080f" size={96} />
              <small>Deploying</small>
              <b>{launch.slide.title}</b>
              <div className="bar"><motion.i initial={{ width: 0 }} animate={{ width: '100%' }} transition={{ duration: 0.9, delay: 0.2 }} /></div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
