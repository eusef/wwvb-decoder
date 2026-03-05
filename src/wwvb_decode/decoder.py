"""Pulse width measurement and symbol classification for WWVB.

Two decoder implementations:
  PulseDecoder        - edge-based threshold crossing (original)
  CorrelationDecoder  - cross-correlation with templates (inspired by WWVB_15.ino)
"""

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class Pulse:
    """A single decoded WWVB pulse."""

    start_time: float  # seconds since stream start
    duration_ms: float  # pulse width in milliseconds
    symbol: str  # "0", "1", "M", or "?"
    confidence: float = 0.0  # 0.0-1.0 classification confidence


class PulseDecoder:
    """Convert normalized envelope signal into WWVB symbols.

    Uses hysteresis thresholding to detect low-power periods.
    Classifies pulse widths:
      100-350 ms -> "0" (binary zero)
      350-650 ms -> "1" (binary one)
      650-900 ms -> "M" (position marker)
      outside    -> "?" (error/noise)
    """

    def __init__(self, threshold: float = 0.5, hysteresis: float = 0.10,
                 debounce_ms: float = 100.0):
        self.threshold_high = threshold + hysteresis  # Rising edge threshold
        self.threshold_low = threshold - hysteresis  # Falling edge threshold
        self._state = "HIGH"  # "HIGH", "LOW", or "CONFIRMING"
        self._low_start_sample = 0
        self._sample_count = 0

        # Rising-edge debounce: after signal crosses above threshold_high,
        # require it to STAY above for debounce_ms before finalizing the
        # pulse end. If it drops back below threshold_low during this
        # window, it was a noise spike - return to LOW and keep measuring.
        # This is the primary defense against noise splitting markers.
        self._debounce_ms = debounce_ms
        self._confirm_start_sample = 0  # When CONFIRMING state began

        # Refractory period: after a pulse STARTS (falling edge), ignore new
        # falling edges for this many ms. WWVB sends exactly 1 pulse/sec,
        # so consecutive falling edges are ~1000ms apart. A 900ms refractory
        # from the falling edge blocks spurious noise pulses while allowing
        # the next valid pulse (which arrives at ~1000ms).
        # Measured from falling edge, not rising edge, because the gap
        # between rising edge and next falling edge varies: 800ms after "0",
        # 500ms after "1", only 200ms after "M".
        self._refractory_ms = 900.0
        self._refractory_until_sample = 0  # No refractory active initially

        # Pulse width classification boundaries (ms)
        # Widened from spec values to handle noisy/weak signals where
        # envelope edges are detected early, shortening apparent pulse widths.
        # Theoretical: 0=200ms, 1=500ms, M=800ms
        # Observed weak signal: 0~167ms, 1~450ms, M~732ms
        self._min_pulse_ms = 60   # Reject shorter than this
        self._max_pulse_ms = 1100  # Reject longer than this
        self._zero_max_ms = 330   # 0: ~60-330ms
        self._one_max_ms = 580    # 1: ~330-580ms
        self._marker_max_ms = 950 # M: ~580-950ms

        # Running pulse width stats
        self._pulse_counts: dict[str, int] = {"0": 0, "1": 0, "M": 0, "?": 0}
        self._pulse_sums: dict[str, float] = {"0": 0.0, "1": 0.0, "M": 0.0}

    def process(self, envelope: np.ndarray, sample_rate: float) -> list[Pulse]:
        """Detect pulses from normalized envelope samples.

        Uses a 3-state machine:
          HIGH       - full power, waiting for falling edge
          LOW        - reduced power (pulse in progress), measuring duration
          CONFIRMING - signal crossed above threshold, waiting debounce_ms
                       to confirm it's a real rising edge (not noise)

        Args:
            envelope: float64 normalized envelope (0.0-1.0) at sample_rate
            sample_rate: samples per second (typically 1000 Hz after decimation)

        Returns:
            List of Pulse objects detected in this chunk
        """
        pulses = []
        ms_per_sample = 1000.0 / sample_rate

        refractory_samples = self._refractory_ms / ms_per_sample
        debounce_samples = self._debounce_ms / ms_per_sample

        for sample in envelope:
            if self._state == "HIGH":
                # Looking for falling edge (HIGH -> LOW)
                # But only if refractory period has elapsed
                if sample < self.threshold_low:
                    if self._sample_count >= self._refractory_until_sample:
                        self._state = "LOW"
                        self._low_start_sample = self._sample_count
                        # Start refractory from this falling edge
                        self._refractory_until_sample = (
                            self._sample_count + int(refractory_samples)
                        )
                    # else: still in refractory, ignore this dip

            elif self._state == "LOW":
                # Looking for rising edge (LOW -> HIGH)
                if sample > self.threshold_high:
                    # Don't finalize yet - enter CONFIRMING state
                    self._state = "CONFIRMING"
                    self._confirm_start_sample = self._sample_count
                else:
                    # Check for timeout (missed rising edge)
                    duration_samples = self._sample_count - self._low_start_sample
                    duration_ms = duration_samples * ms_per_sample
                    if duration_ms > self._max_pulse_ms:
                        start_time = self._low_start_sample / sample_rate
                        logger.debug(
                            f"Pulse timeout at {duration_ms:.0f}ms, "
                            f"emitting '?' at t={start_time:.3f}s"
                        )
                        pulse = Pulse(
                            start_time=start_time,
                            duration_ms=duration_ms,
                            symbol="?",
                        )
                        pulses.append(pulse)
                        self._pulse_counts["?"] = (
                            self._pulse_counts.get("?", 0) + 1
                        )
                        self._state = "HIGH"

            elif self._state == "CONFIRMING":
                # Signal crossed above threshold - is it real or noise?
                if sample < self.threshold_low:
                    # Dropped back below threshold - it was a noise spike.
                    # Return to LOW, pulse is still in progress.
                    self._state = "LOW"
                    logger.debug(
                        f"Debounce rejected false rising edge at "
                        f"t={self._sample_count / sample_rate:.3f}s"
                    )
                elif (self._sample_count - self._confirm_start_sample) >= debounce_samples:
                    # Stayed above threshold for debounce period - real rising edge.
                    # Measure pulse from low_start to where it first crossed high
                    # (confirm_start), not current sample, for accurate width.
                    duration_samples = self._confirm_start_sample - self._low_start_sample
                    duration_ms = duration_samples * ms_per_sample
                    start_time = self._low_start_sample / sample_rate

                    symbol = self._classify(duration_ms)

                    if symbol != "_":
                        pulse = Pulse(
                            start_time=start_time,
                            duration_ms=duration_ms,
                            symbol=symbol,
                        )
                        pulses.append(pulse)

                        self._pulse_counts[symbol] = (
                            self._pulse_counts.get(symbol, 0) + 1
                        )
                        if symbol in self._pulse_sums:
                            self._pulse_sums[symbol] += duration_ms

                        logger.debug(
                            f"Pulse: {duration_ms:.1f}ms -> {symbol} "
                            f"at t={start_time:.3f}s"
                        )

                    self._state = "HIGH"
                # else: still confirming, wait more samples

            self._sample_count += 1

        return pulses

    def _classify(self, duration_ms: float) -> str:
        """Classify a pulse by its duration.

        Returns:
            "0", "1", "M", "?", or "_" (rejected - too short/long)
        """
        if duration_ms < self._min_pulse_ms:
            return "_"  # Too short, noise
        if duration_ms > self._max_pulse_ms:
            return "_"  # Too long, missed edge

        if duration_ms < self._zero_max_ms:
            return "0"
        elif duration_ms < self._one_max_ms:
            return "1"
        elif duration_ms <= self._marker_max_ms:
            return "M"
        else:
            return "?"

    @property
    def avg_pulse_widths(self) -> dict[str, float]:
        """Running average pulse widths for each symbol type."""
        result = {}
        for sym in ("0", "1", "M"):
            count = self._pulse_counts.get(sym, 0)
            if count > 0:
                result[sym] = self._pulse_sums[sym] / count
            else:
                result[sym] = 0.0
        return result

    @property
    def total_pulses(self) -> int:
        return sum(self._pulse_counts.values())

    def reset(self) -> None:
        """Reset decoder state (for resync)."""
        self._state = "HIGH"
        self._low_start_sample = self._sample_count


