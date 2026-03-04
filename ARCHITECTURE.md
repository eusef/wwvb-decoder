# swl-wwvb-tool - Implementation Architecture

**Version:** 0.1.0
**Date:** 2026-03-04
**Status:** Ready for developer handoff

---

## 1. Implementation Phases

Build in this order. Each phase produces a testable artifact before moving on.

| Phase | Deliverable | Test Method | Est. Effort |
|-------|-------------|-------------|-------------|
| 1 - Project scaffold | Package structure, CLI, dependencies | `pip install -e .` and `wwvb-decode --help` | 1-2 hrs |
| 2 - SDRConnect client | WebSocket client with property get/set and binary stream dispatch | Unit tests with mock WebSocket server | 4-6 hrs |
| 3 - Envelope detector | Audio stream -> amplitude envelope -> normalized 0.0-1.0 signal | Unit tests with synthetic PCM data | 3-4 hrs |
| 4 - Pulse decoder | Envelope -> pulse width measurement -> symbol classification (0/1/M) | Unit tests with known pulse patterns | 3-4 hrs |
| 5 - Frame parser | 60-symbol buffer -> BCD extraction -> time struct -> validation | Unit tests with known bit patterns | 3-4 hrs |
| 6 - State machine | CONNECTING -> CONFIGURING -> SYNCING -> DECODING -> DECODED loop | Unit tests for state transitions | 2-3 hrs |
| 7 - Plain output | `--plain` mode with timestamped log lines | Manual test against SDRConnect | 1-2 hrs |
| 8 - Rich TUI | Full Rich Live display with all 6 panels | Manual test against SDRConnect | 6-8 hrs |
| 9 - Integration test | End-to-end with recorded data playback | Replay recorded audio file through mock WS | 3-4 hrs |
| 10 - Live test | Real hardware decode and comparison with NTP | Manual with RSPdx + antenna | 2-4 hrs |

**Total estimate:** 28-41 hours of developer time.

---

## 2. Module Dependency Graph

```
cli.py
  |
  v
__main__.py
  |
  +---> sdrconnect.py (WebSocket client)
  |         |
  |         +---> envelope.py (audio stream processing)
  |         |         |
  |         |         v
  |         |    decoder.py (pulse width -> symbols)
  |         |         |
  |         |         v
  |         |    frame.py (symbol buffer -> time struct)
  |         |
  |         v
  |    state.py (orchestrates the pipeline, holds app state)
  |         |
  |         +---> tui.py (Rich Live display)
  |         +---> plain.py (plain text output)
  v
pyproject.toml / requirements.txt
```

Dependency rule: modules only import downward. `sdrconnect.py` does not import `state.py`. State owns the pipeline and calls into the other modules.

---

## 3. Module Specifications

### 3.1 `cli.py` - Command Line Interface

**Responsibility:** Parse arguments, validate inputs, return a config dataclass.

```python
@dataclass
class Config:
    host: str           # default "127.0.0.1"
    port: int           # default 5454
    no_tune: bool       # default False
    source: str         # "audio" or "iq"
    threshold: float    # 0.0-1.0, default 0.5
    min_frames: int     # default 2
    plain: bool         # default False
    debug: bool         # default False (implies plain=True)
```

Use `argparse`. No subcommands. Single entry point.

### 3.2 `sdrconnect.py` - WebSocket Client

**Responsibility:** Manage the WebSocket connection, send/receive JSON messages, dispatch binary streams.

Key design decisions:

- Use `websockets` async library. The entire app runs on `asyncio`.
- Provide callback-based API for binary data: `on_audio(samples: np.ndarray)`, `on_iq(samples: np.ndarray)`
- Provide async methods: `get_property(name) -> str`, `set_property(name, value)`, `enable_audio_stream()`, etc.
- Handle reconnection internally with exponential backoff (1s, 2s, 4s, 8s, 16s max). 5 attempts then exit.
- Parse binary messages: strip 2-byte LE header, convert remaining bytes to numpy arrays.

