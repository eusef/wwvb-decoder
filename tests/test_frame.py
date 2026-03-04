"""Unit tests for WWVB frame parsing and BCD decoding."""

import pytest

from wwvb_decode.frame import (
    FrameAssembler,
    FrameEventType,
    WWVBTime,
    bcd_decode,
    parse_frame,
)


class TestBCDDecode:
    def test_simple_bcd(self):
        assert bcd_decode(["1", "0", "1", "0"], [8, 4, 2, 1]) == 10

    def test_zero(self):
        assert bcd_decode(["0", "0", "0", "0"], [8, 4, 2, 1]) == 0

    def test_all_ones(self):
        assert bcd_decode(["1", "1", "1", "1"], [8, 4, 2, 1]) == 15

    def test_weighted(self):
        # Minutes tens: weights 40, 20, 10
        assert bcd_decode(["1", "0", "1"], [40, 20, 10]) == 50

    def test_day_hundreds(self):
        # Day hundreds: weights 200, 100
        assert bcd_decode(["1", "1"], [200, 100]) == 300


def _make_test_frame(
    year=26, day=64, hour=3, minute=18,
    dut1_pos=True, dut1_val=2, dst="on",
    leap_year=False, leap_second=False,
):
    """Generate a valid 60-symbol WWVB frame for testing.

    Args:
        year: 2-digit year (0-99, added to 2000)
        day: day of year (1-366)
        hour: UTC hour (0-23)
        minute: UTC minute (0-59)
        dut1_pos: True if DUT1 is positive
        dut1_val: DUT1 value in tenths (0-9)
        dst: "off", "on", "begins_today", "ends_today"
        leap_year: True if leap year
        leap_second: True if leap second warning
    """
    bits = ["0"] * 60

    # Position 0: Frame reference marker
    bits[0] = "M"

    # Minutes tens (positions 1-3, weights 40, 20, 10)
    min_tens = minute // 10
    bits[1] = "1" if min_tens >= 4 else "0"
    rem = min_tens % 4 if min_tens >= 4 else min_tens
    bits[2] = "1" if rem >= 2 else "0"
    rem2 = rem % 2 if rem >= 2 else rem
    bits[3] = "1" if rem2 >= 1 else "0"

    # Position 4: unused (already 0)

    # Minutes units (positions 5-8, weights 8, 4, 2, 1)
    min_units = minute % 10
    bits[5] = "1" if min_units & 8 else "0"
    bits[6] = "1" if min_units & 4 else "0"
    bits[7] = "1" if min_units & 2 else "0"
    bits[8] = "1" if min_units & 1 else "0"

    # Position 9: Marker P1
    bits[9] = "M"

    # Positions 10-11: unused
    # Hours tens (positions 12-13, weights 20, 10)
    hr_tens = hour // 10
    bits[12] = "1" if hr_tens >= 2 else "0"
    bits[13] = "1" if (hr_tens % 2) >= 1 else "0"

    # Position 14: unused

    # Hours units (positions 15-18, weights 8, 4, 2, 1)
    hr_units = hour % 10
    bits[15] = "1" if hr_units & 8 else "0"
    bits[16] = "1" if hr_units & 4 else "0"
    bits[17] = "1" if hr_units & 2 else "0"
    bits[18] = "1" if hr_units & 1 else "0"

    # Position 19: Marker P2
    bits[19] = "M"

    # Positions 20-21: unused

    # Day hundreds (positions 22-23, weights 200, 100)
    day_hundreds = day // 100
    bits[22] = "1" if day_hundreds >= 2 else "0"
    bits[23] = "1" if (day_hundreds % 2) >= 1 else "0"

    # Day tens (positions 24-27, weights 80, 40, 20, 10)
    day_tens = (day % 100) // 10
    bits[24] = "1" if day_tens & 8 else "0"
    bits[25] = "1" if day_tens & 4 else "0"
    bits[26] = "1" if day_tens & 2 else "0"
    bits[27] = "1" if day_tens & 1 else "0"

    # Position 28: unused

    # Position 29: Marker P3
    bits[29] = "M"

    # Day units (positions 30-33, weights 8, 4, 2, 1)
    day_units = day % 10
    bits[30] = "1" if day_units & 8 else "0"
    bits[31] = "1" if day_units & 4 else "0"
    bits[32] = "1" if day_units & 2 else "0"
    bits[33] = "1" if day_units & 1 else "0"

    # Positions 34-35: unused

    # DUT1 sign (positions 36-38)
    if dut1_pos:
        bits[36] = "1"
        bits[37] = "0"
        bits[38] = "1"
    else:
        bits[36] = "0"
        bits[37] = "1"
        bits[38] = "0"

    # Position 39: Marker P4
    bits[39] = "M"

    # DUT1 value (positions 40-43, weights 8, 4, 2, 1)
    # DUT1 value is in units, where each unit = 0.1s
    bits[40] = "1" if dut1_val & 8 else "0"
    bits[41] = "1" if dut1_val & 4 else "0"
    bits[42] = "1" if dut1_val & 2 else "0"
    bits[43] = "1" if dut1_val & 1 else "0"

    # Position 44: unused

    # Year tens (positions 45-48, weights 80, 40, 20, 10)
    yr_tens = year // 10
    bits[45] = "1" if yr_tens & 8 else "0"
    bits[46] = "1" if yr_tens & 4 else "0"
    bits[47] = "1" if yr_tens & 2 else "0"
    bits[48] = "1" if yr_tens & 1 else "0"

    # Position 49: Marker P5
    bits[49] = "M"

    # Year units (positions 50-53, weights 8, 4, 2, 1)
    yr_units = year % 10
    bits[50] = "1" if yr_units & 8 else "0"
    bits[51] = "1" if yr_units & 4 else "0"
    bits[52] = "1" if yr_units & 2 else "0"
    bits[53] = "1" if yr_units & 1 else "0"

    # Position 54: unused

    # Position 55: Leap year indicator
    bits[55] = "1" if leap_year else "0"

    # Position 56: Leap second warning
    bits[56] = "1" if leap_second else "0"

    # Positions 57-58: DST
    if dst == "on":
        bits[57] = "1"
        bits[58] = "1"
    elif dst == "begins_today":
        bits[57] = "1"
        bits[58] = "0"
    elif dst == "ends_today":
        bits[57] = "0"
        bits[58] = "1"
    else:  # off
        bits[57] = "0"
        bits[58] = "0"

    # Position 59 is the next frame's marker (P0)
    # In the frame buffer it would be whatever the next symbol is.
    # For testing a complete parse, we just leave it as "0" or set to "M"
    # The parse_frame function only checks markers at 0,9,19,29,39,49
    bits[59] = "0"

    return bits


