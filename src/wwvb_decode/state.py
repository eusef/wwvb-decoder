"""State machine and orchestrator for the WWVB decoder application."""

import asyncio
import datetime
import logging
import signal
import sys
import threading
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
        self.sdr_overload: bool = False  # From SDRConnect overload property

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

            # Start the receive loop FIRST so get_property responses
            # can be dispatched during configuration
            receive_task = asyncio.create_task(self.client.run())

            # Register callbacks before enabling streams
            self.client.on_audio(self._on_audio)
            self.client.on_overload(self._on_overload)

            # Phase 2: Configure
            if not self.config.no_tune:
                self.state = AppState.CONFIGURING
                self._log("Configuring radio for WWVB 60 kHz reception", "CONFIG")
                self._update_display()

                results = await self.client.configure_wwvb(
                    antenna=self.config.antenna,
                    if_gain=self.config.if_gain,
                    rf_gain=self.config.rf_gain,
                )

                config_msg = (
                    f"Tuned to 60000 Hz | AM | BW: 100 Hz | AGC: off | Antenna: {self.config.antenna}"
                )
                if self.config.if_gain is not None:
                    config_msg += f" | IF gain red: {self.config.if_gain}"
                if self.config.rf_gain is not None:
                    config_msg += f" | RF gain: {self.config.rf_gain}"
                self._log(config_msg, "CONFIG")
            else:
                self._log("--no-tune: Skipping radio configuration", "CONFIG")

            # Phase 3: Start streaming
            self.state = AppState.WAITING_FOR_DATA
            self._log("Enabling audio stream...", "STREAM")
            self._update_display()

            # Enable the audio stream
            await self.client.enable_audio_stream()
            self._log("Audio stream enabled. Waiting for data...", "STREAM")

            # Start remaining concurrent tasks
            tasks = [
                receive_task,
                asyncio.create_task(self._signal_poller()),
                asyncio.create_task(self._display_updater()),
                asyncio.create_task(self._data_watchdog()),
            ]

            # Keyboard listener for TUI tips navigation (arrow keys)
            # Uses a daemon thread to avoid conflicting with Rich Live
            if isinstance(self.display, TUIDisplay):
                self._start_keyboard_thread()

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

    def _on_overload(self, overloaded: bool) -> None:
        """Callback for SDRConnect overload property changes."""
        self.sdr_overload = overloaded
        if overloaded:
            self._log(
                "ADC OVERLOAD detected by SDRConnect. Reduce RF gain or increase IF gain reduction.",
                "WARN",
            )
        else:
            self._log("ADC overload cleared", "SIGNAL")

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
        """Poll signal_power, signal_snr, and overload every 2 seconds."""
        _prev_audio_overload = False
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

                # NOTE: SDR overload is detected via push events from
                # SDRConnect (property_changed), not polling. The 'overload'
                # property is not readable via get_property on most hardware.
                # See sdrconnect.py _handle_text() and on_overload() callback.

                # Check audio-level clipping from envelope detector
                # This is informational (demod output levels), not a hardware alarm
                audio_clipping = self.envelope_detector.is_overloaded
                if audio_clipping and not _prev_audio_overload:
                    self._log(
                        f"Audio levels high ({self.envelope_detector.clip_percentage:.1f}% samples clipping, "
                        f"peak {self.envelope_detector.peak_level_pct:.0f}%). "
                        "May affect decoding if severe.",
                        "SIGNAL",
                    )
                elif not audio_clipping and _prev_audio_overload:
                    self._log("Audio levels returned to normal", "SIGNAL")
                _prev_audio_overload = audio_clipping

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

    def _start_keyboard_thread(self) -> None:
        """Start a daemon thread to read arrow keys for tips navigation.

        Uses a background thread because terminal reads are blocking and
        connect_read_pipe conflicts with Rich Live's terminal handling.
        """
        import termios
        import tty

        display = self.display
        if not isinstance(display, TUIDisplay):
            return

        fd = sys.stdin.fileno()
        try:
            old_settings = termios.tcgetattr(fd)
        except (termios.error, ValueError):
            return  # Not a real terminal

        def _reader() -> None:
            try:
                tty.setcbreak(fd)
                while self._running:
                    try:
                        ch = sys.stdin.buffer.read(1)
                        if not ch:
                            continue
                        if ch == b"\x1b":
                            seq = sys.stdin.buffer.read(2)
                            if seq == b"[C":  # Right arrow
                                display.tips_next_page()
                            elif seq == b"[D":  # Left arrow
                                display.tips_prev_page()
                        elif ch == b"q":
                            self._running = False
                            break
                    except (OSError, ValueError):
                        break
            finally:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                except (termios.error, ValueError):
                    pass

        t = threading.Thread(target=_reader, daemon=True, name="keyboard")
        t.start()

    def _update_display(self) -> None:
        """Refresh the display."""
        if self.display:
            self.display.update(self)
