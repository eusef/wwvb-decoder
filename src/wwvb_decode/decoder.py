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


class PulseDecoder:
    """Convert normalized envelope signal into WWVB symbols.

    Uses hysteresis thresholding to detect low-power periods.
    Classifies pulse widths:
      100-350 ms -> "0" (binary zero)
      350-650 ms -> "1" (binary one)
      650-900 ms -> "M" (position marker)
      outside    -> "?" (error/noise)
    """

    def __init__(self, threshold: float = 0.5, hysteresis: float = 0.05):
        self.threshold_high = threshold + hysteresis  # Rising edge threshold
        self.threshold_low = threshold - hysteresis  # Falling edge threshold
        self._state = "HIGH"  # "HIGH" = full power, "LOW" = reduced power
        self._low_start_sample = 0
        self._sample_count = 0

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
        self._zero_max_ms = 330   # 0: ~100-330ms (was 350)
        self._one_max_ms = 620    # 1: ~330-620ms (was 650)
        self._marker_max_ms = 950 # M: ~620-950ms (was 900)

        # Running pulse width stats
        self._pulse_counts: dict[str, int] = {"0": 0, "1": 0, "M": 0, "?": 0}
        self._pulse_sums: dict[str, float] = {"0": 0.0, "1": 0.0, "M": 0.0}

    def process(self, envelope: np.ndarray, sample_rate: float) -> list[Pulse]:
        """Detect pulses from normalized envelope samples.

        Args:
            envelope: float64 normalized envelope (0.0-1.0) at sample_rate
            sample_rate: samples per second (typically 1000 Hz after decimation)

        Returns:
            List of Pulse objects detected in this chunk
        """
        pulses = []
        ms_per_sample = 1000.0 / sample_rate

        refractory_samples = self._refractory_ms / ms_per_sample

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
                    self._state = "HIGH"
                    duration_samples = self._sample_count - self._low_start_sample
                    duration_ms = duration_samples * ms_per_sample
                    start_time = self._low_start_sample / sample_rate

                    # Classify the pulse
                    symbol = self._classify(duration_ms)

                    if symbol != "_":  # "_" means rejected (too short/long)
                        pulse = Pulse(
                            start_time=start_time,
                            duration_ms=duration_ms,
                            symbol=symbol,
                        )
                        pulses.append(pulse)

                        # Update stats
                        self._pulse_counts[symbol] = (
                            self._pulse_counts.get(symbol, 0) + 1
                        )
                        if symbol in self._pulse_sums:
                            self._pulse_sums[symbol] += duration_ms

                        logger.debug(
                            f"Pulse: {duration_ms:.1f}ms -> {symbol} "
                            f"at t={start_time:.3f}s"
                        )
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
                        # Emit "?" so frame assembler stays aligned
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
    ):
        self._sample_rate = sample_rate
        self._min_confidence = min_confidence
        self._window_size = int(sample_rate * self.WINDOW_MS / 1000)

        # Build zero-mean templates for each symbol type.
        # Template structure: LOW during pulse, HIGH during gap.
        # Each template is normalized to zero mean so dot product with
        # a zero-mean window measures shape similarity, not amplitude.
        self._templates = {}
        for sym, pulse_ms in [("0", self.PULSE_0_MS),
                               ("1", self.PULSE_1_MS),
                               ("M", self.PULSE_M_MS)]:
            pulse_samples = int(sample_rate * pulse_ms / 1000)
            gap_samples = self._window_size - pulse_samples
            t = np.concatenate([
                np.full(pulse_samples, -1.0),
                np.full(gap_samples, 1.0),
            ])
            # Zero-mean the template itself
            t = t - np.mean(t)
            self._templates[sym] = t

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
