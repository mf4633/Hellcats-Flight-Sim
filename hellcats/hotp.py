"""HOTP authentic RNG and flight math from the 1991 binary."""
import math

# ============== HOTP AUTHENTIC RNG ==============
# Exact Linear Congruential Generator from Hellcats Over the Pacific (1991)
# Reconstructed from Ghidra-decompiled 68k Macintosh CODE segment ID05
# Same algorithm as POSIX rand(): state * 1103515245 + 12345 (mod 2^32)
class HOTP_RNG:
    """Deterministic RNG matching the original 1991 game binary."""
    def __init__(self, seed=54321):
        self.state = seed & 0xFFFFFFFF

    def next(self):
        """15-bit output [0, 32767] - primary game RNG"""
        self.state = (self.state * 0x41C64E6D + 0x3039) & 0xFFFFFFFF
        return (self.state >> 16) & 0x7FFF

    def next_byte(self):
        """8-bit output [0, 255]"""
        self.state = (self.state * 0x41C64E6D + 0x3039) & 0xFFFFFFFF
        return (self.state >> 24) & 0xFF

    def coin_flip(self):
        """Single-bit coin flip (used for weapon type selection in original)"""
        return (self.next() & 1) == 0

    def fraction(self):
        """Return float [0, 1) for probability checks"""
        return self.next() / 32768.0


# Module-level HOTP RNG instance for all AI/combat randomness
hotp_rng = HOTP_RNG()

# HOTP entity flag constants (bitmask fields from decompiled struct offset 0x685)
HOTP_FLAG_JITTER_AXIS1 = 0x04   # Enable RNG perturbation on heading axis
HOTP_FLAG_JITTER_AXIS2 = 0x08   # Enable RNG perturbation on pitch/alt axis
HOTP_FLAG_CONTROL_GATE = 0x40   # Control gate condition for weapon fire
HOTP_FLAG_SMOOTH_CTRL  = 0x80   # Halve control accumulator (smoother movement)

# HOTP aerodynamic lookup table (9 entries, reconstructed from DAT_0001b2c0)
# Used for altitude/speed curve interpolation in the original 68k binary
HOTP_AERO_TABLE_RAW = [
    3720288, 5261024, 7442159, 10526208, 14890655,
    2949165, 1966095, 458754, 421
]
_aero_max = max(HOTP_AERO_TABLE_RAW)
HOTP_AERO_TABLE = [v / _aero_max for v in HOTP_AERO_TABLE_RAW]


def _half_toward_zero(value):
    """HOTP utility: halve an integer toward zero (from sim_core.gd).
    For negative values, adds 1 before right-shift to round toward zero."""
    if value < 0:
        return int((value + 1) / 2)
    return int(value / 2)


def _to_s16(value):
    """Interpret low 16 bits of an integer as signed 16-bit (68k style)."""
    v = value & 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def hotp_delta_smooth(current, target, dt):
    """HOTP-style delta smoothing from the original game's movement system.
    Matches the exact integer logic from add_delta_smoothed_int in flight_math.gd:
    - Small deltas (integer >>3 == 0, i.e. |delta|<8): apply fully per tick
    - Large deltas: apply delta//8 per tick (with negative rounding toward zero)
    Adapted to floating-point with dt scaling for our real-time context."""
    delta = target - current
    rate = min(dt * 60, 1.0)  # normalize to ~60fps tick rate
    # Match original's threshold: (d + 7*(d<0)) >> 3 == 0
    # For positive: |d|<8. For negative: |d|<=8. Close enough with abs<8.
    d_int = int(delta)
    adj = d_int + 7 if d_int < 0 else d_int
    if (adj >> 3) == 0:
        return current + delta * rate
    # Original: (delta + 7*(delta<0)) >> 3 (rounds toward zero for negatives)
    if delta < 0:
        step = -int((-delta + 7) / 8)
    else:
        step = int(delta / 8)
    return current + step * rate


def hotp_delta_smooth_s16(current, target, dt):
    """Signed 16-bit variant of delta smoothing (from add_delta_smoothed_s16).
    Result wrapped to signed 16-bit range [-32768, 32767]."""
    result = hotp_delta_smooth(current, target, dt)
    return _to_s16(int(result))


def hotp_aero_lookup(param):
    """Interpolated lookup in the HOTP aerodynamic table.
    param: 0.0-1.0 input mapped across 9-entry table. Returns normalized value.
    Note: original uses raw 32-bit input where upper 16 bits = index,
    lower 16 bits = fraction, and interprets entries as signed 16-bit via _to_s16.
    We use the normalized version for our altitude performance curve."""
    table = HOTP_AERO_TABLE
    scaled = param * (len(table) - 1)
    idx = max(0, min(int(scaled), len(table) - 2))
    frac = scaled - idx
    return table[idx] * (1 - frac) + table[idx + 1] * frac


def hotp_fun_e570(template_field_38, param_1):
    """FUN_0000e570 — template scaling function (from flight_math.gd).
    Scales an aircraft template parameter by inverse relationship with param_1.
    Original: denominator = (param_1 + 0x105) >> 3; ratio = 0x551A / den;
    result = (field_38 * ratio) >> 8"""
    denominator = (int(param_1) + 0x105) >> 3
    if denominator <= 0:
        return 0
    ratio = int(0x551A / denominator)
    return (int(template_field_38) * ratio) >> 8


def hotp_fun_e468(param_1, param_2):
    """FUN_0000e468 — low-speed damping (from flight_math.gd).
    When param_1 < 0x200 (512), reduces param_2 proportionally.
    Original: scaled = -(param_1 - 0x200) * param_2; param_2 -= scaled >> 12"""
    p1 = int(param_1)
    p2 = param_2
    if p1 < 0x200:
        scaled = -(p1 - 0x200) * p2
        if scaled < 0:
            scaled += 0xFFF  # round toward zero for 12-bit shift
        p2 -= scaled >> 12
    return p2