```python
class SDRConnectClient:
    def __init__(self, host: str, port: int):
        ...

    async def connect(self) -> None:
        """Connect to WebSocket. Raises ConnectionError after max retries."""

    async def disconnect(self) -> None:
        """Disable streams, close WebSocket cleanly."""

    async def get_property(self, name: str) -> str:
        """Send get_property, await get_property_response. Timeout 5s."""

    async def set_property(self, name: str, value: str) -> None:
        """Send set_property. No response expected (fire-and-forget)."""

    async def enable_audio_stream(self) -> None:
    async def disable_audio_stream(self) -> None:
    async def enable_iq_stream(self) -> None:
    async def disable_iq_stream(self) -> None:
    async def enable_device_stream(self) -> None:

    def on_audio(self, callback: Callable[[np.ndarray], None]) -> None:
        """Register callback for audio data. Array is int16, stereo interleaved."""

    def on_iq(self, callback: Callable[[np.ndarray], None]) -> None:
        """Register callback for IQ data. Array is int16, IQ interleaved."""

    async def run(self) -> None:
        """Main receive loop. Dispatches text/binary messages."""
```

**Important API detail from the reference implementations:**

The `event_type` for stream enable messages uses the literal string as the event_type itself (not `set_property`). For example:

```json
{"event_type": "audio_stream_enable", "property": "", "value": "true"}
{"event_type": "device_stream_enable", "property": "", "value": "true"}
```

This is different from property get/set which uses `"event_type": "set_property"`.

**Startup sequence (when `--no-tune` is NOT set):**

1. Connect WebSocket
2. Read `can_control` - warn if `false` but continue
3. Read `started` - if `false`, send `device_stream_enable` = `true`
4. Set `device_center_frequency` = `60000`
5. Set `device_vfo_frequency` = `60000`
6. Set `demodulator` = `AM`
7. Set `filter_bandwidth` = `100`
8. Set `squelch_enable` = `false`
9. Set `agc_enable` = `false`
10. Set `noise_reduction_enable` = `false`
11. Set `audio_filter` = `false`
12. Set `audio_limiters` = `false`
13. Set `am_lowcut_frequency` = `0` (see open question OQ-1)
14. Send `audio_stream_enable` = `true`

**Startup sequence (when `--no-tune` IS set):**

1. Connect WebSocket
2. Read `started` - if `false`, send `device_stream_enable` = `true`
3. Send `audio_stream_enable` = `true`

### 3.3 `envelope.py` - Envelope Detection

**Responsibility:** Convert raw audio PCM stream to a normalized amplitude envelope.

```python
class EnvelopeDetector:
    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        self._filter = None  # scipy Butterworth LPF
        self._min_val = float('inf')
        self._max_val = float('-inf')
        self._window_seconds = 10  # min/max normalization window

    def process(self, audio_stereo: np.ndarray) -> np.ndarray:
        """
        Input: int16 stereo interleaved (LRLR) from SDRConnect
        Output: float64 normalized envelope (0.0 - 1.0), mono, at reduced rate

        Steps:
        1. Extract left channel (every other sample)
        2. Convert to float, take absolute value
        3. Apply 4th-order Butterworth LPF at 5 Hz cutoff
        4. Normalize using running min/max window
        """

    def get_recent_envelope(self, seconds: float = 5.0) -> np.ndarray:
        """Return last N seconds of envelope for TUI display."""
```

**Filter design:**

- Butterworth lowpass, order 4, cutoff 5 Hz
- At 48 kHz sample rate, this is well within stable design range
- Use `scipy.signal.butter` + `scipy.signal.sosfilt` (second-order sections for numerical stability)
- The 5 Hz cutoff preserves the ~1 Hz pulse rate while smoothing out audio frequency content

**Downsampling consideration:**

After the LPF at 5 Hz cutoff, the envelope signal bandwidth is ~5 Hz. The developer could decimate to 100 Hz (every 480th sample) to reduce downstream processing. This is optional but recommended for keeping pulse measurement simple. If implemented, use `scipy.signal.decimate`.

### 3.4 `decoder.py` - Pulse Width Decoder

**Responsibility:** Convert the continuous envelope signal into discrete symbols (0, 1, M, or error).

