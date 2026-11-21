# viewer3d/ — 3D simulation view (owner: Akshatha)

Served at `/view/`. Three.js 0.170 plus its bloom post-processing are vendored in `vendor/` (MIT, see
THREE_LICENSE.txt), so it works with no internet.

**Look:** moonlit night by default (☾/☀ toggles day). It has a moon with a halo, lit clouds,
snow-capped mountains, pine forests, rocks, about 110k instanced grass blades swaying in the wind,
and bloom on LEDs, links, the dome rim and the moon. Units are procedural models: quadcopters with
arms, motors, spinning props, skids and nav lights; a 6-wheel truck; a tripod command post with a
dish and equipment cases; tripod jammers.

**Camera:** 🎥 cycles Cinematic (low, across the field), Overview and Top. Drag to orbit, scroll to zoom.

**Quality:** add `?q=low` to the URL (`/viewer/?q=low`) on a weak laptop. That drops the grass and
bloom; everything else stays.

| File | What |
|---|---|
| `index.html` | Layout: glass panels, control bar, side-by-side captions, benchmark panel |
| `style.css` | Look and feel; compact layout under 1000 px wide |
| `app.js` | Scene, unit models, links/packets, jammer domes, estimate rings, WebSocket client, panels, side-by-side rendering |

The view is a thin client: it draws whatever `state` / `spectrum` / `decision` / `event` messages
say. Instanced meshes (trees, grass, rocks) are capped at their allocation: never write more instances
than that. Bump the `?v=` numbers in index.html when you change app.js or style.css.
