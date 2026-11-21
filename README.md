# AEGIS-LINK

AI-enabled adaptive anti-jamming for tactical drone and vehicle networks.
Team JamBreakers · BITS2WAVE round 2 · SW-26 (software track).

> **Status: Phase 1 done.** Real radio world: link budget with path loss, Rician fading and
> obstacles; 7 jammers; GNU Radio receiver chain (tested on GNU Radio 3.10.9) with a NumPy fallback;
> mesh routing; fixed-hopping and energy-detector baselines; seeded replay; twin worlds.
> The CNN defender (Phase 2) plugs in next. Until then the AI ON side runs the energy detector.

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
| `AEGIS_WORLD` | `sim` | `sim` (real simulation) or `fake` (lightweight placeholder for UI work) |
| `SIGNAL_BACKEND` | `numpy` | `gnuradio` or `numpy`. If GNU Radio fails to load, the server falls back to NumPy and says so in an event |
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

## GNU Radio

The receiver chain is a GNU Radio flowgraph (`sim/phy_gnuradio.py`). Each transmitter runs through
the QPSK Constellation Modulator (`digital.generic_mod`, RRC 0.35), a rotator onto its channel, and the
Rician `fading_model`. The receiver then adds the interference-engine waveforms and thermal noise,
followed by `stream_to_vector`, a 128-point Hann `fft_vcc`, `complex_to_mag_squared`, and a vector
sink. The output matches the NumPy reference to within 0.5 dB on every emitter type.

On Windows, GNU Radio comes from radioconda. Run the server with the radioconda Python:

```
<radioconda>\python.exe -m pip install -r requirements.txt
set SIGNAL_BACKEND=gnuradio
<radioconda>\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

- `scripts/check_gnuradio.py` compares the two backends and times them (about 18 ms per window on GNU Radio vs 4 ms on NumPy).
- `scripts/gr_live_demo.py [narrowband|barrage|sweep]` opens a live Qt waterfall of the chain, for showing judges.

## How the simulation works (Phase 1)

- **Radio:** 8 channels at 2410–2480 MHz, 10 ms TDMA slots, QPSK at 2 Msym/s (2.7 MHz wide), 27 dBm
  radios. Path loss is log-distance from a 1 m free-space reference (exponent 2.2 for air links, 2.9
  for ground links) plus Rician block fading (K = 9 dB air, 3 dB ground). Buildings cost −22 dB and
  hills −18 dB, using a 3D ray–box test. Each 58-byte packet passes or fails on coded BER, drawn per
  slot. BPSK fallback is worth +3 dB.
- **Mesh:** each node routes to the command post along the widest path (best weakest-link SINR), with
  3 dB hysteresis. Delivery means packets that reach the command post end to end.
- **Jammers:** behaviour lives in `sim/jammers.py`. A follower re-tunes about 25 ms after each hop
  *and learns repeating hop patterns*, which is why fixed hopping collapses against it. A reactive
  jammer listens on one channel and jams only the packets it hears.
- **Control plane:** a defence takes effect only when its control frame is delivered. Control frames
  go out on a key-derived rendezvous channel that moves on every retry, with back-off. Hop latency is
  measured from the first jammed slot to the slot when the whole network is on the new channel.
- **Determinism:** separate random streams (fading, packets, jammers, control, spectrum, defender)
  come from one seed. Twin worlds share them, so the AI OFF and AI ON sides see the same fading and
  the same jammer randomness.

Baselines (12 s, jammer from t = 2 s, seed 7; `python -m sim.experiment` style runs via `sim/experiment.py`):

| Jammer | No defence | Fixed hopping (AI OFF) | Energy detector |
|---|---|---|---|
| random | 31 % | 65 % | 90–95 % |
| deceptive | 42 % | 92 % | 99.8 % |
| reactive | 3 % | 88 % | 17 % |
| follower | 3 % | 5 % | 5 % |
| barrage / sweep | 25 % / 10 % | same | same |

The CNN defender has to beat every column. Barrage and sweep need power and rate backups, and the
follower needs keyed hopping.

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
| 1 | GNU Radio + NumPy radio world, 7 jammers, baselines | Kodandarama | ✅ |
| 2 | Data + CNN, intelligent hopping, Grad-CAM, localisation | Vishwas | |
| 3 | AES-256-GCM, keyed hop sequence, security tests | Neha + Vishwas | |
| 4 | Twin worlds (AI OFF/ON) + benchmark vs fixed hopping | Vishwas + Kodandarama | |
| 5 | 3D view, React PWA, judges' screen, QR join | Akshatha, Neha | |
| 6 | Stretch (scenarios, smart jammer, RL) + hardening | all | |
