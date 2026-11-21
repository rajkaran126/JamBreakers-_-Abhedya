# AEGIS-LINK

AI-enabled adaptive anti-jamming for tactical drone and vehicle networks.
Team JamBreakers · BITS2WAVE round 2 · SW-26 (software track).

> **Status: Phase 2 done.** Real radio world (GNU Radio chain tested on GNU Radio 3.10.9, NumPy
> fallback), 7 jammers, baselines, twin worlds, plus the AI. The CNN is 95.4 % accurate on held-out
> live windows, runs in NumPy in 1.9 ms, and comes with Grad-CAM. The defender reacts per class with
> backups, follower detection and keyed fast hopping, and localises jammers by RSSI.

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
| http://localhost:8000/view/ | **3D simulation view** (Three.js, vendored, works offline) |
| /app/ | Phone app (Phase 5) |

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

## The AI (Phase 2)

**Classifier.** A 3-layer CNN (19k parameters) reads a 12 × 128 spectrogram window (0.3 ms ×
80 MHz) and outputs 7 classes. It is trained in PyTorch on 16,800 synthetic windows plus 6,300
windows captured from the running world, then exported to `ai/weights/cnn_v1.npz` and served in pure
NumPy, so the server needs no PyTorch. The global-average-pool head gives Grad-CAM in closed form:
a 12 × 32 heat map showing where the CNN looked.

| Held-out live windows (other seeds) | 1,680 |
|---|---|
| Accuracy | **95.4 %** (clean 100, barrage 100, sweep 100, reactive 97.9, deceptive 95.8, random 88.3, accidental 85.8) |
| NumPy inference | 1.9 ms per window (target < 20 ms) |

Rebuild with `python -m ai.dataset` and then `python -m ai.train` (about 2 + 4 min on a laptop CPU).
Full report: `ai/weights/report.json`.

**Defender** (`ai/defender.py`). It triggers at more than 10 % loss, captures 3 windows at the
receiver that is losing packets, and decides on the average of the 3 classifications:

| Class | Response |
|---|---|
| barrage | Raise power +3 dB per step (cap +9 dB) and drop to BPSK; hopping is pointless |
| sweep | Raise power and hold, then BPSK; hopping only thrashes |
| random | Blacklist the occupied channels and hop to the cleanest one |
| reactive | Keyed fast hopping, and blacklist the channel it listens on |
| deceptive | Hop away and blacklist the channel; authentication rejects the forged frames |
| accidental | No alarm; quietly move to a clean channel |
| clean but losing packets | A link is blocked, so dispatch a relay drone above the tallest obstacle + 30 m |

On top of the per-class responses:

- **Follower detection, from behaviour:** the jammer re-finds us under 300 ms after a hop, or, while fast hopping, the jammed channel matches where we were 1–4 slots earlier. Response: keyed fast hopping that never reuses the last 3 channels.
- **Hop guard and recovery:** at most 4 hops in 5 s; when the band is quiet, emergency measures are stepped back down one at a time.
- **Localisation:** wideband RSSI least squares with per-node path-loss exponents, a leave-one-out NLOS rejection pass (8 dB) and a 95 % uncertainty radius. Estimates are published under 300 m and announced under 150 m. Measured: published in 23 of 30 runs, median error 67 m on a 1.5 × 1.3 km map.

**Results** (12 s runs, jammer from t = 2 s, 4 seeds × random jammer positions; mean delivery):

| Jammer | Fixed hopping (AI OFF) | Energy detector | **AEGIS** | AEGIS worst run |
|---|---|---|---|---|
| barrage | 40.8 % | 40.8 % | **92.6 %** | 86.0 % |
| random | 66.3 % | 93.9 % | **99.0 %** | 97.8 % |
| sweep | 41.2 % | 41.2 % | **93.4 %** | 89.7 % |
| reactive | 88.4 % | 21.7 % | **93.9 %** | 93.2 % |
| deceptive | 92.7 % | 95.2 % | **99.8 %** | 99.8 % |
| accidental | 97.8 % | 99.0 % | **99.6 %** | 99.3 % |
| follower | 13.9 % | 13.1 % | **99.7 %** | 99.6 % |

Hop latency (first jammed slot until the whole network is on the new channel, control frame
included): median 20 ms, p95 50 ms, over 509 hops.

**Lessons this build taught us** (good answers for judges):

- **Keyed hopping needs real choices.** With 4 channels blacklisted and 3 avoided, only one channel was left each slot, so the "keyed" sequence turned into a 4-channel loop that the follower learned. The sequence now always keeps at least 3 candidates, and the blacklist gives way first.
- **The control link must be robust.** Barrage and sweep blocked control frames for 8 s until they were sent like real control traffic: max power, BPSK, repetition coding, and a rendezvous channel that moves on every retry.
- **Don't re-classify every 10 ms.** Under heavy jamming that cost 27 ms per slot and stalled the server. The defender now waits 50 ms after acting and 250 ms after holding, and the server never does more than 2× the normal work per tick.

## 3D view

Open `http://localhost:8000/view/`. It shows:

- **Scene:** night or day sky, terrain with forests, a lake and mountains, the arena's buildings and hill, and the vehicles' roads.
- **Units:** drones with spinning rotors and status LEDs, vehicles, the command post, and relay drones.
- **Links and packets:** links coloured by health, with packets flowing to the command post (red ones are dropped).
- **Jammers and the AI's estimate:** each jammer has an energy-shield dome sized to its reach and a ground heat map. The AI's estimate is a yellow ring sized by its uncertainty.
- **Panels:** KPIs, legend, security, live decisions, the CNN's probabilities with Grad-CAM, and the spectrum with a waterfall.
- **Controls:** pick a jammer type and click the ground to launch it. AI ON, AI OFF and **Side by side** (two viewports in one renderer: AI OFF left, AI ON right, each with its own KPI strip). Day/night toggle.

Drag to orbit, scroll to zoom, right-drag to pan. Units are drawn about 14× real size so they can be read from 1 km away.

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
| 2 | Data + CNN, intelligent hopping, Grad-CAM, localisation | Vishwas | ✅ |
| 3 | AES-256-GCM, keyed hop sequence, security tests | Neha + Vishwas | |
| 4 | Twin worlds (AI OFF/ON) + benchmark vs fixed hopping | Vishwas + Kodandarama | |
| 5 | 3D view, React PWA, judges' screen, QR join | Akshatha, Neha | |
| 6 | Stretch (scenarios, smart jammer, RL) + hardening | all | |
