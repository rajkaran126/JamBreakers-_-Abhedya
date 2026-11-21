# AEGIS-LINK · 3-minute demo script

Two people: **Presenter** (talks, drives the laptop) and **Phone operator** (hands phones to judges, launches jammers).
Screen: `http://localhost:8000/demo` full-screen (F11) on the projector. Keys work on the 3D view: click it once first.

## Before the judges arrive (5 min)

- [ ] Laptop **on mains power** (on battery Windows throttles the CPU 2-3x); Power mode "Best performance"; notifications off.
- [ ] Use **Edge or Chrome** for the 3D view (graphics card). Measured on this laptop: 1 jammer side by side = 20 updates/s,
      18.6 ms CPU each, when the 3D view runs on the GPU.
- [ ] Wi-Fi connected **or** Mobile hotspot on (Settings → Network → Mobile hotspot). No internet is needed.
- [ ] Double-click `run_windows.bat`; wait for `Uvicorn running on http://0.0.0.0:8000`.
- [ ] Open `http://localhost:8000/demo`, press F11. Links green, CNN says "clean".
- [ ] Press **📱 Phone** (or `Q` on /demo): scan with your own phone. It must show **Live**, green dot.
- [ ] On the phone: More → name "JamBreakers". Map tab open.
- [ ] Press **↺ New mission** so the run starts fresh. `/health` → `overrun_ticks` should stay near 0.

## The script

| Time | Do | Say (short version) |
|---|---|---|
| **0:00** | Stay on the arena, links green. | "Drones and vehicles lose contact when they are jammed: India logged 1,951 GNSS interference cases between Nov 2023 and Nov 2025, 465 of them in the border region around Amritsar and Jammu by Feb 2025. Jammers differ, so one fixed defence fails. AEGIS-LINK listens, names the attack, and picks the right counter-move in milliseconds." |
| **0:20** | Point at the QR card. Phone operator hands a judge the phone, or the judge scans the code. | "Everything you see is one simulation: drones, a convoy, the command post. Every packet is really encrypted with AES-256. Please take the phone: you are the attacker." |
| **0:30** | Press **🎬 Scenarios** (`S`) → **Drone delivery**. Read the briefing in one breath, press **▶ Start**. | "A delivery drone is chased by a hostile drone carrying a follower jammer: it re-tunes to our channel 25 ms after every hop." |
| **0:45** | Captions run. Press **AI OFF** at the top (or `A`). | "Conventional radios hop on a fixed public pattern. The follower learns it: **delivery collapses to about 1 %**." |
| **1:00** | Press **AI ON**. Point at the decision log and the yellow ring. | "Same attack, same seed. The AI sees the jammer re-find us within 30 ms, concludes it is being followed, and switches to a secret key-derived hop sequence. Delivery: **99.9 %**. The yellow ring is where it thinks the jammer is." |
| **1:20** | Press **4×** so the 90 s run finishes in ~15 s (the whole scenario plays out while the truck drives its road). Point at the two big numbers. Press **Back to live arena**. | "The report compares both defences on the identical run." |
| **1:30** | Judge on the phone: Map → **Smart** → tap near the drones. | "Now the hard one: a *learning* jammer. Every second it tries follow, predict, spread, pulse or spoof, and keeps whatever hurts us most. Its label shows its tactic live." |
| **1:50** | Phone: **Signal** tab, hold it up. On screen point at CNN bars + Grad-CAM. | "The AI explains itself: the spectrum, the CNN's probabilities, and Grad-CAM, the bright cells are the evidence it used." |
| **2:05** | Left panel: **Tamper**, then **Replay**. | "Security: a flipped bit fails the GCM tag, a replayed frame fails the window. Rejected, with the reason and the real bytes. Forged frames accepted in every test: zero." |
| **2:20** | Press **📊 Results**. | "Seed-replayed benchmark: 9 attacks including one the AI never saw, 6 defences, 10 seeds, identical runs. AI ON (CNN + RL hybrid) delivers **95.1 %** under attack (confidence interval 94.3–95.9); fixed hopping **54.3 %**. Across 568 runs with power, distance, speed, size and interference changed, AI ON wins every condition. Hop latency 20 ms median. Every AI order passes a safety guard first." |
| **2:45** | Leave the Results card up. | "Software-defined, explainable, encrypted, and it runs on a laptop and phones with no internet. Everything above the radio is written against one radio interface, and our bench test plan says exactly how we validate it on real SDRs next. Thank you." |

## If something goes wrong

| Problem | Do this, keep talking |
|---|---|
| Judge's phone won't connect | Use your own phone; firewall/hotspot fixes are in the README. Say "same Wi-Fi only, no internet". |
| Scenario looks wrong / stuck | `✕` → back to arena → Scenarios again. Or **↺ Replay**. |
| Laptop slow | Stay at 1x. Add `?q=low` to the URL for lighter graphics. |
| Server window closed | Double-click `run_windows.bat` (10 s), refresh. |
| Out of time | Skip 1:30-2:05 (smart jammer, signal, security), go straight to Results. |

