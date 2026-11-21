import React from 'react';
import { useStore, shownSpectrum, shownState, shownWorld, CLASS_INFO } from '../store.js';
import { useCanvas, inferno } from '../ui.jsx';

export default function Signal() {
  const S = useStore();
  const sp = shownSpectrum(), st = shownState(), world = shownWorld();
  const chans = S.hello?.channels_mhz || [2410, 2420, 2430, 2440, 2450, 2460, 2470, 2480];
  const cp = st?.nodes.find((n) => n.kind === 'command_post');
  const ours = cp?.channel;
  const f0 = sp?.f_start_mhz ?? 2405, f1 = sp?.f_stop_mhz ?? 2485;

  const specRef = useCanvas((g, W, H) => {
    const L = 30, B = 18, T = 6, pw = W - L - 6, ph = H - B - T, lo = -120, hi = -40;
    g.fillStyle = '#fff4ec'; g.fillRect(L, T, pw, ph);
    const fx = (f) => L + ((f - f0) / (f1 - f0)) * pw, py = (d) => T + ph - ((Math.max(lo, Math.min(hi, d)) - lo) / (hi - lo)) * ph;
    chans.forEach((f, i) => {
      g.fillStyle = (st?.blacklist || []).includes(i) ? 'rgba(210,63,77,.12)' : i === ours ? 'rgba(240,138,93,.14)' : 'rgba(240,138,93,.05)';
      g.fillRect(fx(f - 4), T, fx(f + 4) - fx(f - 4), ph);
      g.fillStyle = i === ours ? '#d9663a' : '#9a8075'; g.font = '9px system-ui'; g.textAlign = 'center'; g.fillText(String(f), fx(f), H - 5);
    });
    g.textAlign = 'right'; g.fillStyle = '#9a8075';
    for (let d = lo; d <= hi; d += 20) { g.fillText(String(d), L - 3, py(d) + 3); g.strokeStyle = 'rgba(240,138,93,.08)'; g.beginPath(); g.moveTo(L, py(d)); g.lineTo(L + pw, py(d)); g.stroke(); }
    if (!sp) return;
    const n = sp.bins.length;
    g.beginPath(); sp.bins.forEach((d, i) => { const x = L + (i / (n - 1)) * pw; i ? g.lineTo(x, py(d)) : g.moveTo(x, py(d)); });
    g.lineTo(L + pw, T + ph); g.lineTo(L, T + ph); g.closePath();
    const gr = g.createLinearGradient(0, T, 0, T + ph); gr.addColorStop(0, 'rgba(35,147,95,.45)'); gr.addColorStop(1, 'rgba(35,147,95,.02)');
    g.fillStyle = gr; g.fill();
    g.beginPath(); sp.bins.forEach((d, i) => { const x = L + (i / (n - 1)) * pw; i ? g.lineTo(x, py(d)) : g.moveTo(x, py(d)); });
    g.strokeStyle = '#1d7d50'; g.lineWidth = 1.4; g.stroke();
  }, [sp, ours, st?.blacklist?.join()]);

  const wfRef = useCanvas((g, W, H) => {
    const rows = S.waterfall[world] || S.waterfall.ai_on || S.waterfall.main || [];
    if (!rows.length) return;
    const n = rows[0].length, cw = W / n, rh = H / 60;
    rows.forEach((r, y) => r.forEach((d, x) => { const [a, b, c] = inferno((d + 115) / 65); g.fillStyle = `rgb(${a},${b},${c})`; g.fillRect(x * cw, y * rh, cw + 0.6, rh + 0.6); }));
  }, [sp]);

  const camRef = useCanvas((g, W, H) => {
    const gc = sp?.gradcam; if (!gc) return;
    const rows = gc.length, cols = gc[0].length, cw = W / cols, rh = H / rows;
    gc.forEach((r, y) => r.forEach((v, x) => { const [a, b, c] = inferno(v); g.fillStyle = `rgb(${a},${b},${c})`; g.fillRect(x * cw, y * rh, cw + 0.6, rh + 0.6); }));
  }, [sp]);

  const probs = sp?.probs ? (S.hello?.classes || Object.keys(sp.probs)).map((c, i) => [c, (Array.isArray(sp.probs) ? sp.probs[i] : sp.probs[c]) ?? 0]) : null;
  const top = sp?.verdict;
  return (
    <div className="tab signal">
      <section className="card">
        <div className="row-h"><h3>Spectrum at the command post</h3><span className="muted small">2.405–2.485 GHz</span></div>
        <canvas ref={specRef} className="spec" />
        <p className="muted small"><span className="sw ours" /> our channel{ours != null ? ` (${chans[ours]} MHz)` : ''} <span className="sw bl" /> blacklisted by the AI</p>
        <canvas ref={wfRef} className="wf" />
        <p className="muted small">Waterfall: newest at the top. Bright = energy. A jammer's pattern is easy to see here.</p>
      </section>

      <section className="card">
        <div className="row-h"><h3>CNN classifier</h3>{top && <span className="tag" style={{ background: CLASS_INFO[top]?.color }}>{CLASS_INFO[top]?.label} · {Math.round((sp.confidence || 0) * 100)} %</span>}</div>
        {!probs ? <p className="muted">{world === 'ai_off' ? 'AI OFF: fixed hopping does not classify anything.' : 'Waiting for the next spectrum window…'}</p> : (
          <div className="bars">{probs.map(([c, p]) => (
            <div key={c} className={`bar ${c === top ? 'best' : ''}`}><span>{CLASS_INFO[c]?.label || c}</span>
              <div><i style={{ width: `${(p * 100).toFixed(1)}%`, background: CLASS_INFO[c]?.color }} /></div><b>{Math.round(p * 100)}%</b></div>
          ))}</div>
        )}
        {top && <p className="small explain">{CLASS_INFO[top]?.plain}</p>}
      </section>

      <section className="card">
        <div className="row-h"><h3>Grad-CAM: why the CNN decided</h3></div>
        {sp?.gradcam ? <canvas ref={camRef} className="cam" /> : <p className="muted">Shown when the AI is classifying a signal.</p>}
        <p className="muted small">Bright cells are the time × frequency regions that drove the decision: the AI shows its evidence, not just an answer.</p>
      </section>
    </div>
  );
}
