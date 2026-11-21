"""GNU Radio implementation of the receiver chain (SIGNAL_BACKEND=gnuradio).

Flowgraph, per 0.3 ms window:

  Stage 1, for each QPSK transmitter (ours, or a deceptive look-alike):
    vector_source_b (random bytes) -> generic_mod (the GRC "Constellation Modulator": QPSK, RRC 0.35, 40 sps)
      -> rotator_cc (move to its channel) -> fading_model (Rician, K) -> vector_sink_c

  Stage 2, the receiver:
    vector_source_c (each scaled emitter: stage-1 output or interference-engine waveform)
      + noise_source_c (thermal noise of the 80 MHz band)
      -> add_cc -> head -> stream_to_vector(128) -> fft_vcc(128, Hann, shifted)
      -> complex_to_mag_squared(128) -> vector_sink_f

The interference engine (jammer waveforms) stays in NumPy, as the build plan says. Output is
identical in shape and calibration to NumpyPhy; scripts/check_gnuradio.py compares the two.
Run from the radioconda Python. If anything here fails, sim.phy.get_phy falls back to NumPy.
"""
from __future__ import annotations

import numpy as np
from gnuradio import analog, blocks, channels, digital, fft, gr  # noqa: F401  (ImportError -> fallback)

from .phy import EmitterSpec, emitter_waveform, gate_samples
from .radio import FFTS_PER_ROW, FS, NFFT, NOISE_BAND_DBM, RRC_ALPHA, SYMBOL_RATE, WINDOW_ROWS, WINDOW_SAMPLES, dbm_to_mw


class GnuRadioPhy:
    name = "gnuradio"

    def __init__(self) -> None:
        self.sps = int(round(FS / SYMBOL_RATE))
        self.window = list(np.hanning(NFFT))
        self.wnorm = float(np.sum(np.square(self.window)) * NFFT)
        self._qpsk = digital.constellation_qpsk().base()
        # smoke test so a broken install fails here (and falls back) rather than mid-demo
        self.synthesize([EmitterSpec("qpsk", -70.0, 0.0)], np.random.default_rng(0))

    def _qpsk_branch(self, e: EmitterSpec, rng: np.random.Generator) -> np.ndarray:
        n = WINDOW_SAMPLES
        n_bytes = n // (self.sps * 4) + 16
        tb = gr.top_block("aegis_qpsk_tx")
        src = blocks.vector_source_b(rng.integers(0, 256, n_bytes).astype(int).tolist(), False)
        mod = digital.generic_mod(self._qpsk, False, self.sps, True, RRC_ALPHA, False, False)
        rot = blocks.rotator_cc(2 * np.pi * e.center_hz / FS)
        head = blocks.head(gr.sizeof_gr_complex, n)
        sink = blocks.vector_sink_c()
        if e.k_db is not None:
            fade = channels.fading_model(8, 1e-6, True, float(10 ** (e.k_db / 10)), int(rng.integers(1, 2**31 - 1)))
            tb.connect(src, mod, rot, fade, head, sink)
        else:
            tb.connect(src, mod, rot, head, sink)
        tb.run()
        y = np.asarray(sink.data(), dtype=complex)
        if len(y) < n:
            y = np.pad(y, (0, n - len(y)))
        y = y[:n] / np.sqrt(np.mean(np.abs(y) ** 2) + 1e-30)
        return y * gate_samples(e.gate, n)

    def synthesize(self, emitters: list[EmitterSpec], rng: np.random.Generator, t0: float = 0.0) -> np.ndarray:
        n = WINDOW_SAMPLES
        tb = gr.top_block("aegis_rx")
        noise = analog.noise_source_c(analog.GR_GAUSSIAN, float(np.sqrt(dbm_to_mw(NOISE_BAND_DBM))),
                                      int(rng.integers(1, 2**31 - 1)))
        adder = blocks.add_cc()
        tb.connect(noise, (adder, 0))
        for i, e in enumerate(emitters, start=1):
            if e.kind == "qpsk":
                x = self._qpsk_branch(e, rng)
            else:
                x = emitter_waveform(e, rng, n, t0)   # interference engine (NumPy)
            x = x * np.sqrt(dbm_to_mw(e.power_dbm))
            tb.connect(blocks.vector_source_c(x.astype(np.complex64).tolist(), False), (adder, i))
        head = blocks.head(gr.sizeof_gr_complex, n)
        s2v = blocks.stream_to_vector(gr.sizeof_gr_complex, NFFT)
        f = fft.fft_vcc(NFFT, True, self.window, True, 1)
        mag = blocks.complex_to_mag_squared(NFFT)
        sink = blocks.vector_sink_f(NFFT)
        tb.connect(adder, head, s2v, f, mag, sink)
        tb.run()
        p = np.asarray(sink.data(), dtype=float).reshape(-1, NFFT)[: WINDOW_ROWS * FFTS_PER_ROW]
        p = p.reshape(WINDOW_ROWS, FFTS_PER_ROW, NFFT).mean(axis=1) / self.wnorm
        return 10 * np.log10(np.maximum(p, 1e-30))