## Questions judges are likely to ask (honest answers)

- **"Is this real RF?"** Simulated physics: log-distance path loss, Rician fading, building/hill losses, coded BER per packet. We also run the signal chain through a GNU Radio flowgraph, which matches our NumPy chain within 0.5 dB. Be clear: that is a software cross-check, not RF validation. Nothing is hardware-validated yet. `hil/` holds the radio interface, the bench test and the measured-vs-predicted comparison for two SDRs on a cabled link (docs/HARDWARE_TEST_PLAN.md).
- **"How accurate is the CNN?"** 97.3 % on held-out windows, 94.3 % on live verdicts during the benchmark. A follower looks like "random" in a single window; the defender spots it by behaviour (it re-finds our channel within 0.3 s).
- **"Why not just hop fast all the time?"** Against a sweep or barrage, hopping doesn't help: they cover every channel. The right move is more power and BPSK. Naming the jammer is what picks the right move; that's why AEGIS beats the energy detector (49.2 %) by so much.
- **"What about several jammers at once?"** A follower hiding under a sweep is invisible per channel; when power and rate are maxed and loss stays high, a behaviour tracker spots it statistically and AEGIS answers both at once (keyed hopping + power + BPSK). Stacked attacks: 61–89 % (AI OFF 1–4 %). Capped at 12 live jammers.
- **"Where does the key come from?"** Each radio has its own device key; the command post signs and hands out a group key, from which HKDF-SHA256 derives per-epoch keys (hop sequence, rendezvous), rotated every 60 s; each radio encrypts with its own session key. AES-256-GCM per packet, 64-frame replay window, authenticated control frames.
- **"Latency?"** First jammed slot → first countermeasure in force: 30 ms median, 150 ms p95. Whole network on a new channel: 20 ms median, 110 ms p95, so we meet the 100 ms target at the median, not at p95. The tail is when every channel is jammed (nothing to hop to) or the AI waits to judge a stacked attack. CNN inference ~2 ms in NumPy.
- **"Where does it fail?"** Honest list: a 46 dBm sweep on every channel (51 %), stacked attacks (61–89 %), unseen patterns (78–87 %), the learning jammer (hybrid 93.3 % vs RL alone 94.9 %), and nothing yet measured on real radios.

### The six "what if" questions (Phase 8)

- **"What if the drone's battery runs out?"** Every drone has a battery model (100 Wh pack, hover power, plus radio power, so raising transmit power really costs battery). Below 25 % it flies back to the command post on its own, gets a 20 s battery swap and relaunches; the mesh reroutes around it while it is away. Below 35 % on any drone the AI limits how much extra power it uses (+6 dB instead of +12 dB). The 3D labels show each drone's battery.
- **"The CNN only knows 7 jammer types. What about an 8th?"** It can say "I don't know". Each spectrum window gets a fingerprint; if it is more than 2× further from every known class than normal, the verdict is **unknown** (2 of 3 windows must agree, so 0.1 % false alarms on known jammers). For an unknown pattern AEGIS tries safe moves one by one (keyed hopping, then power + BPSK, then survival mode), keeps the one that works and **stores it in a signature memory**. Next time the same pattern appears, it looks it up (retrieval, like RAG) and applies the saved answer straight away: 86.8 % the first time, 94.6 % the second time in our test. Demo: launch the *novel* jammer.
- **"What if a drone misses the channel-switch message?"** Every control frame is sent with a 12 dB margin, but a node can still miss one. It then sits on the old channel, notices within 30 ms that it hears nobody, and listens on a **rendezvous channel** derived from the mission key; the command post sends an authenticated beacon there every 50 ms. Typical recovery: ~50 ms. Demo: Security → *Sync loss*.
- **"What if every channel is jammed?"** No endless hopping. A fixed fallback ladder: more power → BPSK (more robust) → a 2 s test of keyed hopping → **survival mode** (BPSK with heavy error-correction, slow but alive) and hopping stops. When the jamming eases it steps back up one rung at a time. Against a 46 dBm barrage on all channels: 64.6 % → 85.3 %.
- **"Can you combine the two AIs?"** Yes: the **Hybrid** is now the AI ON default. AEGIS leads; a referee watches the last 6 s and, if delivery drops below 93 %, gives the RL agent a 4 s trial; whoever does better keeps control. Benchmark mean 95.1 % (best of all six, though within the confidence interval of AEGIS and RL); on the smart jammer 93.3 % (AEGIS alone 90.3 %, RL alone 94.9 %). The referee now also knows whether the attack is stacked, fast-changing or steady.
- **"What if the AI hallucinates or gives orders in a wrong order?"** Every AI order passes a **safety guard** before the radio sees it: it puts actions in a fixed order, removes contradictions (e.g. "hop" and "keyed hopping" together), redirects hops away from jammed or blacklisted channels, clips power to the limit, drops impossible settings, and allows at most 6 radio changes a second. After each change it watches delivery for 1 s and **undoes** the change if things got clearly worse. The live KPIs show how many orders it fixed or undid.

### Real data and the audit trail