```python
@dataclass
class Pulse:
    start_time: float    # seconds since stream start
    duration_ms: float   # pulse width in milliseconds
    symbol: str          # "0", "1", "M", or "?"

class PulseDecoder:
    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        self._state = "HIGH"  # or "LOW"
        self._low_start = 0.0
        self._sample_count = 0

    def process(self, envelope: np.ndarray, sample_rate: float) -> list[Pulse]:
        """
        Detect falling/rising edges in envelope.
        Measure low-power duration.
        Classify:
          100-350 ms -> "0"
          350-650 ms -> "1"
          650-900 ms -> "M"
          outside    -> "?"

        Uses sample count for timing, NOT wall clock.
        """

    @property
    def avg_pulse_widths(self) -> dict[str, float]:
        """Running averages for stats display: {"0": ms, "1": ms, "M": ms}"""
```

**Critical timing note:** At 48 kHz, 1 ms = 48 samples. Even after decimation to 100 Hz, 1 ms ~= 0.1 samples. For accurate pulse width measurement, the developer should measure at the full 48 kHz rate (or at least a decimated rate that gives sub-ms precision, e.g. 1000 Hz). The 5 Hz LPF output can still be at a higher sample rate than its bandwidth - it just means the samples are correlated. Recommend keeping the envelope at 1000 Hz (decimate by 48) for pulse measurement.

**Edge detection approach:**

- Hysteresis thresholding to avoid chatter: use `threshold + 0.05` for rising edge, `threshold - 0.05` for falling edge
- Reject pulses shorter than 80 ms (noise) or longer than 1000 ms (missed edge)
- If two falling edges occur without a rising edge between them, treat as a missed rising edge and reset

### 3.5 `frame.py` - Frame Assembly and BCD Parsing

**Responsibility:** Buffer 60 symbols into a frame, parse BCD fields, validate, produce a decoded time.

```python
@dataclass
class WWVBTime:
    year: int          # 2000-2099
    day_of_year: int   # 1-366
    hour: int          # 0-23
    minute: int        # 0-59
    dut1: float        # -0.9 to +0.9 seconds
    dst: str           # "off", "begins_today", "ends_today", "on"
    leap_year: bool
    leap_second_warning: bool

    def to_utc_string(self) -> str:
        """Format as '2026-03-05 03:18 UTC'"""

    def to_date(self) -> datetime.date:
        """Convert year + day_of_year to a date."""

class FrameAssembler:
    def __init__(self, min_frames: int = 2):
        self._buffer: list[str | None] = [None] * 60
        self._position = 0
        self._synced = False
        self._consecutive_markers = 0
        self._valid_frames: list[WWVBTime] = []
        self._min_frames = min_frames

    def add_symbol(self, symbol: str) -> FrameEvent | None:
        """
        Add a decoded symbol. Returns event if significant:
        - FrameEvent.SYNC_PROGRESS (found N of 2 consecutive markers)
        - FrameEvent.SYNC_ACQUIRED
        - FrameEvent.FRAME_COMPLETE (with WWVBTime if valid)
        - FrameEvent.FRAME_ERROR (with reason string)
        - None (normal bit, no event)
        """

    def parse_frame(self, bits: list[str]) -> tuple[WWVBTime | None, str | None]:
        """
        Parse a complete 60-symbol frame.
        Returns (time, None) on success or (None, error_reason) on failure.

        Validation steps:
        1. Verify markers at positions 0, 9, 19, 29, 39, 49 (59 is next frame's 0)
        2. Verify unused positions are "0"
        3. Extract BCD fields, convert to decimal
        4. Range check: minutes 0-59, hours 0-23, day 1-366, year 0-99
        5. Cross-check leap year indicator with year value
        """

    @property
    def current_position(self) -> int:
        """Current second within frame (0-59)."""

    @property
    def current_bits(self) -> list[str | None]:
        """Current frame buffer for TUI display."""

    @property
    def is_synced(self) -> bool

    @property
    def confirmed_time(self) -> WWVBTime | None:
        """Most recent time confirmed by min_frames consecutive matches."""
```

**Sync algorithm:**

1. Before sync: watch for marker symbols ("M"). When two consecutive symbols are both "M", that's the :59/:00 boundary.
2. After sync: position 0 is the next symbol after the double-marker. Fill positions 0-59.
3. At position 59: expect marker. If not marker, log error and restart sync.
4. After parsing: compare with previous frame. If `min_frames` consecutive frames agree on time (incrementing by 1 minute each), declare confirmed.

