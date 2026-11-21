import React, { useState } from 'react';
import { JOIN_CODE, signIn } from './auth.js';
import { apiBase, signedIn } from './store.js';

export default function Login() {
  const [user, setUser] = useState('');
  const [pw, setPw] = useState('');
  const [code, setCode] = useState(JOIN_CODE);
  const [showCode, setShowCode] = useState(!JOIN_CODE);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setErr('');
    try {
      const d = await signIn(apiBase(), user.trim(), pw, code.trim());
      signedIn({ user: d.user, role: d.role, local: false, auth: true });
    } catch (ex) {
      setErr(ex.message === 'Failed to fetch' ? "Can't reach the laptop. Are you on the same Wi-Fi?" : ex.message);
      if (ex.code === 'join_code') setShowCode(true);
    } finally { setBusy(false); }
  }

  return (
    <div className="login">
      <form className="card login-card" onSubmit={submit} autoComplete="on">
        <img className="wordmark" src="./abhedya_logo_dark.png" alt="ABHEDYA" />
        <h1>Sign in</h1>
        <p className="mute center">to join the mission from this phone</p>
        <label htmlFor="li-u">User ID</label>
        <input id="li-u" value={user} onChange={(e) => setUser(e.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} required />
        <label htmlFor="li-p">Password</label>
        <input id="li-p" type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" required />
        {showCode && <>
          <label htmlFor="li-j">Join code (shown under the laptop's QR)</label>
          <input id="li-j" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} autoCapitalize="characters" spellCheck={false} maxLength={6} />
        </>}
        {!showCode && <p className="ok-line">✓ QR scanned</p>}
        <button className="btn primary wide" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        <p className="err" role="alert">{err}</p>
        <p className="mute small center">No account? Ask the commander at the demo laptop.</p>
      </form>
    </div>
  );
}