- **"Is this only simulated data?"** The closed-loop comparison (AI OFF vs AI ON) is simulated on purpose: only a simulator can replay the identical attack for both defences. But the AI does not depend on the simulator. Its input is a 12 x 128 spectrum window, and the CNN panel can be fed from a **recorded spectrum file** instead (picker "Spectrum from" in the CNN panel, or `python -m ai.sources eval <file>`). Recordings from a HackRF (`hackrf_sweep` CSV) or any table of frequency vs power are converted with `python -m ai.sources convert-sweep / convert-wide`; the noise floor is aligned to our receiver and the band resampled onto our 128 bins. A live HackRF can stream into the same path. The two files shipped in `recordings/` are simulator captures, clearly marked as such; public measured datasets (WiFiSpectralJam on Kaggle, the RF Jamming Dataset on IEEE DataPort) are the next step.
- **"Can you show what the AI did and why, after the run?"** Press **⬇ Log** (or More → Mission log on the phone): a CSV of every AI decision with its reason and latency, every safety-guard correction, every security test and a per-second score snapshot. It is the after-action report.

Sources for the incident numbers: [Ministry of Civil Aviation via GPS World, 1,951 cases Nov 2023 - Nov 2025](https://www.gpsworld.com/iata-sounds-alarm-over-rising-gnss-interference/); [465 cases in the border region, Nov 2023 - Feb 2025 (Deccan Herald)](https://www.deccanherald.com/amp/story/india%2Fseveral-airlines-operating-aircraft-in-around-amritsar-report-gps-interference-govt-3454991).


### Review points A–J (Phase 10)

- **"Has any of this run on real radios?"** No, and we say so. Everything is simulated; GNU Radio is a software cross-check of the signal chain. We built the bridge: one radio interface the AI talks to, a bench test (link budget per channel, retune time, hop sync, injected interference, security), and a script that compares measured packet error with the simulator and gives the dB correction. Plan: two SDRs on a cabled link through attenuators, nothing radiated (docs/HARDWARE_TEST_PLAN.md).
- **"Real receivers have gain errors and AGC. Does the CNN survive that?"** We added calibration: a quiet-band reference at start-up, the radio's reported AGC gain, DC-spike removal, and a slow floor tracker that only learns from quiet bins (so it can't learn the jammer as "normal"). On a deliberately faulty receiver the CNN went from 78–91 % to 100 % correct. Channel width is the real 2.7 MHz (4 FFT bins), not the 10 MHz spacing.
- **"How do the drones agree on time for hopping?"** Beacons every second; each radio estimates its own clock drift and keeps time when beacons stop (70 µs after 2 minutes, guard is 500 µs). If the command post goes silent for 3 s, the lowest-address drone becomes time master. A rebooted radio rejoins through the rendezvous channel in about 50 ms. Without sync, clocks leave the guard in about 25 s.
- **"Are your numbers statistically meaningful?"** 10 seeds per cell; we report mean, standard deviation, 95 % confidence interval and the worst run, plus hop latency p50/p95/p99. A separate robustness run changes one condition at a time: jammer power, distance, drone speed, 4 vs 8 drones, background interference, stacked and unseen jammers (docs/ROBUSTNESS.md).
- **"Several jammers at once, or one you've never seen?"** A behaviour tracker can say several things at once: wideband, tracking, narrowband, intermittent, unknown. A follower hidden under a sweep is found statistically (our channel is consistently hotter than the rest). The response is combined (keyed hopping + power + BPSK). Two unseen patterns are tested; both are flagged unknown.
- **"Why trust the referee between AEGIS and RL?"** It now knows the situation: stacked attack, fast-changing attack, or steady. It keeps a separate scoreboard per situation and judges faster when the attack keeps changing. Smart jammer 92.9 % (AEGIS 89.0, RL 94.5); unknown jammer 93.2 % (best of the three).
- **"Is a position update as important as a command?"** No. Four classes with deadlines (command 50 ms, position 200 ms, battery 1 s, telemetry 2 s), strict priority, store-and-forward when a route is down. On identical jammed links: commands on time 87.9 % vs 65.8 % first-come-first-served, and every command delivered.
- **"One shared key? What if a drone is captured?"** Each radio has its own device key. The command post signs and wraps the group key for each radio. Sessions use a fresh salt every join, so a reboot can't reuse a nonce. A captured drone is revoked: the group key rotates and only the remaining drones get the new one. Impersonation, replay after reboot, and the captured drone's frames are all rejected.
- **"How accurate is the jammer location?"** Measured, not claimed: open field median 58 m, 95 % within 264 m, ring points the right way 87 % of the time. Inside the formation 12–116 m. It fails when the jammer is far outside the formation (about 270 m off): we show that.
- **"Is the battery model realistic?"** Radio power counts (4 W base plus transmit power), the return point depends on distance home plus a 10 % reserve, and nearly-empty drones are avoided as relays. These are modelled values, not flight logs.
- **"Doesn't encryption stop jamming?"** No. Encryption stops forged and replayed commands. Jamming is beaten by hopping, power, modulation, routing and priority.
