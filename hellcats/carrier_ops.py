"""Carrier approach scoring and graded trap evaluation."""
import math

# Letter grades ordered best → worst (index used for comparisons)
GRADE_ORDER = "SABCF"

# Points awarded per letter grade
GRADE_POINTS = {"S": 200, "A": 150, "B": 100, "C": 50, "F": 0}


def _deck_offset(carrier, px, py):
    """Return (forward_ft, lateral_ft) in deck-local coordinates."""
    hdg_rad = math.radians(carrier.heading)
    dx, dy = px - carrier.x, py - carrier.y
    local_fwd = dx * math.sin(hdg_rad) + dy * math.cos(hdg_rad)
    local_lat = dx * math.cos(hdg_rad) - dy * math.sin(hdg_rad)
    return local_fwd, local_lat


class LandingScorer:
    """Grade carrier traps using LSO-style criteria."""

    def __init__(self):
        self.last_result = None
        self._landed_this_approach = False

    def reset_approach(self):
        self._landed_this_approach = False

    def score_trap(self, aircraft, carrier, wire_num, bolter=False):
        """
        Score a carrier landing. Returns dict:
          grade, points, label, breakdown, aircraft_name
        """
        name = getattr(aircraft.__class__, "NAME", "Aircraft")
        ideal_lo, ideal_hi = getattr(aircraft.__class__, "CARRIER_IDEAL_SPEED", (105, 125))
        max_wire = getattr(aircraft.__class__, "CARRIER_MAX_WIRE_SPEED", 150)

        if bolter or wire_num == 0:
            result = {
                "grade": "F",
                "points": 0,
                "label": "BOLTER — missed the wires",
                "breakdown": [],
                "aircraft_name": name,
                "bolter": True,
            }
            self.last_result = result
            return result

        airspeed = aircraft.get_airspeed_kts()
        sink_fpm = abs(aircraft.vz) * 60
        _, lateral = _deck_offset(carrier, aircraft.x, aircraft.y)
        centerline_ft = abs(lateral)

        # Sub-scores 0–100
        wire_scores = {1: 70, 2: 85, 3: 100, 4: 80}
        wire_pts = wire_scores.get(wire_num, 60)

        if ideal_lo <= airspeed <= ideal_hi:
            speed_pts = 100
        elif airspeed < ideal_lo:
            speed_pts = max(40, 100 - (ideal_lo - airspeed) * 2)
        else:
            overshoot = airspeed - ideal_hi
            if airspeed > max_wire:
                speed_pts = 20
            else:
                speed_pts = max(30, 100 - overshoot * 3)

        if sink_fpm <= 600:
            sink_pts = 100
        elif sink_fpm <= 900:
            sink_pts = 75
        elif sink_fpm <= 1200:
            sink_pts = 50
        else:
            sink_pts = 25

        if centerline_ft <= 8:
            line_pts = 100
        elif centerline_ft <= 20:
            line_pts = 75
        elif centerline_ft <= 35:
            line_pts = 50
        else:
            line_pts = 30

        gear_pts = 100 if aircraft.gear_down else 0
        total = (wire_pts * 0.30 + speed_pts * 0.25 + sink_pts * 0.20
                 + line_pts * 0.15 + gear_pts * 0.10)

        if total >= 92:
            grade = "S"
        elif total >= 82:
            grade = "A"
        elif total >= 70:
            grade = "B"
        elif total >= 55:
            grade = "C"
        else:
            grade = "F"

        breakdown = [
            f"Wire {wire_num}: {wire_pts}/100",
            f"Speed {airspeed:.0f} kts (ideal {ideal_lo}-{ideal_hi}): {speed_pts}/100",
            f"Sink rate {sink_fpm:.0f} fpm: {sink_pts}/100",
            f"Centerline {centerline_ft:.0f} ft off: {line_pts}/100",
            f"Gear {'down' if aircraft.gear_down else 'UP'}: {gear_pts}/100",
        ]

        labels = {
            "S": "PERFECT TRAP — LSO grade S",
            "A": "EXCELLENT — solid carrier qual",
            "B": "GOOD PASS — welcome aboard",
            "C": "FAIR — check your approach",
            "F": "NO GRADE — wave off next time",
        }

        result = {
            "grade": grade,
            "points": GRADE_POINTS[grade],
            "label": labels[grade],
            "breakdown": breakdown,
            "aircraft_name": name,
            "bolter": False,
            "total_score": round(total, 1),
        }
        self.last_result = result
        return result

    def grade_at_least(self, grade, minimum):
        """True if grade meets minimum letter (e.g. B accepts B, A, S)."""
        if grade not in GRADE_ORDER or minimum not in GRADE_ORDER:
            return False
        return GRADE_ORDER.index(grade) <= GRADE_ORDER.index(minimum)