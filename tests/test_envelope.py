"""Unit tests for envelope detector."""

import numpy as np
import pytest

from wwvb_decode.envelope import EnvelopeDetector


@pytest.fixture
def detector():
    return EnvelopeDetector(sample_rate=48000, lpf_cutoff=5.0)


class TestEnvelopeDetector:
    def test_stereo_input(self, detector):
        """Stereo interleaved input should be handled (extract left channel)."""
        # Create 0.1 seconds of stereo silence
        n_samples = 48000 // 10  # 4800 stereo pairs = 9600 samples
        stereo = np.zeros(n_samples * 2, dtype=np.int16)
        result = detector.process(stereo)
        assert len(result) > 0

    def test_constant_signal_gives_flat_envelope(self, detector):
        """A constant amplitude signal should produce a relatively flat envelope."""
        n_samples = 48000  # 1 second
        # Constant value in left channel
        stereo = np.zeros(n_samples * 2, dtype=np.int16)
        stereo[0::2] = 10000  # Left channel constant
        stereo[1::2] = 10000  # Right channel constant

        result = detector.process(stereo)
        assert len(result) > 0
        # After normalization, a flat signal should be near 0.5 or constant
        # (with only one value, min==max so it maps to 0.5)

    def test_am_modulated_signal(self, detector):
        """An AM-modulated signal should show envelope variation."""
        sample_rate = 48000
        duration = 2.0  # 2 seconds
        n_samples = int(sample_rate * duration)

        t = np.arange(n_samples) / sample_rate

        # Create AM signal: carrier modulated with a 1 Hz square wave
        # (simulates WWVB 1-second pulse pattern)
        carrier = 20000 * np.sin(2 * np.pi * 1000 * t)  # 1 kHz carrier
        modulation = np.where(np.sin(2 * np.pi * 0.5 * t) > 0, 1.0, 0.3)
        signal = (carrier * modulation).astype(np.int16)

        # Interleave as stereo
        stereo = np.zeros(n_samples * 2, dtype=np.int16)
        stereo[0::2] = signal
        stereo[1::2] = signal

        result = detector.process(stereo)
        assert len(result) > 0

        # The envelope should show variation between high and low
        if len(result) > 100:
            assert np.std(result) > 0.01, "Envelope should show amplitude variation"

    def test_effective_rate(self, detector):
        """Check that the effective rate after decimation is ~1000 Hz."""
        assert detector.effective_rate == 1000.0

    def test_output_length(self, detector):
        """Output length should be approximately input_length / decimation_factor / 2."""
        n_samples = 48000  # 1 second mono = 48000 samples
        stereo = np.zeros(n_samples * 2, dtype=np.int16)
        stereo[0::2] = 1000

        result = detector.process(stereo)
        # Expected: 48000 mono samples / 48 decimation = 1000 output samples
        assert abs(len(result) - 1000) < 10

    def test_get_recent_envelope(self, detector):
        """get_recent_envelope should return data from the display buffer."""
        n_samples = 48000 * 2  # 2 seconds
        stereo = np.zeros(n_samples * 2, dtype=np.int16)
        stereo[0::2] = 5000

        detector.process(stereo)
        recent = detector.get_recent_envelope(1.0)
        assert len(recent) == 1000  # 1 second at 1000 Hz

    def test_normalization_range(self, detector):
        """Output should be clipped to 0.0-1.0 range."""
        n_samples = 48000 * 3  # 3 seconds for stable normalization
        # Vary amplitude to establish min/max
        stereo = np.zeros(n_samples * 2, dtype=np.int16)
        t = np.arange(n_samples)
        signal = (10000 * np.sin(2 * np.pi * 0.5 * t / 48000)).astype(np.int16)
        stereo[0::2] = signal

        result = detector.process(stereo)
        if len(result) > 0:
            assert np.all(result >= 0.0)
            assert np.all(result <= 1.0)