**BCD extraction helper:**

```python
def bcd_decode(bits: list[str], weights: list[int]) -> int:
    """
    bits: list of "0"/"1" strings
    weights: corresponding BCD weights
    Returns: decoded integer
    Example: bcd_decode(["1","0","1","0"], [8,4,2,1]) -> 10
    """
    return sum(int(b) * w for b, w in zip(bits, weights))
```

### 3.6 `state.py` - State Machine / Orchestrator

**Responsibility:** Owns the application lifecycle, connects all modules, drives the event loop.

```python
class AppState(Enum):
    CONNECTING = "CONNECTING"
    CONFIGURING = "CONFIGURING"
    WAITING_FOR_DATA = "WAITING"
    SYNCING = "SYNCING"
    DECODING = "LIVE"
    DECODED = "LIVE"       # brief state after successful decode
    FRAME_ERROR = "LIVE"   # brief state after frame error
    DISCONNECTED = "DISCONNECTED"

class WWVBApp:
    def __init__(self, config: Config):
        self.config = config
        self.state = AppState.CONNECTING
        self.client = SDRConnectClient(config.host, config.port)
        self.envelope = EnvelopeDetector()
        self.decoder = PulseDecoder(threshold=config.threshold)
        self.assembler = FrameAssembler(min_frames=config.min_frames)
        self.display = None  # TUI or Plain, created after config parsed
        self.stats = Stats()

    async def run(self) -> None:
        """
        Main entry point. Runs until Ctrl+C or connection failure.

        1. Create display (TUI or Plain based on config)
        2. Connect to SDRConnect
        3. Configure radio (unless --no-tune)
        4. Register audio callback
        5. Enter main loop:
           - Audio callback -> envelope -> pulses -> symbols -> frame events
           - Update display on each significant event
           - Poll signal_power/signal_snr every 2 seconds
        6. On Ctrl+C: print summary, disable streams, disconnect
        """

    def _on_audio(self, samples: np.ndarray) -> None:
        """Audio callback from SDRConnect client. Runs in asyncio context."""
        envelope = self.envelope.process(samples)
        pulses = self.decoder.process(envelope, self.envelope.effective_rate)
        for pulse in pulses:
            event = self.assembler.add_symbol(pulse.symbol)
            if event:
                self._handle_event(event)

    def _handle_event(self, event: FrameEvent) -> None:
        """Update state machine, stats, and display based on event."""
```

**asyncio architecture:**

- Single event loop
- `SDRConnectClient.run()` is a long-running coroutine that reads WebSocket messages
- Audio processing happens synchronously within the audio callback (fast enough at 1 bps data rate)
- Signal polling is a separate periodic coroutine (`asyncio.create_task`)
- TUI refresh is a separate periodic coroutine (1 Hz)
- `Ctrl+C` handled via `asyncio.get_event_loop().add_signal_handler`

### 3.7 `tui.py` - Rich TUI Display

**Responsibility:** Render all 6 panels using Rich Live display.

```python
class TUIDisplay:
    def __init__(self):
        self._live = Live(refresh_per_second=1)

    def start(self) -> None:
        self._live.start()

    def stop(self) -> None:
        self._live.stop()

    def update(self, state: WWVBApp) -> None:
        """Rebuild layout from current app state and call live.update()."""

    def _render_header(self, state) -> Panel:
        """Connection status, frequency, mode, uptime."""

    def _render_signal(self, state) -> Panel:
        """Power bar, SNR, quality sparkline, envelope trace."""

    def _render_frame(self, state) -> Panel:
        """Progress bar, bit display with field colors, countdown."""

    def _render_time(self, state) -> Panel:
        """Big ASCII clock, date line, DUT1, DST."""

    def _render_stats(self, state) -> Panel:
        """Frame counts, success rate, pulse averages."""

    def _render_log(self, state) -> Panel:
        """Last 10 activity log entries."""
```

**Big clock rendering:** Use a simple 5x7 digit font stored as a dict mapping digits to list-of-strings. No external figlet dependency needed.

