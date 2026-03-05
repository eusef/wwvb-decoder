"""WWVB frame assembly, BCD parsing, and validation."""

import datetime
import logging
from dataclasses import dataclass
from enum import Enum, auto

logger = logging.getLogger(__name__)


# WWVB marker positions within a 60-second frame
MARKER_POSITIONS = {0, 9, 19, 29, 39, 49}
# Position 59 is also a marker (P0 / next frame reference), handled at frame boundary

# Unused bit positions (must be 0)
UNUSED_POSITIONS = {4, 10, 11, 14, 20, 21, 28, 34, 35, 44, 54}


class FrameEventType(Enum):
    SYNC_PROGRESS = auto()
    SYNC_ACQUIRED = auto()
    FRAME_COMPLETE = auto()
    FRAME_ERROR = auto()
    SYMBOL_ADDED = auto()


@dataclass
class FrameEvent:
    """Event emitted by the frame assembler."""

    event_type: FrameEventType
    message: str = ""
    time: "WWVBTime | None" = None
    position: int = 0


@dataclass
class WWVBTime:
    """Decoded WWVB time data from a single frame."""

    year: int  # 2000-2099
    day_of_year: int  # 1-366
    hour: int  # 0-23
    minute: int  # 0-59
    dut1: float  # -0.9 to +0.9 seconds
    dst: str  # "off", "begins_today", "ends_today", "on"
    leap_year: bool
    leap_second_warning: bool

    def to_utc_string(self) -> str:
        """Format as '2026-03-05 03:18 UTC'."""
        try:
            d = self.to_date()
            return f"{d.isoformat()} {self.hour:02d}:{self.minute:02d} UTC"
        except (ValueError, OverflowError):
            return f"{self.year}-day{self.day_of_year:03d} {self.hour:02d}:{self.minute:02d} UTC"

    def to_date(self) -> datetime.date:
        """Convert year + day_of_year to a date."""
        return datetime.date(self.year, 1, 1) + datetime.timedelta(
            days=self.day_of_year - 1
        )

    def matches(self, other: "WWVBTime", allow_minute_increment: bool = True) -> bool:
        """Check if two decoded times are consistent.

        If allow_minute_increment, the other time may be exactly 1 minute later.
        """
        if not other:
            return False

        if not allow_minute_increment:
            return (
                self.year == other.year
                and self.day_of_year == other.day_of_year
                and self.hour == other.hour
                and self.minute == other.minute
            )

        # Check if other is exactly 1 minute after self
        self_total_min = self.day_of_year * 1440 + self.hour * 60 + self.minute
        other_total_min = other.day_of_year * 1440 + other.hour * 60 + other.minute
        return (
            self.year == other.year
            and (other_total_min - self_total_min) in (0, 1)
        )


def bcd_decode(bits: list[str], weights: list[int]) -> int:
    """Decode BCD-weighted bits to integer.

    Args:
        bits: list of "0"/"1" strings
        weights: BCD weight for each bit position

    Returns:
        Decoded integer value
    """
    total = 0
    for bit, weight in zip(bits, weights):
        if bit == "1":
            total += weight
    return total


