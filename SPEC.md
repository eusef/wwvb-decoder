# swl-wwvb-tool - Product Specification

**Version:** 0.1.0-draft
**Date:** 2026-03-04
**Status:** Draft

---

## 1. Overview

A Python CLI tool with a real-time Rich console TUI that connects to an SDRConnect (Simon Brown / SDR-Radio.com) instance via its WebSocket API, tunes to the WWVB time station at 60 kHz, receives the audio data stream, and decodes the AM/PWM time code. The TUI displays live signal status, frame decode progress, decoded time, and signal quality history so the user always knows what the tool is doing and how long until the next decode completes.

## 2. Problem Statement

WWVB is the US national time standard broadcast from Fort Collins, CO at 60 kHz. Decoding it with an SDR requires tuning to VLF, extracting the amplitude envelope, and interpreting the pulse-width-modulated BCD time code. No existing Python tool bridges the SDRConnect WebSocket API to a WWVB decoder.

## 3. Hardware and Software Prerequisites

| Component | Requirement |
|-----------|------------|
| SDR Hardware | SDRplay RSP-series (RSPdx, RSP1A, RSP1B, RSP2, RSPduo) |
| SDR Software | SDRConnect (Simon Brown) with WebSocket API enabled |
| Antenna | VLF-capable antenna (long wire, loop, or ferrite bar for 60 kHz) |
| Network | WebSocket access to SDRConnect instance (local or remote) |
| Python | 3.10+ |
| OS | macOS, Linux, Windows (cross-platform) |

## 4. Architecture

```
┌─────────────┐     WebSocket      ┌──────────────────┐
│ SDRConnect   │◄──────────────────►│  swl-wwvb-tool   │
│ (RSP radio)  │   ws://host:5454   │                  │
│              │                    │  ┌──────────────┐ │
│  60 kHz VFO  │   IQ stream        │  │ IQ Receiver  │ │
│  AM demod    │   (binary 0x0002)  │  └──────┬───────┘ │
│              │                    │         │         │
│              │   Audio stream     │  ┌──────▼───────┐ │
│              │   (binary 0x0001)  │  │ Envelope     │ │
│              │                    │  │ Detector     │ │
│              │                    │  └──────┬───────┘ │
│              │                    │         │         │
│              │                    │  ┌──────▼───────┐ │
│              │                    │  │ Pulse Width  │ │
│              │                    │  │ Decoder      │ │
│              │                    │  └──────┬───────┘ │
│              │                    │         │         │
│              │                    │  ┌──────▼───────┐ │
│              │                    │  │ BCD Frame    │ │
│              │                    │  │ Parser       │ │
│              │                    │  └──────┬───────┘ │
│              │                    │         │         │
│              │                    │  ┌──────▼───────┐ │
│              │                    │  │ TUI Display  │ │
│              │                    │  │ (Rich Live)  │ │
│              │                    │  └──────────────┘ │
└─────────────┘                    └──────────────────┘
```

## 5. SDRConnect WebSocket API Integration

### 5.1 Connection

The tool connects to SDRConnect's WebSocket API at `ws://<host>:<port>` (default port 5454). All JSON messages use the envelope:

```json
{
  "event_type": "<string>",
  "property": "<string>",
  "value": "<string>"
}
```

### 5.2 Startup Sequence

1. Connect to WebSocket at `ws://<host>:5454`
2. Verify connection by reading `started` property
3. Configure radio for WWVB reception:
   - Set `device_center_frequency` to `60000` (60 kHz)
   - Set `device_vfo_frequency` to `60000`
   - Set `demodulator` to `AM`
   - Set `filter_bandwidth` to `100` (100 Hz - narrow for clean pulse detection)
   - Disable squelch: set `squelch_enable` to `false`
   - Disable AGC: set `agc_enable` to `false` (stable amplitude needed for PWM decoding)
   - Set `noise_reduction_enable` to `false` (preserve pulse shape)
4. Enable data streaming:
   - Send `audio_stream_enable` with value `true` (demodulated AM audio for envelope detection)
   - Optionally send `iq_stream_enable` with value `true` (raw IQ for advanced processing)

