"""Pulse width measurement and symbol classification for WWVB."""

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

        for sample in envelope:
            if self._state == "HIGH":
                # Looking for falling edge (HIGH -> LOW)
                if sample < self.threshold_low:
                    self._state = "LOW"
                    self._low_start_sample = self._sample_count
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
                        logger.debug(
                            f"Pulse timeout at {duration_ms:.0f}ms, resetting"
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
