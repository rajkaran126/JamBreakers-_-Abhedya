# viewer3d/ — 3D simulation view (Phase 5 · owner: Akshatha)

Static site served by the backend at `/viewer/` once `viewer3d/index.html` exists.
Vendor Three.js into `viewer3d/vendor/` (no CDN: the demo runs offline).
Connect to `ws://<host>/ws`; read `hello`, then draw every `state` / `spectrum` / `decision` / `event`.
In side-by-side view there are two `state` messages per tick: `world: "ai_off"` and `world: "ai_on"`.
`backend/static/console.html` is a small working reference client.
