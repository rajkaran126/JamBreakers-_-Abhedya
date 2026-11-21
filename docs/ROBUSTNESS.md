# Robustness: does the result hold when conditions change?

`python -m sim.robustness --seeds 8 --duration 12` (2026-11-21 13:22). AI OFF (fixed hopping) vs AI ON (hybrid),
identical seeded runs, one condition changed at a time, 8 seeds per cell, 12 s of attack, 1136 runs in total.
Every run starts with an empty unknown-jammer memory. Simulated, not measured on hardware.

For every cell: mean ± standard deviation over seeds, the 95 % confidence interval of the mean
(t distribution, 7 degrees of freedom) and the worst single run.

## Overall

| | Runs | Mean | SD | 95 % CI | Worst run |
|---|---|---|---|---|---|
| AI OFF | 568 | 28.5 % | 24.0 | 26.5–30.5 % | 0.9 % |
| **AI ON** | 568 | **91.7 %** | 9.8 | 90.9–92.5 % | 46.4 % |

AI ON beats AI OFF in every one of the 71 cells, by 11 to 98 points.

## What changes the result, and what doesn't

- **Drone speed (0.5×–2×), network size (4 vs 8 drones) and background Wi-Fi-like interference** move AI ON by at
  most about 2 points (random jammer with background: 97.4 % with one bad run at 88.4 %).
- **Jammer power matters most.** At 46 dBm a sweep covers every channel so hard that nothing escapes: AI ON
  50.7 % (worst run 46.4 %), barrage 64.9 %. AI OFF gets 2–5 %. This is our weakest single-jammer case.
- **Distance:** a far-away jammer helps AI OFF a lot (barrage 24 → 50 %), AI ON was already near the ceiling.
- **Stacked attacks remain the hard case:** 61–89 %. Random + follower is the worst and the most variable
  (61.0 ± 9.8 %, worst run 52.5 %).
- **Unseen jammers:** the comb pattern 83.9 %, the staircase 77.8 % (worst run 75.5 %), against 9–15 % for AI OFF.
  Both are flagged unknown; neither is in the CNN's training data.

## Latency (AI ON)

Two clocks, both start at the first jammed slot:

- **Response latency**: until the first countermeasure of any kind is in force across the network.
  p50 30 ms, p95 150 ms, p99 550 ms (5495 episodes).
- **Hop latency**: until the whole network is on a new channel. All runs: p50 30 ms, p95 170 ms,
  p99 506.2 ms. Single jammer at any power, distance, speed or size: p50 30, p95 120, p99 300 ms.

| Group | p50 | p95 | p99 |
|---|---|---|---|
| background interference | 20 ms | 110 ms | 220 ms |
| drone speed | 30 ms | 100 ms | 180 ms |
| jammer distance | 20 ms | 116 ms | 285.2 ms |
| jammer power | 30 ms | 250 ms | 942 ms |
| network size | 30 ms | 110 ms | 213.3 ms |
| stacked | 80 ms | 660 ms | 1520 ms |
| unseen | 30 ms | 94.5 ms | 120 ms |

**The 100 ms target is met at the median, not at p95.** The tail has two causes, both visible in the table:
the AI has run out of moves (46 dBm on every channel: nothing to hop to, it goes to survival mode and the clock
keeps running), or under stacked attacks it deliberately waits for a judging window before the next move.
Against single jammers at normal power, nearly all episodes are handled in 20–100 ms, with occasional
150–290 ms outliers against the smart jammer.

## Results by condition

### Jammer power

| Condition | AI OFF mean ± SD | AI OFF worst | **AI ON mean ± SD** | AI ON 95 % CI | AI ON worst |
|---|---|---|---|---|---|
| barrage, 30 dBm | 88.9 ± 0.8 | 87.5 | **99.8 ± 0.0** | 99.8–99.9 | 99.8 |
| barrage, default | 23.9 ± 0.4 | 22.9 | **94.9 ± 0.7** | 94.3–95.6 | 94.0 |
| barrage, 46 dBm | 5.4 ± 0.4 | 4.8 | **64.9 ± 2.9** | 62.4–67.3 | 62.5 |
| random, 30 dBm | 76.1 ± 0.7 | 74.7 | **98.8 ± 0.9** | 98.0–99.6 | 97.3 |
| random, default | 64.7 ± 0.5 | 64.2 | **98.7 ± 1.0** | 97.8–99.5 | 96.2 |
| random, 46 dBm | 62.5 ± 0.2 | 62.2 | **98.1 ± 1.2** | 97.1–99.2 | 96.1 |
| sweep, 30 dBm | 72.7 ± 1.1 | 71.2 | **99.6 ± 0.1** | 99.5–99.7 | 99.3 |
| sweep, default | 10.5 ± 0.2 | 10.0 | **84.8 ± 1.5** | 83.5–86.1 | 83.1 |
| sweep, 46 dBm | 2.0 ± 0.1 | 1.8 | **50.7 ± 5.1** | 46.3–55.1 | 46.4 |
| follower, 30 dBm | 12.0 ± 0.5 | 11.2 | **99.7 ± 0.0** | 99.7–99.7 | 99.7 |
| follower, default | 4.9 ± 0.2 | 4.6 | **99.7 ± 0.0** | 99.7–99.7 | 99.7 |
| follower, 46 dBm | 2.1 ± 0.0 | 2.1 | **99.6 ± 0.0** | 99.6–99.7 | 99.6 |
| smart, 30 dBm | 39.8 ± 0.4 | 39.2 | **93.3 ± 2.7** | 90.9–95.6 | 88.9 |
| smart, default | 33.4 ± 0.2 | 33.1 | **91.8 ± 0.8** | 91.1–92.5 | 90.5 |
| smart, 46 dBm | 32.2 ± 0.0 | 32.2 | **87.5 ± 0.7** | 86.9–88.2 | 86.6 |

