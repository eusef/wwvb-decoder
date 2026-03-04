"""WebSocket client for SDRConnect API."""

import asyncio
import json
import logging
import struct
from collections.abc import Callable

import numpy as np
import websockets

logger = logging.getLogger(__name__)

# Binary stream header types (little-endian int16)
STREAM_AUDIO = 0x0001
STREAM_IQ = 0x0002
STREAM_SPECTRUM = 0x0003


class SDRConnectClient:
    """Async WebSocket client for the SDRConnect API.

    Handles JSON property get/set and dispatches binary audio/IQ streams
    to registered callbacks.

    IMPORTANT: The receive loop (run()) must be running concurrently for
    get_property() to work, since responses arrive as WebSocket messages.
    """

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.url = f"ws://{host}:{port}"
        self._ws = None
        self._running = False
        self._audio_callbacks: list[Callable[[np.ndarray], None]] = []
        self._iq_callbacks: list[Callable[[np.ndarray], None]] = []
        self._pending_gets: dict[str, asyncio.Future] = {}
        self._max_retries = 5
        self._connected = asyncio.Event()
        # Overload detection from SDRConnect property_changed events
        self.overload_flag = False
        self._overload_callbacks: list[Callable[[bool], None]] = []

    async def connect(self) -> None:
        """Connect to SDRConnect WebSocket with retry logic."""
        delay = 1.0
        for attempt in range(1, self._max_retries + 1):
            try:
                logger.info(f"Connecting to {self.url} (attempt {attempt})")
                self._ws = await websockets.connect(
                    self.url,
                    max_size=2**22,  # 4MB for large audio chunks
                    ping_interval=30,
                    ping_timeout=20,
                    close_timeout=5,
                )
                self._connected.set()
                logger.info(f"Connected to {self.url}")
                return
            except (OSError, websockets.exceptions.WebSocketException) as e:
                logger.warning(f"Connection attempt {attempt} failed: {e}")
                if attempt < self._max_retries:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 16.0)
                else:
                    raise ConnectionError(
                        f"Failed to connect to {self.url} after {self._max_retries} attempts"
                    ) from e

    async def disconnect(self) -> None:
        """Disable streams and close connection cleanly."""
        self._running = False
        self._connected.clear()
        if self._ws:
            try:
                await asyncio.wait_for(
                    self._send_stream_enable("audio_stream_enable", False),
                    timeout=2.0,
                )
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._ws.close(), timeout=3.0)
            except Exception:
                pass
            self._ws = None

    async def _safe_send(self, msg: str) -> bool:
        """Send a message, returning False if the connection is closed."""
        if not self._ws:
            return False
        try:
            await self._ws.send(msg)
            return True
        except (websockets.exceptions.ConnectionClosed, RuntimeError) as e:
            logger.debug(f"Send failed (connection closed): {e}")
            return False

    async def get_property(self, name: str, timeout: float = 5.0) -> str | None:
        """Send get_property request and wait for response.

        NOTE: The receive loop (run()) must be running concurrently.
        """
        if not self._ws:
            return None

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_gets[name] = future

        msg = json.dumps({"event_type": "get_property", "property": name})
        if not await self._safe_send(msg):
            self._pending_gets.pop(name, None)
            return None

        try:
            value = await asyncio.wait_for(future, timeout=timeout)
            return value
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for property: {name}")
            self._pending_gets.pop(name, None)
            return None

    async def set_property(self, name: str, value: str) -> None:
        """Send set_property (fire-and-forget)."""
        msg = json.dumps({
            "event_type": "set_property",
            "property": name,
            "value": str(value),
        })
        await self._safe_send(msg)
        logger.debug(f"Set {name} = {value}")

    async def _send_stream_enable(self, event_type: str, enable: bool) -> None:
        """Send stream enable/disable command."""
        msg = json.dumps({
            "event_type": event_type,
            "property": "",
            "value": "true" if enable else "false",
        })
        await self._safe_send(msg)

    async def enable_audio_stream(self) -> None:
        await self._send_stream_enable("audio_stream_enable", True)
        logger.info("Audio stream enabled")

    async def disable_audio_stream(self) -> None:
        await self._send_stream_enable("audio_stream_enable", False)
        logger.info("Audio stream disabled")

    async def enable_iq_stream(self) -> None:
        await self._send_stream_enable("iq_stream_enable", True)
        logger.info("IQ stream enabled")

    async def disable_iq_stream(self) -> None:
        await self._send_stream_enable("iq_stream_enable", False)
        logger.info("IQ stream disabled")

    async def enable_device_stream(self) -> None:
        await self._send_stream_enable("device_stream_enable", True)
        logger.info("Device stream enabled")

    def on_audio(self, callback: Callable[[np.ndarray], None]) -> None:
        """Register callback for audio data (int16 stereo interleaved)."""
        self._audio_callbacks.append(callback)

    def on_iq(self, callback: Callable[[np.ndarray], None]) -> None:
        """Register callback for IQ data (int16 IQ interleaved)."""
        self._iq_callbacks.append(callback)

    def on_overload(self, callback: Callable[[bool], None]) -> None:
        """Register callback for overload state changes from SDRConnect."""
        self._overload_callbacks.append(callback)

    async def run(self) -> None:
        """Main receive loop. Dispatches text and binary messages.

        Must be running for get_property() responses to be received.
        """
        self._running = True
        while self._running:
            try:
                await self._connected.wait()
                if not self._ws:
                    break
                async for message in self._ws:
                    if not self._running:
                        break
                    if isinstance(message, str):
                        self._handle_text(message)
                    elif isinstance(message, bytes):
                        self._handle_binary(message)
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket connection closed: {e}")
                self._connected.clear()
                if self._running:
                    try:
                        await self.connect()
                    except ConnectionError:
                        logger.error("Reconnection failed. Exiting.")
                        self._running = False
                        break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in receive loop: {e}")
                if self._running:
                    await asyncio.sleep(1)

    def _handle_text(self, message: str) -> None:
        """Parse JSON text message from SDRConnect."""
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON: {message[:100]}")
            return

        event_type = data.get("event_type", "")
        prop = data.get("property", "")
        value = data.get("value", "")

        if event_type in ("get_property_response", "property_changed"):
            # Resolve any pending get_property future
            future = self._pending_gets.pop(prop, None)
            if future and not future.done():
                future.set_result(value)

            # Track overload property (pushed by SDRConnect when ADC overloads)
            if prop == "overload":
                new_overload = value.lower() == "true"
                if new_overload != self.overload_flag:
                    self.overload_flag = new_overload
                    for cb in self._overload_callbacks:
                        try:
                            cb(new_overload)
                        except Exception:
                            pass

            logger.debug(f"Property {prop} = {value}")

    def _handle_binary(self, data: bytes) -> None:
        """Parse binary stream message. First 2 bytes are LE header."""
        if len(data) < 4:  # Need at least header + some data
            return

        header = struct.unpack_from("<H", data, 0)[0]
        payload = data[2:]

        if header == STREAM_AUDIO and self._audio_callbacks:
            samples = np.frombuffer(payload, dtype=np.int16)
            for cb in self._audio_callbacks:
                try:
                    cb(samples)
                except Exception as e:
                    logger.error(f"Audio callback error: {e}")

        elif header == STREAM_IQ and self._iq_callbacks:
            samples = np.frombuffer(payload, dtype=np.int16)
            for cb in self._iq_callbacks:
                try:
                    cb(samples)
                except Exception as e:
                    logger.error(f"IQ callback error: {e}")

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._connected.is_set()

    async def configure_wwvb(
        self,
        antenna: str = "Hi-Z",
        if_gain: int | None = None,
        rf_gain: int | None = None,
    ) -> dict[str, str]:
        """Configure SDRConnect for WWVB 60 kHz reception.

        NOTE: The receive loop must be running concurrently so that
        get_property responses are dispatched.

        Returns:
            Dict of verified property values.
        """
        results = {}

        # Check if we can control
        can_control = await self.get_property("can_control")
        if can_control == "false":
            logger.warning("Another client may have control. Tune commands may be ignored.")
        results["can_control"] = can_control or "unknown"

        # Check if device is started
        started = await self.get_property("started")
        if started == "false":
            await self.enable_device_stream()
            await asyncio.sleep(0.5)

        # Set tuning - fire all set_property calls quickly (no response needed)
        await self.set_property("device_center_frequency", "60000")
        await self.set_property("device_vfo_frequency", "60000")
        await self.set_property("demodulator", "AM")
        await self.set_property("filter_bandwidth", "100")

        # Disable processing that would distort pulses
        await self.set_property("squelch_enable", "false")
        await self.set_property("agc_enable", "false")
        await self.set_property("noise_reduction_enable", "false")
        await self.set_property("audio_filter", "false")
        await self.set_property("audio_limiters", "false")
        await self.set_property("am_lowcut_frequency", "0")

        # Set antenna
        await self.set_property("antenna_select", antenna)

        # Set gain if specified
        if if_gain is not None:
            await self.set_property("device_if_gain_reduction", str(if_gain))
            logger.info(f"IF gain reduction set to {if_gain}")
            results["if_gain"] = str(if_gain)

        if rf_gain is not None:
            await self.set_property("lna_state", str(rf_gain))
            logger.info(f"LNA state (RF gain) set to {rf_gain}")
            results["rf_gain"] = str(rf_gain)

        # Brief pause for settings to take effect, then verify
        await asyncio.sleep(0.5)

        verify_props = [
            "device_center_frequency",
            "device_vfo_frequency",
            "demodulator",
            "filter_bandwidth",
        ]
        for prop in verify_props:
            val = await self.get_property(prop, timeout=3.0)
            results[prop] = val or "unknown"
            logger.info(f"Verified {prop} = {val}")

        # NOTE: The 'overload' property is not readable via get_property on
        # most SDR hardware (including RSPdx). Overload state is detected via
        # push events (property_changed) in _handle_text() instead.
        results["overload_monitoring"] = "push events only"

        return results
