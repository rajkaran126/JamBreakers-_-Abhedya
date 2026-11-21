# sim/ — radio world (owner: Kodandarama)

| File | What |
|---|---|
| `radio.py` | Band plan, link budget, path loss, Rician fading, coded BER → packet delivery, obstacle ray test |
| `phy.py` | Emitter descriptions + NumPy receiver chain → 12×128 spectrogram windows (0.3 ms) |
| `phy_gnuradio.py` | The same chain as a GNU Radio flowgraph (`SIGNAL_BACKEND=gnuradio`) |
| `jammers.py` | Interference engine: barrage, random, sweep, reactive, deceptive, accidental, follower |
| `hopping.py` | Fixed FHSS pattern, HMAC keyed hop sequence, key-derived rendezvous channel |
| `network.py` | Nodes and motion, obstacles, per-slot SINR and packet draws, widest-path mesh routing |
| `defenders.py` | Defender interface + baselines (none, fixed_hopping, energy) and the hop guard |
| `world.py` | SimWorld (one world, 10 ms slots, control plane, KPIs, messages) and SimArena (server World, twins) |
| `experiment.py` | Headless single runs for tests and the benchmark |

Defenders see only measurements (loss, per-channel energy, spectrogram on request), never the jammer list.
