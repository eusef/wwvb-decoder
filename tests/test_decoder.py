"""Unit tests for pulse width decoder and correlation decoder."""

import numpy as np
import pytest

from wwvb_decode.decoder import CorrelationDecoder, PulseDecoder, Pulse


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


class TestPulseTimeout:
    """Test that timeouts emit '?' symbols instead of silently resetting."""

    def test_timeout_emits_question_mark(self, decoder):
        """A signal that drops low and never comes back should emit '?'."""
        rate = 1000.0
        # 200ms high, then 1200ms low (exceeds max_pulse_ms of 1100)
        envelope = np.concatenate([
            np.full(int(rate * 0.2), 0.9),
            np.full(int(rate * 1.2), 0.1),
        ])
        pulses = decoder.process(envelope, rate)
        assert len(pulses) == 1
        assert pulses[0].symbol == "?"

    def test_timeout_followed_by_valid_pulse(self, decoder):
        """After a timeout '?', the next valid pulse should still be detected."""
        rate = 1000.0

        def make_second(pulse_ms):
            low = np.full(int(rate * pulse_ms / 1000), 0.1)
            high = np.full(int(rate * (1000 - pulse_ms) / 1000), 0.9)
            return np.concatenate([low, high])

        envelope = np.concatenate([
            np.full(int(rate * 0.2), 0.9),  # lead-in
            np.full(int(rate * 1.2), 0.1),  # timeout pulse (1200ms low)
            np.full(int(rate * 0.2), 0.9),  # gap
            make_second(200),               # valid "0" pulse
            np.full(int(rate * 0.1), 0.9),  # trailing
        ])
        pulses = decoder.process(envelope, rate)
        assert len(pulses) >= 2
        assert pulses[0].symbol == "?"
        # The valid pulse should follow
        valid_pulses = [p for p in pulses if p.symbol != "?"]
        assert len(valid_pulses) >= 1
        assert valid_pulses[0].symbol == "0"


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


# ==================== CorrelationDecoder Tests ====================


def _make_wwvb_second(pulse_ms, rate=1000.0):
    """One WWVB second: LOW for pulse_ms, HIGH for remainder."""
    low = np.zeros(int(rate * pulse_ms / 1000))
    high = np.ones(int(rate * (1000 - pulse_ms) / 1000))
    return np.concatenate([low, high])


@pytest.fixture
def corr_decoder():
    # lpf_cutoff=999 disables LPF rounding (above Nyquist), so sharp
    # test signals match the sharp templates directly.
    return CorrelationDecoder(sample_rate=1000.0, min_confidence=0.5, lpf_cutoff=999.0)


class TestCorrelationClassification:
    """Test that correlation decoder classifies ideal signals correctly."""

    def test_zero_classification(self, corr_decoder):
        """200ms pulse should classify as '0'."""
        window = _make_wwvb_second(200)
        pulses = corr_decoder.process(window, 1000.0)
        # Not synced yet, so no pulses emitted (need MM first)
        # But we can test _classify directly
        symbol, conf = corr_decoder._classify(window)
        assert symbol == "0"
        assert conf > 0.5

    def test_one_classification(self, corr_decoder):
        """500ms pulse should classify as '1'."""
        window = _make_wwvb_second(500)
        symbol, conf = corr_decoder._classify(window)
        assert symbol == "1"
        assert conf > 0.5

    def test_marker_classification(self, corr_decoder):
        """800ms pulse should classify as 'M'."""
        window = _make_wwvb_second(800)
        symbol, conf = corr_decoder._classify(window)
        assert symbol == "M"
        assert conf > 0.5

    def test_noisy_signal_still_classifies(self, corr_decoder):
        """Add moderate noise - should still classify correctly."""
        rng = np.random.default_rng(42)
        window = _make_wwvb_second(500)
        noise = rng.normal(0, 0.15, len(window))
        noisy = np.clip(window + noise, 0.0, 1.0)
        symbol, conf = corr_decoder._classify(noisy)
        assert symbol == "1"
        assert conf > 0.3

    def test_very_noisy_signal_rejected(self, corr_decoder):
        """Pure noise should be rejected as '?'."""
        rng = np.random.default_rng(42)
        window = rng.uniform(0.3, 0.7, 1000)  # Random mid-range values
        symbol, conf = corr_decoder._classify(window)
        assert symbol == "?" or conf < 0.5


class TestCorrelationSync:
    """Test frame synchronization via consecutive markers."""

    def test_sync_on_double_marker(self, corr_decoder):
        """Two consecutive M windows should trigger sync."""
        # Need 3+ seconds for alignment phase, then sync detection
        envelope = np.concatenate([
            _make_wwvb_second(200),  # "0" - alignment data
            _make_wwvb_second(800),  # M
            _make_wwvb_second(800),  # M - triggers sync
            _make_wwvb_second(200),  # "0" - post-sync
        ])
        all_pulses = corr_decoder.process(envelope, 1000.0)
        assert corr_decoder.is_synced
        # Should have M (sync) + "0" (post-sync)
        assert len(all_pulses) >= 1
        synced_m = [p for p in all_pulses if p.symbol == "M"]
        assert len(synced_m) >= 1
        # Last pulse should be "0"
        assert all_pulses[-1].symbol == "0"

    def test_non_marker_resets_consecutive_count(self, corr_decoder):
        """A non-M between two M's should not trigger sync."""
        envelope = np.concatenate([
            _make_wwvb_second(800),  # M
            _make_wwvb_second(200),  # "0" - breaks consecutive M
            _make_wwvb_second(800),  # M - only 1 consecutive, no sync
        ])
        corr_decoder.process(envelope, 1000.0)
        assert not corr_decoder.is_synced

    def test_reset_clears_sync(self, corr_decoder):
        """reset() should return to pre-sync state."""
        envelope = np.concatenate([
            _make_wwvb_second(200),  # alignment data
            _make_wwvb_second(800),  # M
            _make_wwvb_second(800),  # M - triggers sync
        ])
        corr_decoder.process(envelope, 1000.0)
        assert corr_decoder.is_synced

        corr_decoder.reset()
        assert not corr_decoder.is_synced


class TestCorrelationSequence:
    """Test multi-symbol sequences through the correlation decoder."""

    def test_full_sequence(self, corr_decoder):
        """M, M (sync), then 0, 1, M sequence."""
        rate = 1000.0
        envelope = np.concatenate([
            _make_wwvb_second(800),  # M - pre-sync
            _make_wwvb_second(800),  # M - sync acquired
            _make_wwvb_second(200),  # 0
            _make_wwvb_second(500),  # 1
            _make_wwvb_second(800),  # M
        ])

        pulses = corr_decoder.process(envelope, rate)
        # Should get: M (from sync), 0, 1, M = 4 pulses
        assert len(pulses) == 4
        assert pulses[0].symbol == "M"
        assert pulses[1].symbol == "0"
        assert pulses[2].symbol == "1"
        assert pulses[3].symbol == "M"

    def test_chunked_input(self, corr_decoder):
        """Feeding data in small chunks should produce same results."""
        rate = 1000.0
        full = np.concatenate([
            _make_wwvb_second(800),
            _make_wwvb_second(800),
            _make_wwvb_second(200),
        ])

        # Feed in 250-sample chunks
        all_pulses = []
        for i in range(0, len(full), 250):
            chunk = full[i:i + 250]
            all_pulses.extend(corr_decoder.process(chunk, rate))

        assert len(all_pulses) == 2  # M (sync) + 0
        assert all_pulses[0].symbol == "M"
        assert all_pulses[1].symbol == "0"
