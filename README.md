# AEGIS-LINK

AI-enabled adaptive anti-jamming for tactical drone and vehicle networks.
Team JamBreakers · BITS2WAVE round 2 · SW-26 (software track).

> **Status: Phase 0.** Skeleton, message contract, server and a **placeholder (fake) world**.
> The fake world exists so the 3D view and the phone app can be built in parallel. It is not
> the simulation or the AI; `hello.world_source` says `"fake"` until Phase 1 replaces it.

## Run

**Windows (main path):** double-click `run_windows.bat`. The first run creates `.venv` and installs the packages.

**macOS / Linux:** `./run.sh`

**Docker:** `docker build -t aegis-link . && docker run --rm -p 8000:8000 aegis-link`

Then open:

| URL | What |
|---|---|
| http://localhost:8000/ | Debug console: live map, spectrum, KPIs, every command |
| http://localhost:8000/health | Server health |
| http://localhost:8000/api/schema | The message contract (`shared/schema.json`) |
| http://localhost:8000/api/lan | The laptop's LAN URLs (for phones and the QR code) |
| ws://localhost:8000/ws | The one WebSocket: ~20 Hz broadcast + commands |
| /viewer/ · /app/ | 3D view and phone app (served once they're built) |

**Phones:** use the same Wi-Fi or hotspot. The server binds to `0.0.0.0`. On Windows, allow Python
through the firewall for **private** networks.

**Tests:** `.venv\Scripts\python -m pytest -q` (Windows) or `.venv/bin/python -m pytest -q`.

**Probe a running server:** `python scripts/ws_probe.py --cmd '{"action":"launch_jammer","jammer_type":"barrage","pos":[100,100]}'`

### Environment variables (all optional)

| Variable | Default | Meaning |
|---|---|---|
| `AEGIS_WORLD` | `fake` | `fake` (placeholder) or `sim` (real simulation, from Phase 1) |
| `SIGNAL_BACKEND` | `numpy` | `gnuradio` or `numpy` (from Phase 1) |
| `AEGIS_SEED` | `42` | Seed for replayable runs |
| `AEGIS_TICK_HZ` | `20` | Broadcast rate |
| `AEGIS_SLOT_MS` | `10` | Radio slot length inside the simulation |

## Message contract (summary)

The full contract is `shared/schema.json` (JSON Schema 2020-12). Every server message has
`{v:"1.0", type, t, src}`.

- **Server → client:** `hello` (once on connect), `state` (20 Hz, per world), `spectrum` (128 bins,
  CNN probabilities, optional 12×32 Grad-CAM), `event` (plain English, level info/warn/alert/good),
  `decision`, `security`, `score`, `benchmark`, `report`, `error`.
- **Client → server:** `{type:"cmd", id?, player?, action, ...}` with these actions: `launch_jammer`
  {jammer_type, pos:[x,y], power_dbm?}, `clear_jammers`, `toggle_ai` {enabled?}, `set_view`
  {view: single|side_by_side}, `run_benchmark` {seed?, duration_s?}, `security_test`
  {test: tamper|spoof|replay|eavesdrop}, `load_scenario` {name}, `exit_scenario`, `play`, `pause`,
  `set_speed` {1|2|4}, `restart`.
- **Side-by-side:** the server sends two `state` and two `spectrum` messages per tick, with `world` set
  to `ai_off` and `ai_on`. In single view, `world` is `main`.
- **Errors:** an `error` goes only to the client that sent the bad command, with `req_id` echoed back.
  Everything else is broadcast, so every screen stays in sync.
- **Units:** metres, with x east, y north, z up. The arena is x −300..1200 and y −400..900. There are
  8 channels (0–7) at 2410–2480 MHz.

## Layout

```
backend/   FastAPI server, command models, World interface, fake world, debug console
shared/    schema.json, the single message contract
sim/       radio world: GNU Radio chain + NumPy fallback, jammers, baselines   (Phase 1)
ai/        data generator, CNN training/inference, defender, localisation    (Phase 2)
viewer3d/  Three.js 3D view, vendored, offline                               (Phase 5)
mobile/    React PWA built with Vite, served at /app/                         (Phase 5)
tests/     pytest
scripts/   helpers (ws_probe.py)
```

To plug in the real simulation, implement `backend/world_api.World` (`hello_info`, `step`, `handle`)
in `sim/world.py` as `SimArena`, then run with `AEGIS_WORLD=sim`. The server, screens and tests stay
the same.

## Build phases

| Phase | Content | Owner | Status |
|---|---|---|---|
| 0 | Skeleton, schema, server, fake world | Kodandarama | ✅ |
| 1 | GNU Radio + NumPy radio world, 7 jammers, baselines | Kodandarama | |
| 2 | Data + CNN, intelligent hopping, Grad-CAM, localisation | Vishwas | |
| 3 | AES-256-GCM, keyed hop sequence, security tests | Neha + Vishwas | |
| 4 | Twin worlds (AI OFF/ON) + benchmark vs fixed hopping | Vishwas + Kodandarama | |
| 5 | 3D view, React PWA, judges' screen, QR join | Akshatha, Neha | |
| 6 | Stretch (scenarios, smart jammer, RL) + hardening | all | |
