"""Envelope detection from audio PCM stream."""

import numpy as np
from scipy.signal import butter, sosfilt

import logging

logger = logging.getLogger(__name__)


class EnvelopeDetector:
    """Convert raw stereo PCM audio to a normalized amplitude envelope.

    Pipeline:
    1. Extract left channel from stereo interleaved data
    2. Take absolute value
    3. Apply 4th-order Butterworth LPF at 5 Hz cutoff
    4. Decimate to ~1000 Hz
    5. Normalize to 0.0-1.0 using running min/max window
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

        # 2. Absolute value for envelope
        rectified = np.abs(left)

        # 3. Apply Butterworth LPF with stateful filtering
        filtered, self._zi = sosfilt(self._sos, rectified, zi=self._zi)

        # 4. Decimate to ~1000 Hz
        decimated = filtered[:: self.decimation_factor]

        if len(decimated) == 0:
            return np.array([], dtype=np.float64)

        # 5. Update normalization window
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

    def get_recent_envelope(self, seconds: float = 5.0) -> np.ndarray:
        """Return last N seconds of normalized envelope for TUI display."""
        n_samples = int(self.effective_rate * seconds)
        return self._display_buffer[-n_samples:]

    @property
    def has_data(self) -> bool:
        """True if we've received enough data to produce meaningful output."""
        return self._total_samples > self.sample_rate  # At least 1 second
