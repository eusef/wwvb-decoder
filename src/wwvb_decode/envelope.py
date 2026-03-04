"""Envelope detection from audio PCM stream."""

import numpy as np
from scipy.signal import butter, sosfilt

import logging

logger = logging.getLogger(__name__)

# int16 clipping threshold (95% of max to catch near-clipping too)
CLIP_THRESHOLD = int(32767 * 0.95)


class EnvelopeDetector:
    """Convert raw stereo PCM audio to a normalized amplitude envelope.

    Pipeline:
    1. Extract left channel from stereo interleaved data
    2. Check for clipping / ADC overload
    3. Take absolute value
    4. Apply 4th-order Butterworth LPF at 5 Hz cutoff
    5. Decimate to ~1000 Hz
    6. Normalize to 0.0-1.0 using running min/max window
    """

    def __init__(self, sample_rate: int = 48000, lpf_cutoff: float = 5.0):
        self.sample_rate = sample_rate
        self.lpf_cutoff = lpf_cutoff

        # Decimation: 48000 -> 1000 Hz = factor of 48
        self.decimation_factor = sample_rate // 1000
        self.effective_rate = sample_rate / self.decimation_factor  # 1000 Hz

        # Design Butterworth LPF (second-order sections for stability)
        nyquist = sample_rate / 2.0
        normalized_cutoff = lpf_cutoff / nyquist
        self._sos = butter(4, normalized_cutoff, btype="low", output="sos")

        # Filter state (for continuous processing across chunks)
        self._zi = np.zeros((self._sos.shape[0], 2))

        # Normalization window (running min/max over last N seconds)
        self._window_seconds = 10
        self._window_size = int(self.effective_rate * self._window_seconds)
        self._recent_values: list[float] = []
        self._min_val = 0.0
        self._max_val = 1.0

        # Rolling buffer for TUI envelope trace display
        self._display_buffer_seconds = 6
        self._display_buffer_size = int(self.effective_rate * self._display_buffer_seconds)
        self._display_buffer = np.zeros(self._display_buffer_size, dtype=np.float64)

        self._total_samples = 0

        # Clipping / overload detection
        self._clip_count = 0          # Samples at or near int16 max in current window
        self._clip_window_samples = 0  # Total samples in current window
        self._clip_ratio = 0.0         # Fraction of clipped samples (0.0-1.0)
        self._overload = False         # True if clipping is significant
        self._peak_level = 0           # Recent peak absolute sample value (int16)
        self._peak_hold = 0            # Smoothed peak with slow decay
        self._clip_window_size = sample_rate * 2  # 2-second rolling window
        # Hysteresis: must exceed 0.1% to set, drop below 0.02% to clear
        self._overload_set_threshold = 0.001    # 0.1%
        self._overload_clear_threshold = 0.0002  # 0.02%

    def process(self, audio_stereo: np.ndarray) -> np.ndarray:
        """Process a chunk of stereo PCM audio into normalized envelope.

        Args:
            audio_stereo: int16 stereo interleaved samples (LRLR...)

        Returns:
            float64 normalized envelope (0.0-1.0) at effective_rate (1000 Hz)
        """
        if len(audio_stereo) < 2:
            return np.array([], dtype=np.float64)

        # 1. Extract left channel (every other sample)
        left = audio_stereo[0::2].astype(np.float64)

        # 2. Clipping / overload detection on raw int16 samples
        raw_left = audio_stereo[0::2]  # Still int16
        self._update_clipping(raw_left)

        # 3. Absolute value for envelope
        rectified = np.abs(left)

        # 4. Apply Butterworth LPF with stateful filtering
        filtered, self._zi = sosfilt(self._sos, rectified, zi=self._zi)

        # 5. Decimate to ~1000 Hz
        decimated = filtered[:: self.decimation_factor]

        if len(decimated) == 0:
            return np.array([], dtype=np.float64)

        # 6. Update normalization window
        for v in decimated:
            self._recent_values.append(v)
        # Trim to window size
        if len(self._recent_values) > self._window_size:
            self._recent_values = self._recent_values[-self._window_size :]

        # Compute min/max from window (with protection against flat signal)
        if len(self._recent_values) > 100:
            self._min_val = np.percentile(self._recent_values, 2)
            self._max_val = np.percentile(self._recent_values, 98)

        # Normalize
        val_range = self._max_val - self._min_val
        if val_range < 1e-6:
            normalized = np.full_like(decimated, 0.5)
        else:
            normalized = (decimated - self._min_val) / val_range
            normalized = np.clip(normalized, 0.0, 1.0)

        # Update display buffer
        self._display_buffer = np.roll(self._display_buffer, -len(normalized))
        self._display_buffer[-len(normalized) :] = normalized

        self._total_samples += len(left)

        return normalized

    def _update_clipping(self, raw_samples: np.ndarray) -> None:
        """Track ADC clipping / overload from raw int16 samples.

        Maintains a rolling 2-second window of clip ratio with hysteresis
        to prevent the overload flag from flickering at borderline levels.
        Peak level uses a hold-and-decay approach for smooth display.
        """
        abs_samples = np.abs(raw_samples)
        n_clipped = int(np.sum(abs_samples >= CLIP_THRESHOLD))
        chunk_peak = int(np.max(abs_samples)) if len(abs_samples) > 0 else 0

        self._clip_count += n_clipped
        self._clip_window_samples += len(raw_samples)
        self._peak_level = max(self._peak_level, chunk_peak)

        # Smooth peak hold: track max, decay slowly toward current level
        if chunk_peak >= self._peak_hold:
            self._peak_hold = chunk_peak
        else:
            # Decay ~10% per chunk toward the current peak
            self._peak_hold = int(self._peak_hold * 0.9 + chunk_peak * 0.1)

        # Roll the window every 2 seconds worth of samples
        if self._clip_window_samples >= self._clip_window_size:
            self._clip_ratio = self._clip_count / max(1, self._clip_window_samples)
            # Hysteresis: different thresholds for set vs clear
            if self._overload:
                # Already flagged: require ratio to drop well below to clear
                if self._clip_ratio < self._overload_clear_threshold:
                    self._overload = False
            else:
                # Not flagged: require ratio to exceed threshold to set
                if self._clip_ratio > self._overload_set_threshold:
                    self._overload = True
            # Reset window
            self._clip_count = 0
            self._clip_window_samples = 0
            self._peak_level = chunk_peak

    def get_recent_envelope(self, seconds: float = 5.0) -> np.ndarray:
        """Return last N seconds of normalized envelope for TUI display."""
        n_samples = int(self.effective_rate * seconds)
        return self._display_buffer[-n_samples:]

    @property
    def has_data(self) -> bool:
        """True if we've received enough data to produce meaningful output."""
        return self._total_samples > self.sample_rate  # At least 1 second

    @property
    def is_overloaded(self) -> bool:
        """True if ADC clipping is detected (>0.1% of samples)."""
        return self._overload

    @property
    def clip_percentage(self) -> float:
        """Percentage of samples clipping in the last window."""
        return self._clip_ratio * 100.0

    @property
    def peak_level_pct(self) -> float:
        """Peak sample level as percentage of int16 max (smoothed hold)."""
        return (self._peak_hold / 32767.0) * 100.0