class TestParseFrame:
    def test_valid_frame(self):
        """Test parsing a known valid frame: 2026-03-05 03:18 UTC."""
        bits = _make_test_frame(year=26, day=64, hour=3, minute=18, dst="on")
        time_obj, error = parse_frame(bits)
        assert error is None
        assert time_obj is not None
        assert time_obj.year == 2026
        assert time_obj.day_of_year == 64
        assert time_obj.hour == 3
        assert time_obj.minute == 18
        assert time_obj.dst == "on"
        assert time_obj.dut1 == 0.2

    def test_midnight(self):
        bits = _make_test_frame(year=26, day=1, hour=0, minute=0)
        time_obj, error = parse_frame(bits)
        assert error is None
        assert time_obj.hour == 0
        assert time_obj.minute == 0
        assert time_obj.day_of_year == 1

    def test_max_values(self):
        bits = _make_test_frame(year=99, day=366, hour=23, minute=59)
        time_obj, error = parse_frame(bits)
        assert error is None
        assert time_obj.year == 2099
        assert time_obj.day_of_year == 366
        assert time_obj.hour == 23
        assert time_obj.minute == 59

    def test_missing_marker(self):
        bits = _make_test_frame()
        bits[9] = "0"  # Remove marker at position 9
        time_obj, error = parse_frame(bits)
        assert time_obj is None
        assert "marker" in error.lower()

    def test_invalid_hours(self):
        """Hours > 23 should be rejected."""
        bits = _make_test_frame(hour=0)
        # Manually set hours to 25 (tens=2, units=5)
        bits[12] = "1"  # 20
        bits[13] = "0"
        bits[15] = "0"
        bits[16] = "1"  # 4
        bits[17] = "0"
        bits[18] = "1"  # 1 -> units=5, total=25
        time_obj, error = parse_frame(bits)
        assert time_obj is None
        assert "hours" in error.lower()

    def test_wrong_length(self):
        time_obj, error = parse_frame(["0"] * 59)
        assert time_obj is None
        assert "60" in error

    def test_dst_variants(self):
        for dst_val, expected in [
            ("off", "off"),
            ("on", "on"),
            ("begins_today", "begins_today"),
            ("ends_today", "ends_today"),
        ]:
            bits = _make_test_frame(dst=dst_val)
            time_obj, _ = parse_frame(bits)
            assert time_obj.dst == expected

    def test_negative_dut1(self):
        bits = _make_test_frame(dut1_pos=False, dut1_val=3)
        time_obj, error = parse_frame(bits)
        assert error is None
        assert abs(time_obj.dut1 - (-0.3)) < 1e-9

    def test_leap_year_indicator(self):
        bits = _make_test_frame(year=24, leap_year=True)
        time_obj, _ = parse_frame(bits)
        assert time_obj.leap_year is True

    def test_to_utc_string(self):
        bits = _make_test_frame(year=26, day=64, hour=3, minute=18)
        time_obj, _ = parse_frame(bits)
        utc_str = time_obj.to_utc_string()
        assert "2026" in utc_str
        assert "03:18" in utc_str
        assert "UTC" in utc_str


