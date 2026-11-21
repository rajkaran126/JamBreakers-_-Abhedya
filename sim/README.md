# sim/ — radio world (Phase 1 · owner: Kodandarama)

Will hold the real simulation that replaces `backend/fake_world.py`:
GNU Radio flowgraph (QPSK, 2.4 GHz, path loss, Rician fading, jammer injection, 128-bin FFT),
a NumPy fallback of the same blocks (`SIGNAL_BACKEND=gnuradio|numpy`), the 7 jammers, mesh routing,
FHSS and energy-detector baselines, seeded replay.

Contract: expose `sim.world.SimArena(settings)` implementing `backend/world_api.World`
(`hello_info()`, `step(dt)`, `handle(cmd)`). Start the server with `AEGIS_WORLD=sim`.
Every message must validate against `shared/schema.json` (the tests check this).