**Envelope trace:** Single line of ~60 characters using Unicode block elements (similar to sparkline but horizontal). Map last 5 seconds of envelope samples to characters.

**Frame bit display color coding:** Use Rich's `[cyan]`, `[green]`, `[yellow]`, `[magenta]`, `[blue]`, `[white]`, `[dim]` markup per the spec's field color assignments.

### 3.8 `plain.py` - Plain Text Output

**Responsibility:** Simple timestamped log lines to stdout.

```python
class PlainDisplay:
    def log(self, category: str, message: str) -> None:
        """Print '[YYYY-MM-DD HH:MM:SS] CATEGORY message'"""
```

Categories: CONNECT, CONFIG, STREAM, SYNC, SIGNAL, DECODE, STATS, ERROR, WARN.

Same interface as TUIDisplay where it matters (start/stop/update) so state.py doesn't need to know which one it's using.

---

## 4. Data Flow Detail

```
SDRConnect WS  --(binary 0x0001)-->  sdrconnect.py
    |
    | int16 stereo PCM @ 48kHz (LRLR interleaved)
    v
envelope.py
    |
    | 1. Extract left channel
    | 2. abs() -> float
    | 3. Butterworth LPF 5 Hz
    | 4. Decimate to 1000 Hz
    | 5. Normalize 0.0-1.0
    v
decoder.py
    |
    | 1. Hysteresis threshold crossing
    | 2. Measure low-power duration (ms)
    | 3. Classify: 0/1/M/?
    v
frame.py
    |
    | 1. Buffer into 60-position array
    | 2. Sync on double-marker
    | 3. Parse BCD fields
    | 4. Validate ranges + markers
    | 5. Multi-frame confirmation
    v
state.py  --->  tui.py or plain.py
```

---

## 5. Key Technical Decisions

### 5.1 asyncio vs threading

**Decision: asyncio throughout.**

The `websockets` library is natively async. Audio processing is lightweight (1 bps data rate means we process ~48,000 samples to extract 1 bit). No CPU-bound work that would benefit from threading. Single-threaded async avoids all concurrency bugs.

### 5.2 Envelope sample rate for pulse measurement

**Decision: Decimate to 1000 Hz (not lower).**

At 1000 Hz, each sample is 1 ms. A 200 ms pulse is 200 samples. This gives clean integer-ish measurements without excessive computation. Lower rates (e.g., 100 Hz) would give only 20 samples per pulse, making classification noisier.

### 5.3 Protocol for get_property response matching

**Decision: Use a simple async future with timeout.**

When `get_property` is sent, store the property name and an `asyncio.Future`. When a `get_property_response` arrives for that property, resolve the future. Timeout after 5 seconds. Only one outstanding get per property at a time.

### 5.4 Audio callback threading model

**Decision: Audio processing runs inline in the receive loop.**

Since the receive loop is async and audio processing takes microseconds relative to the ~20ms between audio chunks (48000 samples/sec, typical WebSocket frame of ~960 samples = 20ms), there's no need to offload to a separate thread or queue. If profiling shows this is too slow, add an `asyncio.Queue` between receive and processing.

### 5.5 Display interface abstraction

**Decision: Duck typing, not an ABC.**

Both `TUIDisplay` and `PlainDisplay` implement `start()`, `stop()`, and `update(state)`. No formal interface class needed. State machine calls whichever one was created based on `--plain`.

---

## 6. Open Questions for Phil

These need answers (or hardware testing) before implementation is complete. None block starting Phase 1-6.

### OQ-1: `am_lowcut_frequency` effect on audio stream

**Question:** Does setting `am_lowcut_frequency` to 0 Hz change the audio stream content in a way that helps envelope detection? Or does the audio stream always carry the full amplitude envelope regardless?

**Why it matters:** If SDRConnect's AM low-cut filter at 50 Hz removes the DC/near-DC component from the audio, the envelope might appear as AC-coupled (oscillating around zero rather than showing clear high/low levels). Setting it to 0 would preserve the DC offset.