### 5.3 Binary Data Streams

Binary WebSocket messages have a 2-byte little-endian header identifying the payload type:

| Header | Type | Format |
|--------|------|--------|
| 0x0001 | Audio | Signed 16-bit PCM stereo @ 48kHz (LRLR interleaved) |
| 0x0002 | IQ | Signed 16-bit interleaved IQ (IQIQ) |
| 0x0003 | Spectrum | Unsigned 8-bit FFT bins |

### 5.4 Primary Data Path

**Audio stream (0x0001)** is the primary data path. SDRConnect performs AM demodulation internally, so the audio stream already contains the baseband amplitude envelope of the WWVB carrier. This is the simplest path to pulse-width detection.

**IQ stream (0x0002)** is the fallback/advanced path. If the audio stream proves insufficient (e.g., distorted envelope), the tool can compute the amplitude envelope directly from IQ data as `sqrt(I^2 + Q^2)`.

### 5.5 Key API Properties Used

| Property | Read/Write | Purpose |
|----------|-----------|---------|
| `device_center_frequency` | R/W | Set hardware LO to 60 kHz |
| `device_vfo_frequency` | R/W | Set VFO to 60 kHz |
| `demodulator` | R/W | Set to AM mode |
| `filter_bandwidth` | R/W | Narrow filter for clean detection |
| `agc_enable` | R/W | Disable for stable amplitude |
| `squelch_enable` | R/W | Disable to avoid gating |
| `noise_reduction_enable` | R/W | Disable to preserve pulse edges |
| `signal_power` | R | Monitor signal strength |
| `signal_snr` | R | Monitor signal quality |
| `started` | R | Confirm device is streaming |
| `can_control` | R | Confirm we have control |

## 6. WWVB Signal Format

### 6.1 Carrier

- Frequency: 60,000 Hz
- Location: Fort Collins, Colorado (40.68N, 105.04W)
- ERP: 70 kW (full power), reduced to 1.4 kW during low-power pulses
- Modulation: AM/PWM at 1 bit per second (legacy), plus BPSK phase modulation (since 2012)

### 6.2 AM/PWM Encoding (Legacy - target for v1)

At the start of each UTC second, the carrier power drops by 17 dB. The duration of the low-power period encodes one of three symbols:

| Duration | Symbol | Meaning |
|----------|--------|---------|
| 200 ms | 0 | Binary zero |
| 500 ms | 1 | Binary one |
| 800 ms | M | Position marker |

### 6.3 Frame Structure (60 bits per minute)

One complete frame is transmitted every 60 seconds (seconds :00 through :59). The frame encodes the time as of the start of that minute.

```
Sec  Field             Weight   Notes
---  -----             ------   -----
 0   Frame Ref Marker  M        Always marker (0.8s)
 1   Minutes (tens)    40
 2   Minutes (tens)    20
 3   Minutes (tens)    10
 4   Unused            0        Always 0
 5   Minutes (units)   8
 6   Minutes (units)   4
 7   Minutes (units)   2
 8   Minutes (units)   1
 9   Marker P1         M        Always marker
10   Unused            0        Always 0
11   Unused            0        Always 0
12   Hours (tens)      20
13   Hours (tens)      10
14   Unused            0        Always 0
15   Hours (units)     8
16   Hours (units)     4
17   Hours (units)     2
18   Hours (units)     1
19   Marker P2         M        Always marker
20   Unused            0        Always 0
21   Unused            0        Always 0
22   Day of Year (100s) 200
23   Day of Year (100s) 100
24   Day of Year (tens) 80
25   Day of Year (tens) 40
26   Day of Year (tens) 20
27   Day of Year (tens) 10
28   Unused            0        Always 0
29   Marker P3         M        Always marker
30   Day of Year (units) 8
31   Day of Year (units) 4
32   Day of Year (units) 2
33   Day of Year (units) 1
34   Unused            0        Always 0
35   Unused            0        Always 0
36   DUT1 sign         +        DUT1 positive if 1
37   DUT1 sign         -        DUT1 negative if 1
38   DUT1 sign         +        DUT1 positive if 1
39   Marker P4         M        Always marker
40   DUT1 value        0.8
41   DUT1 value        0.4
42   DUT1 value        0.2
43   DUT1 value        0.1
44   Unused            0        Always 0
45   Year (tens)       80
46   Year (tens)       40
47   Year (tens)       20
48   Year (tens)       10
49   Marker P5         M        Always marker
50   Year (units)      8
51   Year (units)      4
52   Year (units)      2
53   Year (units)      1
54   Unused            0        Always 0
55   Leap Year Ind.    LYI      1 = current year is leap year
56   Leap Second Warn  LSW      1 = leap second at end of month
57   DST               DST2     DST status bits (see table)
58   DST               DST1     DST status bits (see table)
59   Marker P0         M        Always marker (also next frame ref)
```

