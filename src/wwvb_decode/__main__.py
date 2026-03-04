"""Entry point for python -m wwvb_decode."""

import asyncio
import sys

from .cli import parse_args
from .state import WWVBApp


def main():
    config = parse_args()
    app = WWVBApp(config)
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