**Test plan:** Connect to RSPdx tuned to 60 kHz AM. Record a few seconds of audio stream with `am_lowcut_frequency` at 50 (default) and at 0. Compare the waveforms. If the 50 Hz version still shows clear amplitude variation between full-power and reduced-power periods, it's fine.

**Default for now:** Set to 0 during configuration (safe default). Add a `--am-lowcut` CLI flag if needed.

### OQ-2: Audio stream sample delivery size and timing

**Question:** How large are the binary audio chunks from SDRConnect? Is it consistent (fixed size per message) or variable?

**Why it matters:** The envelope detector needs to handle whatever chunk size arrives. The C# reference just copies the entire buffer, suggesting variable sizes. The developer should handle any chunk size gracefully, but knowing the typical size helps with buffer pre-allocation.

**Test plan:** Log the byte count of the first 100 audio binary messages. Check min/max/average.

**Default for now:** Handle any size. Use numpy append for simplicity, optimize later if needed.

### OQ-3: `device_stream_enable` behavior

**Question:** Does `device_stream_enable` start the RSP hardware, or does it just enable the data stream to this WebSocket client? If the device is already running (started=true) for another client, does calling this cause any disruption?

**Why it matters:** The app needs to decide whether to call `device_stream_enable` blindly or only conditionally.

**Test plan:** With SDRConnect open and device running, connect the tool and read `started`. If true, skip `device_stream_enable`. If false, send it and check if device starts. Test both paths.

**Default for now:** Check `started` first, only send `device_stream_enable` if false (your preferred approach).

### OQ-4: Write verification for critical properties

**Question:** The property report showed writes that didn't read back correctly (e.g., `agc_enable` wrote `false` but read back `true`). Is this a timing issue (need a delay between write and readback) or does it indicate the property was rejected?

**Why it matters:** If writes silently fail, the tool could think AGC is off when it's still on, leading to unstable amplitude and bad decodes.

**Test plan:** With device connected and streaming, write `agc_enable` = `false`, wait 500ms, read it back. Repeat for each critical property. Log results.

**Default for now:** Write all properties, then read them back with a small delay. Log warnings for any mismatches. Don't block execution on mismatches (the user can always use `--no-tune`).

### OQ-5: `antenna_select` for VLF

**Question:** The property report shows `antenna_select` as not readable but blindly writable with `"Hi-Z"`. For RSPdx at 60 kHz, Hi-Z is the correct antenna port. Should the tool set this, or leave it to the user?

**Why it matters:** Wrong antenna port = no signal at 60 kHz.

**Test plan:** Not needed if we add it as an optional CLI flag.

**Default for now:** Add `--antenna` CLI flag (default `Hi-Z`). Send `antenna_select` write during configuration unless `--no-tune` is set. Since we can't read it back, just log what we sent.

---

## 7. Error Handling Strategy

| Error | Response |
|-------|----------|
| WebSocket connection refused | Retry with exponential backoff (1s, 2s, 4s, 8s, 16s). Exit after 5 failures. |
| WebSocket drops mid-stream | Log disconnect. Re-enter CONNECTING state. Retry same backoff. Reset frame sync. |
| `can_control` is false | Log warning: "Another client may have control. Tune commands may be ignored." Continue. |
| Property write mismatch | Log warning per property. Continue. |
| Pulse width outside all ranges | Classify as "?". Log in activity log. Don't count toward frame. |
| Frame marker validation fail | Log specific position. Increment error counter. Reset for next frame. |
| Frame BCD range validation fail | Log specific field and value. Increment error counter. Reset for next frame. |
| No audio data for 10 seconds | Log warning. Check `started` property. If false, attempt `device_stream_enable`. |
| Ctrl+C | Graceful shutdown: print summary, disable streams, close WS, exit 0. |

---

## 8. Testing Strategy

### 8.1 Unit Test Plan