### 6.4 DST Bits (seconds 57-58)

| DST2 | DST1 | Meaning |
|------|------|---------|
| 0 | 0 | DST not in effect |
| 1 | 0 | DST begins today |
| 0 | 1 | DST ends today |
| 1 | 1 | DST is in effect |

### 6.5 Frame Synchronization

Two consecutive markers at seconds :59 and :00 identify the top of the minute. The decoder should:

1. Detect marker pulses (800 ms low-power periods)
2. Identify two consecutive markers as frame boundary
3. Validate markers at seconds 9, 19, 29, 39, 49 within the frame
4. Reject frames where expected marker positions don't contain markers

## 7. Signal Processing Pipeline

### 7.1 Envelope Detection (from audio stream)

1. Receive 16-bit PCM stereo audio at 48 kHz
2. Extract mono channel (L or R, or average)
3. Compute amplitude envelope:
   - Take absolute value of samples
   - Apply low-pass filter (cutoff ~5 Hz) to smooth
4. Normalize envelope to 0.0-1.0 range using a running min/max window

### 7.2 Pulse Width Measurement

1. Apply threshold at ~50% of normalized envelope to produce binary signal (HIGH = full power, LOW = reduced power)
2. Detect falling edges (HIGH to LOW transitions) - these mark the start of each second
3. Detect rising edges (LOW to HIGH transitions) - end of low-power period
4. Measure duration of each low-power period in milliseconds
5. Classify pulse width:
   - 100-350 ms -> binary 0
   - 350-650 ms -> binary 1
   - 650-900 ms -> marker
   - Outside range -> error/noise

### 7.3 Frame Assembly

1. Buffer decoded symbols into a 60-element array
2. Detect frame sync: two consecutive markers
3. Validate marker positions (0, 9, 19, 29, 39, 49, 59)
4. Extract BCD fields and convert to decimal
5. Validate ranges (minutes 0-59, hours 0-23, day 1-366, year 0-99)

### 7.4 Multi-Frame Validation

Because WWVB reception can be noisy:

- Require at least 2 consecutive matching frames before declaring a valid decode
- Track per-bit confidence over multiple frames
- Report frame error rate to the user

## 8. User Interface

