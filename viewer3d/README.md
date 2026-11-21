# viewer3d/ — 3D simulation view (owner: Akshatha)

Served at `/view/` (and `/viewer/`). Three.js 0.170 is vendored in `vendor/` (MIT, see THREE_LICENSE.txt),
so it works with no internet.

| File | What |
|---|---|
| `index.html` | Layout: glass panels, controls, side-by-side captions |
| `style.css` | Look and feel |
| `app.js` | Scene (sky, terrain, trees, obstacles), unit models, links/packets, jammer domes, estimate rings, WebSocket client, side-by-side rendering |

The view is a thin client. It draws whatever `state` / `spectrum` / `decision` / `event` messages
say, so it needs no changes when the simulation changes. Trees are an InstancedMesh capped at
TREE_MAX: never write more instances than that.
