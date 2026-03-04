"""State machine and orchestrator for the WWVB decoder application."""

import asyncio
import datetime
import logging
import signal
import time
from enum import Enum

import numpy as np

from .cli import Config
from .decoder import PulseDecoder
from .envelope import EnvelopeDetector
from .frame import FrameAssembler, FrameEventType
from .plain import PlainDisplay
from .sdrconnect import SDRConnectClient
from .tui import TUIDisplay

logger = logging.getLogger(__name__)


class AppState(Enum):
    """Application lifecycle states."""

    CONNECTING = "CONNECTING"
    CONFIGURING = "CONFIGURING"
    WAITING_FOR_DATA = "WAITING"
    SYNCING = "SYNCING"
    DECODING = "LIVE"
    DECODED = "LIVE"
    FRAME_ERROR = "LIVE"
    DISCONNECTED = "DISCONNECTED"


class WWVBApp:
    """Main application class. Owns all modules and drives the event loop."""

    def __init__(self, config: Config):
        self.config = config
        self.state = AppState.CONNECTING
        self.client = SDRConnectClient(config.host, config.port)
        self.envelope_detector = EnvelopeDetector()
        self.pulse_decoder = PulseDecoder(threshold=config.threshold)
        self.assembler = FrameAssembler(min_frames=config.min_frames)

        # Display
        self.display = None

        # Signal monitoring
        self.signal_power: float | None = None
        self.signal_snr: float | None = None
        self.snr_history: list[float] = []
        self.has_control: bool | None = None

        # Activity log
        self.log_entries: list[str] = []

        # Timing
        self._start_time = time.monotonic()
        self._last_audio_time = 0.0
        self._running = False

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self._start_time

    def _log(self, message: str, category: str = "INFO") -> None:
        """Add an entry to the activity log."""
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        entry = f"  {ts}  {message}"
        self.log_entries.append(entry)
        # Keep last 100 entries
        if len(self.log_entries) > 100:
            self.log_entries = self.log_entries[-100:]

        # Also log to plain display if active
        if isinstance(self.display, PlainDisplay):
            self.display.log(category, message)

        logger.info(message)

    async def run(self) -> None:
        """Main entry point. Runs until Ctrl+C or connection failure."""
        # Configure logging
        log_level = logging.DEBUG if self.config.debug else logging.WARNING
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )

        # Create display
        if self.config.plain:
            self.display = PlainDisplay(debug=self.config.debug)
        else:
            self.display = TUIDisplay()

        self.display.start()
        self._running = True

        # Handle Ctrl+C
        loop = asyncio.get_event_loop()
        try:
            loop.add_signal_handler(signal.SIGINT, self._handle_sigint)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

        try:
            # Phase 1: Connect
            self.state = AppState.CONNECTING
            self._log(f"Connecting to {self.config.ws_url}", "CONNECT")
            self._update_display()

            await self.client.connect()
            self._log(f"Connected to {self.config.ws_url}", "CONNECT")

            # Phase 2: Configure
            if not self.config.no_tune:
                self.state = AppState.CONFIGURING
                self._log("Configuring radio for WWVB 60 kHz reception", "CONFIG")
                self._update_display()

                await self.client.configure_wwvb(antenna=self.config.antenna)
                self._log(
                    f"Tuned to 60000 Hz | AM | BW: 100 Hz | AGC: off | Antenna: {self.config.antenna}",
                    "CONFIG",
                )
            else:
                self._log("--no-tune: Skipping radio configuration", "CONFIG")

            # Phase 3: Start streaming
            self.state = AppState.WAITING_FOR_DATA
            self._log("Enabling audio stream...", "STREAM")
            self._update_display()

            # Register audio callback
            self.client.on_audio(self._on_audio)

            # Enable the audio stream
            await self.client.enable_audio_stream()
            self._log("Audio stream enabled. Waiting for data...", "STREAM")

            # Start concurrent tasks
            tasks = [
                asyncio.create_task(self.client.run()),
                asyncio.create_task(self._signal_poller()),
                asyncio.create_task(self._display_updater()),
                asyncio.create_task(self._data_watchdog()),
            ]

            # Wait for tasks (they run forever until cancelled)
            await asyncio.gather(*tasks, return_exceptions=True)

        except ConnectionError as e:
            self.state = AppState.DISCONNECTED
            self._log(f"Connection failed: {e}", "ERROR")
            self._update_display()
        except asyncio.CancelledError:
            pass
        finally:
            await self._shutdown()

    def _handle_sigint(self) -> None:
        """Handle Ctrl+C signal."""
        self._running = False
        # Cancel all tasks
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()

    async def _shutdown(self) -> None:
        """Clean shutdown: print summary, disable streams, close WS."""
        self._running = False

        # Print summary
        asm = self.assembler
        uptime = datetime.timedelta(seconds=int(self.uptime_seconds))
        summary = (
            f"Session ended. Duration: {uptime} | "
            f"Frames: {asm.total_frames} decoded, {asm.error_frames} errors | "
            f"Success rate: {asm.success_rate:.1f}%"
        )
        self._log(summary, "STATS")

        # Stop display
        if self.display:
            self.display.stop()

        # Print summary to stdout (visible after TUI clears)
        print(f"\n{summary}")

        # Disconnect
        try:
            await self.client.disconnect()
        except Exception:
            pass

    def _on_audio(self, samples: np.ndarray) -> None:
        """Audio callback from SDRConnect. Processes samples through the pipeline."""
        if not self._running:
            return

        self._last_audio_time = time.monotonic()

        # Transition from WAITING to SYNCING on first data
        if self.state == AppState.WAITING_FOR_DATA:
            self.state = AppState.SYNCING
            self._log("Audio data received. Searching for frame sync...", "SYNC")

        # Pipeline: audio -> envelope -> pulses -> symbols -> frame events
        try:
            envelope = self.envelope_detector.process(samples)
            pulses = self.pulse_decoder.process(
                envelope, self.envelope_detector.effective_rate
            )

            for pulse in pulses:
                if self.config.debug and isinstance(self.display, PlainDisplay):
                    self.display.log_debug(
                        f"Pulse: {pulse.duration_ms:.1f}ms -> {pulse.symbol}"
                    )

                event = self.assembler.add_symbol(pulse.symbol)
                if event:
                    self._handle_frame_event(event)

        except Exception as e:
            logger.error(f"Audio processing error: {e}", exc_info=True)

    def _handle_frame_event(self, event) -> None:
        """Update state and log based on frame assembler events."""
        if event.event_type == FrameEventType.SYNC_PROGRESS:
            self._log(event.message, "SYNC")

        elif event.event_type == FrameEventType.SYNC_ACQUIRED:
            self.state = AppState.DECODING
            self._log("Frame sync acquired", "SYNC")

        elif event.event_type == FrameEventType.FRAME_COMPLETE:
            self.state = AppState.DECODED
            self._log(event.message, "DECODE")

            # Log stats periodically
            asm = self.assembler
            self._log(
                f"frames={asm.total_frames} errors={asm.error_frames} "
                f"rate={asm.success_rate:.1f}%",
                "STATS",
            )

            # Record SNR at decode time
            if self.signal_snr is not None:
                self.snr_history.append(self.signal_snr)

            # Reset state to DECODING after brief display
            self.state = AppState.DECODING

        elif event.event_type == FrameEventType.FRAME_ERROR:
            self.state = AppState.FRAME_ERROR
            self._log(f"Frame error: {event.message}", "ERROR")

            # If sync was lost, go back to SYNCING
            if not self.assembler.is_synced:
                self.state = AppState.SYNCING
                self._log("Sync lost. Resyncing...", "SYNC")
            else:
                self.state = AppState.DECODING

    async def _signal_poller(self) -> None:
        """Poll signal_power and signal_snr every 2 seconds."""
        while self._running:
            try:
                power = await self.client.get_property("signal_power")
                if power:
                    try:
                        self.signal_power = float(power)
                    except ValueError:
                        pass

                snr = await self.client.get_property("signal_snr")
                if snr:
                    try:
                        self.signal_snr = float(snr)
                    except ValueError:
                        pass

                # Check control status
                control = await self.client.get_property("can_control")
                if control:
                    self.has_control = control.lower() == "true"

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Signal poll error: {e}")

            await asyncio.sleep(2)

    async def _display_updater(self) -> None:
        """Update the TUI display once per second."""
        while self._running:
            try:
                self._update_display()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Display update error: {e}")

            await asyncio.sleep(1)

    async def _data_watchdog(self) -> None:
        """Watch for stalled audio stream."""
        while self._running:
            try:
                if (
                    self._last_audio_time > 0
                    and time.monotonic() - self._last_audio_time > 10
                    and self.state not in (AppState.CONNECTING, AppState.CONFIGURING)
                ):
                    self._log(
                        "No audio data for 10 seconds. Checking device status...",
                        "WARN",
                    )
                    started = await self.client.get_property("started")
                    if started == "false":
                        self._log("Device not streaming. Sending device_stream_enable...", "WARN")
                        await self.client.enable_device_stream()
                        await asyncio.sleep(1)
                        await self.client.enable_audio_stream()
                    self._last_audio_time = time.monotonic()  # Reset timer

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Watchdog error: {e}")

            await asyncio.sleep(5)

    def _update_display(self) -> None:
        """Refresh the display."""
        if self.display:
            self.display.update(self)
