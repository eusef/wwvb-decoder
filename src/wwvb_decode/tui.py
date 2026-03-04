"""Rich TUI display for WWVB decoder."""

import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from .state import WWVBApp

# Minimum terminal width to show the two-column layout with tips panel.
# Below this, we fall back to single-column (decoder only).
MIN_WIDTH_FOR_TIPS = 120


def _load_tips_pages() -> list[str]:
    """Load tips content from tips.txt, split into pages by '---' lines."""
    tips_path = Path(__file__).parent / "tips.txt"
    if not tips_path.exists():
        return ["[dim]Tips file not found.\nExpected at src/wwvb_decode/tips.txt[/]"]

    raw = tips_path.read_text(encoding="utf-8")
    pages = [p.strip() for p in raw.split("\n---\n") if p.strip()]
    return pages if pages else ["[dim]Tips file is empty.[/]"]

# Big ASCII digit font (5 wide x 7 tall)
DIGITS = {
    "0": [
        " ####  ",
        "##  ## ",
        "##  ## ",
        "##  ## ",
        "##  ## ",
        "##  ## ",
        " ####  ",
    ],
    "1": [
        "   ##  ",
        "  ###  ",
        "   ##  ",
        "   ##  ",
        "   ##  ",
        "   ##  ",
        " ##### ",
    ],
    "2": [
        " ####  ",
        "##  ## ",
        "    ## ",
        "  ###  ",
        " ##    ",
        "##     ",
        "###### ",
    ],
    "3": [
        " ####  ",
        "##  ## ",
        "    ## ",
        "  ###  ",
        "    ## ",
        "##  ## ",
        " ####  ",
    ],
    "4": [
        "##  ## ",
        "##  ## ",
        "##  ## ",
        "###### ",
        "    ## ",
        "    ## ",
        "    ## ",
    ],
    "5": [
        "###### ",
        "##     ",
        "#####  ",
        "    ## ",
        "    ## ",
        "##  ## ",
        " ####  ",
    ],
    "6": [
        " ####  ",
        "##     ",
        "#####  ",
        "##  ## ",
        "##  ## ",
        "##  ## ",
        " ####  ",
    ],
    "7": [
        "###### ",
        "    ## ",
        "   ##  ",
        "  ##   ",
        "  ##   ",
        "  ##   ",
        "  ##   ",
    ],
    "8": [
        " ####  ",
        "##  ## ",
        "##  ## ",
        " ####  ",
        "##  ## ",
        "##  ## ",
        " ####  ",
    ],
    "9": [
        " ####  ",
        "##  ## ",
        "##  ## ",
        " ##### ",
        "    ## ",
        "    ## ",
        " ####  ",
    ],
    ":": [
        "       ",
        "  ##   ",
        "  ##   ",
        "       ",
        "  ##   ",
        "  ##   ",
        "       ",
    ],
    " ": [
        "       ",
        "       ",
        "       ",
        "       ",
        "       ",
        "       ",
        "       ",
    ],
}

# Field ranges for color coding in bit display
FIELD_COLORS = {
    # (start, end, color, label)
    "minutes": (1, 8, "cyan", "min"),
    "hours": (12, 18, "green", "hr"),
    "day_hi": (22, 27, "yellow", "day"),
    "day_lo": (30, 33, "yellow", "day"),
    "dut1_sign": (36, 38, "blue", "dut1"),
    "dut1_val": (40, 43, "blue", "dut1"),
    "year_tens": (45, 48, "magenta", "yr"),
    "year_units": (50, 53, "magenta", "yr"),
}

# Sparkline characters for envelope and quality display
SPARK_CHARS = " _.,:-=!#"
BLOCK_CHARS = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"


def _sparkline(values, width: int = 60) -> str:
    """Create a sparkline string from a sequence of 0.0-1.0 values."""
    if len(values) == 0:
        return " " * width

    # Resample to width
    import numpy as np

    if len(values) > width:
        indices = np.linspace(0, len(values) - 1, width, dtype=int)
        resampled = [values[i] for i in indices]
    else:
        resampled = list(values)

    chars = []
    for v in resampled:
        idx = int(max(0, min(1, v)) * (len(BLOCK_CHARS) - 1))
        chars.append(BLOCK_CHARS[idx])
    return "".join(chars)


def _big_time(time_str: str) -> str:
    """Render a time string (HH:MM:SS) in large ASCII digits."""
    lines = [""] * 7
    for ch in time_str:
        digit_lines = DIGITS.get(ch, DIGITS[" "])
        for i in range(7):
            lines[i] += digit_lines[i]
    return "\n".join(lines)


