"""Generate synthetic WWVB audio test data.

Creates a stereo 48kHz PCM audio stream that encodes a known WWVB frame.
The audio simulates what SDRConnect's AM demodulator would output:
amplitude variations representing the WWVB pulse-width modulation.
"""

import numpy as np
from pathlib import Path


def generate_wwvb_frame_bits(
    year: int = 26, day: int = 64, hour: int = 3, minute: int = 18
) -> list[str]:
    """Generate the 60 symbols for a WWVB frame.

    Uses the same logic as test_frame._make_test_frame.
    """
    bits = ["0"] * 60

    # Markers
    for pos in [0, 9, 19, 29, 39, 49]:
        bits[pos] = "M"

    # Minutes
    min_tens = minute // 10
    bits[1] = "1" if min_tens >= 4 else "0"
    rem = min_tens % 4 if min_tens >= 4 else min_tens
    bits[2] = "1" if rem >= 2 else "0"
    bits[3] = "1" if (rem % 2) >= 1 else "0"

    min_units = minute % 10
    bits[5] = "1" if min_units & 8 else "0"
    bits[6] = "1" if min_units & 4 else "0"
    bits[7] = "1" if min_units & 2 else "0"
    bits[8] = "1" if min_units & 1 else "0"

    # Hours
    hr_tens = hour // 10
    bits[12] = "1" if hr_tens >= 2 else "0"
    bits[13] = "1" if (hr_tens % 2) >= 1 else "0"

    hr_units = hour % 10
    bits[15] = "1" if hr_units & 8 else "0"
    bits[16] = "1" if hr_units & 4 else "0"
    bits[17] = "1" if hr_units & 2 else "0"
    bits[18] = "1" if hr_units & 1 else "0"

    # Day of year
    day_h = day // 100
    bits[22] = "1" if day_h >= 2 else "0"
    bits[23] = "1" if (day_h % 2) >= 1 else "0"

    day_t = (day % 100) // 10
    bits[24] = "1" if day_t & 8 else "0"
    bits[25] = "1" if day_t & 4 else "0"
    bits[26] = "1" if day_t & 2 else "0"
    bits[27] = "1" if day_t & 1 else "0"

    day_u = day % 10
    bits[30] = "1" if day_u & 8 else "0"
    bits[31] = "1" if day_u & 4 else "0"
    bits[32] = "1" if day_u & 2 else "0"
    bits[33] = "1" if day_u & 1 else "0"

    # DUT1 positive, value 2 (0.2s)
    bits[36] = "1"
    bits[38] = "1"
    bits[42] = "1"  # weight 2

    # Year
    yr_tens = year // 10
    bits[45] = "1" if yr_tens & 8 else "0"
    bits[46] = "1" if yr_tens & 4 else "0"
    bits[47] = "1" if yr_tens & 2 else "0"
    bits[48] = "1" if yr_tens & 1 else "0"

    yr_units = year % 10
    bits[50] = "1" if yr_units & 8 else "0"
    bits[51] = "1" if yr_units & 4 else "0"
    bits[52] = "1" if yr_units & 2 else "0"
    bits[53] = "1" if yr_units & 1 else "0"

    # DST on
    bits[57] = "1"
    bits[58] = "1"

    # Position 59 is the P0 marker (also next frame's reference)
    # Critical for sync: two consecutive markers at :59 and :00
    bits[59] = "M"

    return bits


def symbols_to_audio(
    symbols: list[str],
    sample_rate: int = 48000,
    high_amplitude: float = 0.8,
    low_amplitude: float = 0.1,
    noise_level: float = 0.02,
) -> np.ndarray:
    """Convert WWVB symbols to stereo PCM audio.

    Each symbol occupies exactly 1 second.
    Low-power periods:
      "0" -> 200ms low
      "1" -> 500ms low
      "M" -> 800ms low
    """
    total_samples = len(symbols) * sample_rate
    audio = np.full(total_samples, high_amplitude)

    for i, sym in enumerate(symbols):
        start = i * sample_rate

        if sym == "0":
            low_duration = int(sample_rate * 0.200)
        elif sym == "1":
            low_duration = int(sample_rate * 0.500)
        elif sym == "M":
            low_duration = int(sample_rate * 0.800)
        else:
            continue

        audio[start : start + low_duration] = low_amplitude

    # Add noise
    noise = np.random.normal(0, noise_level, total_samples)
    audio = audio + noise

    # Scale to int16 range
    audio = np.clip(audio, -1.0, 1.0)
    mono_int16 = (audio * 32000).astype(np.int16)

    # Create stereo interleaved
    stereo = np.zeros(total_samples * 2, dtype=np.int16)
    stereo[0::2] = mono_int16
    stereo[1::2] = mono_int16

    return stereo


def main():
    """Generate test audio files."""
    output_dir = Path(__file__).parent / "test_data"
    output_dir.mkdir(exist_ok=True)

    # Generate two consecutive frames (120 seconds)
    frame1 = generate_wwvb_frame_bits(year=26, day=64, hour=3, minute=18)
    frame2 = generate_wwvb_frame_bits(year=26, day=64, hour=3, minute=19)

    # Full sequence:
    # - 3 seconds of "high power" lead-in (0 pulses) for filter stabilization
    # - P0 marker at :59 of "previous" frame (triggers first consecutive marker)
    # - frame1 (starts with M at position 0 = second consecutive marker -> sync)
    # - frame2
    # The sync pattern: M at :59 followed by M at :00 = double marker
    frame3 = generate_wwvb_frame_bits(year=26, day=64, hour=3, minute=20)
    # Lead-in for filter stabilization, then 3 frames
    # Sync happens at frame1[59]/frame2[0] boundary (double M)
    # frame2 and frame3 are the two decoded frames for confirmation
    lead_in = ["0"] * 3
    symbols = lead_in + frame1 + frame2 + frame3

    audio = symbols_to_audio(symbols, noise_level=0.02)

    output_path = output_dir / "wwvb_test_2frames.raw"
    audio.tofile(str(output_path))
    print(f"Generated: {output_path}")
    print(f"  Symbols: {len(symbols)} seconds")
    print(f"  Samples: {len(audio)} (stereo int16 @ 48kHz)")
    print(f"  Size: {len(audio) * 2 / 1024 / 1024:.1f} MB")
    print(f"  Frame 1: 2026 day 064 03:18 UTC")
    print(f"  Frame 2: 2026 day 064 03:19 UTC")


if __name__ == "__main__":
    main()
