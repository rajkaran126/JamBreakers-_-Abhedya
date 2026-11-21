# Hardware-in-the-loop test plan

**Status: not yet run on hardware.** Every number elsewhere in this repository comes from the simulator.
This plan is how we find out whether the simulator is right, and by how much it is wrong.

## What stays the same, what changes

The AI, the defender, the safety guard, AES-GCM framing, key management, keyed hopping and time sync all
talk to one radio interface (`hil/radio_backend.py`): `tune`, `set_tx_power`, `set_modulation`, `send`,
`receive`, `sweep`, `gain_db`. Today that interface is backed by the simulator (`SimBackend`). On the
bench it is backed by an SDR (`SdrBackend`, a documented wiring guide that refuses to run until it has
been built and checked). Only the backend changes.

Encryption does **not** stop jamming. It stops forged or replayed commands. Jamming is handled by hopping,
power, modulation and routing. The bench tests both, separately.

## Setup (authorised, contained)

- Two SDRs (HackRF One or ADALM-Pluto), each on a laptop running the same code.
- **Cabled link**: TX → SMA cable → step attenuator (0–110 dB) → combiner → RX. A second port of the
  combiner takes the interference source (a third SDR or a signal generator), also through an attenuator.
  Nothing radiates. If a radiated test is ever needed, it is done in a shielded box or under the college's
  authorised lab arrangement, never in the open 2.4 GHz band.
- Fixed receive gain (AGC off) so `gain_db` is known; calibration as in `ai/calibration.py`.

## Tests

| # | Test | Measure | Pass if |
|---|---|---|---|
| 1 | Link budget | PER and RSSI at attenuator steps 96–110 dB, 300+ frames each | measured PER curve within 3 dB of the simulator's after one fixed implementation-loss offset |
| 2 | Per channel | test 1 on all 8 channels | spread between channels under 3 dB (otherwise model it per channel) |
| 3 | Retune time | time from `tune()` to first good frame | under the slot guard (0.5 ms); otherwise widen the guard and re-run the benchmark |
| 4 | Hop sync | both ends follow the keyed sequence for 10,000 slots; then with a deliberate clock offset | ≥ 99 % same-channel slots synced; the offset at which it breaks matches `GUARD_S` |
| 5 | Time sync | clock error between the two laptops with and without beacons, over 10 min | error stays inside the guard with beacons |
| 6 | Interference | injected noise on one channel through the combiner | PER rises on that channel only; the AI blacklists it; the CNN verdict on the real sweep is recorded |
| 7 | Security | tampered, replayed and wrong-key frames injected into the RX path | all rejected, 0 accepted |

## Comparing with the simulator

```
python -m hil.bench_test --backend sim --out results/bench_sim.csv    # prediction (works today)
python -m hil.bench_test --backend sdr --out results/bench_sdr.csv    # measurement (on the bench)
python -m hil.compare results/bench_sdr.csv
```

`hil.compare` finds the single SINR offset (implementation loss) that best aligns measured and predicted
PER and reports the error left after it. That offset goes back into `sim/radio.py`, then the benchmark is
re-run. Dry run on the simulator backend today: 48 link-budget rows, RMS PER error 0.011 at 0 dB offset
(as expected: it is comparing the model with itself, which only proves the scripts work).

## What we will report

Measured vs predicted PER curves, retune time, sync error, and how many benchmark points move once the
measured offset is applied. If the real radio is much worse than the model, we say so.