def _get_bit_color(pos: int) -> str:
    """Get the Rich color markup for a bit position."""
    if pos in {0, 9, 19, 29, 39, 49, 59}:
        return "white bold"
    for field_name, (start, end, color, _) in FIELD_COLORS.items():
        if start <= pos <= end:
            return color
    if pos in {4, 10, 11, 14, 20, 21, 28, 34, 35, 44, 54}:
        return "dim"
    # DST/LY/LSW
    if pos in {55, 56, 57, 58}:
        return "bright_white"
    return "white"


class TUIDisplay:
    """Rich Live TUI with responsive two-column layout for WWVB decoder."""

    def __init__(self):
        self._console = Console()
        self._live = Live(
            console=self._console,
            refresh_per_second=2,
            screen=True,  # Use alternate screen buffer for clean refresh
        )
        self._tips_pages = _load_tips_pages()
        self._tips_page_index = 0

    def start(self) -> None:
        self._live.start()

    def stop(self) -> None:
        try:
            self._live.stop()
        except Exception:
            pass

    def tips_next_page(self) -> None:
        """Advance to the next tips page (wraps around)."""
        self._tips_page_index = (self._tips_page_index + 1) % len(self._tips_pages)

    def tips_prev_page(self) -> None:
        """Go to the previous tips page (wraps around)."""
        self._tips_page_index = (self._tips_page_index - 1) % len(self._tips_pages)

    def update(self, state: "WWVBApp") -> None:
        """Rebuild and render the full TUI layout."""
        try:
            layout = self._build_layout(state)
            self._live.update(layout)
        except Exception:
            pass  # Don't crash on display errors

    def _render_tips(self) -> Panel:
        """Render the current tips page with navigation hint and dots."""
        page_markup = self._tips_pages[self._tips_page_index]
        page_text = Text.from_markup(page_markup)

        total = len(self._tips_pages)
        current = self._tips_page_index + 1

        # Page indicator dots
        dots = Text()
        for i in range(total):
            if i == self._tips_page_index:
                dots.append(" \u25cf ", style="cyan")  # filled circle
            else:
                dots.append(" \u25cb ", style="dim")   # empty circle

        content = Group(page_text, Text(""), dots)

        return Panel(
            content,
            title=f"Help & Tips [{current}/{total}]",
            subtitle="\u2190 \u2192 arrow keys to page",
            border_style="dim cyan",
        )

    def _build_layout(self, state: "WWVBApp") -> Layout | Group:
        """Build layout. Two columns (60/40) if wide enough, else single."""
        left_panels = Group(
            self._render_header(state),
            self._render_signal(state),
            self._render_frame(state),
            self._render_time(state),
            self._render_stats(state),
            self._render_log(state),
        )

        # Responsive: only show tips column if terminal is wide enough
        term_width = self._console.size.width
        if term_width < MIN_WIDTH_FOR_TIPS:
            return left_panels

        layout = Layout()
        layout.split_row(
            Layout(left_panels, name="main", ratio=3),
            Layout(self._render_tips(), name="tips", ratio=2),
        )
        return layout

    def _render_header(self, state: "WWVBApp") -> Panel:
        """Panel 1: Connection status."""
        status_colors = {
            "CONNECTING": "yellow",
            "CONFIGURING": "yellow",
            "WAITING": "yellow",
            "SYNCING": "cyan",
            "LIVE": "green",
            "DISCONNECTED": "red",
        }
        status_label = state.state.value
        color = status_colors.get(status_label, "white")

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(width=40)
        table.add_column(width=35)

        table.add_row(
            f"Connection   {state.config.ws_url}",
            Text(f"Status: ", style="white")
            + Text(f"\u25cf {status_label}", style=f"bold {color}"),
        )
        table.add_row(
            f"Frequency    60,000 Hz          Mode: AM",
            f"Control: {'Yes' if state.has_control else 'Unknown'}",
        )

        uptime = str(datetime.timedelta(seconds=int(state.uptime_seconds)))
        table.add_row(
            f"Uptime       {uptime}",
            f"Data source: {state.config.source.capitalize()} stream",
        )

        return Panel(table, title="WWVB Decoder", border_style="bright_blue")

    def _render_signal(self, state: "WWVBApp") -> Panel:
        """Panel 2: Signal quality."""
        lines = []

        sdr_overload = state.sdr_overload
        audio_clipping = state.envelope_detector.is_overloaded
        peak_pct = state.envelope_detector.peak_level_pct

        # SDR ADC Overload: red alarm (matches SDRConnect's own indicator)
        if sdr_overload:
            warn = Text()
            warn.append("  \u26a0 OVERLOAD ", style="bold white on red")
            warn.append("  ADC overload reported by SDR hardware", style="bold red")
            warn.append("  - Reduce RF gain or increase IF gain reduction", style="red")
            lines.append(warn)

        # Audio levels high: yellow advisory (demod output near max, not ADC issue)
        if audio_clipping and not sdr_overload:
            info = Text()
            clip_pct = state.envelope_detector.clip_percentage
            info.append("  \u26a0 LEVELS HIGH ", style="bold black on yellow")
            info.append(
                f"  Audio output clipping: {clip_pct:.1f}% (peak {peak_pct:.0f}%)",
                style="yellow",
            )
            info.append("  - May affect decoding if severe", style="dim yellow")
            lines.append(info)

        # Power and SNR
        power_str = f"{state.signal_power:.1f} dBm" if state.signal_power else "---"
        snr_str = f"{state.signal_snr:.1f} dB" if state.signal_snr else "---"

        # SNR-based color
        if state.signal_snr and state.signal_snr > 10:
            snr_color = "green"
        elif state.signal_snr and state.signal_snr > 5:
            snr_color = "yellow"
        else:
            snr_color = "red"

        power_line = Text()
        power_line.append("  Power   ")
        power_line.append(f"{power_str:12s}")

        # Simple power bar
        bar_width = 30
        if state.signal_power:
            # Map -100 to 0 dBm range to 0-1
            bar_pct = max(0, min(1, (state.signal_power + 100) / 100))
            filled = int(bar_pct * bar_width)
        else:
            filled = 0
        power_line.append(
            "\u2588" * filled + "\u2591" * (bar_width - filled),
            style=snr_color,
        )
        power_line.append(f"  SNR {snr_str}", style=snr_color)
        lines.append(power_line)

        # Peak audio level meter
        peak_line = Text()
        peak_line.append("  Audio   ")
        # Color-coded peak level
        if peak_pct > 95:
            peak_style = "bold red"
        elif peak_pct > 80:
            peak_style = "yellow"
        else:
            peak_style = "green"
        # Visual meter bar
        meter_width = 20
        meter_filled = int(min(1.0, peak_pct / 100.0) * meter_width)
        peak_line.append("\u2588" * meter_filled, style=peak_style)
        peak_line.append("\u2591" * (meter_width - meter_filled), style="dim")
        peak_line.append(f"  {peak_pct:.0f}%", style=peak_style)
        if peak_pct > 95:
            peak_line.append(" CLIP", style="bold red")
        lines.append(peak_line)

        # Quality sparkline (per-frame SNR history)
        quality_line = Text()
        quality_line.append("  Quality ")
        if state.snr_history:
            # Normalize SNR values to 0-1 (0-20 dB range)
            normalized = [max(0, min(1, s / 20.0)) for s in state.snr_history[-30:]]
            quality_line.append(_sparkline(normalized, 40))
            quality_line.append(f"  (last {len(state.snr_history[-30:])} frames)")
        else:
            quality_line.append("Waiting for data...")
        lines.append(quality_line)

        # Envelope trace
        envelope_line = Text()
        envelope_line.append("  Envelope ")
        envelope = state.envelope_detector.get_recent_envelope(5.0)
        if len(envelope) > 0 and state.envelope_detector.has_data:
            envelope_line.append(_sparkline(envelope, 50))
            envelope_line.append("  (live)")
        else:
            envelope_line.append("Waiting for audio data...")
        lines.append(envelope_line)

        content = Group(*lines)
        # Only red border for actual SDR overload; yellow for audio clipping
        if sdr_overload:
            border = "bold red"
        elif audio_clipping:
            border = "yellow"
        else:
            border = "bright_blue"
        return Panel(content, title="Signal", border_style=border)

    def _render_frame(self, state: "WWVBApp") -> Panel:
        """Panel 3: Current frame progress."""
        pos = state.assembler.current_position
        bits = state.assembler.current_bits
        is_synced = state.assembler.is_synced

        if not is_synced:
            content = Text("  Searching for frame sync...", style="yellow")
            return Panel(
                content,
                title="Current Frame",
                subtitle="Waiting for sync",
                border_style="yellow",
            )

        lines = []

        # Progress bar
        pct = pos / 60 * 100 if pos > 0 else 0
        progress_text = Text()
        progress_text.append("  ")
        bar_width = 60
        filled = int(pos / 60 * bar_width)
        progress_text.append("\u2588" * filled, style="green")
        progress_text.append("\u2591" * (bar_width - filled), style="dim")
        progress_text.append(f" {pct:.0f}%")
        lines.append(progress_text)

        # Bit display with color coding
        bit_line = Text()
        bit_line.append("  ")
        for i in range(60):
            bit = bits[i]
            color = _get_bit_color(i)
            if bit is not None:
                bit_line.append(f"{bit} ", style=color)
            else:
                bit_line.append("\u00b7 ", style="dim")
        lines.append(bit_line)

        # Field labels line
        label_line = Text()
        label_line.append("  ")
        label_line.append("\u2191min" + " " * 10, style="cyan")
        label_line.append("  \u2191hr" + " " * 9, style="green")
        label_line.append("  \u2191day" + " " * 14, style="yellow")
        label_line.append(" \u2191yr", style="magenta")
        lines.append(label_line)

        # Countdown
        remaining = 60 - pos
        countdown = Text()
        countdown.append(f"  Second {pos} of 60")
        countdown.append(f"     Next complete frame in: ~{remaining} seconds")
        lines.append(countdown)

        content = Group(*lines)
        return Panel(
            content,
            title="Current Frame",
            subtitle=f"Second {pos} of 60",
            border_style="green" if pos > 0 else "yellow",
        )

    def _render_time(self, state: "WWVBApp") -> Panel:
        """Panel 4: Decoded time display."""
        decoded = state.assembler.confirmed_time or state.assembler.last_decoded

        if decoded is None:
            content = Text(
                "  Waiting for first decode...", style="dim italic",
            )
            return Panel(
                content, title="Decoded Time", border_style="bright_blue",
            )

        lines = []

        # Big clock
        time_str = f"{decoded.hour:02d}:{decoded.minute:02d}"
        big = _big_time(time_str)

        is_confirmed = state.assembler.confirmed_time is not None
        clock_style = "bold bright_green" if is_confirmed else "dim"

        clock_text = Text(big, style=clock_style)
        lines.append(clock_text)
        lines.append(Text(f"{'':>45}UTC", style=clock_style))

        # Date line
        try:
            date = decoded.to_date()
            date_str = date.isoformat()
        except (ValueError, OverflowError):
            date_str = f"{decoded.year}-???"

        info_line = Text()
        info_line.append(f"   {date_str}  ")
        info_line.append(f"Day {decoded.day_of_year:03d}  ")
        info_line.append(f"DUT1: {decoded.dut1:+.1f}s  ")
        dst_labels = {
            "off": "Not in effect",
            "on": "In effect",
            "begins_today": "Begins today",
            "ends_today": "Ends today",
        }
        info_line.append(f"DST: {dst_labels.get(decoded.dst, decoded.dst)}  ")
        info_line.append(f"LY: {'Yes' if decoded.leap_year else 'No'}")
        lines.append(info_line)

        if not is_confirmed:
            lines.append(Text(""))
            lines.append(
                Text(
                    f"   (Awaiting {state.config.min_frames} consecutive matching frames for confirmation)",
                    style="dim italic",
                )
            )

        content = Group(*lines)
        return Panel(content, title="Decoded Time", border_style="bright_green" if is_confirmed else "bright_blue")

    def _render_stats(self, state: "WWVBApp") -> Panel:
        """Panel 5: Statistics."""
        asm = state.assembler
        dec = state.pulse_decoder

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(width=28)
        table.add_column(width=28)
        table.add_column(width=28)

        table.add_row(
            f"Frames decoded: {asm.total_frames}",
            f"Frame errors: {asm.error_frames}",
            f"Success rate: {asm.success_rate:.1f}%",
        )

        last_good = asm.last_decoded
        last_str = last_good.to_utc_string() if last_good else "---"
        table.add_row(
            f"Last good decode: {last_str}",
            f"Consecutive good: {asm.consecutive_good}",
            "",
        )

        avgs = dec.avg_pulse_widths
        table.add_row(
            f"Avg pulse 0: {avgs.get('0', 0):.0f}ms",
            f"Avg pulse 1: {avgs.get('1', 0):.0f}ms",
            f"Avg marker: {avgs.get('M', 0):.0f}ms",
        )

        return Panel(table, title="Statistics", border_style="bright_blue")

    def _render_log(self, state: "WWVBApp") -> Panel:
        """Panel 6: Activity log (newest first)."""
        lines = []
        for entry in reversed(state.log_entries[-10:]):
            lines.append(Text(entry))

        if not lines:
            lines.append(Text("  No activity yet...", style="dim"))

        content = Group(*lines)
        return Panel(content, title="Activity Log", border_style="bright_blue")
