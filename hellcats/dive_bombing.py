"""SBD dive-bombing attack mechanics."""

# Release window (ft AGL) — historical SBD drop band
RELEASE_ALT_MIN = 1500
RELEASE_ALT_MAX = 3000
# Enter dive when nose-down beyond this pitch (degrees)
DIVE_ENTER_PITCH = -28
# Minimum altitude to commence a dive run
DIVE_START_MIN_ALT = 4000
# Pullout when nose rises above this after release
PULLOUT_PITCH = -12
# Max dive airspeed before structural warning (kts)
DIVE_MAX_SPEED = 300


def in_release_window(altitude_ft):
    return RELEASE_ALT_MIN <= altitude_ft <= RELEASE_ALT_MAX


def can_arm_dive(aircraft):
    """True when aircraft is positioned to begin a dive attack."""
    return (
        aircraft.z >= DIVE_START_MIN_ALT
        and aircraft.pitch <= DIVE_ENTER_PITCH
        and getattr(aircraft, 'dive_brakes', False)
    )


def update_dive_state(aircraft, dt):
    """
    Update SBD dive-bombing state machine.
    Returns optional status string for HUD.
    """
    if not hasattr(aircraft, 'dive_mode'):
        return None

    pitch = aircraft.pitch
    alt = aircraft.z
    kts = aircraft.get_airspeed_kts()
    mode = aircraft.dive_mode

    if mode == 'cruise':
        if can_arm_dive(aircraft):
            aircraft.dive_mode = 'diving'
            aircraft.dive_start_alt = alt
    elif mode == 'diving':
        # Gentle pitch authority boost with brakes extended (stabilized dive)
        if getattr(aircraft, 'dive_brakes', False):
            aircraft.pitch_rate *= 0.85

        if kts > DIVE_MAX_SPEED:
            aircraft.overspeed = True
            return "!! DIVE OVERSPEED — PULL UP !!"

        if in_release_window(alt):
            aircraft.dive_bomb_armed = True
        else:
            aircraft.dive_bomb_armed = False

        if alt < RELEASE_ALT_MIN - 200:
            aircraft.dive_mode = 'pullout'
            return "!! PULL UP — TOO LOW !!"

        if aircraft.bombs <= 0 and getattr(aircraft, 'dive_bomb_released', False):
            aircraft.dive_mode = 'pullout'

    elif mode == 'pullout':
        aircraft.dive_bomb_armed = False
        if pitch >= PULLOUT_PITCH:
            aircraft.dive_mode = 'cruise'
            aircraft.dive_bomb_released = False

    return None


def dive_hud_lines(aircraft):
    """Return list of HUD status lines for dive bombing."""
    if not hasattr(aircraft, 'dive_mode'):
        return []

    mode = aircraft.dive_mode
    alt = int(aircraft.z)
    lines = []

    if mode == 'cruise':
        lines.append("DIVE: Climb above 4,000 ft, roll in, hold B for brakes")
    elif mode == 'diving':
        lines.append(f"DIVE ATTACK — {alt} ft")
        if getattr(aircraft, 'dive_bomb_armed', False):
            lines.append("RELEASE WINDOW — DROP BOMB (weapon 3 + SPACE)")
        elif alt > RELEASE_ALT_MAX:
            lines.append(f"Steeper dive — release window at {RELEASE_ALT_MAX} ft")
        else:
            lines.append(f"Pull up after release (min {RELEASE_ALT_MIN} ft)")
    elif mode == 'pullout':
        lines.append("PULLOUT — recover from dive")

    return lines


def validate_dive_drop(aircraft):
    """Return (ok, reason) for SBD dive bomb release."""
    if aircraft.bombs <= 0:
        return False, "NO BOMBS REMAINING"
    if aircraft.dive_mode != 'diving':
        return False, "NOT IN DIVE — pitch down with brakes (B)"
    if not in_release_window(aircraft.z):
        return False, f"OUTSIDE WINDOW ({RELEASE_ALT_MIN}-{RELEASE_ALT_MAX} ft)"
    if aircraft.pitch > -15:
        return False, "TOO SHALLOW — steepen dive"
    return True, ""