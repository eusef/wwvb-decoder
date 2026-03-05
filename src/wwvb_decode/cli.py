"""Command line interface for wwvb-decode."""

import argparse
from dataclasses import dataclass


@dataclass
class Config:
    """Application configuration from CLI arguments."""

    host: str = "127.0.0.1"
    port: int = 5454
    no_tune: bool = False
    source: str = "audio"
    threshold: float = 0.5
    min_frames: int = 2
    plain: bool = False
    debug: bool = False
    antenna: str = "Hi-Z"
    freq: int = 60000              # Tuning frequency in Hz
    if_gain: int | None = None     # IF gain reduction (0-59 for RSPdx)
    rf_gain: int | None = None     # LNA state / RF gain level
    correlation: bool = False      # Use cross-correlation decoder
    min_confidence: float = 0.5    # Minimum confidence for correlation decoder
    max_errors: int = 8            # Max tolerated errors per frame (0=strict)
    log_file: str | None = None    # Path to write decoder log

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}"


def parse_args(argv: list[str] | None = None) -> Config:
    """Parse command line arguments and return a Config."""
    parser = argparse.ArgumentParser(
        prog="wwvb-decode",
        description="Decode WWVB 60 kHz time signal via SDRConnect WebSocket API",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="SDRConnect WebSocket host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5454,
        help="SDRConnect WebSocket port (default: 5454)",
    )
    parser.add_argument(
        "--freq",
        type=int,
        default=60000,
        metavar="HZ",
        help="Tuning frequency in Hz (default: 60000). Adjust if your SDR "
             "oscillator is offset, e.g. --freq 60020.",
    )
    parser.add_argument(
        "--no-tune",
        action="store_true",
        default=False,
        help="Skip tuning commands (assume SDRConnect already tuned to 60 kHz)",
    )
    parser.add_argument(
        "--source",
        choices=["audio", "iq"],
        default="audio",
        help="Data source: audio (demodulated AM) or iq (raw IQ) (default: audio)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Envelope threshold 0.0-1.0 for pulse detection (default: 0.5)",
    )
    parser.add_argument(
        "--min-frames",
        type=int,
        default=2,
        help="Consecutive matching frames required before reporting (default: 2)",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        default=False,
        help="Disable TUI; use plain timestamped log output",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Show raw sample data and signal levels (implies --plain)",
    )
    parser.add_argument(
        "--antenna",
        default="Hi-Z",
        help="Antenna port selection (default: Hi-Z for VLF)",
    )
    parser.add_argument(
        "--if-gain",
        type=int,
        default=None,
        metavar="N",
        help="IF gain reduction (0-59 dB for RSPdx). Lower = more gain. "
             "Tip: set to 0 for WWVB to avoid overload.",
    )
    parser.add_argument(
        "--rf-gain",
        type=int,
        default=None,
        metavar="N",
        help="LNA state / RF gain level. Higher = more gain. "
             "For RSPdx: 0 (min) to 9 (max).",
    )

    parser.add_argument(
        "--correlation",
        action="store_true",
        default=False,
        help="Use cross-correlation decoder instead of edge-based "
             "(more robust on weak signals).",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.5,
        metavar="F",
        help="Minimum correlation confidence for valid bit, 0.0-1.0 "
             "(default: 0.5). Only used with --correlation.",
    )

    parser.add_argument(
        "--max-errors",
        type=int,
        default=8,
        metavar="N",
        help="Maximum tolerated errors per 60-symbol frame (default: 8). "
             "Set to 0 for strict mode (all markers must be present).",
    )

    parser.add_argument(
        "--log",
        default=None,
        metavar="FILE",
        help="Write decoder log to FILE (pulses, sync, frames, signal). "
             "Works with both TUI and --plain modes.",
    )

    args = parser.parse_args(argv)

    # --debug implies --plain
    if args.debug:
        args.plain = True

    return Config(
        host=args.host,
        port=args.port,
        freq=args.freq,
        no_tune=args.no_tune,
        source=args.source,
        threshold=args.threshold,
        min_frames=args.min_frames,
        plain=args.plain,
        debug=args.debug,
        antenna=args.antenna,
        if_gain=args.if_gain,
        rf_gain=args.rf_gain,
        correlation=args.correlation,
        min_confidence=args.min_confidence,
        max_errors=args.max_errors,
        log_file=args.log,
    )