def parse_frame(
    bits: list[str | None],
    max_errors: int = 0,
) -> tuple[WWVBTime | None, str | None]:
    """Parse a complete 60-symbol WWVB frame.

    Args:
        bits: 60-element list of symbols ("0", "1", "M", "?", or None)
        max_errors: Maximum tolerated errors (missing markers, "?" symbols
                    in data positions). 0 = strict mode (original behavior).
                    The Arduino WWVB_15 reference uses max_errors=8.

    Returns:
        (WWVBTime, None) on success or (None, error_reason) on failure
    """
    if len(bits) != 60:
        return None, f"Frame has {len(bits)} bits, expected 60"

    # 1. Count errors: missing markers, "?" in data positions
    error_count = 0
    marker_errors = []
    for pos in MARKER_POSITIONS:
        if bits[pos] != "M":
            marker_errors.append(pos)
            error_count += 1

    # Count "?" in non-marker positions
    for i, bit in enumerate(bits):
        if i not in MARKER_POSITIONS and bit == "?":
            error_count += 1

    if error_count > max_errors:
        if marker_errors:
            return None, (
                f"Too many errors ({error_count}): "
                f"missing markers at {marker_errors}"
            )
        return None, f"Too many errors ({error_count}) in frame"

    # Treat "?" in data positions as "0" for BCD decoding
    # (conservative: unknown bits contribute 0 to totals)
    clean_bits = list(bits)
    for i in range(60):
        if clean_bits[i] in ("?", None):
            clean_bits[i] = "0"
        # Force expected markers to "M" if we're in tolerant mode
        if i in MARKER_POSITIONS and clean_bits[i] != "M":
            clean_bits[i] = "M"
    bits = clean_bits

    # 2. Check unused positions are "0" (warn but don't reject)
    for pos in UNUSED_POSITIONS:
        if bits[pos] not in ("0", None):
            logger.debug(f"Unused position {pos} has value '{bits[pos]}' (expected 0)")

    # 3. Extract and decode BCD fields
    try:
        # Minutes: positions 1-3 (tens) and 5-8 (units)
        minutes_tens = bcd_decode(
            [bits[1], bits[2], bits[3]], [40, 20, 10]
        )
        minutes_units = bcd_decode(
            [bits[5], bits[6], bits[7], bits[8]], [8, 4, 2, 1]
        )
        minute = minutes_tens + minutes_units

        # Hours: positions 12-13 (tens) and 15-18 (units)
        hours_tens = bcd_decode(
            [bits[12], bits[13]], [20, 10]
        )
        hours_units = bcd_decode(
            [bits[15], bits[16], bits[17], bits[18]], [8, 4, 2, 1]
        )
        hour = hours_tens + hours_units

        # Day of year: positions 22-23 (hundreds), 24-27 (tens), 30-33 (units)
        day_hundreds = bcd_decode(
            [bits[22], bits[23]], [200, 100]
        )
        day_tens = bcd_decode(
            [bits[24], bits[25], bits[26], bits[27]], [80, 40, 20, 10]
        )
        day_units = bcd_decode(
            [bits[30], bits[31], bits[32], bits[33]], [8, 4, 2, 1]
        )
        day_of_year = day_hundreds + day_tens + day_units

        # DUT1 sign: positions 36-38
        dut1_positive = bits[36] == "1" or bits[38] == "1"
        dut1_negative = bits[37] == "1"

        # DUT1 value: positions 40-43
        dut1_val = bcd_decode(
            [bits[40], bits[41], bits[42], bits[43]], [8, 4, 2, 1]
        )
        # DUT1 is in tenths of seconds (0.1s resolution)
        dut1 = dut1_val * 0.1
        if dut1_negative and not dut1_positive:
            dut1 = -dut1

        # Year: positions 45-48 (tens) and 50-53 (units)
        year_tens = bcd_decode(
            [bits[45], bits[46], bits[47], bits[48]], [80, 40, 20, 10]
        )
        year_units = bcd_decode(
            [bits[50], bits[51], bits[52], bits[53]], [8, 4, 2, 1]
        )
        year = 2000 + year_tens + year_units

        # Leap year indicator: position 55
        leap_year = bits[55] == "1"

        # Leap second warning: position 56
        leap_second_warning = bits[56] == "1"

        # DST: positions 57-58
        dst2 = bits[57] == "1"
        dst1 = bits[58] == "1"
        if dst2 and dst1:
            dst = "on"
        elif dst2 and not dst1:
            dst = "begins_today"
        elif not dst2 and dst1:
            dst = "ends_today"
        else:
            dst = "off"

    except (IndexError, TypeError) as e:
        return None, f"BCD decode error: {e}"

    # 4. Range validation
    if not (0 <= minute <= 59):
        return None, f"Minutes {minute} out of range 0-59"
    if not (0 <= hour <= 23):
        return None, f"Hours {hour} out of range 0-23"
    if not (1 <= day_of_year <= 366):
        return None, f"Day of year {day_of_year} out of range 1-366"
    if not (2000 <= year <= 2099):
        return None, f"Year {year} out of range 2000-2099"

    # 5. Leap year cross-check
    actual_leap = (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
    if leap_year != actual_leap:
        logger.debug(
            f"Leap year indicator ({leap_year}) doesn't match year {year} "
            f"(computed: {actual_leap})"
        )

    return WWVBTime(
        year=year,
        day_of_year=day_of_year,
        hour=hour,
        minute=minute,
        dut1=dut1,
        dst=dst,
        leap_year=leap_year,
        leap_second_warning=leap_second_warning,
    ), None


class FrameAssembler:
    """Buffer decoded symbols and assemble WWVB frames.

    Handles frame synchronization by detecting two consecutive markers
    (positions 59 and 0), then fills a 60-element buffer.
    """

    def __init__(self, min_frames: int = 2, max_errors: int = 0):
        self._buffer: list[str | None] = [None] * 60
        self._position = 0
        self._synced = False
        self._consecutive_markers = 0
        self._valid_frames: list[WWVBTime] = []
        self._min_frames = min_frames
        self._max_errors = max_errors
        self._confirmed_time: WWVBTime | None = None
        self._last_decoded: WWVBTime | None = None
        self._total_frames = 0
        self._error_frames = 0
        self._consecutive_good = 0

    def add_symbol(self, symbol: str) -> FrameEvent | None:
        """Add a decoded symbol to the frame buffer.

        Returns a FrameEvent if something significant happened.
        """
        if not self._synced:
            return self._handle_sync(symbol)
        else:
            return self._handle_decode(symbol)

    def _handle_sync(self, symbol: str) -> FrameEvent | None:
        """Before sync: look for two consecutive markers."""
        if symbol == "M":
            self._consecutive_markers += 1
            if self._consecutive_markers >= 2:
                # Found double marker = frame boundary
                # The NEXT symbol will be position 0 of a new frame
                self._synced = True
                self._position = 0
                self._buffer = [None] * 60
                # Position 0 is also a marker (the second M we just saw
                # is both sec:59 of old frame and we treat next as sec:0)
                # Actually: the two consecutive M are sec:59 M and sec:0 M.
                # So the LAST M we saw is sec:0. Place it.
                self._buffer[0] = "M"
                self._position = 1
                logger.info("Frame sync acquired")
                return FrameEvent(
                    event_type=FrameEventType.SYNC_ACQUIRED,
                    message="Frame sync acquired",
                    position=0,
                )
            else:
                return FrameEvent(
                    event_type=FrameEventType.SYNC_PROGRESS,
                    message=f"Found {self._consecutive_markers} of 2 consecutive markers",
                    position=0,
                )
        else:
            self._consecutive_markers = 0
            return None

    def _handle_decode(self, symbol: str) -> FrameEvent | None:
        """After sync: fill frame buffer and parse when complete."""
        if self._position >= 60:
            # Shouldn't happen, but protect
            self._position = 0
            self._buffer = [None] * 60

        self._buffer[self._position] = symbol
        current_pos = self._position
        self._position += 1

        if self._position < 60:
            # Frame not complete yet
            return FrameEvent(
                event_type=FrameEventType.SYMBOL_ADDED,
                position=current_pos,
            )

        # Frame complete! Parse it.
        self._total_frames += 1
        self._position = 0
        frame_bits = list(self._buffer)
        self._buffer = [None] * 60

        decoded_time, error = parse_frame(frame_bits, max_errors=self._max_errors)

        if error:
            self._error_frames += 1
            self._consecutive_good = 0
            logger.warning(f"Frame error: {error}")

            # Only lose sync if errors are overwhelming (> 2x tolerance)
            # With error tolerance, occasional marker misses are expected
            if "Too many errors" in error and self._max_errors > 0:
                # Parse error count from message
                try:
                    err_count = int(error.split("(")[1].split(")")[0])
                    if err_count > self._max_errors * 2:
                        self._synced = False
                        self._consecutive_markers = 0
                except (IndexError, ValueError):
                    pass
            elif "marker" in error.lower() and self._max_errors == 0:
                self._synced = False
                self._consecutive_markers = 0

            return FrameEvent(
                event_type=FrameEventType.FRAME_ERROR,
                message=error,
                position=59,
            )

        # Valid frame
        self._consecutive_good += 1
        self._last_decoded = decoded_time

        # Multi-frame validation
        if self._valid_frames:
            prev = self._valid_frames[-1]
            # Check if new time follows previous (prev.matches checks if other
            # is 0 or 1 minute after self)
            if prev.matches(decoded_time):
                self._valid_frames.append(decoded_time)
            else:
                # Mismatch, reset sequence
                self._valid_frames = [decoded_time]
        else:
            self._valid_frames.append(decoded_time)

        # Check if we have enough consecutive matching frames
        if len(self._valid_frames) >= self._min_frames:
            self._confirmed_time = decoded_time

        logger.info(f"Frame decoded: {decoded_time.to_utc_string()}")

        return FrameEvent(
            event_type=FrameEventType.FRAME_COMPLETE,
            message=f"Frame decoded: {decoded_time.to_utc_string()}",
            time=decoded_time,
            position=59,
        )

    @property
    def current_position(self) -> int:
        return self._position

    @property
    def current_bits(self) -> list[str | None]:
        return list(self._buffer)

    @property
    def is_synced(self) -> bool:
        return self._synced

    @property
    def confirmed_time(self) -> WWVBTime | None:
        return self._confirmed_time

    @property
    def last_decoded(self) -> WWVBTime | None:
        return self._last_decoded

    @property
    def total_frames(self) -> int:
        return self._total_frames

    @property
    def error_frames(self) -> int:
        return self._error_frames

    @property
    def consecutive_good(self) -> int:
        return self._consecutive_good

    @property
    def success_rate(self) -> float:
        if self._total_frames == 0:
            return 0.0
        return (self._total_frames - self._error_frames) / self._total_frames * 100.0

    def reset_sync(self) -> None:
        """Reset synchronization state."""
        self._synced = False
        self._consecutive_markers = 0
        self._position = 0
        self._buffer = [None] * 60