class TestWWVBTimeMatches:
    def test_same_time_matches(self):
        t1 = WWVBTime(2026, 64, 3, 18, 0.2, "on", False, False)
        t2 = WWVBTime(2026, 64, 3, 18, 0.2, "on", False, False)
        assert t1.matches(t2)

    def test_one_minute_later_matches(self):
        t1 = WWVBTime(2026, 64, 3, 18, 0.2, "on", False, False)
        t2 = WWVBTime(2026, 64, 3, 19, 0.2, "on", False, False)
        assert t1.matches(t2)

    def test_two_minutes_later_no_match(self):
        t1 = WWVBTime(2026, 64, 3, 18, 0.2, "on", False, False)
        t2 = WWVBTime(2026, 64, 3, 20, 0.2, "on", False, False)
        assert not t1.matches(t2)


class TestFrameAssembler:
    def test_sync_on_double_marker(self):
        asm = FrameAssembler(min_frames=1)
        # Feed non-marker symbols, then two markers
        for _ in range(5):
            event = asm.add_symbol("0")
        event = asm.add_symbol("M")
        assert event.event_type == FrameEventType.SYNC_PROGRESS
        event = asm.add_symbol("M")
        assert event.event_type == FrameEventType.SYNC_ACQUIRED
        assert asm.is_synced

    def test_full_frame_decode(self):
        asm = FrameAssembler(min_frames=1)
        bits = _make_test_frame(year=26, day=64, hour=3, minute=18)

        # Sync: two consecutive markers
        asm.add_symbol("M")
        asm.add_symbol("M")  # This triggers sync, and places M at position 0

        # Now feed bits 1-59 (position 0 already placed by sync)
        last_event = None
        for i in range(1, 60):
            event = asm.add_symbol(bits[i])
            if event and event.event_type in (
                FrameEventType.FRAME_COMPLETE,
                FrameEventType.FRAME_ERROR,
            ):
                last_event = event

        assert last_event is not None
        assert last_event.event_type == FrameEventType.FRAME_COMPLETE
        assert last_event.time is not None
        assert last_event.time.year == 2026
        assert last_event.time.minute == 18

    def test_multi_frame_confirmation(self):
        """Two consecutive matching frames should produce confirmed time."""
        asm = FrameAssembler(min_frames=2)

        # Frame 1
        bits1 = _make_test_frame(year=26, day=64, hour=3, minute=18)

        # Sync: two M's. The second M is placed at position 0.
        asm.add_symbol("M")
        event = asm.add_symbol("M")
        assert event.event_type == FrameEventType.SYNC_ACQUIRED

        # Feed bits 1-59 for frame 1 (position 0 already filled by sync)
        for i in range(1, 60):
            asm.add_symbol(bits1[i])

        assert asm.confirmed_time is None  # Not confirmed yet (need 2 frames)
        assert asm.last_decoded is not None
        assert asm.last_decoded.minute == 18

        # Frame 2 (one minute later)
        # After frame 1 completes, position resets to 0.
        # We need to feed all 60 symbols for frame 2.
        bits2 = _make_test_frame(year=26, day=64, hour=3, minute=19)
        for i in range(0, 60):
            asm.add_symbol(bits2[i])

        assert asm.confirmed_time is not None
        assert asm.confirmed_time.minute == 19