The tool uses [Rich](https://github.com/Textualize/rich) for a live-updating console TUI that keeps the user informed at every stage. A `--plain` flag falls back to simple timestamped log lines for piping to files or running over SSH without terminal features.

### 8.1 Installation and Setup

```bash
cd swl-wwvb-tool
python3 -m venv .venv
source .venv/bin/activate    # macOS/Linux
# .venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

### 8.2 Usage

```bash
wwvb-decode --host <sdrconnect-host> [options]
```

### 8.3 Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--host` | `127.0.0.1` | SDRConnect WebSocket host |
| `--port` | `5454` | SDRConnect WebSocket port |
| `--no-tune` | false | Skip tuning commands (assume SDRConnect already tuned) |
| `--source` | `audio` | Data source: `audio` (demodulated) or `iq` (raw IQ) |
| `--threshold` | `0.5` | Envelope threshold (0.0-1.0) for pulse detection |
| `--min-frames` | `2` | Consecutive matching frames required before reporting |
| `--plain` | false | Disable TUI; use plain timestamped log output |
| `--debug` | false | Show raw sample data and signal levels (implies --plain) |

### 8.4 TUI Layout (Rich Live Display)

The TUI is built with `rich.live.Live` and `rich.layout.Layout`, updating once per second. It consists of five panels stacked vertically:

```
┌─ WWVB Decoder ─────────────────────────────────────────────────────┐
│  Connection    ws://192.168.1.50:5454              Status: ● LIVE  │
│  Frequency     60,000 Hz          Mode: AM         Control: Yes    │
│  Uptime        00:04:32           Data source: Audio stream        │
├─ Signal ───────────────────────────────────────────────────────────┤
│  Power   -42.3 dBm  ████████████████░░░░░░░░░░░░░░░░  SNR 14.1 dB│
│  Quality ▁▂▃▅▇█▇▅▃▂▁▂▃▅▇█▇▅▃▂▁▂▃▅▇█▇▅▃▂  (last 30 frames)      │
│  Envelope ───╲___╱──╲________╱──╲___╱──╲________╱──   (live trace)│
├─ Current Frame ───────────────────────────── Second 23 of 60 ─────┤
│  ████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  38%│
│  M 0 0 1 1 0 0 1 0 M 0 0 1 0 0 1 0 0 0 M 0 0 1 0 · · · · · · · │
│  ↑min────────────↑  ↑hours───────────↑  ↑day─...                  │
│  Next complete frame in: ~37 seconds                               │
├─ Decoded Time ─────────────────────────────────────────────────────┤
│                                                                    │
│   ██  ██████      ██████  ██████      ██    ██████                 │
│  ███       ██          ██      ██    ███   ██    ██                │
│    ██  ██████      █████   █████      ██    ██████                 │
│    ██       ██         ██ ██          ██   ██    ██                │
│    ██  ██████  ██  █████   ██████     ██    ██████    UTC          │
│                                                                    │
│   2026-03-05  Day 064  DUT1: +0.2s  DST: In effect  LY: No       │
│                                                                    │
├─ Statistics ───────────────────────────────────────────────────────┤
│  Frames decoded: 12     Frame errors: 2     Success rate: 85.7%   │
│  Last good decode: 03:18 UTC    Consecutive good: 4               │
│  Avg pulse 0: 198ms    Avg pulse 1: 502ms    Avg marker: 801ms    │
├─ Activity Log ─────────────────────────────────────────────────────┤
│  22:18:02  Frame 14 decoded: 2026-03-05 03:18 UTC (valid)         │
│  22:17:02  Frame 13 decoded: 2026-03-05 03:17 UTC (valid)         │
│  22:16:02  Frame 12 failed: marker missing at position 29         │
│  22:15:02  Frame 11 decoded: 2026-03-05 03:15 UTC (valid)         │
│  22:15:00  Frame sync acquired                                     │
│  22:14:01  Waiting for sync... found 1 of 2 consecutive markers   │
│  22:14:00  Audio stream active. Receiving data.                    │
│  22:13:59  Tuned to 60000 Hz | AM | BW: 100 Hz | AGC: off         │
│  22:13:58  Connected to ws://192.168.1.50:5454                     │
└────────────────────────────────────────────────────────────────────┘
                              Ctrl+C to exit
```

### 8.5 TUI Panel Descriptions

#### Panel 1: Header / Connection Status

Always visible. Shows the user whether the tool is connected and receiving data.

| Field | Source | Update frequency |
|-------|--------|-----------------|
| Connection URL | CLI args | Static |
| Status indicator | WebSocket state | On change (colored: green=LIVE, yellow=CONNECTING, red=DISCONNECTED) |
| Frequency/Mode | `device_vfo_frequency`, `demodulator` properties | On change |
| Control | `can_control` property | On change |
| Uptime | Internal timer | Every second |
| Data source | CLI args | Static |

#### Panel 2: Signal Quality

Gives the user confidence about whether the signal is strong enough to decode.

| Element | Source | Update frequency |
|---------|--------|-----------------|
| Power (dBm) | `signal_power` property | Polled every 2 seconds |
| SNR (dB) | `signal_snr` property | Polled every 2 seconds |
| Power bar | Normalized signal_power | Every 2 seconds |
| Quality sparkline | Per-frame SNR history (last 30 frames) | After each frame |
| Envelope trace | Live amplitude from audio stream | Every second |

The power bar uses color thresholds:
- Green: SNR > 10 dB (good decode likely)
- Yellow: SNR 5-10 dB (marginal, may have errors)
- Red: SNR < 5 dB (decode unlikely)

The envelope trace is a single-line ASCII waveform showing the last ~5 seconds of the smoothed amplitude envelope. This lets the user visually confirm they're seeing the characteristic WWVB pulse pattern (sharp dips every second, varying in width).

#### Panel 3: Current Frame Progress

The most important panel for user feedback during the 60-second decode cycle.

| Element | Description |
|---------|-------------|
| Progress bar | 60-segment bar filling left-to-right as each second is decoded. Color: green for valid bits, yellow for uncertain, red for errors |
| Bit display | Shows decoded symbols as they arrive: `M`, `0`, `1`, or `·` (pending). Uses color to distinguish field groups |
| Field labels | Annotates the bit stream with field names (minutes, hours, day, year) so the user can see partial decodes forming |
| Time remaining | Countdown: "Next complete frame in: ~37 seconds" |
| Second counter | "Second 23 of 60" with percentage |

Field color coding in the bit display:
- Cyan: Minutes field
- Green: Hours field
- Yellow: Day-of-year field
- Magenta: Year field
- Blue: DUT1 fields
- White: Markers
- Dim: Unused bits

As bits arrive, partially decoded values appear in the field labels. For example, after second 8 the user can already see "Minutes: 32" even though the frame is only 13% complete.

#### Panel 4: Decoded Time

Shows the most recently fully-decoded and validated time in large format.

| Element | Description |
|---------|-------------|
| Big clock | Large ASCII digit rendering of HH:MM:SS UTC (using Rich's `Text` with figlet-style digits or box drawing) |
| Date line | Full date, day-of-year, DUT1, DST status, leap year indicator |

This panel updates once per minute (after each successful frame decode). Before the first decode, it shows "Waiting for first decode..." with a spinner.

If the most recent frame failed validation, the last good decode is retained but dimmed, with a note: "Last valid decode was 2 minutes ago."

#### Panel 5: Statistics

Running totals so the user can gauge overall reception quality.

| Stat | Description |
|------|-------------|
| Frames decoded | Total successful frame decodes since start |
| Frame errors | Total frames that failed validation |
| Success rate | Percentage of good frames |
| Last good decode | UTC time from most recent valid frame |
| Consecutive good | Streak of consecutive valid frames (resets on error) |
| Avg pulse widths | Running average of pulse durations for each symbol type (0, 1, M). Helps diagnose timing issues. |

#### Panel 6: Activity Log

Scrolling log (last ~10 entries) of significant events, newest first.

Event types logged:

| Event | Example |
|-------|---------|
| Connection | "Connected to ws://192.168.1.50:5454" |
| Tuning | "Tuned to 60000 Hz, AM, BW: 100 Hz, AGC: off" |
| Stream start | "Audio stream active. Receiving data." |
| Sync search | "Waiting for sync... found 1 of 2 consecutive markers" |
| Sync acquired | "Frame sync acquired" |
| Frame decoded | "Frame 14 decoded: 2026-03-05 03:18 UTC (valid)" |
| Frame error | "Frame 12 failed: marker missing at position 29" |
| Validation error | "Frame 10 failed: hours=25 out of range" |
| Reconnecting | "WebSocket disconnected. Reconnecting in 5s..." |
| Signal warning | "SNR dropped below 5 dB - decode quality may suffer" |

### 8.6 State Machine and User Feedback

The tool progresses through a clear sequence of states. The TUI communicates which state the tool is in and what needs to happen next.

```
State              Header Status    Frame Panel Shows           User Message
─────              ─────────────    ──────────────────          ────────────
CONNECTING         ● CONNECTING     "Connecting..."             "Establishing WebSocket connection"
CONFIGURING        ● CONFIGURING    "Configuring radio..."      "Setting frequency, mode, filters"
WAITING_FOR_DATA   ● WAITING        "Waiting for audio data"    "Audio stream requested, waiting for first samples"
SYNCING            ● SYNCING        "Searching for sync"        "Looking for two consecutive markers (may take up to 2 min)"
DECODING           ● LIVE           Progress bar filling        "Second XX of 60 - next decode in ~YY seconds"
DECODED            ● LIVE           Complete bar (green)        "Frame decoded successfully" (holds 2s, then resets for next)
FRAME_ERROR        ● LIVE           Complete bar (red)          "Frame error: <reason>. Resyncing..." (holds 2s, then resets)
DISCONNECTED       ● DISCONNECTED   "Connection lost"           "Reconnecting in Xs..."
```

### 8.7 Plain Mode (--plain)

When `--plain` is set, all TUI rendering is disabled. Output is simple timestamped lines to stdout, suitable for piping to a file or running on a headless system.

```
[2026-03-04 22:13:58] CONNECT ws://192.168.1.50:5454
[2026-03-04 22:13:59] CONFIG freq=60000 mode=AM bw=100 agc=off
[2026-03-04 22:14:00] STREAM audio=on
[2026-03-04 22:14:01] SYNC searching...
[2026-03-04 22:15:01] SYNC acquired
[2026-03-04 22:15:01] SIGNAL power=-42.3dBm snr=14.1dB
[2026-03-04 22:16:02] DECODE 2026-03-05 03:16 UTC day=064 dut1=+0.2 dst=active ly=no
[2026-03-04 22:16:02] STATS frames=1 errors=0 rate=100.0%
[2026-03-04 22:17:02] DECODE 2026-03-05 03:17 UTC day=064 dut1=+0.2 dst=active ly=no
```

Each line is structured for easy grep/awk processing. The prefix after the timestamp identifies the message type: CONNECT, CONFIG, STREAM, SYNC, SIGNAL, DECODE, STATS, ERROR, WARN.

### 8.8 Exit

Ctrl+C gracefully:

1. Prints a summary line (total frames decoded, error rate, session duration)
2. Disables audio/IQ streaming
3. Closes the WebSocket connection
4. Exits with code 0

If the connection is lost and reconnection fails after 5 attempts, the tool exits with code 1.

## 9. Python Package Structure

```
swl-wwvb-tool/
├── .venv/                      # Virtual environment (git-ignored)
├── pyproject.toml              # Project metadata and dependencies
├── requirements.txt            # Pinned dependencies for reproducibility
├── README.md
├── SPEC.md                     # This file
├── src/
│   └── wwvb_decode/
│       ├── __init__.py
│       ├── __main__.py         # Entry point (python -m wwvb_decode)
│       ├── cli.py              # argparse CLI setup
│       ├── sdrconnect.py       # WebSocket client for SDRConnect API
│       ├── envelope.py         # Envelope detection and filtering
│       ├── decoder.py          # Pulse width measurement and symbol classification
│       ├── frame.py            # Frame assembly, BCD parsing, validation
│       ├── state.py            # State machine (CONNECTING -> DECODING -> etc.)
│       ├── tui.py              # Rich Live TUI layout and panel rendering
│       └── plain.py            # Plain text output for --plain mode
└── tests/
    ├── test_decoder.py         # Unit tests for pulse classification
    ├── test_frame.py           # Unit tests for BCD parsing and validation
    ├── test_state.py           # Unit tests for state transitions
    └── test_data/              # Recorded test data for offline testing
        └── README.md
```

## 10. Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `websockets` | >=12.0 | WebSocket client for SDRConnect |
| `numpy` | >=1.24 | Signal processing (envelope, filtering) |
| `scipy` | >=1.10 | Low-pass filter design (Butterworth) |
| `rich` | >=13.0 | TUI rendering (Live display, Layout, panels, progress bars, sparklines) |

No heavy DSP frameworks required. The signal processing is straightforward given the 1 bps data rate. The `rich` library handles all TUI rendering with no additional terminal dependencies.

## 11. Key Design Decisions

### 11.1 Audio Stream vs IQ Stream

**Decision: Start with audio stream, IQ as fallback.**

SDRConnect already performs AM demodulation. The audio stream (48 kHz PCM) provides the amplitude envelope directly. Processing IQ data would mean reimplementing AM demodulation in Python, which adds complexity without clear benefit for v1.

If the audio stream proves insufficient (e.g., SDRConnect's AGC or audio filtering distorts the pulse shape), the tool can switch to IQ mode and compute `sqrt(I^2 + Q^2)` directly.

### 11.2 AM/PWM Only (No BPSK)

**Decision: Decode the legacy AM/PWM time code only.**

The BPSK phase-modulated code (added 2012) requires coherent carrier phase tracking, which is significantly more complex. AM/PWM decoding is well-understood, requires only amplitude envelope analysis, and provides all the same time data. BPSK support can be added later if needed.

### 11.3 Rich Console TUI (not Textual)

**Decision: Use Rich Live display, not a full Textual TUI app.**

Rich provides live-updating panels, progress bars, tables, sparklines, and colored output with minimal complexity. It renders to any terminal that supports ANSI escape codes. Textual would provide mouse interaction and scrollable panes, but adds significant complexity and framework lock-in for a tool that fundamentally displays one screen of updating data.

The `--plain` fallback ensures the tool works in environments where even basic ANSI support is unavailable (piped output, CI, minimal SSH sessions).

### 11.4 No Radio Control Option (--no-tune)

The `--no-tune` flag allows the tool to work in listen-only mode. This is important for scenarios where:

- SDRConnect is already configured by the user
- The user has fine-tuned gain settings manually
- Another client has exclusive control of the radio

## 12. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| VLF reception too noisy | No decode | Multi-frame averaging, configurable threshold, verbose mode for diagnostics |
| SDRConnect audio processing distorts pulses | Incorrect pulse widths | Fall back to IQ stream; disable audio_filter, audio_limiters, noise_reduction |
| RSP can't tune to 60 kHz | No signal | RSPdx supports 1 kHz-2 GHz; RSP1A supports 1 kHz-2 GHz. Verify `antenna_select` = Hi-Z for best VLF performance |
| WebSocket drops connection | Lost data | Auto-reconnect with backoff; resume frame sync |
| Clock drift between samples | Misaligned pulse measurements | Use sample count (not wall clock) for timing; 48 kHz sample rate gives sub-ms precision |

## 13. Testing Strategy

### 13.1 Unit Tests

- Pulse classifier: feed known-duration pulses, verify 0/1/M classification
- BCD parser: verify correct decode of all fields for known bit patterns
- Frame validator: verify marker position checking and range validation

### 13.2 Integration Testing with Recorded Data

- Record raw IQ/audio from a real WWVB reception session
- Save to `tests/test_data/` for offline replay
- Verify end-to-end decode matches expected time

### 13.3 Live Testing

- Connect to SDRConnect with RSPdx tuned to 60 kHz
- Run tool and compare decoded time against NTP or system clock
- Test at different times of day (WWVB signal strength varies - strongest at night)

## 14. Future Enhancements (Out of Scope for v1)

- BPSK phase-modulated time code decoding
- Logging decoded times to file (CSV, JSON)
- Web UI dashboard
- Automatic gain optimization
- Support for other time stations (DCF77 at 77.5 kHz, JJY at 40/60 kHz, MSF at 60 kHz)
- NTP server mode (serve decoded WWVB time as NTP)
- Textual-based full TUI upgrade (if richer interaction is needed)

## 15. References

- [NIST Radio Station WWVB](https://www.nist.gov/pml/time-and-frequency-division/time-distribution/radio-station-wwvb)
- [WWVB Time Code Format (NIST)](https://www.nist.gov/pml/time-and-frequency-division/time-distribution/radio-station-wwvb/wwvb-time-code-format)
- [Enhanced WWVB Broadcast Format (NIST PDF)](https://www.nist.gov/system/files/documents/2017/05/09/NIST-Enhanced-WWVB-Broadcast-Format-1_01-2013-11-06.pdf)
- [SDRConnect WebSocket API 1.0.1 Documentation](./research/SDRconnect_WebSocket_API.pdf)
- [SDRConnect WebSocket API Examples (C#)](./research/SDRconnectWebSocketAPI/)
- [SDRConnect WebSocket API Examples (JS)](./research/SDRconnect_WebSocket_JS/)
