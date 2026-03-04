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

    args = parser.parse_args(argv)

    # --debug implies --plain
    if args.debug:
        args.plain = True

    return Config(
        host=args.host,
        port=args.port,
        no_tune=args.no_tune,
        source=args.source,
        threshold=args.threshold,
        min_frames=args.min_frames,
        plain=args.plain,
        debug=args.debug,
        antenna=args.antenna,
    )