class CorrelationDecoder:
    """Classify WWVB symbols using cross-correlation with templates.

    Instead of detecting edges and measuring pulse widths, this decoder
    accumulates 1-second windows of envelope data and correlates each
    window against three ideal templates (0, 1, M). The best-matching
    template determines the symbol. A confidence threshold rejects
    ambiguous windows as "?".

    Inspired by the Arduino WWVB_15 implementation which uses unweighted
    cross-correlation at 50 Hz. This version uses continuous dot-product
    correlation at 1000 Hz for better SNR on weak SDR signals.

    Three-phase operation:
      Alignment: Slide a window across the first few seconds of data to
                 find the offset where correlation peaks. This aligns
                 the 1-second windows with actual WWVB second boundaries.
      Pre-sync:  Classify aligned windows, watch for two consecutive M
      Post-sync: Emit aligned Pulse objects, one per second
    """

    # Template durations in ms (= samples at 1000 Hz)
    PULSE_0_MS = 200
    PULSE_1_MS = 500
    PULSE_M_MS = 800
    WINDOW_MS = 1000

    # Alignment: scan this many seconds of data to find the boundary
    _ALIGN_SECONDS = 3

    def __init__(
        self,
        sample_rate: float = 1000.0,
        min_confidence: float = 0.5,
        lpf_cutoff: float = 5.0,
    ):
        self._sample_rate = sample_rate
        self._min_confidence = min_confidence
        self._window_size = int(sample_rate * self.WINDOW_MS / 1000)

        # Build matched-filter templates: ideal square pulses passed
        # through the same Butterworth LPF used by the envelope detector.
        # This ensures templates have the same edge rounding as real data,
        # maximizing cosine similarity for correct matches.
        self._templates = {}
        self._build_matched_templates(sample_rate, lpf_cutoff)

        # State
        self._buffer = np.array([], dtype=np.float64)
        self._sample_count = 0
        self._aligned = False  # Have we found the second boundary?
        self._synced = False   # Have we found two consecutive M?
        self._last_symbol = ""
        self._consecutive_markers = 0

        # Stats (match PulseDecoder interface)
        self._pulse_counts: dict[str, int] = {"0": 0, "1": 0, "M": 0, "?": 0}
        self._pulse_sums: dict[str, float] = {"0": 0.0, "1": 0.0, "M": 0.0}

    def _build_matched_templates(
        self, sample_rate: float, lpf_cutoff: float
    ) -> None:
        """Build templates by filtering ideal square pulses through the LPF.

        Uses CAUSAL filtering (sosfilt) to match the real envelope detector
        pipeline. The envelope detector applies a forward-only Butterworth
        filter, which introduces phase delay. Templates must have this same
        delay or the cosine similarity drops significantly (e.g., 0.56
        instead of 1.0 for a perfect signal at 5 Hz cutoff).

        Multiple copies of the ideal pulse are filtered to let the causal
        filter reach steady state, then a late copy is extracted.
        """
        from scipy.signal import butter, sosfilt

        # Design the same filter as envelope.py but at the decoder's rate
        nyquist = sample_rate / 2.0
        if lpf_cutoff >= nyquist:
            # Filter cutoff above Nyquist: use sharp templates (no filtering)
            for sym, pulse_ms in [("0", self.PULSE_0_MS),
                                   ("1", self.PULSE_1_MS),
                                   ("M", self.PULSE_M_MS)]:
                pulse_samples = int(sample_rate * pulse_ms / 1000)
                gap_samples = self._window_size - pulse_samples
                t = np.concatenate([
                    np.zeros(pulse_samples),
                    np.ones(gap_samples),
                ])
                t = t - np.mean(t)
                self._templates[sym] = t
            return

        sos = butter(4, lpf_cutoff / nyquist, btype="low", output="sos")

        for sym, pulse_ms in [("0", self.PULSE_0_MS),
                               ("1", self.PULSE_1_MS),
                               ("M", self.PULSE_M_MS)]:
            pulse_samples = int(sample_rate * pulse_ms / 1000)
            gap_samples = self._window_size - pulse_samples

            # Create 5 copies so causal filter reaches steady state,
            # then extract the 4th copy (well past startup transient)
            one_sec = np.concatenate([
                np.zeros(pulse_samples),    # LOW during pulse
                np.ones(gap_samples),       # HIGH during gap
            ])
            padded = np.tile(one_sec, 5)
            filtered = sosfilt(sos, padded)

            # Extract the 4th second (index 3, past transient)
            start = 3 * self._window_size
            t = filtered[start : start + self._window_size]

            # Zero-mean
            t = t - np.mean(t)
            self._templates[sym] = t

    def process(self, envelope: np.ndarray, sample_rate: float) -> list[Pulse]:
        """Process envelope chunk, return classified pulses.

        Args:
            envelope: float64 normalized envelope (0.0-1.0)
            sample_rate: samples per second (typically 1000 Hz)

        Returns:
            List of Pulse objects (one per complete 1-second window)
        """
        pulses: list[Pulse] = []
        self._buffer = np.concatenate([self._buffer, envelope])

        # Phase 0: Alignment. Accumulate enough data, then find the
        # offset within the first second where correlation peaks.
        if not self._aligned:
            needed = int(self._ALIGN_SECONDS * self._window_size)
            if len(self._buffer) < needed:
                return pulses  # Keep accumulating

            offset = self._find_alignment(self._buffer[:needed])
            # Discard samples before the alignment offset
            self._buffer = self._buffer[offset:]
            self._sample_count = offset
            self._aligned = True
            logger.info(
                f"Correlation decoder: aligned at offset {offset} samples "
                f"({offset / sample_rate * 1000:.0f}ms)"
            )

        # Process aligned 1-second windows
        while len(self._buffer) >= self._window_size:
            window = self._buffer[:self._window_size]
            self._buffer = self._buffer[self._window_size:]

            symbol, confidence = self._classify(window)
            start_time = self._sample_count / sample_rate
            self._sample_count += self._window_size

            logger.debug(
                f"Corr: {symbol} (conf={confidence:.2f}) "
                f"at t={start_time:.3f}s"
            )

            if not self._synced:
                # Pre-sync: look for two consecutive markers
                if symbol == "M":
                    self._consecutive_markers += 1
                    if self._consecutive_markers >= 2:
                        self._synced = True
                        logger.info("Correlation decoder: frame sync acquired")
                        # Emit the second M as position 0 of the new frame
                        pulse = Pulse(
                            start_time=start_time,
                            duration_ms=float(self.WINDOW_MS),
                            symbol="M",
                            confidence=confidence,
                        )
                        pulses.append(pulse)
                        self._update_stats("M")
                else:
                    self._consecutive_markers = 0
                    # Emit pre-sync symbols so the FrameAssembler sees
                    # non-M symbols too (needed to reset consecutive count)
            else:
                # Post-sync: emit every classified symbol
                pulse = Pulse(
                    start_time=start_time,
                    duration_ms=float(self.WINDOW_MS),
                    symbol=symbol,
                    confidence=confidence,
                )
                pulses.append(pulse)
                self._update_stats(symbol)

        return pulses

    def _find_alignment(self, data: np.ndarray) -> int:
        """Slide a 1-second window across the data to find where
        the best correlation occurs. Returns the optimal offset (0 to
        window_size-1) that aligns windows with WWVB second boundaries.

        Tests every 10th sample for speed (1ms resolution at 1000Hz).
        """
        best_offset = 0
        best_score = -np.inf
        step = max(1, self._window_size // 100)  # 10 samples at 1kHz

        for offset in range(0, self._window_size, step):
            # Score this offset by summing best correlations across
            # all complete windows
            total_score = 0.0
            n_windows = 0
            pos = offset
            while pos + self._window_size <= len(data):
                window = data[pos:pos + self._window_size]
                _, confidence = self._classify(window)
                total_score += confidence
                n_windows += 1
                pos += self._window_size

            if n_windows > 0:
                avg_score = total_score / n_windows
                if avg_score > best_score:
                    best_score = avg_score
                    best_offset = offset

        logger.debug(
            f"Alignment search: best offset={best_offset}, "
            f"avg_confidence={best_score:.3f}"
        )
        return best_offset

    def _classify(self, window: np.ndarray) -> tuple[str, float]:
        """Correlate normalized window against zero-mean templates.

        Per-window normalization (zero-mean, unit-norm) removes amplitude
        dependence so classification works on weak signals where the
        envelope doesn't swing cleanly between 0 and 1. The result is
        cosine similarity: 1.0 = perfect shape match, 0.0 = orthogonal.

        Returns:
            (symbol, confidence) where symbol is "0", "1", "M", or "?"
            Confidence is cosine similarity, ranging 0.0 to 1.0.
        """
        # Center on actual window mean (not fixed 0.5)
        centered = window - np.mean(window)

        # Normalize to unit norm for cosine similarity
        norm = np.linalg.norm(centered)
        if norm < 1e-10:
            return "?", 0.0  # Flat signal, no information
        centered = centered / norm

        correlations = {}
        for sym, template in self._templates.items():
            # Templates are already zero-mean; normalize to unit norm
            t_norm = np.linalg.norm(template)
            correlations[sym] = float(np.dot(centered, template / t_norm))

        best_sym = max(correlations, key=correlations.get)
        best_corr = correlations[best_sym]

        # Confidence = cosine similarity of best match (0..1)
        confidence = max(0.0, best_corr)

        if confidence < self._min_confidence:
            return "?", confidence

        return best_sym, confidence

    def _update_stats(self, symbol: str) -> None:
        """Update running pulse statistics."""
        self._pulse_counts[symbol] = self._pulse_counts.get(symbol, 0) + 1

    @property
    def avg_pulse_widths(self) -> dict[str, float]:
        """Not applicable for correlation decoder, return zeros."""
        return {"0": 0.0, "1": 0.0, "M": 0.0}

    @property
    def total_pulses(self) -> int:
        return sum(self._pulse_counts.values())

    @property
    def is_synced(self) -> bool:
        return self._synced

    def reset(self) -> None:
        """Reset to pre-sync state."""
        self._synced = False
        self._aligned = False
        self._consecutive_markers = 0
        self._last_symbol = ""
        self._buffer = np.array([], dtype=np.float64)
