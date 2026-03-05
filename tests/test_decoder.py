"""Unit tests for pulse width decoder."""

import numpy as np
import pytest

from wwvb_decode.decoder import PulseDecoder, Pulse


@pytest.fixture
def decoder():
    return PulseDecoder(threshold=0.5, hysteresis=0.05)


def _make_pulse(sample_rate: float, duration_ms: float, high_val=0.9, low_val=0.1):
    """Create a synthetic envelope with one low-power pulse.

    Returns an array: 200ms high, <duration_ms> low, 200ms high
    """
    high_samples = int(sample_rate * 0.2)
    low_samples = int(sample_rate * duration_ms / 1000.0)

    envelope = np.concatenate([
        np.full(high_samples, high_val),
        np.full(low_samples, low_val),
        np.full(high_samples, high_val),
    ])
    return envelope


class TestPulseClassification:
    """Test that pulse widths are classified correctly."""

    def test_200ms_is_zero(self, decoder):
        envelope = _make_pulse(1000.0, 200)
        pulses = decoder.process(envelope, 1000.0)
        assert len(pulses) == 1
        assert pulses[0].symbol == "0"
        assert 180 < pulses[0].duration_ms < 220

    def test_500ms_is_one(self, decoder):
        envelope = _make_pulse(1000.0, 500)
        pulses = decoder.process(envelope, 1000.0)
        assert len(pulses) == 1
        assert pulses[0].symbol == "1"
        assert 480 < pulses[0].duration_ms < 520

    def test_800ms_is_marker(self, decoder):
        envelope = _make_pulse(1000.0, 800)
        pulses = decoder.process(envelope, 1000.0)
        assert len(pulses) == 1
        assert pulses[0].symbol == "M"
        assert 780 < pulses[0].duration_ms < 820

    def test_50ms_is_rejected(self, decoder):
        """Pulses shorter than 80ms should be rejected."""
        envelope = _make_pulse(1000.0, 50)
        pulses = decoder.process(envelope, 1000.0)
        assert len(pulses) == 0

    def test_boundary_330ms(self, decoder):
        """330ms is the boundary between 0 and 1."""
        envelope = _make_pulse(1000.0, 329)
        pulses = decoder.process(envelope, 1000.0)
        assert pulses[0].symbol == "0"

        decoder2 = PulseDecoder(threshold=0.5)
        envelope2 = _make_pulse(1000.0, 331)
        pulses2 = decoder2.process(envelope2, 1000.0)
        assert pulses2[0].symbol == "1"

    def test_boundary_620ms(self, decoder):
        """620ms is the boundary between 1 and M."""
        envelope = _make_pulse(1000.0, 619)
        pulses = decoder.process(envelope, 1000.0)
        assert pulses[0].symbol == "1"

        decoder2 = PulseDecoder(threshold=0.5)
        envelope2 = _make_pulse(1000.0, 621)
        pulses2 = decoder2.process(envelope2, 1000.0)
        assert pulses2[0].symbol == "M"


class TestMultiplePulses:
    """Test detection of sequences of pulses."""

    def test_three_pulses(self, decoder):
        """Detect M, 0, 1 in sequence with realistic 1-second spacing.

        WWVB sends exactly one pulse per second. Each second starts
        with a falling edge (power drop). Consecutive falling edges
        are exactly 1000ms apart:
          Sec N:   low for pulse_duration, high for (1000 - pulse_duration)
          Sec N+1: low for pulse_duration, high for (1000 - pulse_duration)
        """
        rate = 1000.0

        def make_second(pulse_ms):
            """One WWVB second: low (pulse) then high (gap)."""
            low = np.full(int(rate * pulse_ms / 1000), 0.1)
            high = np.full(int(rate * (1000 - pulse_ms) / 1000), 0.9)
            return np.concatenate([low, high])

        envelope = np.concatenate([
            make_second(800),  # M
            make_second(200),  # 0
            make_second(500),  # 1
            np.full(int(rate * 0.1), 0.9),  # trailing high
        ])
        pulses = decoder.process(envelope, rate)
        assert len(pulses) == 3
        assert pulses[0].symbol == "M"
        assert pulses[1].symbol == "0"
        assert pulses[2].symbol == "1"


class TestPulseStats:
    """Test running average pulse width statistics."""

    def test_avg_pulse_widths(self, decoder):
        rate = 1000.0
        gap = np.full(int(rate * 0.2), 0.9)

        # Feed several zero pulses
        for _ in range(5):
            env = np.concatenate([gap, np.full(int(rate * 0.2), 0.1), gap])
            decoder.process(env, rate)

        avgs = decoder.avg_pulse_widths
        assert 180 < avgs["0"] < 220
        assert avgs["1"] == 0.0  # No 1s detected