### Jammer distance

| Condition | AI OFF mean ± SD | AI OFF worst | **AI ON mean ± SD** | AI ON 95 % CI | AI ON worst |
|---|---|---|---|---|---|
| barrage, close | 15.1 ± 0.4 | 14.5 | **95.9 ± 0.5** | 95.5–96.3 | 95.6 |
| barrage, default | 23.9 ± 0.4 | 22.9 | **94.9 ± 0.7** | 94.3–95.6 | 94.0 |
| barrage, far (800, 650) | 49.7 ± 0.8 | 48.6 | **93.6 ± 0.5** | 93.3–94.0 | 93.1 |
| random, close | 63.8 ± 0.4 | 63.5 | **98.7 ± 1.0** | 97.8–99.5 | 96.3 |
| random, default | 64.7 ± 0.5 | 64.2 | **98.7 ± 1.0** | 97.8–99.5 | 96.2 |
| random, far (800, 650) | 76.0 ± 0.3 | 75.5 | **98.9 ± 0.8** | 98.2–99.6 | 97.1 |
| sweep, close | 5.6 ± 0.5 | 5.1 | **83.9 ± 1.6** | 82.5–85.3 | 82.3 |
| sweep, default | 10.5 ± 0.2 | 10.0 | **84.8 ± 1.5** | 83.5–86.1 | 83.1 |
| sweep, far (800, 650) | 40.0 ± 0.6 | 39.1 | **87.5 ± 1.3** | 86.5–88.6 | 86.2 |
| follower, close | 3.8 ± 0.2 | 3.5 | **99.7 ± 0.0** | 99.7–99.7 | 99.7 |
| follower, default | 4.9 ± 0.2 | 4.6 | **99.7 ± 0.0** | 99.7–99.7 | 99.7 |
| follower, far (800, 650) | 34.4 ± 0.5 | 33.6 | **99.7 ± 0.1** | 99.7–99.8 | 99.6 |
| smart, close | 32.8 ± 0.0 | 32.8 | **91.7 ± 0.9** | 90.9–92.5 | 90.4 |
| smart, default | 33.4 ± 0.2 | 33.1 | **91.8 ± 0.8** | 91.1–92.5 | 90.5 |
| smart, far (800, 650) | 51.9 ± 0.4 | 51.1 | **93.5 ± 1.5** | 92.1–94.8 | 91.1 |

### Drone speed

| Condition | AI OFF mean ± SD | AI OFF worst | **AI ON mean ± SD** | AI ON 95 % CI | AI ON worst |
|---|---|---|---|---|---|
| barrage, 0.5x | 21.7 ± 0.4 | 21.2 | **95.1 ± 0.7** | 94.6–95.7 | 94.2 |
| barrage, 1x | 23.9 ± 0.4 | 22.9 | **94.9 ± 0.7** | 94.3–95.6 | 94.0 |
| barrage, 2x | 24.2 ± 0.3 | 23.8 | **94.4 ± 0.7** | 93.8–95.0 | 93.5 |
| random, 0.5x | 64.4 ± 0.5 | 63.8 | **98.6 ± 1.0** | 97.8–99.4 | 96.2 |
| random, 1x | 64.7 ± 0.5 | 64.2 | **98.7 ± 1.0** | 97.8–99.5 | 96.2 |
| random, 2x | 64.7 ± 0.5 | 64.1 | **98.8 ± 1.0** | 97.9–99.6 | 96.3 |
| sweep, 0.5x | 8.9 ± 0.3 | 8.3 | **85.1 ± 1.6** | 83.7–86.5 | 83.3 |
| sweep, 1x | 10.5 ± 0.2 | 10.0 | **84.8 ± 1.5** | 83.5–86.1 | 83.1 |
| sweep, 2x | 11.0 ± 0.4 | 10.4 | **82.8 ± 1.7** | 81.3–84.3 | 80.6 |
| follower, 0.5x | 4.3 ± 0.2 | 4.1 | **99.7 ± 0.0** | 99.7–99.7 | 99.7 |
| follower, 1x | 4.9 ± 0.2 | 4.6 | **99.7 ± 0.0** | 99.7–99.7 | 99.7 |
| follower, 2x | 5.1 ± 0.2 | 4.7 | **99.7 ± 0.0** | 99.7–99.7 | 99.7 |
| smart, 0.5x | 33.0 ± 0.1 | 32.9 | **91.9 ± 1.0** | 91.0–92.8 | 90.4 |
| smart, 1x | 33.4 ± 0.2 | 33.1 | **91.8 ± 0.8** | 91.1–92.5 | 90.5 |
| smart, 2x | 33.4 ± 0.2 | 33.2 | **91.2 ± 1.6** | 89.7–92.6 | 88.4 |