| Test File | What It Tests | Key Test Cases |
|-----------|---------------|----------------|
| `test_envelope.py` | EnvelopeDetector | Synthetic sine wave -> envelope is flat; Synthetic AM pulse (200ms low) -> correct envelope shape; Stereo interleave handling |
| `test_decoder.py` | PulseDecoder | 200ms low -> "0"; 500ms low -> "1"; 800ms low -> "M"; 50ms low -> rejected; Edge cases at classification boundaries (350ms, 650ms) |
| `test_frame.py` | FrameAssembler, BCD parsing | Known NIST example frame -> correct time; Missing marker -> error; Out-of-range hour -> error; Two consecutive good frames -> confirmed time |
| `test_state.py` | AppState transitions | CONNECTING->CONFIGURING->WAITING->SYNCING->DECODING; Disconnect during any state -> DISCONNECTED; Reconnect -> CONNECTING |
| `test_sdrconnect.py` | SDRConnectClient | Mock WS server: JSON get/set round trip; Binary audio dispatch; Binary IQ dispatch; Reconnection on close |

### 8.2 Synthetic Test Data Generator

Build a utility (`tests/generate_test_data.py`) that creates:

1. A fake audio stream encoding a known WWVB frame (e.g., 2026-03-05 03:18 UTC)
2. The stream has proper pulse widths (200/500/800 ms) with configurable noise
3. Output as raw PCM int16 stereo @ 48kHz
4. Can be fed through the full pipeline for integration testing

This is critical for development since you won't always have the RSP hardware available.

### 8.3 Mock WebSocket Server

Build a minimal WebSocket server (`tests/mock_server.py`) that:

1. Accepts connections on configurable port
2. Responds to `get_property` with canned values
3. Acknowledges `set_property` with `property_changed`
4. Streams pre-recorded audio binary data at realistic rate
5. Can simulate disconnects on demand

---

## 9. File-by-File Implementation Notes

### `pyproject.toml`

```toml
[project]
name = "wwvb-decode"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "websockets>=12.0",
    "numpy>=1.24",
    "scipy>=1.10",
    "rich>=13.0",
]

[project.scripts]
wwvb-decode = "wwvb_decode.__main__:main"
```

### `requirements.txt`

Pin exact versions after initial `pip install`. For development:

```
websockets>=12.0
numpy>=1.24
scipy>=1.10
rich>=13.0
pytest>=7.0
```

### `__main__.py`

```python
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
        pass  # graceful shutdown handled in app.run()
    sys.exit(0)

if __name__ == "__main__":
    main()
```

---

## 10. Platform Notes (macOS first)

- **macOS**: Primary development target. Python 3.10+ via Homebrew or pyenv. No platform-specific code expected.
- **Windows**: SDRConnect runs natively on Windows. The tool should work via `python -m wwvb_decode`. Test `Ctrl+C` handling on Windows (use `signal.signal` fallback if `add_signal_handler` fails).
- **Linux**: Raspberry Pi is a likely deployment target. Test with Python 3.10+ on ARM. Rich terminal rendering should work in any modern terminal.

No platform-specific code in Phase 1-9. Platform edge cases surface in Phase 10 (live testing).

---

## 11. Dependency Justification

| Package | Why | Alternatives Considered |
|---------|-----|------------------------|
| `websockets` | Native asyncio WebSocket client. Clean API. Well-maintained. | `aiohttp` (heavier, more features than needed) |
| `numpy` | Array math for audio samples. Universal standard. | Pure Python (too slow for 48kHz stream) |
| `scipy` | Butterworth filter design. Small, targeted use. | `numpy` only (would need manual filter impl) |
| `rich` | TUI panels, progress bars, sparklines, colored text. No terminal deps. | `curses` (much more work), `textual` (overkill) |

---

## 12. Glossary

| Term | Definition |
|------|-----------|
| BCD | Binary-Coded Decimal. Each decimal digit encoded separately in binary. |
| DUT1 | Difference between UTC and UT1 (earth rotation time). Broadcast to 0.1s precision. |
| Envelope | The amplitude outline of a modulated signal. For AM, tracks carrier power changes. |
| Frame | One complete 60-second WWVB transmission containing time data. |
| IQ | In-phase / Quadrature. Complex signal representation from SDR hardware. |
| LPF | Low-Pass Filter. Removes high-frequency content above a cutoff. |
| PWM | Pulse Width Modulation. Information encoded in the duration of pulses. |
| VFO | Variable Frequency Oscillator. The tuned receive frequency. |
| VLF | Very Low Frequency. 3-30 kHz band. WWVB at 60 kHz is technically LF. |
