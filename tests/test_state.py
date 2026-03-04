"""Unit tests for state machine transitions."""

import pytest

from wwvb_decode.state import AppState, WWVBApp
from wwvb_decode.cli import Config


class TestAppState:
    def test_initial_state(self):
        config = Config()
        app = WWVBApp(config)
        assert app.state == AppState.CONNECTING

    def test_state_values(self):
        """State display values should match the spec."""
        assert AppState.CONNECTING.value == "CONNECTING"
        assert AppState.CONFIGURING.value == "CONFIGURING"
        assert AppState.WAITING_FOR_DATA.value == "WAITING"
        assert AppState.SYNCING.value == "SYNCING"
        assert AppState.DECODING.value == "LIVE"

    def test_config_defaults(self):
        config = Config()
        assert config.host == "127.0.0.1"
        assert config.port == 5454
        assert config.threshold == 0.5
        assert config.source == "audio"
        assert config.min_frames == 2
        assert not config.plain
        assert not config.debug
        assert config.antenna == "Hi-Z"

    def test_ws_url(self):
        config = Config(host="192.168.1.50", port=5454)
        assert config.ws_url == "ws://192.168.1.50:5454"

    def test_debug_implies_plain(self):
        from wwvb_decode.cli import parse_args
        config = parse_args(["--debug"])
        assert config.plain is True
        assert config.debug is True

    def test_app_has_all_modules(self):
        config = Config()
        app = WWVBApp(config)
        assert app.client is not None
        assert app.envelope_detector is not None
        assert app.pulse_decoder is not None
        assert app.assembler is not None
        assert app.log_entries == []
        assert app.signal_power is None
        assert app.signal_snr is None