### Network size

| Condition | AI OFF mean ± SD | AI OFF worst | **AI ON mean ± SD** | AI ON 95 % CI | AI ON worst |
|---|---|---|---|---|---|
| barrage, 4 drones | 23.9 ± 0.4 | 22.9 | **94.9 ± 0.7** | 94.3–95.6 | 94.0 |
| barrage, 8 drones | 21.9 ± 0.5 | 21.3 | **94.8 ± 0.3** | 94.5–95.0 | 94.4 |
| random, 4 drones | 64.7 ± 0.5 | 64.2 | **98.7 ± 1.0** | 97.8–99.5 | 96.2 |
| random, 8 drones | 64.1 ± 0.1 | 64.0 | **97.7 ± 1.7** | 96.2–99.2 | 95.2 |
| sweep, 4 drones | 10.5 ± 0.2 | 10.0 | **84.8 ± 1.5** | 83.5–86.1 | 83.1 |
| sweep, 8 drones | 8.9 ± 0.2 | 8.4 | **83.9 ± 0.8** | 83.2–84.5 | 83.0 |
| follower, 4 drones | 4.9 ± 0.2 | 4.6 | **99.7 ± 0.0** | 99.7–99.7 | 99.7 |
| follower, 8 drones | 4.2 ± 0.1 | 4.1 | **99.6 ± 0.0** | 99.6–99.7 | 99.6 |
| smart, 4 drones | 33.4 ± 0.2 | 33.1 | **91.8 ± 0.8** | 91.1–92.5 | 90.5 |
| smart, 8 drones | 33.0 ± 0.1 | 32.8 | **91.0 ± 1.4** | 89.8–92.2 | 88.9 |

### Background interference

| Condition | AI OFF mean ± SD | AI OFF worst | **AI ON mean ± SD** | AI ON 95 % CI | AI ON worst |
|---|---|---|---|---|---|
| barrage, no background | 23.9 ± 0.4 | 22.9 | **94.9 ± 0.7** | 94.3–95.6 | 94.0 |
| barrage, with background | 23.6 ± 0.6 | 22.8 | **93.8 ± 1.0** | 92.9–94.6 | 92.3 |
| random, no background | 64.7 ± 0.5 | 64.2 | **98.7 ± 1.0** | 97.8–99.5 | 96.2 |
| random, with background | 62.8 ± 0.8 | 61.9 | **97.4 ± 3.7** | 94.1–100.0 | 88.4 |
| sweep, no background | 10.5 ± 0.2 | 10.0 | **84.8 ± 1.5** | 83.5–86.1 | 83.1 |
| sweep, with background | 10.3 ± 0.6 | 9.2 | **83.5 ± 2.0** | 81.8–85.1 | 80.5 |
| follower, no background | 4.9 ± 0.2 | 4.6 | **99.7 ± 0.0** | 99.7–99.7 | 99.7 |
| follower, with background | 4.8 ± 0.4 | 4.2 | **98.3 ± 0.5** | 97.9–98.7 | 97.5 |
| smart, no background | 33.4 ± 0.2 | 33.1 | **91.8 ± 0.8** | 91.1–92.5 | 90.5 |
| smart, with background | 32.5 ± 0.4 | 32.0 | **92.0 ± 0.9** | 91.2–92.8 | 90.7 |

### Stacked

| Condition | AI OFF mean ± SD | AI OFF worst | **AI ON mean ± SD** | AI ON 95 % CI | AI ON worst |
|---|---|---|---|---|---|
| sweep + follower | 2.4 ± 0.1 | 2.2 | **74.1 ± 4.5** | 70.3–78.0 | 66.7 |
| sweep + follower + smart | 1.1 ± 0.1 | 0.9 | **71.8 ± 2.9** | 69.4–74.3 | 67.2 |
| random + follower | 3.8 ± 0.2 | 3.6 | **61.0 ± 9.8** | 52.5–69.6 | 52.5 |
| barrage + follower | 3.6 ± 0.2 | 3.3 | **88.6 ± 4.3** | 84.8–92.3 | 84.2 |

### Unseen

| Condition | AI OFF mean ± SD | AI OFF worst | **AI ON mean ± SD** | AI ON 95 % CI | AI ON worst |
|---|---|---|---|---|---|
| novel | 15.2 ± 0.3 | 14.8 | **83.9 ± 1.1** | 82.9–84.9 | 82.8 |
| novel_staircase | 9.5 ± 0.2 | 9.2 | **77.8 ± 1.8** | 76.2–79.3 | 75.5 |
