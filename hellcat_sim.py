"""
FLIGHT SIMULATOR - Aircraft Selection
Choose between:
  - Grumman F6F-5 Hellcat (WWII Fighter)
  - Boeing 747-200 (Jumbo Jet)
  - Disaster Recreations (Historic accidents)

Real physics for all aircraft with accurate specifications.

Controls:
  W/S - Pitch
  A/D - Roll
  Q/E - Yaw
  SHIFT/CTRL - Throttle
  F - Flaps
  G - Gear
  V - Cycle camera view (Overhead/Cockpit/Chase)
  +/- (or ]/[) - Increase/Decrease drag coefficient
  R - Reset
  M - Return to menu
  ESC - Menu/Quit

Weapons (F6F Hellcat only):
  1 - Select .50 cal Machine Guns (6x M2 Browning)
  2 - Select HVAR Rockets (6x 5-inch)
  3 - Select 500 lb Bomb
  SPACE - Fire selected weapon (hold for MG)
"""

import pygame
import math
import os
import random

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


# ============== WEATHER SYSTEM ==============
class Weather:
    """Dynamic weather — wind, rain, clouds, visibility. Affects physics and rendering."""
    CLEAR = 0
    OVERCAST = 1
    RAIN = 2
    STORM = 3
    NAMES = ['CLEAR', 'OVERCAST', 'RAIN', 'STORM']

    def __init__(self, condition=0):
        self.condition = condition
        self.wind_speed = 0        # kts
        self.wind_heading = 0      # degrees (direction wind is coming FROM)
        self.wind_gust = 0         # current gust component (kts)
        self.gust_timer = 0
        self.visibility = 1.0      # 1.0 = unlimited, 0.0 = zero vis
        self.cloud_base = 15000    # ft AGL
        self.rain_intensity = 0.0  # 0-1
        self.rain_drops = []       # screen-space particles [(x, y, vy, life)]
        self.turbulence = 0.0      # 0-1 intensity
        self._set_for_condition()

    def _set_for_condition(self):
        if self.condition == self.CLEAR:
            self.wind_speed = 5
            self.visibility = 1.0
            self.cloud_base = 20000
            self.rain_intensity = 0.0
            self.turbulence = 0.0
        elif self.condition == self.OVERCAST:
            self.wind_speed = 15
            self.visibility = 0.7
            self.cloud_base = 8000
            self.rain_intensity = 0.0
            self.turbulence = 0.15
        elif self.condition == self.RAIN:
            self.wind_speed = 25
            self.visibility = 0.4
            self.cloud_base = 4000
            self.rain_intensity = 0.6
            self.turbulence = 0.3
        elif self.condition == self.STORM:
            self.wind_speed = 45
            self.visibility = 0.2
            self.cloud_base = 2000
            self.rain_intensity = 1.0
            self.turbulence = 0.6

    def set_condition(self, cond):
        self.condition = cond
        self._set_for_condition()

    def get_wind_vector(self):
        """Returns (wx, wy) wind velocity in ft/s for physics."""
        total = (self.wind_speed + self.wind_gust) * 1.68781  # kts to ft/s
        wr = math.radians(self.wind_heading)
        return -math.sin(wr) * total, -math.cos(wr) * total

    def update(self, dt):
        # Wind gusts
        self.gust_timer -= dt
        if self.gust_timer <= 0:
            self.gust_timer = 2.0 + hotp_rng.fraction() * 4.0
            max_gust = self.wind_speed * 0.4 * self.turbulence
            self.wind_gust = (hotp_rng.fraction() - 0.3) * max_gust * 2

        # Rain particles (screen space)
        if self.rain_intensity > 0:
            # Spawn new drops
            spawn_count = int(self.rain_intensity * 15)
            for _ in range(spawn_count):
                self.rain_drops.append([
                    hotp_rng.next() % 1280,  # x
                    -5,                       # y (top of screen)
                    400 + hotp_rng.next() % 300,  # vy (fall speed)
                    0                          # life
                ])
            # Update existing
            for drop in self.rain_drops:
                drop[1] += drop[2] * dt
                drop[0] += self.wind_speed * 0.5 * dt  # Wind drift
                drop[3] += dt
            self.rain_drops = [d for d in self.rain_drops if d[1] < 920 and d[3] < 3.0]
            # Cap particles
            if len(self.rain_drops) > 400:
                self.rain_drops = self.rain_drops[-400:]

    def apply_turbulence(self, aircraft, dt):
        """Apply wind gusts and turbulence to aircraft."""
        if self.turbulence <= 0:
            return
        # Random pitch/roll/yaw perturbation
        t = self.turbulence
        aircraft.pitch_rate += (hotp_rng.fraction() - 0.5) * t * 30 * dt
        aircraft.roll_rate += (hotp_rng.fraction() - 0.5) * t * 40 * dt
        aircraft.yaw_rate += (hotp_rng.fraction() - 0.5) * t * 15 * dt

    def get_fog_color(self, is_night=False):
        """Fog/haze color adjusted for weather and time of day."""
        if is_night:
            base = (15, 20, 30)
        else:
            base = (180, 195, 210)
        if self.condition >= self.RAIN:
            # Grey, darker fog in rain/storm
            if is_night:
                return (10, 12, 18)
            return (130, 135, 140)
        return base

    def get_sky_tint(self, is_night=False):
        """Returns (r_mult, g_mult, b_mult) to tint sky colors."""
        if is_night:
            return (0.08, 0.08, 0.15)
        if self.condition == self.CLEAR:
            return (1.0, 1.0, 1.0)
        if self.condition == self.OVERCAST:
            return (0.6, 0.6, 0.65)
        if self.condition == self.RAIN:
            return (0.4, 0.4, 0.45)
        # STORM
        return (0.25, 0.25, 0.3)

    def draw_rain(self, surface):
        """Draw rain streaks on screen."""
        if self.rain_intensity <= 0 or not self.rain_drops:
            return
        for drop in self.rain_drops:
            x, y = int(drop[0]), int(drop[1])
            if 0 <= x < 1280 and 0 <= y < 900:
                length = int(6 + self.rain_intensity * 8)
                max(60, min(180, int(180 * self.rain_intensity)))
                pygame.draw.line(surface, (180, 190, 210), (x, y), (x - 1, y + length), 1)

    def draw_cloud_layer(self, surface, aircraft):
        """Draw cloud base when flying near/through clouds."""
        if aircraft.z < self.cloud_base - 2000:
            return  # Too far below to see
        if aircraft.z > self.cloud_base + 1000:
            return  # Above the layer
        # Proximity alpha
        dist_to_base = abs(aircraft.z - self.cloud_base)
        if dist_to_base < 500:
            alpha = 200  # In the soup
        else:
            alpha = int(200 * max(0, 1.0 - dist_to_base / 2000))
        if alpha <= 0:
            return
        overlay = pygame.Surface((surface.get_width(), surface.get_height()), pygame.SRCALPHA)
        overlay.fill((220, 225, 235, alpha))
        surface.blit(overlay, (0, 0))


# ============== NIGHT / TIME-OF-DAY ==============
class TimeOfDay:
    """Day/night state with searchlights and star field."""
    DAY = 0
    NIGHT = 1

    def __init__(self, mode=0):
        self.mode = mode
        self.stars = []  # pre-generated star positions
        self.flares = []  # active flares [(x, y, z, brightness, life)]
        if mode == self.NIGHT:
            self._generate_stars()

    def _generate_stars(self):
        self.stars = []
        for _ in range(120):
            self.stars.append((
                random.randint(0, 1280),
                random.randint(0, 500),
                random.randint(150, 255)
            ))

    def set_night(self):
        self.mode = self.NIGHT
        if not self.stars:
            self._generate_stars()

    def set_day(self):
        self.mode = self.DAY

    def is_night(self):
        return self.mode == self.NIGHT

    def drop_flare(self, x, y, z):
        """Drop an illumination flare at world position."""
        self.flares.append([x, y, z, 1.0, 0])  # brightness, age

    def update(self, dt):
        for flare in self.flares:
            flare[4] += dt       # age
            flare[2] -= 15 * dt  # descend slowly
            flare[3] = max(0, 1.0 - flare[4] / 30.0)  # fade over 30s
        self.flares = [f for f in self.flares if f[3] > 0.01]

    def get_sky_colors(self):
        """Returns (deep_sky, horizon) colors for sky gradient."""
        if self.mode == self.NIGHT:
            return (5, 8, 20), (15, 20, 40)
        return (50, 100, 180), (185, 206, 235)

    def draw_night_sky(self, surface, view_rect=None):
        """Draw stars on the sky portion of cockpit/chase view."""
        if self.mode != self.NIGHT:
            return
        for sx, sy, brightness in self.stars:
            if view_rect and not view_rect.collidepoint(sx, sy):
                continue
            c = (brightness, brightness, min(255, brightness + 30))
            surface.set_at((sx, sy), c)
            if brightness > 220:
                surface.set_at((sx + 1, sy), (brightness // 2, brightness // 2, brightness // 2))

    def draw_searchlights(self, surface, targets, aircraft):
        """Draw searchlight cones from AA gun positions."""
        if self.mode != self.NIGHT:
            return
        for tgt in targets:
            if not tgt.alive or not hasattr(tgt, 'ground_type'):
                continue
            if tgt.ground_type != 'aa_gun':
                continue
            # Project searchlight position to screen
            dx = tgt.x - aircraft.x
            dy = tgt.y - aircraft.y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist > 40000 or dist < 100:
                continue
            # Simple screen projection
            hdg_rad = math.radians(aircraft.heading)
            rel_x = dx * math.cos(hdg_rad) - dy * math.sin(hdg_rad)
            rel_y = dx * math.sin(hdg_rad) + dy * math.cos(hdg_rad)
            if rel_y < 100:
                continue
            sx = int(640 + rel_x / rel_y * 800)
            sy = int(450 - aircraft.z / rel_y * 800)
            if not (-100 < sx < 1380):
                continue
            # Beam cone
            beam_top = max(0, sy - 300)
            beam_surf = pygame.Surface((60, sy - beam_top), pygame.SRCALPHA)
            for row in range(beam_surf.get_height()):
                alpha = max(5, 25 - row * 25 // max(1, beam_surf.get_height()))
                w = 4 + row * 50 // max(1, beam_surf.get_height())
                cx_b = 30
                pygame.draw.line(beam_surf, (255, 255, 200, alpha),
                                 (cx_b - w // 2, row), (cx_b + w // 2, row), 1)
            surface.blit(beam_surf, (sx - 30, beam_top))

    def draw_flares(self, surface, aircraft):
        """Draw active illumination flares in cockpit/chase view."""
        if not self.flares:
            return
        for flare in self.flares:
            dx = flare[0] - aircraft.x
            dy = flare[1] - aircraft.y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist > 30000 or dist < 10:
                continue
            hdg_rad = math.radians(aircraft.heading)
            rel_y = dx * math.sin(hdg_rad) + dy * math.cos(hdg_rad)
            if rel_y < 50:
                continue
            sx = int(640 + (dx * math.cos(hdg_rad) - dy * math.sin(hdg_rad)) / rel_y * 800)
            sy = int(450 - (flare[2] - aircraft.z) / rel_y * 800)
            if 0 < sx < 1280 and 0 < sy < 900:
                brightness = int(flare[3] * 255)
                r = int(8 * flare[3])
                pygame.draw.circle(surface, (brightness, brightness, brightness // 2), (sx, sy), r)
                # Glow
                glow = pygame.Surface((r * 6, r * 6), pygame.SRCALPHA)
                pygame.draw.circle(glow, (brightness, brightness, 100, 30), (r * 3, r * 3), r * 3)
                surface.blit(glow, (sx - r * 3, sy - r * 3))

    def get_night_overlay_alpha(self):
        """Alpha for overall darkness overlay when flying at night."""
        if self.mode == self.NIGHT:
            return 120  # Semi-dark, not black — moonlight
        return 0


# ============== RADIO CHATTER ==============
class RadioChatter:
    """Context-sensitive text comms from wingmen, carrier, and command."""
    def __init__(self):
        self.messages = []   # [(text, sender, time_remaining, priority)]
        self.cooldowns = {}  # message_type -> cooldown timer
        self.max_display = 4
        self.last_callouts = {}

    # Message templates by category
    WINGMAN_CALLS = {
        'tally':     ["Tally ho! Bogeys, {clock} o'clock {alt}!",
                       "Contact! Bandits, {clock} o'clock!",
                       "I see 'em! {clock} o'clock {alt}!"],
        'splash':    ["Splash one!", "Got him! He's going down!",
                       "That's a kill!"],
        'hit':       ["I'm hit! Taking fire!", "Damage! Engine's rough!"],
        'engaging':  ["Engaging the bandit!", "I'm on him!",
                       "Fox two! Guns guns guns!"],
        'clear':     ["Skies clear. No contacts.", "All clear topside."],
        'formation': ["Rejoining formation.", "On your wing, lead."],
    }
    CARRIER_CALLS = {
        'approach':  ["Paddles: Call the ball.",
                       "LSO: You're on glideslope, looking good.",
                       "Tower: Cleared to land, wind down the deck."],
        'waveoff':   ["WAVE OFF! WAVE OFF! Too fast!",
                       "LSO: You're high, go around!"],
        'trapped':   ["Nice trap! Wire {wire}. Welcome aboard.",
                       "Good catch! Taxi forward and shut down."],
        'bolter':    ["Bolter! Bolter! Go around.",
                       "Missed the wires. Come around again."],
        'launch':    ["Cat officer: Ready for launch!",
                       "Tower: Wind is {wind} knots down the deck. You're cleared."],
    }
    COMMAND_CALLS = {
        'mission_start': ["Command: Good hunting, pilot.",
                           "Command: Give 'em hell out there."],
        'objective':     ["Command: Target is bearing {bearing}, {range} miles.",
                           "Command: Objective updated. Check your heading."],
        'rtb':           ["Command: Mission complete. RTB.",
                           "Command: Well done. Bring it home."],
        'warning':       ["Command: Multiple bogeys inbound!",
                           "Command: Heads up, heavy resistance ahead."],
        'mission_fail':  ["Command: Mission failure. Return to base.",
                           "Command: We've lost the objective. Pull back."],
    }

    def push(self, text, sender="RADIO", duration=5.0, priority=0):
        """Add a message to the display queue."""
        self.messages.append([text, sender, duration, priority])
        # Keep limited
        if len(self.messages) > 8:
            self.messages = self.messages[-8:]

    def call(self, category, subcategory, cooldown=8.0, **kwargs):
        """Try to play a radio call. Respects cooldowns."""
        key = f"{category}_{subcategory}"
        if key in self.cooldowns and self.cooldowns[key] > 0:
            return
        self.cooldowns[key] = cooldown
        templates = None
        if category == 'wingman':
            templates = self.WINGMAN_CALLS.get(subcategory)
        elif category == 'carrier':
            templates = self.CARRIER_CALLS.get(subcategory)
        elif category == 'command':
            templates = self.COMMAND_CALLS.get(subcategory)
        if not templates:
            return
        text = templates[hotp_rng.next() % len(templates)]
        # Fill in kwargs
        for k, v in kwargs.items():
            text = text.replace('{' + k + '}', str(v))
        sender = category.upper()
        self.push(text, sender, 5.0)

    def update(self, dt):
        for cd_key in list(self.cooldowns):
            self.cooldowns[cd_key] -= dt
            if self.cooldowns[cd_key] <= 0:
                del self.cooldowns[cd_key]
        for msg in self.messages:
            msg[2] -= dt
        self.messages = [m for m in self.messages if m[2] > 0]

    def check_context(self, aircraft, target_mgr, carrier, wingmen, active_mission):
        """Auto-generate contextual radio calls based on game state."""
        # Tally-ho when enemies detected
        if target_mgr and target_mgr.enemy_aircraft:
            for enemy in target_mgr.enemy_aircraft:
                if not enemy.alive:
                    continue
                dist = math.sqrt((enemy.x - aircraft.x)**2 + (enemy.y - aircraft.y)**2)
                if dist < 15000:
                    # Clock position
                    dx = enemy.x - aircraft.x
                    dy = enemy.y - aircraft.y
                    angle = (math.degrees(math.atan2(dx, dy)) - aircraft.heading) % 360
                    clock = max(1, min(12, int(angle / 30 + 0.5)))
                    if clock == 0:
                        clock = 12
                    alt = "high" if enemy.z > aircraft.z + 1000 else (
                          "low" if enemy.z < aircraft.z - 1000 else "level")
                    self.call('wingman', 'tally', cooldown=15.0, clock=clock, alt=alt)
                    break

        # Carrier approach
        if carrier and hasattr(aircraft, 'mg_ammo'):
            dist_to_carrier = math.sqrt((aircraft.x - carrier.x)**2 + (aircraft.y - carrier.y)**2)
            if dist_to_carrier < 5000 and aircraft.z < 1000:
                self.call('carrier', 'approach', cooldown=20.0)

        # Wingman status
        if wingmen:
            for wm in wingmen:
                if wm.alive and wm.ai_state == 'engage' and wm.firing:
                    self.call('wingman', 'engaging', cooldown=12.0)
                    break
                if wm.alive and wm.ai_state == 'rejoin':
                    self.call('wingman', 'formation', cooldown=20.0)
                    break

    def draw(self, surface):
        """Draw radio messages on screen."""
        if not self.messages:
            return
        y = 95
        for msg in self.messages[-self.max_display:]:
            text, sender, time_left, priority = msg
            # Fade out in last second
            alpha = min(255, int(time_left * 255)) if time_left < 1.0 else 255
            color = (0, 255, 100) if sender == 'WINGMAN' else (
                    (100, 200, 255) if sender == 'CARRIER' else (255, 200, 50))
            # Background bar
            bar = pygame.Surface((500, 22), pygame.SRCALPHA)
            bar.fill((0, 0, 0, min(150, alpha)))
            surface.blit(bar, (10, y))
            # Sender tag
            tag = font_tiny.render(f"[{sender}]", True, color)
            surface.blit(tag, (14, y + 2))
            # Message text
            tw = font_tiny.render(text, True, (min(255, alpha), min(255, alpha), min(255, alpha)))
            surface.blit(tw, (14 + tag.get_width() + 6, y + 2))
            y += 24


# ============== SOUND SYSTEM ==============
class SoundManager:
    """Procedural sound effects generated at startup. No external audio files needed."""

    def __init__(self):
        self.enabled = True
        self.sounds = {}
        try:
            self._generate_all()
            self.channels = {
                'engine': pygame.mixer.Channel(0),
                'weapons': pygame.mixer.Channel(1),
                'effects': pygame.mixer.Channel(2),
                'alerts': pygame.mixer.Channel(3),
            }
            self._engine_playing = None
        except Exception:
            self.enabled = False

    def _make_sound(self, duration, gen_func, sr=22050):
        """Generate a Sound from a waveform callback gen_func(t, i, n) -> [-1,1]."""
        n = int(sr * duration)
        buf = bytearray(n * 2)
        for i in range(n):
            t = i / sr
            val = gen_func(t, i, n)
            sample = int(max(-32768, min(32767, val * 32767)))
            buf[i * 2] = sample & 0xFF
            buf[i * 2 + 1] = (sample >> 8) & 0xFF
        return pygame.mixer.Sound(buffer=bytes(buf))

    def _generate_all(self):
        # Engine idle: low rumble with harmonics
        self.sounds['engine_idle'] = self._make_sound(1.0, lambda t, i, n:
            math.sin(2*math.pi*80*t)*0.15 + math.sin(2*math.pi*120*t)*0.10 +
            math.sin(2*math.pi*47*t)*0.08)

        # Engine full power: higher pitch
        self.sounds['engine_full'] = self._make_sound(1.0, lambda t, i, n:
            math.sin(2*math.pi*160*t)*0.15 + math.sin(2*math.pi*240*t)*0.10 +
            math.sin(2*math.pi*95*t)*0.08)

        # Machine guns: short crackling burst
        self.sounds['guns'] = self._make_sound(0.12, lambda t, i, n:
            (math.sin(2*math.pi*800*t + 5*math.sin(2*math.pi*60*t)) +
             (random.random()-0.5)*0.8) * max(0, 1-t*10) * 0.35)

        # Explosion: low boom with pitch drop
        self.sounds['explosion'] = self._make_sound(1.0, lambda t, i, n:
            math.sin(2*math.pi*(60+40*max(0,1-t*3))*t)*0.5 *
            max(0, 1-t*1.5) + (random.random()-0.5)*0.2*max(0,1-t*2))

        # Large explosion: deeper, longer
        self.sounds['explosion_large'] = self._make_sound(1.5, lambda t, i, n:
            math.sin(2*math.pi*(40+30*max(0,1-t*2))*t)*0.6 *
            max(0, 1-t*0.8) + (random.random()-0.5)*0.3*max(0,1-t*1))

        # Stall horn: pulsing beep
        self.sounds['stall'] = self._make_sound(2.0, lambda t, i, n:
            math.sin(2*math.pi*800*t) * 0.3 * (1.0 if (t*3)%1.0 < 0.5 else 0.0))

        # Wire catch: metallic screech
        self.sounds['wire_catch'] = self._make_sound(0.5, lambda t, i, n:
            (math.sin(2*math.pi*2000*t + 10*math.sin(2*math.pi*50*t)) +
             math.sin(2*math.pi*3500*t)*0.3) * max(0, 1-t*4) * 0.25)

        # Bullet snap (near miss)
        self.sounds['bullet_snap'] = self._make_sound(0.06, lambda t, i, n:
            (random.random()-0.5) * max(0, 1-t*30) * 0.5)

        # Rocket whoosh
        self.sounds['rocket'] = self._make_sound(0.8, lambda t, i, n:
            ((random.random()-0.5)*0.4 + math.sin(2*math.pi*(200+400*t)*t)*0.2) *
            min(1, t*10) * max(0, 1-t*2))

        # Torpedo splash
        self.sounds['torpedo'] = self._make_sound(0.4, lambda t, i, n:
            ((random.random()-0.5)*0.4 + math.sin(2*math.pi*100*t)*0.3) *
            max(0, 1-t*3) * min(1, t*15))

    def play(self, name, loop=False):
        if not self.enabled or name not in self.sounds:
            return
        ch_name = 'effects'
        if 'engine' in name: ch_name = 'engine'
        elif name in ('guns', 'rocket', 'torpedo'): ch_name = 'weapons'
        elif name == 'stall': ch_name = 'alerts'
        ch = self.channels.get(ch_name)
        if ch:
            ch.play(self.sounds[name], loops=(-1 if loop else 0))

    def stop(self, channel_name):
        if self.enabled and channel_name in self.channels:
            self.channels[channel_name].stop()

    def update_engine(self, throttle, flying=True):
        if not self.enabled:
            return
        ch = self.channels.get('engine')
        if not ch:
            return
        if not flying:
            ch.stop()
            self._engine_playing = None
            return
        target = 'engine_full' if throttle > 0.5 else 'engine_idle'
        if self._engine_playing != target:
            ch.play(self.sounds[target], loops=-1)
            self._engine_playing = target
        ch.set_volume(0.15 + throttle * 0.35)


# Initialize
pygame.mixer.pre_init(22050, -16, 1, 512)
pygame.init()
WIDTH, HEIGHT = 1280, 900
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Flight Simulator - Aircraft Selection")
clock = pygame.time.Clock()

# Colors
HUD_GREEN = (0, 255, 0)
HUD_AMBER = (255, 191, 0)
HUD_RED = (255, 50, 50)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
NAVY_BLUE = (0, 30, 60)
SKY_BLUE = (135, 206, 235)

# Fonts
pygame.font.init()
font_title = pygame.font.Font(None, 72)
font_large = pygame.font.Font(None, 56)
font_med = pygame.font.Font(None, 36)
font_small = pygame.font.Font(None, 28)
font_tiny = pygame.font.Font(None, 22)

# Cached surfaces (avoid per-frame allocation)
_panel_surface = pygame.Surface((WIDTH, 250), pygame.SRCALPHA)
_panel_surface.fill((20, 30, 40, 230))
_map_surface = pygame.Surface((WIDTH, HEIGHT))
_haze_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
_ai_mask_cache = {}  # keyed by size

def _get_ai_mask(size):
    """Get or create cached circle mask for attitude indicator"""
    if size not in _ai_mask_cache:
        diam = size * 2
        mask = pygame.Surface((diam, diam))
        mask.fill((1, 1, 1))
        pygame.draw.circle(mask, (0, 0, 0), (size, size), size)
        mask.set_colorkey((0, 0, 0))
        _ai_mask_cache[size] = mask
    return _ai_mask_cache[size]

# Load satellite map
def _resource_path(filename):
    """Get path to bundled resource (works for PyInstaller and normal execution)"""
    import sys
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, filename)
    return os.path.join(os.path.expanduser('~'), filename)

MAP_FILE = _resource_path("long_island_satellite.png")

def _placeholder_satellite_map():
    # Geo bounds (set below) span ~1.055 deg lon and ~0.532 deg lat;
    # at the project's 189.4 ft/pixel scale that's roughly 4537 x 1724.
    width, height = 4537, 1724
    surf = pygame.Surface((width, height))
    surf.fill((0, 105, 148))  # water blue, matches in-game ocean color
    try:
        font = pygame.font.SysFont("Arial", 36, bold=True)
        notice = font.render(
            "long_island_satellite.png missing - placeholder map",
            True, (255, 200, 0),
        )
        for x in range(0, width, 900):
            for y in range(0, height, 350):
                surf.blit(notice, (x + 20, y + 20))
    except pygame.error:
        pass
    return surf

try:
    satellite_map = pygame.image.load(MAP_FILE)
except (FileNotFoundError, pygame.error) as _map_err:
    print(f"Warning: satellite map not found at {MAP_FILE} ({_map_err}). Using placeholder.")
    satellite_map = _placeholder_satellite_map()
MAP_WIDTH, MAP_HEIGHT = satellite_map.get_size()

# Map geo-reference
MAP_NW_LAT, MAP_NW_LON = 41.1125, -73.8281
MAP_SE_LAT, MAP_SE_LON = 40.5806, -72.7734
MAP_SCALE_FT_PER_PIXEL = 189.4


def geo_to_pixel(lat, lon):
    x = (lon - MAP_NW_LON) / (MAP_SE_LON - MAP_NW_LON) * MAP_WIDTH
    y = (MAP_NW_LAT - lat) / (MAP_NW_LAT - MAP_SE_LAT) * MAP_HEIGHT
    return x, y


def feet_to_pixel(x_ft, y_ft, ref_lat, ref_lon):
    d_lat = y_ft / 364000
    d_lon = x_ft / 288000
    return geo_to_pixel(ref_lat + d_lat, ref_lon + d_lon)


# ============== FLIGHT DATA RECORDER ==============
class FlightDataRecorder:
    """Records flight data for plotting"""
    def __init__(self, max_samples=500):
        self.max_samples = max_samples
        self.clear()

    def clear(self):
        self.time = []
        self.altitude = []
        self.airspeed = []
        self.vsi = []
        self.distance = []
        self.start_x = None
        self.start_y = None
        self.disaster_time = None

    def record(self, t, alt, speed, vertical_speed, x, y):
        if self.start_x is None:
            self.start_x = x
            self.start_y = y

        # Calculate distance from start in nm
        dist_ft = math.sqrt((x - self.start_x)**2 + (y - self.start_y)**2)
        dist_nm = dist_ft / 6076.12

        self.time.append(t)
        self.altitude.append(alt)
        self.airspeed.append(speed)
        self.vsi.append(vertical_speed)
        self.distance.append(dist_nm)

        # Trim old data
        if len(self.time) > self.max_samples:
            self.time = self.time[-self.max_samples:]
            self.altitude = self.altitude[-self.max_samples:]
            self.airspeed = self.airspeed[-self.max_samples:]
            self.vsi = self.vsi[-self.max_samples:]
            self.distance = self.distance[-self.max_samples:]

    def mark_disaster(self, t):
        self.disaster_time = t


# ============== WEAPONS SYSTEM ==============
class Projectile:
    """Base class for all projectiles"""
    def __init__(self, x, y, z, vx, vy, vz, heading, pitch):
        self.x, self.y, self.z = x, y, z
        self.vx, self.vy, self.vz = vx, vy, vz
        self.heading = heading
        self.pitch = pitch
        self.alive = True
        self.age = 0

    def update(self, dt):
        self.age += dt
        # Gravity
        self.vz -= 32.174 * dt
        # Update position
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += self.vz * dt
        # Ground collision
        if self.z <= 0:
            self.alive = False


class Bullet(Projectile):
    """M2 Browning .50 cal tracer round"""
    MUZZLE_VELOCITY = 2910  # ft/s
    TRACER_INTERVAL = 5  # every 5th round is tracer

    def __init__(self, x, y, z, aircraft_vx, aircraft_vy, aircraft_vz, heading, pitch, is_tracer=False):
        # Calculate bullet velocity in aircraft direction
        hdg_rad = math.radians(heading)
        pitch_rad = math.radians(pitch)
        # Muzzle velocity components
        mv_x = math.sin(hdg_rad) * math.cos(pitch_rad) * self.MUZZLE_VELOCITY
        mv_y = math.cos(hdg_rad) * math.cos(pitch_rad) * self.MUZZLE_VELOCITY
        mv_z = math.sin(pitch_rad) * self.MUZZLE_VELOCITY
        # Add aircraft velocity
        super().__init__(x, y, z, aircraft_vx + mv_x, aircraft_vy + mv_y, aircraft_vz + mv_z, heading, pitch)
        self.is_tracer = is_tracer
        self.max_range = 6000  # ft effective range
        self.start_x, self.start_y, self.start_z = x, y, z

    def update(self, dt):
        super().update(dt)
        # Check max range
        dist = math.sqrt((self.x - self.start_x)**2 + (self.y - self.start_y)**2 + (self.z - self.start_z)**2)
        if dist > self.max_range:
            self.alive = False
        # Bullets die after 3 seconds
        if self.age > 3.0:
            self.alive = False


class Rocket(Projectile):
    """5-inch HVAR (High Velocity Aircraft Rocket)"""
    ROCKET_VELOCITY = 1375  # ft/s muzzle velocity
    BURN_TIME = 0.75  # seconds of motor burn
    THRUST = 8000  # lbs of thrust during burn

    def __init__(self, x, y, z, aircraft_vx, aircraft_vy, aircraft_vz, heading, pitch):
        hdg_rad = math.radians(heading)
        pitch_rad = math.radians(pitch)
        # Initial velocity is aircraft velocity + small launch velocity
        launch_v = 100  # ft/s initial kick
        mv_x = math.sin(hdg_rad) * math.cos(pitch_rad) * launch_v
        mv_y = math.cos(hdg_rad) * math.cos(pitch_rad) * launch_v
        mv_z = math.sin(pitch_rad) * launch_v
        super().__init__(x, y, z, aircraft_vx + mv_x, aircraft_vy + mv_y, aircraft_vz + mv_z, heading, pitch)
        self.burning = True
        self.smoke_trail = []  # List of (x, y, z) positions for smoke
        self.weight = 140  # lbs (full HVAR weight)

    def update(self, dt):
        # Rocket motor thrust during burn
        if self.burning and self.age < self.BURN_TIME:
            hdg_rad = math.radians(self.heading)
            pitch_rad = math.radians(self.pitch)
            # F = ma, a = F/m, convert lbs to slugs
            mass_slugs = self.weight / 32.174
            accel = self.THRUST / mass_slugs  # ft/s^2
            self.vx += math.sin(hdg_rad) * math.cos(pitch_rad) * accel * dt
            self.vy += math.cos(hdg_rad) * math.cos(pitch_rad) * accel * dt
            self.vz += math.sin(pitch_rad) * accel * dt
        else:
            self.burning = False

        # Add smoke trail point
        if len(self.smoke_trail) == 0 or self.age > 0.05:
            self.smoke_trail.append((self.x, self.y, self.z, self.age))
            # Limit trail length
            if len(self.smoke_trail) > 30:
                self.smoke_trail.pop(0)

        super().update(dt)

        # Rockets fly for max 8 seconds
        if self.age > 8.0:
            self.alive = False


class Bomb(Projectile):
    """500 lb GP (General Purpose) bomb"""

    def __init__(self, x, y, z, aircraft_vx, aircraft_vy, aircraft_vz, heading, pitch):
        # Bombs just inherit aircraft velocity, no launch velocity
        super().__init__(x, y, z, aircraft_vx, aircraft_vy, aircraft_vz, heading, pitch)
        self.weight = 500  # lbs
        self.armed = False
        self.arm_altitude = z - 500  # Arms after falling 500 ft
        self.trail = []  # Falling trail for visual

    def update(self, dt):
        # Simple drag on bomb
        speed = math.sqrt(self.vx**2 + self.vy**2 + self.vz**2)
        if speed > 10:
            drag_coef = 0.003  # Simplified drag
            drag = drag_coef * speed * speed
            drag_factor = drag / speed * dt
            self.vx -= self.vx / speed * drag_factor
            self.vy -= self.vy / speed * drag_factor
            # Don't slow vertical as much
            self.vz -= self.vz / speed * drag_factor * 0.3

        # Add trail points
        self.trail.append((self.x, self.y, self.z, self.age))
        if len(self.trail) > 20:
            self.trail.pop(0)

        super().update(dt)

        # Arm after falling
        if self.z < self.arm_altitude:
            self.armed = True

        # Max flight time 30 seconds
        if self.age > 30.0:
            self.alive = False


class Torpedo(Projectile):
    """Mk 13 aerial torpedo - historically carried by F6F Hellcat.
    Must be dropped below 300 ft and 150 kts. Runs on water surface at 33.5 kts."""
    WATER_SPEED = 33.5 * 1.68781  # 33.5 kts in ft/s (~56.5)
    MAX_RUN_TIME = 60  # seconds (4000 yard range)

    def __init__(self, x, y, z, aircraft_vx, aircraft_vy, aircraft_vz, heading, pitch):
        # Torpedo inherits aircraft velocity at release
        super().__init__(x, y, z, aircraft_vx, aircraft_vy, aircraft_vz, heading, pitch)
        self.weight = 2216  # lbs (Mk 13 torpedo)
        self.in_water = False
        self.armed = False
        self.water_distance = 0
        self.wake = []  # trail of (x, y, age) on water surface
        self.drop_valid = True

    def update(self, dt):
        self.age += dt
        if not self.in_water:
            # Falling through air - normal gravity
            self.vz -= 32.174 * dt
            self.x += self.vx * dt
            self.y += self.vy * dt
            self.z += self.vz * dt
            if self.z <= 0:
                # Splash! Torpedo enters water
                self.z = 0
                self.in_water = True
                self.vz = 0
                # Set velocity to torpedo run speed in heading direction
                hdg_rad = math.radians(self.heading)
                self.vx = math.sin(hdg_rad) * self.WATER_SPEED
                self.vy = math.cos(hdg_rad) * self.WATER_SPEED
        else:
            # Running on water surface - constant speed, no gravity
            self.x += self.vx * dt
            self.y += self.vy * dt
            self.z = 0  # stays on surface
            self.water_distance += self.WATER_SPEED * dt
            # Arm after 300 ft of water travel
            if self.water_distance > 300:
                self.armed = True
            # Add wake trail
            if len(self.wake) == 0 or self.age - (self.wake[-1][2] if self.wake else 0) > 0.1:
                self.wake.append((self.x, self.y, self.age))
                if len(self.wake) > 40:
                    self.wake.pop(0)

        # Max run time
        if self.age > self.MAX_RUN_TIME:
            self.alive = False


class WeaponsManager:
    """Manages all projectiles in the simulation"""
    def __init__(self):
        self.bullets = []
        self.rockets = []
        self.bombs = []
        self.torpedoes = []
        self.explosions = []  # (x, y, z, age, size) for visual effects
        self.bullet_count = 0  # For tracer pattern

    def fire_guns(self, aircraft):
        """Fire 6x .50 cal machine guns"""
        if aircraft.mg_ammo <= 0:
            return False

        # Fire rate: ~800 rounds/min per gun = 80 rounds total per second
        # We'll spawn 6 bullets (1 per gun) per call
        hdg_rad = math.radians(aircraft.heading)

        for i in range(6):
            if aircraft.mg_ammo <= 0:
                break
            aircraft.mg_ammo -= 1
            self.bullet_count += 1

            # Offset guns across wingspan (3 per wing)
            wing_offset = (i - 2.5) * 3  # feet from centerline
            gun_x = aircraft.x + math.cos(hdg_rad) * wing_offset
            gun_y = aircraft.y - math.sin(hdg_rad) * wing_offset
            gun_z = aircraft.z - 2  # Below aircraft CG

            # Every 5th round is a tracer
            is_tracer = (self.bullet_count % Bullet.TRACER_INTERVAL) == 0

            bullet = Bullet(gun_x, gun_y, gun_z, aircraft.vx, aircraft.vy, aircraft.vz,
                           aircraft.heading, aircraft.pitch, is_tracer)
            self.bullets.append(bullet)

        return True

    def fire_rocket(self, aircraft):
        """Fire one HVAR rocket"""
        if aircraft.rockets <= 0:
            return False

        aircraft.rockets -= 1
        # Rockets mounted under wings
        side = 1 if aircraft.rockets % 2 == 0 else -1
        hdg_rad = math.radians(aircraft.heading)
        offset = 8 * side  # 8 feet from centerline

        rocket_x = aircraft.x + math.cos(hdg_rad) * offset
        rocket_y = aircraft.y - math.sin(hdg_rad) * offset
        rocket_z = aircraft.z - 4

        rocket = Rocket(rocket_x, rocket_y, rocket_z, aircraft.vx, aircraft.vy, aircraft.vz,
                       aircraft.heading, aircraft.pitch)
        self.rockets.append(rocket)
        return True

    def drop_bomb(self, aircraft):
        """Release 500 lb bomb"""
        if aircraft.bombs <= 0:
            return False

        aircraft.bombs -= 1
        # Centerline mounted
        bomb = Bomb(aircraft.x, aircraft.y, aircraft.z - 5,
                   aircraft.vx, aircraft.vy, aircraft.vz,
                   aircraft.heading, aircraft.pitch)
        self.bombs.append(bomb)
        # Reduce aircraft weight
        aircraft.weight -= 500
        return True

    def drop_torpedo(self, aircraft):
        """Release Mk 13 torpedo — must be below 300 ft and 150 kts"""
        if not hasattr(aircraft, 'torpedoes') or aircraft.torpedoes <= 0:
            return False
        # Check drop constraints
        if aircraft.z > 300:
            return False  # Too high
        if aircraft.get_airspeed_kts() > 150:
            return False  # Too fast
        aircraft.torpedoes -= 1
        torp = Torpedo(aircraft.x, aircraft.y, aircraft.z - 8,
                       aircraft.vx, aircraft.vy, aircraft.vz,
                       aircraft.heading, aircraft.pitch)
        self.torpedoes.append(torp)
        aircraft.weight -= 2216
        return True

    def update(self, dt):
        """Update all projectiles"""
        # Update bullets
        for bullet in self.bullets:
            bullet.update(dt)
        self.bullets = [b for b in self.bullets if b.alive]

        # Update rockets
        for rocket in self.rockets:
            rocket.update(dt)
            if not rocket.alive:
                self.explosions.append([rocket.x, rocket.y, rocket.z, 0, 50])
        self.rockets = [r for r in self.rockets if r.alive]

        # Update bombs
        for bomb in self.bombs:
            bomb.update(dt)
            if not bomb.alive:
                self.explosions.append([bomb.x, bomb.y, bomb.z, 0, 200])
        self.bombs = [b for b in self.bombs if b.alive]

        # Update torpedoes
        for torp in self.torpedoes:
            torp.update(dt)
        self.torpedoes = [t for t in self.torpedoes if t.alive]

        # Update explosions
        for exp in self.explosions:
            exp[3] += dt
        self.explosions = [e for e in self.explosions if e[3] <= 2.0]

    def clear(self):
        """Clear all projectiles"""
        self.bullets.clear()
        self.rockets.clear()
        self.bombs.clear()
        self.torpedoes.clear()
        self.explosions.clear()
        self.bullet_count = 0


# ============== TARGET SYSTEM ==============
class Target:
    """Base class for all targets"""
    def __init__(self, x, y, z, target_type, health=100):
        self.x, self.y, self.z = x, y, z
        self.target_type = target_type
        self.health = health
        self.max_health = health
        self.alive = True
        self.burning = False
        self.burn_time = 0

    def take_damage(self, damage):
        self.health -= damage
        if self.health <= 0:
            self.alive = False
            self.burning = True
        elif self.health < self.max_health * 0.5:
            self.burning = True

    def update(self, dt):
        if self.burning:
            self.burn_time += dt


class Ship(Target):
    """Naval target - carriers, destroyers, battleships, cruisers"""
    TYPES = {
        'carrier': {'length': 800, 'width': 100, 'health': 500, 'name': 'Carrier', 'aa_rate': 0.06},
        'battleship': {'length': 680, 'width': 95, 'health': 400, 'name': 'Battleship', 'aa_rate': 0.08},
        'cruiser': {'length': 500, 'width': 55, 'health': 200, 'name': 'Cruiser', 'aa_rate': 0.04},
        'destroyer': {'length': 350, 'width': 40, 'health': 200, 'name': 'Destroyer', 'aa_rate': 0.03},
        'transport': {'length': 450, 'width': 60, 'health': 150, 'name': 'Transport', 'aa_rate': 0.01},
    }

    # HOTP scoring per ship type
    SCORE = {
        'carrier': 2500,
        'battleship': 1500,
        'cruiser': 750,
        'destroyer': 500,
        'transport': 250,
    }

    def __init__(self, x, y, ship_type='destroyer', heading=0):
        specs = self.TYPES.get(ship_type, self.TYPES['destroyer'])
        super().__init__(x, y, 0, 'ship', specs['health'])
        self.ship_type = ship_type
        self.length = specs['length']
        self.width = specs['width']
        self.name = specs['name']
        self.aa_rate = specs.get('aa_rate', 0.02)  # Ship AA fire rate
        self.heading = heading
        self.speed = 20 if ship_type == 'carrier' else 25  # knots

    def update(self, dt):
        super().update(dt)
        # Ships move slowly
        if self.alive:
            hdg_rad = math.radians(self.heading)
            speed_fps = self.speed * 1.68781  # knots to ft/s
            self.x += math.sin(hdg_rad) * speed_fps * dt
            self.y += math.cos(hdg_rad) * speed_fps * dt

    def check_hit(self, px, py, pz):
        """Check if a point hits this ship"""
        if pz > 100:  # Too high
            return False
        # Rotate point to ship coordinates
        hdg_rad = math.radians(self.heading)
        dx = px - self.x
        dy = py - self.y
        # Local coordinates
        local_x = dx * math.cos(hdg_rad) - dy * math.sin(hdg_rad)
        local_y = dx * math.sin(hdg_rad) + dy * math.cos(hdg_rad)
        # Check bounds
        return abs(local_x) < self.width / 2 and abs(local_y) < self.length / 2


class GroundTarget(Target):
    """Ground installation - AA guns, bunkers, fuel tanks"""
    TYPES = {
        'aa_gun': {'radius': 20, 'health': 50, 'name': 'AA Gun'},
        'bunker': {'radius': 40, 'health': 150, 'name': 'Bunker'},
        'fuel_tank': {'radius': 30, 'health': 30, 'name': 'Fuel Tank'},
        'hangar': {'radius': 80, 'health': 200, 'name': 'Hangar'},
    }

    def __init__(self, x, y, ground_type='aa_gun'):
        specs = self.TYPES.get(ground_type, self.TYPES['aa_gun'])
        super().__init__(x, y, 0, 'ground', specs['health'])
        self.ground_type = ground_type
        self.radius = specs['radius']
        self.name = specs['name']

    def check_hit(self, px, py, pz):
        """Check if a point hits this target"""
        if pz > 50:  # Too high
            return False
        dist = math.sqrt((px - self.x)**2 + (py - self.y)**2)
        return dist < self.radius


class EnemyAircraft(Target):
    """Enemy aircraft - A6M Zero fighters with dogfighting AI"""

    # HOTP Entity Templates (from decompiled entity template struct)
    # Each variant has a template record with performance and weapon specifications
    TEMPLATES = {
        'fighter': {
            'name': 'A6M Zero', 'health': 30,
            'cruise_speed': 250, 'max_speed': 330, 'min_speed': 80,
            'combat_speed': 280, 'max_turn_rate': 12, 'max_climb_rate': 50,
            'max_roll_rate': 90, 'detection_range': 90000,
            'gun_range': 2500, 'gun_max_range': 3000, 'break_range': 500,
            'merge_alt_band': 2000,
            'fire_threshold': 80,       # HOTP template field_1e
            'scaling_factor': 0.70,     # HOTP template field_38 (normalized)
            'speed_threshold': 200,     # HOTP template field_3e
            'direction_adjust': 1.0,    # HOTP template field_40
            'alt_ceiling': 13000,       # Nakajima Sakae 12 critical altitude (ft)
            'hotp_flags': HOTP_FLAG_JITTER_AXIS1 | HOTP_FLAG_JITTER_AXIS2,
        },
        'bomber': {
            'name': 'G4M Betty', 'health': 80,
            'cruise_speed': 180, 'max_speed': 250, 'min_speed': 100,
            'combat_speed': 180, 'max_turn_rate': 4, 'max_climb_rate': 25,
            'max_roll_rate': 30, 'detection_range': 90000,
            'gun_range': 2000, 'gun_max_range': 2500, 'break_range': 800,
            'merge_alt_band': 2000,
            'fire_threshold': 200,
            'scaling_factor': 0.40,
            'speed_threshold': 150,
            'direction_adjust': 0.5,
            'alt_ceiling': 15000,       # Mitsubishi Kasei 11 critical altitude (ft)
            'hotp_flags': HOTP_FLAG_JITTER_AXIS1 | HOTP_FLAG_JITTER_AXIS2 | HOTP_FLAG_SMOOTH_CTRL,
        },
    }

    # Default class constants (overridden per-instance from template)
    CRUISE_SPEED = 250
    MAX_SPEED = 330
    MIN_SPEED = 80
    COMBAT_SPEED = 280
    MAX_TURN_RATE = 12
    MAX_CLIMB_RATE = 50
    MAX_ROLL_RATE = 90
    DETECTION_RANGE = 90000
    GUN_RANGE = 2500
    GUN_MAX_RANGE = 3000
    BREAK_RANGE = 500
    MERGE_ALT_BAND = 2000

    def __init__(self, x, y, z, heading=0, variant='fighter'):
        tmpl = self.TEMPLATES.get(variant, self.TEMPLATES['fighter'])
        super().__init__(x, y, z, 'aircraft', health=tmpl['health'])
        self.heading = heading
        self.pitch = 0
        self.roll = 0
        self.variant = variant
        self.name = tmpl['name']

        # Load performance from HOTP entity template
        self.CRUISE_SPEED = tmpl['cruise_speed']
        self.MAX_SPEED = tmpl['max_speed']
        self.MIN_SPEED = tmpl['min_speed']
        self.COMBAT_SPEED = tmpl['combat_speed']
        self.MAX_TURN_RATE = tmpl['max_turn_rate']
        self.MAX_CLIMB_RATE = tmpl['max_climb_rate']
        self.DETECTION_RANGE = tmpl['detection_range']
        self.GUN_RANGE = tmpl['gun_range']
        self.GUN_MAX_RANGE = tmpl['gun_max_range']
        self.BREAK_RANGE = tmpl['break_range']

        self.speed = self.CRUISE_SPEED
        self.vx = 0
        self.vy = 0
        self.vz = 0

        # AI state machine
        self.ai_state = 'patrol'  # patrol, intercept, attack, evade, kamikaze
        self.state_timer = 0
        self.target_heading = heading
        self.target_alt = z
        self.target_speed = self.speed

        # Patrol parameters
        self.patrol_center_x = x
        self.patrol_center_y = y
        self.patrol_radius = 10000  # ft
        self.patrol_dir = 1  # 1=right, -1=left

        # Combat state
        self.turn_rate = 0
        self.firing = False
        self.burst_timer = 0
        self.burst_cooldown = 0
        self.evasion_dir = 1  # 1=right, -1=left
        self.evasion_timer = 0
        self.last_known_player_x = 0
        self.last_known_player_y = 0
        self.last_known_player_z = 0
        self.smoke_trail = False
        self.erratic_flight = False

        # HOTP authentic mechanics (reconstructed from decompiled 68k binary)
        # Entity flags control per-tick behavior via bitmask (struct offset 0x685)
        self.hotp_flags = tmpl['hotp_flags']
        self.hotp_alt_ceiling = tmpl.get('alt_ceiling', 15000)  # engine critical altitude
        self.hotp_status = 0x0000       # status bitmask (struct offset 0x1A1)
        self.hotp_axis1 = 0             # heading perturbation accumulator [-512, 512]
        self.hotp_axis2 = 0             # altitude perturbation accumulator [-320, 320]
        self.hotp_fire_accum = 0        # weapon fire accumulator (builds toward threshold)
        self.hotp_fire_threshold = tmpl['fire_threshold']  # entity template field_1e
        self.hotp_control_accum = 0     # control input accumulator (signed)
        self.hotp_speed_factor = 1.0    # low-speed damping multiplier (from FUN_0000e468)
        # Three movement smoothing accumulators (from Pacific Conflict.c lines 14179-14244)
        # Only update for player-designated and target-designated entities in original
        self.hotp_move_66a = 0          # combined movement accumulator
        self.hotp_move_66e = 0          # heading-axis smoothed accumulator
        self.hotp_move_672 = 0          # template-scaled smoothed accumulator
        self.hotp_move_669 = 1          # control gate output byte (1=enabled)
        self.hotp_move_62a = 0          # movement base value (speed component)
        # Direction character (struct offset 0x679): '-' (0x2D) = full template adjust
        self.hotp_direction_char = 0x2D if variant == 'fighter' else 0x00
        # Weapon counters (struct offsets 0x67d, 0x67e)
        self.hotp_weapon_67d = 6 if variant == 'fighter' else 2  # primary weapon count
        self.hotp_weapon_67e = 4 if variant == 'fighter' else 8  # secondary weapon count

        # Damage behavior thresholds
        self.kamikaze_threshold = 0.25  # Go kamikaze below 25% health
        self.evade_threshold = 0.50     # Start evading below 50% health

    def _angle_to(self, tx, ty):
        """Get heading angle toward a target point"""
        dx = tx - self.x
        dy = ty - self.y
        return math.degrees(math.atan2(dx, dy)) % 360

    def _dist_to(self, tx, ty, tz=None):
        """Distance to target point"""
        d2 = (tx - self.x)**2 + (ty - self.y)**2
        if tz is not None:
            d2 += (tz - self.z)**2
        return math.sqrt(d2)

    def _hdg_diff(self, target_hdg):
        """Signed heading difference (-180 to 180)"""
        return ((target_hdg - self.heading + 180) % 360) - 180

    def _is_player_behind(self, player):
        """Check if player is in our rear hemisphere"""
        hdg_to_player = self._angle_to(player.x, player.y)
        diff = abs(self._hdg_diff(hdg_to_player))
        return diff > 120

    def _is_facing_target(self, tx, ty, cone=45):
        """Check if we're pointed within cone degrees of target"""
        hdg_to_target = self._angle_to(tx, ty)
        return abs(self._hdg_diff(hdg_to_target)) < cone

    def _get_alt_factor(self):
        """HOTP altitude performance factor from the 9-entry aerodynamic table.
        Maps current altitude through the table with peak at engine critical altitude.
        Zero: peak at 13,000 ft (Sakae 12), cliff above 15,000 ft.
        Betty: peak at 15,000 ft (Kasei 11), cliff above 18,000 ft.
        This creates realistic altitude-dependent performance:
        the F6F Hellcat's R-2800 (critical alt 23,400 ft) dominates above 20,000 ft."""
        # Table peak is at index 4 of 9. Map so critical altitude = peak.
        # alt_ceiling * 2.0 = full table span
        param = min(1.0, max(0.0, self.z / (self.hotp_alt_ceiling * 2.0)))
        return max(0.3, hotp_aero_lookup(param))

    def _steer_toward(self, target_hdg, dt, aggression=1.0):
        """Steer toward target heading using HOTP delta smoothing.
        Small corrections apply instantly; large ones at 1/8 rate per tick."""
        diff = self._hdg_diff(target_hdg)
        alt_factor = self._get_alt_factor()
        max_rate = self.MAX_TURN_RATE * aggression * alt_factor
        if self.variant == 'bomber':
            max_rate *= 0.3  # Bombers turn sluggishly
        desired_rate = max(-max_rate, min(max_rate, diff * 1.5))
        # HOTP delta smoothing: signature floaty-but-responsive feel
        self.turn_rate = hotp_delta_smooth(self.turn_rate, desired_rate, dt)
        self.heading = (self.heading + self.turn_rate * dt) % 360

    def _adjust_altitude(self, target_alt, dt):
        """Climb or descend using HOTP delta smoothing on vertical rate.
        Climb rate scaled by altitude performance factor."""
        alt_diff = target_alt - self.z
        alt_factor = self._get_alt_factor()
        max_climb = self.MAX_CLIMB_RATE * alt_factor
        if self.variant == 'bomber':
            max_climb *= 0.5
        target_climb = max(-max_climb * 1.5, min(max_climb, alt_diff * 0.3))
        # HOTP smoothing: small vz corrections snap, large ones ease in at 1/8
        self.vz = hotp_delta_smooth(self.vz, target_climb, dt)
        self.pitch = math.degrees(math.atan2(self.vz, self.speed * 1.68781))

    def _adjust_speed(self, target_speed, dt):
        """Adjust speed with HOTP low-speed damping and delta smoothing.
        Below 200 kts, effectiveness drops (from FUN_0000e468 stall behavior).
        Uses aero lookup table for performance scaling."""
        speed_diff = target_speed - self.speed
        accel = 15 if speed_diff > 0 else 25  # Decelerate faster
        # HOTP low-speed damping (exact formula from FUN_0000e468):
        # when param_1 < 0x200: param_2 -= (-(param_1-0x200)*param_2) >> 12
        # Map speed (kts) to game units (~2.56x): 200 kts ≈ 0x200 game units
        speed_units = int(self.speed * 2.56)
        effective_accel = hotp_fun_e468(speed_units, accel)
        raw_target = self.speed + max(-effective_accel * dt, min(effective_accel * dt, speed_diff))
        # HOTP delta smoothing on speed
        self.speed = hotp_delta_smooth(self.speed, raw_target, dt)
        # Altitude caps effective max speed (thin air = less thrust)
        alt_factor = self._get_alt_factor()
        effective_max = self.MIN_SPEED + (self.MAX_SPEED - self.MIN_SPEED) * alt_factor
        self.speed = max(self.MIN_SPEED, min(effective_max, self.speed))

    def update(self, dt, player=None, carrier=None):
        super().update(dt)
        self.firing = False

        if not self.alive:
            # Falling aircraft - smoke, tumble
            self.vz -= 32.174 * dt
            self.x += self.vx * dt
            self.y += self.vy * dt
            self.z += self.vz * dt
            self.pitch = min(self.pitch + 30 * dt, 60)
            self.roll += 45 * dt  # Tumbling roll
            self.z = max(0, self.z)
            return

        self.state_timer += dt

        # Check damage-driven state changes
        health_pct = self.health / (30 if self.variant == 'fighter' else 80)
        self.smoke_trail = health_pct < 0.70
        self.erratic_flight = health_pct < 0.40

        if health_pct <= self.kamikaze_threshold and self.ai_state != 'kamikaze':
            # Heavily damaged - kamikaze into nearest friendly ship
            if carrier and self.variant == 'fighter':
                self.ai_state = 'kamikaze'
                self.state_timer = 0
        elif health_pct <= self.evade_threshold and self.ai_state == 'attack':
            self.ai_state = 'evade'
            self.state_timer = 0
            self.evasion_dir = 1 if hotp_rng.coin_flip() else -1

        # Run current AI state
        if self.ai_state == 'patrol':
            self._ai_patrol(dt, player)
        elif self.ai_state == 'intercept':
            self._ai_intercept(dt, player)
        elif self.ai_state == 'attack':
            self._ai_attack(dt, player)
        elif self.ai_state == 'evade':
            self._ai_evade(dt, player)
        elif self.ai_state == 'kamikaze':
            self._ai_kamikaze(dt, carrier)

        # HOTP authentic AI jitter (reconstructed from 68k movement system)
        # Per-tick RNG perturbation on two axes, clamped to original ranges
        # Creates natural "wobble" in AI flight paths; damage amplifies it
        if self.hotp_flags & HOTP_FLAG_JITTER_AXIS1:
            jitter1 = (hotp_rng.next() & 0x7F) - 0x40  # [-64, +63]
            if self.erratic_flight:
                jitter1 *= 3  # Damage triples jitter amplitude
            self.hotp_axis1 += jitter1 * dt * 60
            self.hotp_axis1 = max(-512, min(512, self.hotp_axis1))
            # Map axis1 to heading: 512 units ~ 3 deg deviation
            self.heading += self.hotp_axis1 * 0.006 * dt

        if self.hotp_flags & HOTP_FLAG_JITTER_AXIS2:
            jitter2 = (hotp_rng.next() & 0x7F) - 0x40  # [-64, +63]
            if self.erratic_flight:
                jitter2 *= 3
            self.hotp_axis2 += jitter2 * dt * 60
            self.hotp_axis2 = max(-320, min(320, self.hotp_axis2))
            # Map axis2 to altitude: 320 units ~ 15 ft/s vz deviation
            self.vz += self.hotp_axis2 * 0.05 * dt

        # HOTP status override: forced descent when bit 0x01 set
        # (original: movement_662=0, movement_666=-0x80)
        if self.hotp_status & 0x01:
            self.hotp_axis1 = 0
            self.hotp_axis2 = -128

        # HOTP status bit 0x0040: clear control gate when heading accum reaches zero
        if (self.hotp_status & 0x0040) and self.hotp_move_66e == 0:
            self.hotp_move_669 = 0

        # HOTP status bits 0x0300: disable control gate (prevent weapon fire)
        if self.hotp_status & 0x0300:
            self.hotp_move_669 = 0

        # Three movement smoothing accumulators (Pacific Conflict.c lines 14179-14244)
        # These create the signature smooth movement of the original game.
        # 0x66e: heading-axis accumulator (from jitter + control input)
        target_66e = int(self.hotp_axis1 * 0.5 + self.hotp_control_accum * 2)
        target_66e - self.hotp_move_66e
        self.hotp_move_66e = hotp_delta_smooth(self.hotp_move_66e, target_66e, dt)

        # 0x672: template-scaled accumulator (gated by 0x669 and status bits)
        if self.hotp_move_669 == 0 or (self.hotp_status & 0x4300) != 0:
            source_672 = 0
        else:
            # FUN_0000e570: template_field_38 * (0x551A / ((param+0x105)>>3)) >> 8
            tmpl = self.TEMPLATES.get(self.variant, self.TEMPLATES['fighter'])
            raw_38 = int(tmpl['scaling_factor'] * 100)  # scale normalized to raw-ish
            source_672 = hotp_fun_e570(raw_38, int(self.speed * 2.56)) >> 9
            # Direction character: '-' = full, other = half
            if self.hotp_direction_char == 0x2D:
                pass  # full adjustment
            else:
                source_672 = _half_toward_zero(source_672)
            if self.hotp_flags & HOTP_FLAG_SMOOTH_CTRL:
                source_672 = _half_toward_zero(source_672)
        self.hotp_move_672 = hotp_delta_smooth(self.hotp_move_672, source_672, dt)

        # 0x66a: combined accumulator (speed + heading interaction)
        speed_component = int(self.hotp_move_62a) >> 2 if self.hotp_move_62a else 0
        target_66a = int(self.hotp_move_66e * 0.5 + speed_component)
        self.hotp_move_66a = hotp_delta_smooth(self.hotp_move_66a, target_66a, dt)

        # Feed smoothed accumulators back into movement
        self.heading += self.hotp_move_66e * 0.001 * dt
        self.vz += self.hotp_move_672 * 0.02 * dt
        self.hotp_move_62a = self.speed * 2.56  # update base value

        # Apply roll from turn rate (visual only)
        target_roll = self.turn_rate * 4  # Bank proportional to turn
        self.roll += (target_roll - self.roll) * min(3.0 * dt, 1.0)
        self.roll = max(-60, min(60, self.roll))

        # Convert heading + speed to velocity
        hdg_rad = math.radians(self.heading)
        speed_fps = self.speed * 1.68781
        self.vx = math.sin(hdg_rad) * speed_fps
        self.vy = math.cos(hdg_rad) * speed_fps

        # Update position
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += self.vz * dt
        self.z = max(50, self.z)  # Don't fly into the water

    def _ai_patrol(self, dt, player):
        """Circle patrol point, scanning for player"""
        # Check for player detection
        if player and player.z > 0:
            dist = self._dist_to(player.x, player.y, player.z)
            if dist < self.DETECTION_RANGE:
                self.ai_state = 'intercept'
                self.state_timer = 0
                self.last_known_player_x = player.x
                self.last_known_player_y = player.y
                self.last_known_player_z = player.z
                return

        # Standard patrol circle
        dx = self.x - self.patrol_center_x
        dy = self.y - self.patrol_center_y
        dist = math.sqrt(dx**2 + dy**2)

        if dist > self.patrol_radius * 1.2:
            target_hdg = self._angle_to(self.patrol_center_x, self.patrol_center_y)
            self._steer_toward(target_hdg, dt, aggression=0.5)
        else:
            # Gentle orbit
            self.turn_rate = 2.0 * self.patrol_dir
            self.heading = (self.heading + self.turn_rate * dt) % 360

        self._adjust_speed(self.CRUISE_SPEED if self.variant == 'fighter' else 180, dt)
        self._adjust_altitude(self.target_alt, dt)

    def _ai_intercept(self, dt, player):
        """Close distance to player, set up attack run"""
        if not player or player.z <= 0:
            self.ai_state = 'patrol'
            self.state_timer = 0
            return

        dist = self._dist_to(player.x, player.y, player.z)
        self.last_known_player_x = player.x
        self.last_known_player_y = player.y
        self.last_known_player_z = player.z

        # Lost contact - return to patrol
        if dist > self.DETECTION_RANGE * 1.5:
            self.ai_state = 'patrol'
            self.state_timer = 0
            return

        # Close enough to engage - switch to attack
        if dist < self.GUN_MAX_RANGE * 2:
            self.ai_state = 'attack'
            self.state_timer = 0
            return

        # Intercept: lead the target, climb/descend to engagement altitude
        # Lead pursuit - aim ahead of where player is going
        lead_time = dist / (self.speed * 1.68781) * 0.5
        lead_x = player.x + player.vx * lead_time
        lead_y = player.y + player.vy * lead_time

        target_hdg = self._angle_to(lead_x, lead_y)
        self._steer_toward(target_hdg, dt, aggression=0.8)

        # Speed up for intercept
        self._adjust_speed(self.MAX_SPEED if self.variant == 'fighter' else 200, dt)

        # Match altitude band
        target_alt = player.z
        self._adjust_altitude(target_alt, dt)

    def _ai_attack(self, dt, player):
        """Dogfight - get on player's tail and fire"""
        if not player or player.z <= 0:
            self.ai_state = 'patrol'
            self.state_timer = 0
            return

        dist = self._dist_to(player.x, player.y, player.z)
        self.last_known_player_x = player.x
        self.last_known_player_y = player.y
        self.last_known_player_z = player.z

        # Bombers don't dogfight - they just keep flying toward objective
        if self.variant == 'bomber':
            self._ai_bomber_attack(dt, player)
            return

        # Lost contact
        if dist > self.DETECTION_RANGE:
            self.ai_state = 'intercept'
            self.state_timer = 0
            return

        # Lead pursuit - aim where the player will be
        closing_speed = max(100, self.speed * 1.68781)
        lead_time = min(dist / closing_speed, 2.0)
        lead_x = player.x + player.vx * lead_time
        lead_y = player.y + player.vy * lead_time
        lead_z = player.z + getattr(player, 'vz', 0) * lead_time

        target_hdg = self._angle_to(lead_x, lead_y)

        # If too close, break off and re-engage
        if dist < self.BREAK_RANGE:
            # Break turn - pull hard in current turn direction
            break_hdg = (self.heading + 90 * (1 if self.turn_rate >= 0 else -1)) % 360
            self._steer_toward(break_hdg, dt, aggression=1.0)
            self._adjust_speed(self.COMBAT_SPEED, dt)
            self._adjust_altitude(self.z + 500, dt)
            return

        # Main attack steering
        hdg_diff = abs(self._hdg_diff(target_hdg))

        if hdg_diff < 30:
            # Nearly lined up - fine tracking, maintain speed for gun solution
            self._steer_toward(target_hdg, dt, aggression=0.6)
            self._adjust_speed(self.COMBAT_SPEED, dt)
        else:
            # Turn hard to get on target
            self._steer_toward(target_hdg, dt, aggression=1.0)
            # Tighten turn by slowing down
            turn_speed = self.COMBAT_SPEED - abs(hdg_diff) * 0.5
            self._adjust_speed(max(self.MIN_SPEED + 50, turn_speed), dt)

        # Altitude: try to stay at or slightly above player
        self._adjust_altitude(lead_z + 200, dt)

        # HOTP accumulator-based weapon fire (from _apply_control_threshold_decrement)
        # Control gate conditions (from _apply_control_gate_accumulator):
        #   gate = ((flags & 0x40)==0 OR status_1a3!=0) AND (status & 0x0300)==0 AND ammo>0
        # Accumulator builds; fires when accumulator EXCEEDS threshold (not >=)
        # RNG coin flip selects which weapon counter to decrement
        self.firing = False
        has_ammo = self.hotp_weapon_67d > 0 or self.hotp_weapon_67e > 0
        gate_enabled = (not (self.hotp_flags & HOTP_FLAG_CONTROL_GATE) or
                        (self.hotp_status & 0xFF00) != 0)  # status_1a3 proxy
        gate_enabled = gate_enabled and (self.hotp_status & 0x0300) == 0 and has_ammo

        if dist < self.GUN_MAX_RANGE and hdg_diff < 15 and gate_enabled:
            alt_diff = abs(self.z - player.z)
            if alt_diff < dist * 0.3:
                closeness = 1.0 - dist / self.GUN_MAX_RANGE
                self.hotp_control_accum = max(1, int(10 * closeness))
                # SMOOTH_CTRL: halve accumulator toward zero each tick
                if self.hotp_flags & HOTP_FLAG_SMOOTH_CTRL:
                    self.hotp_control_accum = _half_toward_zero(self.hotp_control_accum)
                self.hotp_fire_accum += self.hotp_control_accum * dt * 60
                # Original fires when accumulator > threshold (strict greater-than)
                if self.hotp_fire_accum > self.hotp_fire_threshold:
                    self.hotp_fire_accum -= self.hotp_fire_threshold
                    # RNG coin flip for weapon type selection (original logic)
                    rng_bit = hotp_rng.next() & 1
                    if rng_bit == 0 or self.hotp_weapon_67d == 0:
                        if self.hotp_weapon_67e > 0:
                            self.hotp_weapon_67e -= 1
                    else:
                        self.hotp_weapon_67d -= 1
                    self.firing = True
            else:
                self.hotp_fire_accum = max(0, self.hotp_fire_accum - 20 * dt * 60)
        else:
            # Gate closed: accumulator decays
            if self.hotp_flags & HOTP_FLAG_SMOOTH_CTRL:
                self.hotp_fire_accum = _half_toward_zero(int(self.hotp_fire_accum))
            else:
                self.hotp_fire_accum = max(0, self.hotp_fire_accum - 40 * dt * 60)
            self.hotp_control_accum = 0

    def _ai_bomber_attack(self, dt, player):
        """Bombers fly straight to objective, minimal maneuvering"""
        # Bombers just fly toward their patrol center (the target)
        target_hdg = self._angle_to(self.patrol_center_x, self.patrol_center_y)
        self._steer_toward(target_hdg, dt, aggression=0.3)
        self._adjust_speed(180, dt)
        self._adjust_altitude(self.target_alt, dt)

    def _ai_evade(self, dt, player):
        """Break away from combat, try to disengage"""
        self.evasion_timer += dt

        if not player:
            self.ai_state = 'patrol'
            self.state_timer = 0
            return

        dist = self._dist_to(player.x, player.y)

        # If we've opened up distance, return to patrol or re-engage
        if dist > self.DETECTION_RANGE * 0.8 or self.evasion_timer > 15:
            self.ai_state = 'patrol'
            self.state_timer = 0
            self.evasion_timer = 0
            return

        # Evasion: turn away from player with jinking
        away_hdg = self._angle_to(player.x, player.y)
        away_hdg = (away_hdg + 180) % 360  # Opposite direction

        # Add jinking - change direction periodically
        jink_period = 3.0
        if int(self.evasion_timer / jink_period) % 2 == 0:
            away_hdg = (away_hdg + 40 * self.evasion_dir) % 360
        else:
            away_hdg = (away_hdg - 40 * self.evasion_dir) % 360

        self._steer_toward(away_hdg, dt, aggression=1.0)
        self._adjust_speed(self.MAX_SPEED, dt)  # Full speed escape

        # Dive for speed if player is behind
        if self._is_player_behind(player):
            self._adjust_altitude(max(500, self.z - 2000), dt)
        else:
            self._adjust_altitude(self.z + 500, dt)

    def _ai_kamikaze(self, dt, carrier):
        """Dive at nearest friendly ship - from manual: damaged enemy loses fear of death"""
        if not carrier:
            # No carrier target, just dive
            self._adjust_altitude(0, dt)
            self._adjust_speed(self.MAX_SPEED, dt)
            return

        target_hdg = self._angle_to(carrier.x, carrier.y)
        dist = self._dist_to(carrier.x, carrier.y)

        self._steer_toward(target_hdg, dt, aggression=1.0)
        self._adjust_speed(self.MAX_SPEED, dt)

        # Dive toward carrier - steeper as we get closer
        if dist < 5000:
            self._adjust_altitude(0, dt)
            self.vz = -100  # Hard dive
            self.pitch = -30
        else:
            self._adjust_altitude(carrier.y if hasattr(carrier, 'z') else 200, dt)

    def check_hit(self, px, py, pz):
        """Check if a point hits this aircraft"""
        dist = math.sqrt((px - self.x)**2 + (py - self.y)**2 + (pz - self.z)**2)
        return dist < 40  # ~40 ft hit radius


class TargetManager:
    """Manages all targets in the simulation"""
    def __init__(self, ref_lat, ref_lon):
        self.ref_lat = ref_lat
        self.ref_lon = ref_lon
        self.ships = []
        self.ground_targets = []
        self.enemy_aircraft = []
        self.score = 0
        self.kills = {'ship': 0, 'ground': 0, 'aircraft': 0}
        self.spawn_targets()

    def spawn_targets(self):
        """Create initial target setup - Pacific theater style"""
        # Enemy fleet - visible on 3nm radar from start, south of start position
        fleet_x = 8000   # feet east
        fleet_y = -15000  # feet south (~2.5 nm, visible on 3nm radar)

        # Carrier group
        self.ships.append(Ship(fleet_x, fleet_y, 'carrier', heading=45))
        self.ships.append(Ship(fleet_x - 2000, fleet_y - 3000, 'destroyer', heading=45))
        self.ships.append(Ship(fleet_x + 2000, fleet_y - 2500, 'destroyer', heading=45))
        self.ships.append(Ship(fleet_x - 1000, fleet_y + 4000, 'transport', heading=45))
        self.ships.append(Ship(fleet_x + 3000, fleet_y - 1000, 'battleship', heading=45))

        # Second group further east
        self.ships.append(Ship(fleet_x + 25000, fleet_y - 5000, 'carrier', heading=90))
        self.ships.append(Ship(fleet_x + 23000, fleet_y - 7000, 'destroyer', heading=90))
        self.ships.append(Ship(fleet_x + 26000, fleet_y - 3000, 'cruiser', heading=90))

        # Ground targets on Long Island (simulating enemy-held airfield)
        airfield_x = 25000
        airfield_y = 15000

        # AA defenses
        self.ground_targets.append(GroundTarget(airfield_x - 500, airfield_y - 500, 'aa_gun'))
        self.ground_targets.append(GroundTarget(airfield_x + 500, airfield_y - 500, 'aa_gun'))
        self.ground_targets.append(GroundTarget(airfield_x - 500, airfield_y + 500, 'aa_gun'))
        self.ground_targets.append(GroundTarget(airfield_x + 500, airfield_y + 500, 'aa_gun'))

        # Hangars and fuel
        self.ground_targets.append(GroundTarget(airfield_x, airfield_y, 'hangar'))
        self.ground_targets.append(GroundTarget(airfield_x - 300, airfield_y + 200, 'fuel_tank'))
        self.ground_targets.append(GroundTarget(airfield_x + 300, airfield_y + 200, 'fuel_tank'))
        self.ground_targets.append(GroundTarget(airfield_x, airfield_y - 400, 'bunker'))

        # Enemy aircraft on patrol
        self.enemy_aircraft.append(EnemyAircraft(20000, 0, 8000, heading=180))
        self.enemy_aircraft.append(EnemyAircraft(25000, 5000, 7000, heading=220))
        self.enemy_aircraft.append(EnemyAircraft(10000, -20000, 6000, heading=0))
        self.enemy_aircraft.append(EnemyAircraft(40000, -30000, 9000, heading=270))

    def _get_score(self, target):
        """Get HOTP-accurate score for a destroyed target"""
        if isinstance(target, Ship):
            return Ship.SCORE.get(target.ship_type, 250)
        if isinstance(target, EnemyAircraft):
            return 1000 if target.variant == 'bomber' else 500
        if isinstance(target, GroundTarget):
            return 50 if target.ground_type == 'aa_gun' else 100
        return 100

    def check_hits(self, weapons_mgr):
        """Check for weapon hits on targets"""
        # Check bullets
        for bullet in weapons_mgr.bullets[:]:
            # Check ships
            for ship in self.ships:
                if ship.alive and ship.check_hit(bullet.x, bullet.y, bullet.z):
                    ship.take_damage(5)  # .50 cal does light damage to ships
                    bullet.alive = False
                    if not ship.alive:
                        self.score += self._get_score(ship)
                        self.kills['ship'] += 1
                        weapons_mgr.explosions.append([ship.x, ship.y, 0, 0, 300])
                    break

            # Check ground targets
            for target in self.ground_targets:
                if target.alive and target.check_hit(bullet.x, bullet.y, bullet.z):
                    target.take_damage(10)
                    bullet.alive = False
                    if not target.alive:
                        self.score += self._get_score(target)
                        self.kills['ground'] += 1
                        weapons_mgr.explosions.append([target.x, target.y, 0, 0, 80])
                    break

            # Check enemy aircraft
            for enemy in self.enemy_aircraft:
                if enemy.alive and enemy.check_hit(bullet.x, bullet.y, bullet.z):
                    enemy.take_damage(15)
                    bullet.alive = False
                    if not enemy.alive:
                        self.score += self._get_score(enemy)
                        self.kills['aircraft'] += 1
                        weapons_mgr.explosions.append([enemy.x, enemy.y, enemy.z, 0, 100])
                    break

        # Check rockets (more damage)
        for rocket in weapons_mgr.rockets[:]:
            for ship in self.ships:
                if ship.alive and ship.check_hit(rocket.x, rocket.y, rocket.z):
                    ship.take_damage(75)
                    rocket.alive = False
                    weapons_mgr.explosions.append([rocket.x, rocket.y, rocket.z, 0, 100])
                    if not ship.alive:
                        self.score += self._get_score(ship)
                        self.kills['ship'] += 1
                        weapons_mgr.explosions.append([ship.x, ship.y, 0, 0, 300])
                    break

            for target in self.ground_targets:
                if target.alive and target.check_hit(rocket.x, rocket.y, rocket.z):
                    target.take_damage(100)  # Rockets destroy most ground targets
                    rocket.alive = False
                    weapons_mgr.explosions.append([rocket.x, rocket.y, 0, 0, 80])
                    if not target.alive:
                        self.score += self._get_score(target)
                        self.kills['ground'] += 1
                    break

            for enemy in self.enemy_aircraft:
                if enemy.alive and enemy.check_hit(rocket.x, rocket.y, rocket.z):
                    enemy.take_damage(100)  # Instant kill
                    rocket.alive = False
                    weapons_mgr.explosions.append([enemy.x, enemy.y, enemy.z, 0, 100])
                    if not enemy.alive:
                        self.score += self._get_score(enemy)
                        self.kills['aircraft'] += 1
                    break

        # Check bombs (massive damage)
        for bomb in weapons_mgr.bombs[:]:
            if not bomb.alive:
                continue
            # Bombs check on impact (z near 0)
            if bomb.z <= 10:
                # Check all targets in blast radius (200 ft)
                for ship in self.ships:
                    if ship.alive:
                        dist = math.sqrt((bomb.x - ship.x)**2 + (bomb.y - ship.y)**2)
                        if dist < 200:
                            damage = 300 * (1 - dist / 200)
                            ship.take_damage(damage)
                            if not ship.alive:
                                self.score += self._get_score(ship)
                                self.kills['ship'] += 1
                                weapons_mgr.explosions.append([ship.x, ship.y, 0, 0, 300])

                for target in self.ground_targets:
                    if target.alive:
                        dist = math.sqrt((bomb.x - target.x)**2 + (bomb.y - target.y)**2)
                        if dist < 150:
                            target.take_damage(200)
                            if not target.alive:
                                self.score += self._get_score(target)
                                self.kills['ground'] += 1

        # Check torpedoes (massive damage to ships, must be armed and in water)
        for torp in weapons_mgr.torpedoes[:]:
            if not torp.in_water or not torp.armed:
                continue
            for ship in self.ships:
                if ship.alive and ship.check_hit(torp.x, torp.y, 0):
                    # Mk 13 torpedo: devastating against ships
                    ship.take_damage(400)
                    torp.alive = False
                    weapons_mgr.explosions.append([torp.x, torp.y, 0, 0, 400])
                    if not ship.alive:
                        self.score += self._get_score(ship)
                        self.kills['ship'] += 1
                        weapons_mgr.explosions.append([ship.x, ship.y, 0, 0, 500])
                    break

    def check_enemy_fire(self, player, dt):
        """Enemy aircraft and AA fire at the player"""
        for enemy in self.enemy_aircraft:
            if not enemy.alive:
                continue
            # Use AI firing state - the AI decides when to shoot
            if not enemy.firing:
                continue
            dx = player.x - enemy.x
            dy = player.y - enemy.y
            dz = player.z - enemy.z
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            if dist > enemy.GUN_MAX_RANGE or dist < 50:
                continue
            # Hit probability based on range and deflection
            # Better accuracy when closer, worse when target is maneuvering
            base_chance = 0.08 * dt * (1000 / max(dist, 200))
            # Reduce accuracy if player is turning hard
            player_g = abs(getattr(player, 'roll', 0)) / 90.0
            maneuver_penalty = 1.0 - player_g * 0.6
            hit_chance = base_chance * max(0.2, maneuver_penalty)
            if hotp_rng.fraction() < hit_chance:
                if hasattr(player, 'take_hit'):
                    player.take_hit()
            elif dist < 300:
                # Near miss — bullets crack past, cause screen shake/flinch
                if hasattr(player, 'near_miss_shake'):
                    intensity = 0.3 * (1 - dist / 300)
                    player.near_miss_shake = max(player.near_miss_shake, intensity)

        # AA guns fire at player
        for target in self.ground_targets:
            if not target.alive or target.ground_type != 'aa_gun':
                continue
            dx = player.x - target.x
            dy = player.y - target.y
            dist = math.sqrt(dx*dx + dy*dy)
            if dist > 5000 or player.z > 8000:  # AA range and ceiling
                continue
            hit_chance = 0.02 * dt * (2000 / max(dist, 200))
            if hotp_rng.fraction() < hit_chance:
                if hasattr(player, 'take_hit'):
                    player.take_hit()

        # Ship AA fire at player (scaled by ship type)
        for ship in self.ships:
            if not ship.alive:
                continue
            dx = player.x - ship.x
            dy = player.y - ship.y
            dist = math.sqrt(dx*dx + dy*dy)
            if dist > 8000 or player.z > 12000:  # Ship AA range and ceiling
                continue
            hit_chance = ship.aa_rate * dt * (3000 / max(dist, 300))
            if hotp_rng.fraction() < hit_chance:
                if hasattr(player, 'take_hit'):
                    player.take_hit()
            elif dist < 400 and hasattr(player, 'near_miss_shake'):
                player.near_miss_shake = max(player.near_miss_shake, 0.2)

    def update(self, dt, weapons_mgr, player=None, carrier=None, wingmen=None):
        """Update all targets using HOTP four-array ordering.
        Original game processes entities in strict order:
          Array 1: friendly entities (carrier) with param=0
          Array 2: player entity with param=0
          Array 3: enemy aircraft with param=1
          Array 4: ground/naval targets with param=1
        This order is absolute and cannot be reordered without breaking parity."""
        # Array 1 & 2: friendly entities (param=0) - carrier updated externally
        # Wingmen updated here as friendly array
        if wingmen:
            for wm in wingmen:
                wm.update(dt, player, self.enemy_aircraft)

        # Array 3: enemy aircraft (param=1)
        for enemy in self.enemy_aircraft:
            enemy.update(dt, player=player, carrier=carrier)

        # Array 4: ground/naval targets (param=1)
        for ship in self.ships:
            ship.update(dt)
        for target in self.ground_targets:
            target.update(dt)

        # Post-tick: collision detection and fire
        self.check_hits(weapons_mgr)

        # Enemy fires at player
        if player:
            self.check_enemy_fire(player, dt)

        # Enemy fires at wingmen
        if wingmen:
            for wm in wingmen:
                if wm.alive:
                    self._check_enemy_fire_at_wingman(wm, dt)

    def _check_enemy_fire_at_wingman(self, wingman, dt):
        """Enemy aircraft fire at wingman (simplified)"""
        for enemy in self.enemy_aircraft:
            if not enemy.alive or not enemy.firing:
                continue
            dist = math.sqrt((wingman.x - enemy.x)**2 + (wingman.y - enemy.y)**2 +
                             (wingman.z - enemy.z)**2)
            if dist > enemy.GUN_MAX_RANGE or dist < 50:
                continue
            hit_chance = 0.05 * dt * (800 / max(dist, 200))
            if hotp_rng.fraction() < hit_chance:
                wingman.take_damage(10)

    def clear(self):
        """Reset all targets"""
        self.ships.clear()
        self.ground_targets.clear()
        self.enemy_aircraft.clear()
        self.score = 0
        self.kills = {'ship': 0, 'ground': 0, 'aircraft': 0}
        self.spawn_targets()


# ============== FRIENDLY CARRIER ==============
class FriendlyCarrier:
    """Essex-class carrier for takeoff/landing operations"""
    LENGTH = 872  # ft (Essex class)
    WIDTH = 100   # ft flight deck
    WIRE_ZONE_START = 0.5  # Back 50% of deck has arresting wires
    NUM_WIRES = 4
    SPEED_KTS = 18  # Carrier steams into wind

    def __init__(self, x, y, heading=0):
        self.x = x
        self.y = y
        self.heading = heading
        self.speed_fps = self.SPEED_KTS * 1.68781
        self.active = True

    def update(self, dt):
        hdg_rad = math.radians(self.heading)
        self.x += math.sin(hdg_rad) * self.speed_fps * dt
        self.y += math.cos(hdg_rad) * self.speed_fps * dt

    def get_deck_bounds(self):
        """Return deck corners in world coordinates"""
        hdg_rad = math.radians(self.heading)
        sin_h, cos_h = math.sin(hdg_rad), math.cos(hdg_rad)
        half_l = self.LENGTH / 2
        half_w = self.WIDTH / 2
        # Corners: bow-left, bow-right, stern-right, stern-left
        return [
            (self.x + sin_h * half_l - cos_h * half_w,
             self.y + cos_h * half_l + sin_h * half_w),
            (self.x + sin_h * half_l + cos_h * half_w,
             self.y + cos_h * half_l - sin_h * half_w),
            (self.x - sin_h * half_l + cos_h * half_w,
             self.y - cos_h * half_l - sin_h * half_w),
            (self.x - sin_h * half_l - cos_h * half_w,
             self.y - cos_h * half_l + sin_h * half_w),
        ]

    def check_on_deck(self, px, py):
        """Check if a point is over the flight deck"""
        hdg_rad = math.radians(self.heading)
        dx = px - self.x
        dy = py - self.y
        # Rotate to deck-local coords (forward = along ship)
        local_fwd = dx * math.sin(hdg_rad) + dy * math.cos(hdg_rad)
        local_lat = dx * math.cos(hdg_rad) - dy * math.sin(hdg_rad)
        return abs(local_fwd) < self.LENGTH / 2 and abs(local_lat) < self.WIDTH / 2

    def check_wire_catch(self, px, py, vz, airspeed_kts, gear_down):
        """Check if landing in arresting wire zone. Returns (caught, wire_num) or (False, 0)"""
        if not gear_down:
            return False, 0
        if airspeed_kts > 150:  # Too fast for wires
            return False, 0

        hdg_rad = math.radians(self.heading)
        dx = px - self.x
        dy = py - self.y
        local_fwd = dx * math.sin(hdg_rad) + dy * math.cos(hdg_rad)
        local_lat = dx * math.cos(hdg_rad) - dy * math.sin(hdg_rad)

        # Must be on deck laterally
        if abs(local_lat) > self.WIDTH / 2:
            return False, 0

        # Wire zone is the stern half of the deck
        wire_start = -self.LENGTH / 2  # Stern
        wire_end = wire_start + self.LENGTH * self.WIRE_ZONE_START
        if wire_start <= local_fwd <= wire_end:
            # Determine which wire (1-4, 3 is ideal)
            wire_pos = (local_fwd - wire_start) / (wire_end - wire_start)
            wire_num = min(4, max(1, int(wire_pos * 4) + 1))
            return True, wire_num

        return False, 0

    def get_takeoff_position(self):
        """Return position and heading for catapult launch from bow"""
        hdg_rad = math.radians(self.heading)
        # Start at stern of deck
        start_x = self.x - math.sin(hdg_rad) * (self.LENGTH * 0.4)
        start_y = self.y - math.cos(hdg_rad) * (self.LENGTH * 0.4)
        return start_x, start_y, self.heading


# ============== WINGMAN AI ==============
class FriendlyAircraft:
    """AI wingman — flies formation with player, engages enemies using HOTP mechanics."""
    CRUISE_SPEED = 250
    MAX_SPEED = 350
    MIN_SPEED = 80
    COMBAT_SPEED = 280
    MAX_TURN_RATE = 10
    MAX_CLIMB_RATE = 45
    GUN_MAX_RANGE = 3000

    def __init__(self, player, offset_side=1):
        self.x, self.y, self.z = player.x, player.y, player.z
        self.vx, self.vy, self.vz = player.vx, player.vy, 0
        self.heading = player.heading
        self.pitch = self.roll = 0
        self.speed = self.CRUISE_SPEED
        self.alive = True
        self.health = 40
        self.max_health = 40
        self.name = "F6F Wingman"
        self.offset_side = offset_side
        self.turn_rate = 0
        self.firing = False
        self.smoke_trail = False
        self.ai_state = 'formation'
        self.target_enemy = None
        # HOTP mechanics
        self.hotp_flags = HOTP_FLAG_JITTER_AXIS1 | HOTP_FLAG_JITTER_AXIS2
        self.hotp_axis1 = self.hotp_axis2 = 0
        self.hotp_fire_accum = 0
        self.hotp_fire_threshold = 60
        self.hotp_control_accum = 0
        self.hotp_alt_ceiling = 23400  # R-2800 critical altitude (ft)

    def _get_alt_factor(self):
        """F6F altitude performance — R-2800 peaks at 23,400 ft, well above Zeros."""
        param = min(1.0, max(0.0, self.z / (self.hotp_alt_ceiling * 2.0)))
        return max(0.4, hotp_aero_lookup(param))

    def _angle_to(self, tx, ty):
        return math.degrees(math.atan2(tx - self.x, ty - self.y)) % 360

    def _dist_to(self, tx, ty, tz=None):
        d2 = (tx - self.x)**2 + (ty - self.y)**2
        if tz is not None: d2 += (tz - self.z)**2
        return math.sqrt(d2)

    def _hdg_diff(self, target_hdg):
        return ((target_hdg - self.heading + 180) % 360) - 180

    def _steer_toward(self, target_hdg, dt, aggression=1.0):
        diff = self._hdg_diff(target_hdg)
        max_rate = self.MAX_TURN_RATE * aggression * self._get_alt_factor()
        desired = max(-max_rate, min(max_rate, diff * 1.5))
        self.turn_rate = hotp_delta_smooth(self.turn_rate, desired, dt)
        self.heading = (self.heading + self.turn_rate * dt) % 360

    def _adjust_alt(self, target_alt, dt):
        diff = target_alt - self.z
        target_vz = max(-self.MAX_CLIMB_RATE * 1.5, min(self.MAX_CLIMB_RATE, diff * 0.3))
        self.vz = hotp_delta_smooth(self.vz, target_vz, dt)
        self.pitch = math.degrees(math.atan2(self.vz, self.speed * 1.68781))

    def _adjust_speed(self, target_speed, dt):
        diff = target_speed - self.speed
        accel = 15 if diff > 0 else 25
        raw = self.speed + max(-accel * dt, min(accel * dt, diff))
        self.speed = hotp_delta_smooth(self.speed, raw, dt)
        self.speed = max(self.MIN_SPEED, min(self.MAX_SPEED, self.speed))

    def take_damage(self, amount):
        self.health -= amount
        if self.health <= 0:
            self.alive = False
            self.health = 0

    def check_hit(self, px, py, pz):
        return math.sqrt((px-self.x)**2 + (py-self.y)**2 + (pz-self.z)**2) < 40

    def update(self, dt, player, enemies):
        if not self.alive:
            self.vz -= 32.174 * dt
            self.x += self.vx * dt; self.y += self.vy * dt; self.z += self.vz * dt
            self.z = max(0, self.z)
            return

        self.firing = False
        self.smoke_trail = self.health / self.max_health < 0.5

        # Find closest enemy
        closest_enemy, closest_dist = None, 999999
        for e in enemies:
            if e.alive:
                d = self._dist_to(e.x, e.y, e.z)
                if d < closest_dist:
                    closest_enemy, closest_dist = e, d

        # State transitions
        if self.ai_state == 'formation' and closest_enemy and closest_dist < 8000:
            self.ai_state = 'engage'
            self.target_enemy = closest_enemy
        elif self.ai_state == 'engage':
            if not self.target_enemy or not self.target_enemy.alive:
                self.ai_state = 'rejoin'
                self.target_enemy = None
            elif self._dist_to(self.target_enemy.x, self.target_enemy.y) > 15000:
                self.ai_state = 'rejoin'
        elif self.ai_state == 'rejoin':
            if self._dist_to(player.x, player.y) < 1000:
                self.ai_state = 'formation'

        # Execute state
        if self.ai_state == 'formation':
            hdg_rad = math.radians(player.heading)
            lat = 200 * self.offset_side
            trail = -300
            fx = player.x + math.cos(hdg_rad) * lat + math.sin(hdg_rad) * trail
            fy = player.y - math.sin(hdg_rad) * lat + math.cos(hdg_rad) * trail
            dist = self._dist_to(fx, fy)
            if dist > 500:
                self._steer_toward(self._angle_to(fx, fy), dt, 0.8)
            else:
                self._steer_toward(player.heading, dt, 0.4)
            self._adjust_alt(player.z + 50, dt)
            ps = math.sqrt(player.vx**2 + player.vy**2) / 1.68781
            self._adjust_speed(ps, dt)

        elif self.ai_state == 'engage' and self.target_enemy:
            e = self.target_enemy
            dist = self._dist_to(e.x, e.y, e.z)
            cs = max(100, self.speed * 1.68781)
            lt = min(dist / cs, 2.0)
            lx, ly = e.x + e.vx * lt, e.y + e.vy * lt
            th = self._angle_to(lx, ly)
            hd = abs(self._hdg_diff(th))
            if dist < 500:
                self._steer_toward((self.heading + 90) % 360, dt, 1.0)
            else:
                self._steer_toward(th, dt, 0.9)
            self._adjust_alt(e.z + 200, dt)
            self._adjust_speed(self.COMBAT_SPEED, dt)
            # HOTP accumulator fire
            if dist < self.GUN_MAX_RANGE and hd < 15:
                closeness = 1.0 - dist / self.GUN_MAX_RANGE
                self.hotp_control_accum = max(1, int(10 * closeness))
                self.hotp_fire_accum += self.hotp_control_accum * dt * 60
                if self.hotp_fire_accum >= self.hotp_fire_threshold:
                    self.hotp_fire_accum -= self.hotp_fire_threshold
                    hotp_rng.next()
                    self.firing = True
                    e.take_damage(8)
                    if not e.alive:
                        self.ai_state = 'rejoin'
                        self.target_enemy = None
            else:
                self.hotp_fire_accum = max(0, self.hotp_fire_accum - 20 * dt * 60)

        elif self.ai_state == 'rejoin':
            self._steer_toward(self._angle_to(player.x, player.y), dt, 0.7)
            self._adjust_alt(player.z, dt)
            self._adjust_speed(self.MAX_SPEED * 0.9, dt)

        # HOTP jitter
        if self.hotp_flags & HOTP_FLAG_JITTER_AXIS1:
            j = (hotp_rng.next() & 0x7F) - 0x40
            self.hotp_axis1 = max(-512, min(512, self.hotp_axis1 + j * dt * 60))
            self.heading += self.hotp_axis1 * 0.003 * dt
        if self.hotp_flags & HOTP_FLAG_JITTER_AXIS2:
            j = (hotp_rng.next() & 0x7F) - 0x40
            self.hotp_axis2 = max(-320, min(320, self.hotp_axis2 + j * dt * 60))
            self.vz += self.hotp_axis2 * 0.02 * dt

        # Roll visual
        tr = self.turn_rate * 4
        self.roll += (tr - self.roll) * min(3.0 * dt, 1.0)
        self.roll = max(-60, min(60, self.roll))

        # Velocity
        hdg_rad = math.radians(self.heading)
        sfps = self.speed * 1.68781
        self.vx = math.sin(hdg_rad) * sfps
        self.vy = math.cos(hdg_rad) * sfps
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += self.vz * dt
        self.z = max(100, self.z)


# ============== FRIENDLY BOMBERS ==============
class FriendlyBomber:
    """B-17 Flying Fortress — flies a fixed route to target. Player must escort."""
    CRUISE_SPEED = 180  # kts
    MAX_CLIMB_RATE = 15  # ft/s (heavy, slow climber)

    def __init__(self, x, y, z, heading, target_x, target_y, offset_idx=0):
        self.x, self.y, self.z = x, y, z
        self.heading = heading
        self.pitch = 0
        self.roll = 0
        self.speed = self.CRUISE_SPEED
        self.vx = math.sin(math.radians(heading)) * self.CRUISE_SPEED * 1.68781
        self.vy = math.cos(math.radians(heading)) * self.CRUISE_SPEED * 1.68781
        self.vz = 0
        self.alive = True
        self.health = 120  # B-17 was famously tough
        self.max_health = 120
        self.name = f"B-17 #{offset_idx + 1}"
        self.target_x = target_x
        self.target_y = target_y
        self.bombs_dropped = False
        self.smoking = False
        self.on_fire = False
        self.turn_rate = 0
        # Formation offset from lead
        self.form_offset_x = (offset_idx % 2) * 400 * (1 if offset_idx % 3 else -1)
        self.form_offset_y = offset_idx * -500  # staggered back

    def _dist_to_target(self):
        return math.sqrt((self.target_x - self.x)**2 + (self.target_y - self.y)**2)

    def take_damage(self, amount):
        self.health -= amount
        if self.health < self.max_health * 0.6:
            self.smoking = True
        if self.health < self.max_health * 0.3:
            self.on_fire = True
        if self.health <= 0:
            self.alive = False
            self.health = 0

    def check_hit(self, px, py, pz):
        """B-17 is big — 50 ft hit radius"""
        return math.sqrt((px-self.x)**2 + (py-self.y)**2 + (pz-self.z)**2) < 50

    def update(self, dt):
        if not self.alive:
            # Falling
            self.vz -= 32.174 * dt * 0.3  # Slow fall (wings still provide some lift)
            self.x += self.vx * dt
            self.y += self.vy * dt
            self.z += self.vz * dt
            self.pitch = min(self.pitch + 5 * dt, 30)
            self.roll += 15 * dt
            self.z = max(0, self.z)
            return

        # Fire damage spreads
        if self.on_fire:
            self.health -= 5 * dt

        # Steer toward target
        dx = self.target_x - self.x
        dy = self.target_y - self.y
        target_hdg = math.degrees(math.atan2(dx, dy)) % 360
        hdg_diff = ((target_hdg - self.heading + 180) % 360) - 180
        max_turn = 2.0  # Bombers turn very slowly
        desired_rate = max(-max_turn, min(max_turn, hdg_diff * 0.5))
        self.turn_rate = hotp_delta_smooth(self.turn_rate, desired_rate, dt)
        self.heading = (self.heading + self.turn_rate * dt) % 360

        # Roll from turn
        self.roll += (self.turn_rate * 3 - self.roll) * min(2.0 * dt, 1.0)
        self.roll = max(-20, min(20, self.roll))

        # HOTP jitter for natural movement
        self.heading += ((hotp_rng.next() & 0x3F) - 0x20) * 0.0005 * dt
        self.vz += ((hotp_rng.next() & 0x3F) - 0x20) * 0.01 * dt

        # Velocity
        hdg_rad = math.radians(self.heading)
        speed_fps = self.speed * 1.68781
        self.vx = math.sin(hdg_rad) * speed_fps
        self.vy = math.cos(hdg_rad) * speed_fps

        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += self.vz * dt
        self.z = max(3000, self.z)  # Bombers don't descend below 3000 ft

        # Check if over target — drop bombs
        if self._dist_to_target() < 2000 and not self.bombs_dropped:
            self.bombs_dropped = True


# ============== MISSION SYSTEM ==============
class Mission:
    """Base class for combat missions"""
    NAME = "Unknown"
    BRIEFING = []
    OBJECTIVE = "Complete the mission"
    ORIGIN = "carrier"  # "carrier" or "airfield"
    START_ALT = 5000
    START_SPEED = 250
    START_HEADING = 0
    DIFFICULTY = 1  # 1-5 stars
    WEATHER = Weather.CLEAR
    TIME_OF_DAY = TimeOfDay.DAY
    CARRIER_TAKEOFF = False  # True = start on deck

    def __init__(self):
        self.status = "active"  # active, success, failed
        self.time = 0
        self.kills = {'aircraft': 0, 'ship': 0, 'ground': 0}
        self.objectives_met = False
        self.returned_to_base = False

    def setup_targets(self, target_mgr, carrier):
        """Override to customize targets for this mission"""

    def check_objectives(self, aircraft, target_mgr, carrier):
        """Override to check mission-specific objectives. Returns status string."""
        return "active"

    def get_score(self):
        return (self.kills['aircraft'] * 500 +
                self.kills['ship'] * 1000 +
                self.kills['ground'] * 100)


class MissionFlightSchool(Mission):
    NAME = "Flight School"
    DIFFICULTY = 1
    OBJECTIVE = "Practice flight skills. Land back on the carrier."
    BRIEFING = [
        "FLIGHT SCHOOL",
        "",
        "Welcome to fighter training, Ensign.",
        "Practice flying the F6F Hellcat.",
        "Get comfortable with takeoff, flight, and landing.",
        "",
        "Objective: Land back on the friendly carrier.",
        "The carrier is marked green on your radar (TAB to cycle range).",
        "",
        "Controls: W/S pitch, A/D roll, SHIFT/CTRL throttle",
        "F: flaps, G: gear, SPACE: fire weapons",
    ]
    START_ALT = 3000
    START_SPEED = 200

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()

    def check_objectives(self, aircraft, target_mgr, carrier):
        if aircraft.on_ground and carrier.check_on_deck(aircraft.x, aircraft.y):
            v = math.sqrt(aircraft.vx**2 + aircraft.vy**2)
            if v < 15:
                self.returned_to_base = True
                return "success"
        return "active"


class MissionBombBase(Mission):
    NAME = "Bomb Base"
    DIFFICULTY = 2
    OBJECTIVE = "Bomb the enemy runway. Return to carrier."
    BRIEFING = [
        "BOMB BASE",
        "",
        "Intelligence reports an enemy airfield at bearing 045,",
        "approximately 4 miles from the carrier.",
        "",
        "Your mission: destroy the enemy runway and any",
        "ground installations. Watch for AA defenses.",
        "",
        "After completing the strike, return to the carrier",
        "for a safe landing.",
        "",
        "Loadout: 6x .50 cal, 6x HVAR rockets, 1x 500lb bomb",
    ]
    START_ALT = 5000
    START_SPEED = 250
    START_HEADING = 45

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.enemy_aircraft.clear()
        target_mgr.ground_targets.clear()
        # Enemy airfield
        base_x, base_y = 20000, 20000
        target_mgr.ground_targets.append(GroundTarget(base_x, base_y, 'hangar'))
        target_mgr.ground_targets.append(GroundTarget(base_x - 400, base_y, 'aa_gun'))
        target_mgr.ground_targets.append(GroundTarget(base_x + 400, base_y, 'aa_gun'))
        target_mgr.ground_targets.append(GroundTarget(base_x, base_y - 300, 'fuel_tank'))
        target_mgr.ground_targets.append(GroundTarget(base_x, base_y + 300, 'fuel_tank'))
        # A few patrol fighters
        target_mgr.enemy_aircraft.append(EnemyAircraft(base_x + 5000, base_y, 6000, heading=180))
        target_mgr.enemy_aircraft.append(EnemyAircraft(base_x - 3000, base_y + 5000, 5000, heading=270))

    def check_objectives(self, aircraft, target_mgr, carrier):
        # Check if hangar destroyed
        hangars_alive = sum(1 for t in target_mgr.ground_targets
                           if t.ground_type == 'hangar' and t.alive)
        if hangars_alive == 0:
            self.objectives_met = True

        if self.objectives_met and aircraft.on_ground and carrier.check_on_deck(aircraft.x, aircraft.y):
            v = math.sqrt(aircraft.vx**2 + aircraft.vy**2)
            if v < 15:
                self.returned_to_base = True
                return "success"

        return "active"


class MissionScramble(Mission):
    NAME = "Scramble"
    DIFFICULTY = 3
    OBJECTIVE = "Intercept incoming enemy bomber and escorts. Defend the carrier."
    BRIEFING = [
        "SCRAMBLE!",
        "",
        "Radar has detected incoming bogeys heading for the fleet!",
        "One enemy bomber with fighter escort, bearing 000,",
        "closing fast at 15,000 feet.",
        "",
        "You must intercept and destroy the bomber before it",
        "reaches the carrier. Destroy escorts if possible.",
        "",
        "Time is critical - you have less than 3 minutes!",
    ]
    START_ALT = 8000
    START_SPEED = 300
    START_HEADING = 0

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()
        # Incoming bomber group from north
        bomber = EnemyAircraft(0, 60000, 12000, heading=180, variant='bomber')
        bomber.patrol_center_x = carrier.x  # Bomber flies toward carrier
        bomber.patrol_center_y = carrier.y
        target_mgr.enemy_aircraft.append(bomber)
        # Escorts
        target_mgr.enemy_aircraft.append(EnemyAircraft(2000, 62000, 11000, heading=180))
        target_mgr.enemy_aircraft.append(EnemyAircraft(-2000, 62000, 11000, heading=180))
        target_mgr.enemy_aircraft.append(EnemyAircraft(0, 64000, 13000, heading=180))

    def check_objectives(self, aircraft, target_mgr, carrier):
        # Check if bomber destroyed
        bomber_alive = any(e.alive and e.name == "G4M Betty" for e in target_mgr.enemy_aircraft)
        if not bomber_alive:
            self.objectives_met = True
            return "success"
        # Fail if bomber gets close to carrier
        for enemy in target_mgr.enemy_aircraft:
            if enemy.alive and enemy.name == "G4M Betty":
                dist = math.sqrt((enemy.x - carrier.x)**2 + (enemy.y - carrier.y)**2)
                if dist < 3000:
                    return "failed"
        return "active"


class MissionDivineWind(Mission):
    NAME = "Divine Wind"
    DIFFICULTY = 4
    OBJECTIVE = "Defend the carrier from 10 kamikaze fighters."
    BRIEFING = [
        "DIVINE WIND",
        "",
        "Spotters report two groups of five enemy suicide",
        "fighters approaching from the north.",
        "",
        "You are the only fighter in position to intercept.",
        "The carrier must not be hit.",
        "",
        "There are 10 enemy planes vs. you alone.",
        "Good luck!",
    ]
    START_ALT = 10000
    START_SPEED = 300
    START_HEADING = 0

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()
        # Two waves of 5 kamikazes
        for i in range(5):
            x_off = (i - 2) * 1500
            target_mgr.enemy_aircraft.append(
                EnemyAircraft(x_off, 50000, 8000 + i * 500, heading=180))
        for i in range(5):
            x_off = (i - 2) * 1500
            target_mgr.enemy_aircraft.append(
                EnemyAircraft(x_off + 500, 70000, 9000 + i * 500, heading=180))

    def check_objectives(self, aircraft, target_mgr, carrier):
        enemies_alive = sum(1 for e in target_mgr.enemy_aircraft if e.alive)
        if enemies_alive == 0:
            self.objectives_met = True
            return "success"
        # Fail if any kamikaze gets within 500 ft of carrier
        for enemy in target_mgr.enemy_aircraft:
            if enemy.alive:
                dist = math.sqrt((enemy.x - carrier.x)**2 + (enemy.y - carrier.y)**2)
                if dist < 500:
                    return "failed"
        return "active"


class MissionFlatTop(Mission):
    NAME = "Flat Top"
    DIFFICULTY = 5
    OBJECTIVE = "Find and sink the enemy carrier."
    BRIEFING = [
        "FLAT TOP",
        "",
        "An enemy carrier has been spotted approximately",
        "8 miles northeast of your position.",
        "",
        "It is escorted by destroyers and has fighters",
        "on combat air patrol.",
        "",
        "Sink the carrier using bombs and rockets.",
        "Watch for heavy AA fire from the escort ships.",
        "Return to base when mission is complete.",
    ]
    START_ALT = 8000
    START_SPEED = 280
    START_HEADING = 45

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()
        # Enemy fleet 8 nm northeast
        fleet_x, fleet_y = 40000, 40000
        target_mgr.ships.append(Ship(fleet_x, fleet_y, 'carrier', heading=225))
        target_mgr.ships.append(Ship(fleet_x - 2000, fleet_y - 3000, 'destroyer', heading=225))
        target_mgr.ships.append(Ship(fleet_x + 2000, fleet_y - 2000, 'destroyer', heading=225))
        # CAP fighters
        target_mgr.enemy_aircraft.append(EnemyAircraft(fleet_x + 3000, fleet_y, 10000, heading=0))
        target_mgr.enemy_aircraft.append(EnemyAircraft(fleet_x - 3000, fleet_y + 3000, 9000, heading=90))
        target_mgr.enemy_aircraft.append(EnemyAircraft(fleet_x, fleet_y - 5000, 8000, heading=180))

    def check_objectives(self, aircraft, target_mgr, carrier):
        carrier_alive = any(s.alive and s.ship_type == 'carrier' for s in target_mgr.ships)
        if not carrier_alive:
            self.objectives_met = True

        if self.objectives_met and aircraft.on_ground and carrier.check_on_deck(aircraft.x, aircraft.y):
            v = math.sqrt(aircraft.vx**2 + aircraft.vy**2)
            if v < 15:
                self.returned_to_base = True
                return "success"

        return "active"


class MissionBomberEscort(Mission):
    NAME = "Bomber Escort"
    DIFFICULTY = 4
    OBJECTIVE = "Escort B-17 formation to target. Protect them from interceptors."
    BRIEFING = [
        "BOMBER ESCORT",
        "",
        "Three B-17 Flying Fortresses are inbound to bomb an",
        "enemy supply depot 6 miles northeast of the carrier.",
        "",
        "Enemy fighters will attempt to intercept the formation.",
        "You must protect the bombers until they reach the target.",
        "",
        "At least ONE bomber must survive to drop its payload.",
        "Stay close to the formation — the Zeros will come fast.",
        "",
        "Loadout: 6x .50 cal, 6x HVAR rockets",
    ]
    START_ALT = 12000
    START_SPEED = 200
    START_HEADING = 45

    def __init__(self):
        super().__init__()
        self.bombers = []
        self.wave_timer = 0
        self.waves_spawned = 0
        self.max_waves = 3

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()

        # Target is 6 nm northeast
        tgt_x, tgt_y = 30000, 30000

        # Ground target (supply depot)
        target_mgr.ground_targets.append(GroundTarget(tgt_x, tgt_y, 'hangar'))
        target_mgr.ground_targets.append(GroundTarget(tgt_x - 300, tgt_y, 'fuel_tank'))
        target_mgr.ground_targets.append(GroundTarget(tgt_x + 300, tgt_y, 'fuel_tank'))
        target_mgr.ground_targets.append(GroundTarget(tgt_x, tgt_y + 400, 'aa_gun'))

        # Spawn 3 B-17 bombers in formation, heading toward target
        bomber_start_x, bomber_start_y = 5000, 5000
        for i in range(3):
            b = FriendlyBomber(bomber_start_x + (i-1)*400, bomber_start_y - i*500,
                               12000, 45, tgt_x, tgt_y, offset_idx=i)
            self.bombers.append(b)

        # First wave of interceptors from the target direction
        target_mgr.enemy_aircraft.append(EnemyAircraft(20000, 20000, 13000, heading=225))
        target_mgr.enemy_aircraft.append(EnemyAircraft(22000, 18000, 12000, heading=225))
        self.waves_spawned = 1

    def check_objectives(self, aircraft, target_mgr, carrier):
        self.time += PHYSICS_DT

        # Update bombers
        for b in self.bombers:
            b.update(PHYSICS_DT)

        # Enemy fighters target bombers (redirect AI toward closest bomber)
        for enemy in target_mgr.enemy_aircraft:
            if enemy.alive and enemy.ai_state in ('patrol', 'intercept'):
                closest_bomber = None
                closest_dist = 999999
                for b in self.bombers:
                    if b.alive:
                        d = math.sqrt((b.x-enemy.x)**2 + (b.y-enemy.y)**2)
                        if d < closest_dist:
                            closest_dist = d
                            closest_bomber = b
                if closest_bomber and closest_dist < 30000:
                    enemy.last_known_player_x = closest_bomber.x
                    enemy.last_known_player_y = closest_bomber.y
                    enemy.last_known_player_z = closest_bomber.z

        # Enemy fire at bombers
        for enemy in target_mgr.enemy_aircraft:
            if not enemy.alive or not enemy.firing:
                continue
            for b in self.bombers:
                if not b.alive:
                    continue
                dist = math.sqrt((b.x-enemy.x)**2 + (b.y-enemy.y)**2 + (b.z-enemy.z)**2)
                if dist < enemy.GUN_MAX_RANGE:
                    hit_chance = 0.12 * PHYSICS_DT * (1000 / max(dist, 200))
                    if hotp_rng.fraction() < hit_chance:
                        b.take_damage(12)

        # Spawn new interceptor waves
        self.wave_timer += PHYSICS_DT
        if self.waves_spawned < self.max_waves and self.wave_timer > 20 * self.waves_spawned:
            # Spawn from different directions
            angles = [180, 315, 90]
            a = angles[self.waves_spawned % len(angles)]
            rad = math.radians(a)
            # Spawn near the bomber formation
            avg_bx = sum(b.x for b in self.bombers if b.alive) / max(1, sum(1 for b in self.bombers if b.alive))
            avg_by = sum(b.y for b in self.bombers if b.alive) / max(1, sum(1 for b in self.bombers if b.alive))
            for i in range(2 + self.waves_spawned):
                sx = avg_bx + math.sin(rad) * 15000 + (i-1) * 1500
                sy = avg_by + math.cos(rad) * 15000
                target_mgr.enemy_aircraft.append(
                    EnemyAircraft(sx, sy, 11000 + i*1000, heading=(a+180)%360))
            self.waves_spawned += 1

        # Check success: at least one bomber dropped its payload
        bombers_dropped = sum(1 for b in self.bombers if b.bombs_dropped)
        if bombers_dropped > 0:
            self.objectives_met = True
            return "success"

        # Check failure: all bombers destroyed
        bombers_alive = sum(1 for b in self.bombers if b.alive)
        if bombers_alive == 0:
            return "failed"

        return "active"


class MissionTorpedoRun(Mission):
    NAME = "Torpedo Run"
    DIFFICULTY = 4
    OBJECTIVE = "Torpedo the enemy transport convoy. Sink at least 2 ships."
    BRIEFING = [
        "TORPEDO RUN",
        "",
        "A Japanese supply convoy has been spotted 5 miles",
        "east of the fleet. Three transport ships escorted",
        "by two destroyers.",
        "",
        "You are armed with a Mk 13 aerial torpedo.",
        "Drop constraints: below 300 ft, under 150 kts.",
        "Make your run low and fast — the destroyers have AA.",
        "",
        "Sink at least 2 transports, then return to carrier.",
        "",
        "Loadout: 6x .50 cal, 1x Mk 13 torpedo",
        "Press 4 to select torpedo, SPACE to drop.",
    ]
    START_ALT = 3000
    START_SPEED = 200
    START_HEADING = 90
    CARRIER_TAKEOFF = True

    def __init__(self):
        super().__init__()
        self.ships_sunk = 0

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()
        # Convoy 5 nm east — 3 transports in column, 2 destroyer escorts
        convoy_x, convoy_y = 30000, 0
        for i in range(3):
            target_mgr.ships.append(Ship(convoy_x, convoy_y + i * 2000, 'transport', heading=0))
        target_mgr.ships.append(Ship(convoy_x - 2000, convoy_y + 1000, 'destroyer', heading=0))
        target_mgr.ships.append(Ship(convoy_x + 2000, convoy_y + 3000, 'destroyer', heading=0))
        # Light air cover
        target_mgr.enemy_aircraft.append(EnemyAircraft(convoy_x + 5000, convoy_y, 8000, heading=270))

    def check_objectives(self, aircraft, target_mgr, carrier):
        # Count sunk transports
        transports_sunk = sum(1 for s in target_mgr.ships
                              if s.ship_type == 'transport' and not s.alive)
        self.ships_sunk = transports_sunk
        if transports_sunk >= 2:
            self.objectives_met = True

        if self.objectives_met and aircraft.on_ground and carrier.check_on_deck(aircraft.x, aircraft.y):
            v = math.sqrt(aircraft.vx**2 + aircraft.vy**2)
            if v < 15:
                self.returned_to_base = True
                return "success"

        return "active"

    def get_score(self):
        return (self.kills['aircraft'] * 500 +
                self.ships_sunk * 1500 +
                self.kills['ground'] * 100)


class MissionNightStrike(Mission):
    NAME = "Night Strike"
    DIFFICULTY = 5
    OBJECTIVE = "Night attack on enemy harbor. Destroy fuel depot."
    BRIEFING = [
        "NIGHT STRIKE",
        "",
        "Under cover of darkness, strike an enemy fuel depot",
        "on the coast, 6 miles northeast.",
        "",
        "AA searchlights will sweep for you. Stay low to avoid",
        "detection. Destroy the fuel tanks and return.",
        "",
        "Visibility is limited — use your instruments.",
        "Flares (press L) can illuminate the target area.",
        "",
        "Loadout: 6x .50 cal, 6x HVAR rockets, 1x 500lb bomb",
    ]
    START_ALT = 4000
    START_SPEED = 220
    START_HEADING = 45
    TIME_OF_DAY = TimeOfDay.NIGHT
    WEATHER = Weather.OVERCAST

    def setup_targets(self, target_mgr, carrier):
        target_mgr.ships.clear()
        target_mgr.ground_targets.clear()
        target_mgr.enemy_aircraft.clear()
        # Fuel depot 6 nm northeast
        depot_x, depot_y = 30000, 30000
        target_mgr.ground_targets.append(GroundTarget(depot_x, depot_y, 'fuel_tank'))
        target_mgr.ground_targets.append(GroundTarget(depot_x + 300, depot_y - 200, 'fuel_tank'))
        target_mgr.ground_targets.append(GroundTarget(depot_x - 300, depot_y + 200, 'fuel_tank'))
        target_mgr.ground_targets.append(GroundTarget(depot_x + 500, depot_y, 'hangar'))
        # AA positions with searchlights
        target_mgr.ground_targets.append(GroundTarget(depot_x - 600, depot_y - 400, 'aa_gun'))
        target_mgr.ground_targets.append(GroundTarget(depot_x + 600, depot_y + 400, 'aa_gun'))
        target_mgr.ground_targets.append(GroundTarget(depot_x, depot_y - 800, 'aa_gun'))
        # Night fighter patrol
        target_mgr.enemy_aircraft.append(EnemyAircraft(depot_x - 5000, depot_y, 6000, heading=90))

    def check_objectives(self, aircraft, target_mgr, carrier):
        fuel_alive = sum(1 for t in target_mgr.ground_targets
                         if t.ground_type == 'fuel_tank' and t.alive)
        if fuel_alive == 0:
            self.objectives_met = True

        if self.objectives_met and aircraft.on_ground and carrier.check_on_deck(aircraft.x, aircraft.y):
            v = math.sqrt(aircraft.vx**2 + aircraft.vy**2)
            if v < 15:
                self.returned_to_base = True
                return "success"

        return "active"


MISSIONS = [MissionFlightSchool, MissionBombBase, MissionScramble, MissionDivineWind,
            MissionFlatTop, MissionBomberEscort, MissionTorpedoRun, MissionNightStrike]


# ============== CAMPAIGN MODE ==============
class Campaign:
    """Linear mission progression with persistent state between sorties."""
    MISSION_ORDER = [
        MissionFlightSchool, MissionBombBase, MissionScramble,
        MissionTorpedoRun, MissionBomberEscort, MissionDivineWind,
        MissionFlatTop, MissionNightStrike
    ]

    def __init__(self):
        self.current_index = 0
        self.active = False
        self.results = []  # list of (mission_name, status)
        self.damage_carry = {}  # carried damage between sorties
        self.ammo_carry = {}    # carried ammo
        self.load()

    def start(self):
        self.active = True
        self.current_index = 0
        self.results = []
        self.damage_carry = {}
        self.ammo_carry = {}

    def get_current_mission_class(self):
        if self.current_index < len(self.MISSION_ORDER):
            return self.MISSION_ORDER[self.current_index]
        return None

    def advance(self, mission):
        """Record result and advance. Returns True if campaign continues."""
        self.results.append((mission.NAME, mission.status))
        if mission.status == "success":
            self.current_index += 1
        # Save state
        self.save()
        return self.current_index < len(self.MISSION_ORDER)

    def is_complete(self):
        return self.current_index >= len(self.MISSION_ORDER)

    def save_aircraft_state(self, aircraft):
        """Save damage/ammo from aircraft for next sortie."""
        self.damage_carry = {
            'engine': aircraft.dmg_engine * 0.5,   # Partial repair between sorties
            'aileron': aircraft.dmg_aileron * 0.5,
            'elevator': aircraft.dmg_elevator * 0.5,
            'rudder': aircraft.dmg_rudder * 0.5,
        }
        self.ammo_carry = {
            'mg_ammo': max(1200, aircraft.mg_ammo),  # At least half reloaded
            'rockets': 6,   # Full rocket rearm
            'bombs': 1,     # Full bomb rearm
            'torpedoes': 1, # Full torpedo rearm
        }
        self.save()

    def apply_aircraft_state(self, aircraft):
        """Apply carried damage/ammo to new sortie aircraft."""
        if self.damage_carry:
            aircraft.dmg_engine = self.damage_carry.get('engine', 0)
            aircraft.dmg_aileron = self.damage_carry.get('aileron', 0)
            aircraft.dmg_elevator = self.damage_carry.get('elevator', 0)
            aircraft.dmg_rudder = self.damage_carry.get('rudder', 0)
            if aircraft.dmg_engine > 0.5:
                aircraft.smoking = True
        if self.ammo_carry:
            aircraft.mg_ammo = self.ammo_carry.get('mg_ammo', 2400)
            aircraft.rockets = self.ammo_carry.get('rockets', 6)
            aircraft.bombs = self.ammo_carry.get('bombs', 1)
            aircraft.torpedoes = self.ammo_carry.get('torpedoes', 1)

    def save(self):
        import json
        data = {
            'current_index': self.current_index,
            'results': self.results,
            'damage_carry': self.damage_carry,
            'ammo_carry': self.ammo_carry,
        }
        try:
            with open(SAVE_FILE) as f:
                save_data = json.load(f)
        except Exception:
            save_data = {}
        save_data['campaign'] = data
        try:
            with open(SAVE_FILE, 'w') as f:
                json.dump(save_data, f, indent=2)
        except Exception:
            pass

    def load(self):
        import json
        try:
            with open(SAVE_FILE) as f:
                data = json.load(f)
            campaign = data.get('campaign', {})
            self.current_index = campaign.get('current_index', 0)
            self.results = campaign.get('results', [])
            self.damage_carry = campaign.get('damage_carry', {})
            self.ammo_carry = campaign.get('ammo_carry', {})
        except Exception:
            pass


def draw_campaign_status(surface, campaign, dossier):
    """Draw campaign progress screen."""
    surface.fill((10, 15, 25))
    title = font_title.render("CAMPAIGN", True, HUD_AMBER)
    surface.blit(title, (WIDTH // 2 - title.get_width() // 2, 40))

    subtitle = font_med.render(f"{dossier.get_rank()} {dossier.name}", True, HUD_GREEN)
    surface.blit(subtitle, (WIDTH // 2 - subtitle.get_width() // 2, 110))

    y = 170
    for i, mission_class in enumerate(Campaign.MISSION_ORDER):
        m = mission_class()
        # Status marker
        if i < len(campaign.results):
            name, status = campaign.results[i]
            if status == "success":
                marker = "[COMPLETE]"
                color = HUD_GREEN
            else:
                marker = "[FAILED - RETRY]"
                color = HUD_RED
        elif i == campaign.current_index:
            marker = ">> NEXT <<"
            color = HUD_AMBER
        else:
            marker = "[LOCKED]"
            color = (80, 80, 80)

        # Mission name
        diff_stars = "*" * m.DIFFICULTY
        line = font_med.render(f"{i+1}. {m.NAME}  {diff_stars}  {marker}", True, color)
        surface.blit(line, (100, y))
        y += 40

    if campaign.is_complete():
        victory = font_large.render("CAMPAIGN VICTORY!", True, (255, 215, 0))
        surface.blit(victory, (WIDTH // 2 - victory.get_width() // 2, y + 30))
        stats = font_med.render(
            f"Missions: {len(campaign.results)} | Score: {dossier.total_score:,}",
            True, HUD_GREEN)
        surface.blit(stats, (WIDTH // 2 - stats.get_width() // 2, y + 80))
    else:
        hint = font_small.render("Press ENTER to launch next mission  |  ESC to return", True, WHITE)
        surface.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT - 60))


# ============== RANKING & DOSSIER ==============
RANKS = [
    (0, "Ensign"),
    (2000, "Lt. Junior Grade"),
    (5000, "Lieutenant"),
    (10000, "Lt. Commander"),
    (20000, "Commander"),
    (40000, "Captain"),
]

SAVE_FILE = os.path.join(os.path.expanduser('~'), 'hellcat_save.json')


class PilotDossier:
    """Persistent pilot record"""
    def __init__(self, name="PLAYER"):
        self.name = name
        self.total_score = 0
        self.total_kills = {'aircraft': 0, 'ship': 0, 'ground': 0}
        self.missions_completed = []
        self.missions_attempted = 0
        self.carrier_landings = 0
        self.load()

    def get_rank(self):
        rank = "Ensign"
        for threshold, name in RANKS:
            if self.total_score >= threshold:
                rank = name
        return rank

    def get_next_rank_progress(self):
        current_idx = 0
        for i, (threshold, name) in enumerate(RANKS):
            if self.total_score >= threshold:
                current_idx = i
        if current_idx >= len(RANKS) - 1:
            return 1.0  # Max rank
        current_threshold = RANKS[current_idx][0]
        next_threshold = RANKS[current_idx + 1][0]
        return (self.total_score - current_threshold) / (next_threshold - current_threshold)

    def add_mission_result(self, mission):
        self.missions_attempted += 1
        if mission.status == "success":
            score = mission.get_score()
            self.total_score += score
            if mission.NAME not in self.missions_completed:
                self.missions_completed.append(mission.NAME)
                self.total_score += 500  # Bonus for first completion
        self.save()

    def record_carrier_landing(self):
        self.carrier_landings += 1
        self.total_score += 50
        self.save()

    def save(self):
        import json
        data = {
            'name': self.name,
            'total_score': self.total_score,
            'total_kills': self.total_kills,
            'missions_completed': self.missions_completed,
            'missions_attempted': self.missions_attempted,
            'carrier_landings': self.carrier_landings,
        }
        try:
            with open(SAVE_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def load(self):
        import json
        try:
            with open(SAVE_FILE) as f:
                data = json.load(f)
            self.name = data.get('name', self.name)
            self.total_score = data.get('total_score', 0)
            self.total_kills = data.get('total_kills', self.total_kills)
            self.missions_completed = data.get('missions_completed', [])
            self.missions_attempted = data.get('missions_attempted', 0)
            self.carrier_landings = data.get('carrier_landings', 0)
        except Exception:
            pass


# ============== DETERMINISTIC REPLAY ==============
PHYSICS_DT = 1.0 / 60.0  # Fixed physics timestep for deterministic replay


class _ReplayKeys:
    """Mimics pygame.key.get_pressed() using recorded bitmask."""
    def __init__(self, state, key_list):
        self._map = {k: i for i, k in enumerate(key_list)}
        self._state = state

    def __getitem__(self, key):
        idx = self._map.get(key)
        return bool(self._state & (1 << idx)) if idx is not None else False


class InputRecorder:
    """Records and replays input for deterministic replay with HOTP_RNG."""
    TRACKED_KEYS = [
        pygame.K_w, pygame.K_s, pygame.K_a, pygame.K_d,
        pygame.K_q, pygame.K_e, pygame.K_LSHIFT, pygame.K_LCTRL,
        pygame.K_SPACE, pygame.K_f, pygame.K_g,
        pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4,
        pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET,
        pygame.K_EQUALS, pygame.K_MINUS,
        pygame.K_UP, pygame.K_DOWN,
    ]

    def __init__(self):
        self.frames = []
        self.rng_seed = 0
        self.recording = False
        self.playing = False
        self.play_index = 0

    def start_recording(self, rng_seed):
        self.frames = []
        self.rng_seed = rng_seed
        self.recording = True
        self.playing = False

    def stop_recording(self):
        self.recording = False

    def record_frame(self, keys):
        state = 0
        for i, k in enumerate(self.TRACKED_KEYS):
            if keys[k]:
                state |= (1 << i)
        self.frames.append(state)

    def start_playback(self):
        global hotp_rng
        hotp_rng = HOTP_RNG(self.rng_seed)
        self.playing = True
        self.recording = False
        self.play_index = 0

    def get_frame_keys(self):
        if self.play_index >= len(self.frames):
            self.playing = False
            return None
        state = self.frames[self.play_index]
        self.play_index += 1
        return _ReplayKeys(state, self.TRACKED_KEYS)

    def save(self, filename):
        import json
        with open(filename, 'w') as f:
            json.dump({'rng_seed': self.rng_seed, 'frames': self.frames, 'version': 1}, f)

    def load(self, filename):
        import json
        with open(filename) as f:
            data = json.load(f)
        self.rng_seed = data['rng_seed']
        self.frames = data['frames']

    @property
    def frame_count(self):
        return len(self.frames)


def draw_dossier(surface, dossier):
    """Draw pilot dossier overlay"""
    # Background
    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 220))
    surface.blit(overlay, (0, 0))

    cx = WIDTH // 2

    # Title
    title = font_title.render("PILOT DOSSIER", True, HUD_GREEN)
    surface.blit(title, title.get_rect(center=(cx, 50)))

    # Rank and name
    rank = dossier.get_rank()
    rank_text = font_large.render(f"{rank} {dossier.name}", True, HUD_AMBER)
    surface.blit(rank_text, rank_text.get_rect(center=(cx, 110)))

    # Score
    score_text = font_large.render(f"Total Score: {dossier.total_score:,}", True, WHITE)
    surface.blit(score_text, score_text.get_rect(center=(cx, 160)))

    # Rank progress bar
    progress = dossier.get_next_rank_progress()
    bar_w = 400
    bar_x = cx - bar_w // 2
    pygame.draw.rect(surface, (40, 40, 40), (bar_x, 195, bar_w, 20))
    pygame.draw.rect(surface, HUD_GREEN, (bar_x, 195, int(bar_w * progress), 20))
    pygame.draw.rect(surface, HUD_GREEN, (bar_x, 195, bar_w, 20), 2)
    prog_label = font_tiny.render("Next Rank", True, (150, 150, 150))
    surface.blit(prog_label, (bar_x + bar_w + 10, 198))

    # Stats
    stats_y = 240
    stats = [
        f"Missions Attempted: {dossier.missions_attempted}",
        f"Missions Completed: {len(dossier.missions_completed)}",
        f"Carrier Landings: {dossier.carrier_landings}",
        f"Aircraft Kills: {dossier.total_kills.get('aircraft', 0)}",
        f"Ships Sunk: {dossier.total_kills.get('ship', 0)}",
        f"Ground Targets: {dossier.total_kills.get('ground', 0)}",
    ]
    for i, stat in enumerate(stats):
        text = font_med.render(stat, True, (200, 200, 200))
        surface.blit(text, (cx - 200, stats_y + i * 35))

    # Mission awards
    awards_y = stats_y + len(stats) * 35 + 30
    awards_title = font_med.render("Mission Awards:", True, HUD_GREEN)
    surface.blit(awards_title, (cx - 200, awards_y))
    if dossier.missions_completed:
        for i, mission_name in enumerate(dossier.missions_completed):
            award = font_small.render(f"  * {mission_name}", True, HUD_AMBER)
            surface.blit(award, (cx - 180, awards_y + 30 + i * 25))
    else:
        none_text = font_small.render("  No awards yet", True, (120, 120, 120))
        surface.blit(none_text, (cx - 180, awards_y + 30))

    # Instructions
    hint = font_med.render("Press ESC to close", True, (150, 150, 150))
    surface.blit(hint, hint.get_rect(center=(cx, HEIGHT - 40)))


def draw_mission_briefing(surface, mission):
    """Draw mission briefing screen"""
    # Background
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = int(10 + 20 * ratio)
        g = int(15 + 25 * ratio)
        b = int(30 + 40 * ratio)
        pygame.draw.rect(surface, (r, g, b), (0, y, WIDTH, 1))

    # Title
    title = font_title.render(mission.NAME, True, HUD_GREEN)
    title_rect = title.get_rect(center=(WIDTH // 2, 60))
    surface.blit(title, title_rect)

    # Difficulty stars
    stars = "*" * mission.DIFFICULTY + " " * (5 - mission.DIFFICULTY)
    diff_text = font_med.render(f"Difficulty: {stars}", True, HUD_AMBER)
    diff_rect = diff_text.get_rect(center=(WIDTH // 2, 100))
    surface.blit(diff_text, diff_rect)

    # Objective
    obj_text = font_med.render(f"Objective: {mission.OBJECTIVE}", True, WHITE)
    obj_rect = obj_text.get_rect(center=(WIDTH // 2, 140))
    surface.blit(obj_text, obj_rect)

    # Briefing text
    pygame.draw.rect(surface, (20, 30, 40), (WIDTH // 2 - 350, 180, 700, 400), border_radius=10)
    pygame.draw.rect(surface, HUD_GREEN, (WIDTH // 2 - 350, 180, 700, 400), 2, border_radius=10)

    for i, line in enumerate(mission.BRIEFING):
        color = HUD_GREEN if i == 0 else (200, 200, 200)
        text = font_med.render(line, True, color)
        surface.blit(text, (WIDTH // 2 - 330, 200 + i * 32))

    # Instructions
    inst = font_large.render("Press ENTER to launch | ESC to cancel", True, WHITE)
    inst_rect = inst.get_rect(center=(WIDTH // 2, HEIGHT - 60))
    surface.blit(inst, inst_rect)


def draw_mission_hud(surface, mission):
    """Draw mission objective status during flight"""
    if not mission or mission.status != "active":
        return

    # Objective bar at top
    pygame.draw.rect(surface, (0, 0, 0, 200), (10, 10, 400, 50))
    pygame.draw.rect(surface, HUD_GREEN, (10, 10, 400, 50), 1)

    name_text = font_small.render(mission.NAME, True, HUD_GREEN)
    surface.blit(name_text, (20, 15))
    obj_text = font_tiny.render(mission.OBJECTIVE[:55], True, WHITE)
    surface.blit(obj_text, (20, 38))


def draw_mission_result(surface, mission):
    """Draw mission success/fail screen"""
    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 180))
    surface.blit(overlay, (0, 0))

    if mission.status == "success":
        color = HUD_GREEN
        title = "MISSION COMPLETE!"
        subtitle = "Excellent work, pilot."
    else:
        color = HUD_RED
        title = "MISSION FAILED"
        subtitle = "Better luck next time."

    title_text = font_title.render(title, True, color)
    title_rect = title_text.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 80))
    surface.blit(title_text, title_rect)

    sub_text = font_large.render(subtitle, True, WHITE)
    sub_rect = sub_text.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 30))
    surface.blit(sub_text, sub_rect)

    score_text = font_med.render(f"Score: {mission.get_score()}", True, HUD_AMBER)
    score_rect = score_text.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 20))
    surface.blit(score_text, score_rect)

    hint = font_med.render("Press M for menu | R to retry", True, (180, 180, 180))
    hint_rect = hint.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 70))
    surface.blit(hint, hint_rect)


# ============== AIRCRAFT BASE CLASS ==============
class Aircraft:
    G = 32.174  # ft/s^2
    RHO_SL = 0.002377  # slug/ft^3

    def __init__(self):
        self.reset()

    def get_air_density(self, altitude):
        if altitude < 36089:
            T = 518.67 - 0.00356616 * altitude
            p = 2116.22 * (T / 518.67) ** 5.256
        else:
            T = 389.97
            p = 472.68 * math.exp(-0.0000481 * (altitude - 36089))
        return p / (1716.49 * T)

    def get_airspeed_kts(self):
        v = math.sqrt(self.vx**2 + self.vy**2 + self.vz**2)
        return v / 1.68781

    def get_vertical_speed(self):
        return self.vz * 60


# ============== GRUMMAN F6F-5 HELLCAT ==============
class F6F_Hellcat(Aircraft):
    NAME = "F6F-5 Hellcat"
    DESCRIPTION = "WWII Navy Fighter"

    # Specifications
    WING_AREA = 334.0
    WINGSPAN = 42.83
    ASPECT_RATIO = WINGSPAN ** 2 / WING_AREA
    EMPTY_WEIGHT = 9238
    FUEL_WEIGHT = 1880
    COMBAT_WEIGHT = 12598
    MAX_WEIGHT = 15413

    MAX_POWER_HP = 2000
    CRITICAL_ALT = 23400

    # Aerodynamics
    CD0_CLEAN = 0.035
    CD0_GEAR = 0.025
    CD0_FLAPS = 0.10
    OSWALD_E = 0.75
    CLMAX_CLEAN = 1.35
    CLMAX_FLAPS = 1.85
    CL_ALPHA = 0.1
    CL0 = 0.2
    CL_FLAPS_BONUS = 0.4  # Extra lift from flaps

    VNE = 400
    MANEUVERING_SPEED = 250
    FLAPS_MAX_SPEED = 120
    GEAR_MAX_SPEED = 140
    STALL_SPEED_CLEAN = 87
    STALL_SPEED_FLAPS = 70

    def reset(self):
        self.ref_lat = 40.7288
        self.ref_lon = -73.4134
        self.x, self.y, self.z = 0, 0, 5000
        self.vx, self.vy, self.vz = 0, 250 * 1.68781, 0
        self.pitch, self.roll, self.heading = 2, 0, 0
        self.pitch_rate, self.roll_rate, self.yaw_rate = 0.0, 0.0, 0.0
        self.aoa = 2
        self.throttle = 0.75
        self.flaps = False
        self.gear_down = False
        self.fuel = self.FUEL_WEIGHT
        self.weight = self.COMBAT_WEIGHT
        self.drag_modifier = 1.0
        self.stalled = False
        self.overspeed = False
        self.on_ground = False
        self.lift_deficit = False
        # Weapons - F6F-5 Hellcat armament
        self.mg_ammo = 2400  # 400 rounds per gun x 6 guns
        self.rockets = 6  # 6x HVAR 5-inch rockets
        self.bombs = 1  # 1x 500lb bomb (centerline)
        self.torpedoes = 1  # 1x Mk 13 torpedo (belly mount)
        self.mg_firing = False
        self.last_mg_fire = 0
        self.selected_weapon = 0  # 0=MG, 1=Rockets, 2=Bombs
        self.radar_range = 3  # nm (1, 3, or 15)
        self.near_miss_shake = 0.0  # Screen shake intensity from near-misses
        # Component damage (0.0 = pristine, 1.0 = destroyed)
        self.dmg_engine = 0.0
        self.dmg_aileron = 0.0
        self.dmg_elevator = 0.0
        self.dmg_rudder = 0.0
        self.dmg_flaps = 0.0
        self.dmg_gear = 0.0
        self.dmg_fuel = 0.0  # fuel leak rate
        self.dmg_pilot = 0.0
        self.smoking = False
        self.on_fire = False
        # G-force effects on pilot
        self.g_effect = 0.0    # 0=clear vision, 1=full blackout/redout
        self.g_loc_timer = 0.0 # Seconds until GLOC recovery
        self.g_tolerance = 5.0 # Base positive G tolerance (trained WWII pilot)

    def get_engine_power(self, altitude, throttle):
        if altitude < 8000:
            power_ratio = 1.0
        elif altitude < self.CRITICAL_ALT:
            power_ratio = 1.0 + 0.15 * (altitude - 8000) / (self.CRITICAL_ALT - 8000)
        else:
            power_ratio = 1.15 - 0.4 * (altitude - self.CRITICAL_ALT) / (40000 - self.CRITICAL_ALT)
        power = self.MAX_POWER_HP * throttle * max(0.1, power_ratio)
        # Engine damage reduces power output
        power *= max(0.0, 1.0 - self.dmg_engine)
        return power

    def take_hit(self):
        """Random component takes damage from enemy fire"""
        component = random.choice(['engine', 'aileron', 'elevator', 'rudder',
                                    'flaps', 'gear', 'fuel', 'pilot'])
        dmg = random.uniform(0.15, 0.4)
        if component == 'engine':
            self.dmg_engine = min(1.0, self.dmg_engine + dmg)
            if self.dmg_engine > 0.5:
                self.smoking = True
            if self.dmg_engine > 0.8:
                self.on_fire = True
        elif component == 'aileron':
            self.dmg_aileron = min(1.0, self.dmg_aileron + dmg)
        elif component == 'elevator':
            self.dmg_elevator = min(1.0, self.dmg_elevator + dmg)
        elif component == 'rudder':
            self.dmg_rudder = min(1.0, self.dmg_rudder + dmg)
        elif component == 'flaps':
            self.dmg_flaps = min(1.0, self.dmg_flaps + dmg)
        elif component == 'gear':
            self.dmg_gear = min(1.0, self.dmg_gear + dmg)
        elif component == 'fuel':
            self.dmg_fuel = min(1.0, self.dmg_fuel + dmg * 2)
        elif component == 'pilot':
            self.dmg_pilot = min(1.0, self.dmg_pilot + dmg * 0.5)
        return component

    def calculate_forces(self):
        v_horizontal = math.sqrt(self.vx**2 + self.vy**2)
        airspeed = math.sqrt(self.vx**2 + self.vy**2 + self.vz**2)
        airspeed_kts = airspeed / 1.68781

        rho = self.get_air_density(self.z)
        q = 0.5 * rho * airspeed**2

        if airspeed > 10:
            flight_path_angle = math.degrees(math.atan2(self.vz, v_horizontal))
            self.aoa = self.pitch - flight_path_angle
        else:
            self.aoa = self.pitch

        # Lift coefficient with flaps effect
        cl_max = self.CLMAX_FLAPS if self.flaps else self.CLMAX_CLEAN
        stall_aoa = 18.0 if self.flaps else 14.0
        cl_base = self.CL0 + self.CL_ALPHA * self.aoa

        # Flaps increase lift coefficient
        if self.flaps:
            cl_base += self.CL_FLAPS_BONUS

        if self.aoa < stall_aoa and self.aoa > -8:
            cl = min(cl_base, cl_max)
            self.stalled = False
        else:
            self.stalled = True
            if self.aoa >= stall_aoa:
                excess_aoa = self.aoa - stall_aoa
                cl = cl_max * math.exp(-0.15 * excess_aoa)
                cl = max(cl, 0.3)
            else:
                cl = -0.4

        roll_rad = math.radians(self.roll)
        effective_lift_factor = math.cos(roll_rad)

        # Drag with gear and flaps effects
        cd0 = self.CD0_CLEAN
        if self.gear_down:
            cd0 += self.CD0_GEAR
        if self.flaps:
            cd0 += self.CD0_FLAPS
        if self.stalled:
            cd0 += 0.05
        if self.throttle < 0.3:
            cd0 += 0.02 * (1 - self.throttle / 0.3)

        cd_induced = cl**2 / (math.pi * self.ASPECT_RATIO * self.OSWALD_E)
        cd_total = (cd0 + cd_induced) * self.drag_modifier

        lift = q * self.WING_AREA * cl
        drag = q * self.WING_AREA * cd_total

        power_hp = self.get_engine_power(self.z, self.throttle)
        power_ftlbs = power_hp * 550
        if airspeed > 50:
            thrust = power_ftlbs / airspeed
        else:
            thrust = power_ftlbs / 100 * 0.8

        prop_efficiency = 0.85 - 0.1 * (airspeed_kts / self.VNE)
        thrust *= max(0.4, prop_efficiency)

        weight = self.weight
        return lift, drag, thrust, weight, airspeed_kts, q, effective_lift_factor, cd0

    def update(self, dt, keys):
        # Control surface inputs (-1 to 1)
        elevator = 0  # S = pull back (pitch up), W = push forward (pitch down)
        aileron = 0   # D = right roll, A = left roll
        rudder = 0    # E = right yaw, Q = left yaw

        # During GLOC, all controls are frozen
        gloc = getattr(self, 'g_loc_timer', 0) > 0

        if not gloc and keys[pygame.K_s]: elevator += 1
        if not gloc and keys[pygame.K_w]: elevator -= 1
        if not gloc and keys[pygame.K_d]: aileron += 1
        if not gloc and keys[pygame.K_a]: aileron -= 1
        if not gloc and keys[pygame.K_e]: rudder += 1
        if not gloc and keys[pygame.K_q]: rudder -= 1
        if keys[pygame.K_LSHIFT]:
            self.throttle = min(1.0, self.throttle + 0.5 * dt)
        if keys[pygame.K_LCTRL]:
            self.throttle = max(0.0, self.throttle - 0.5 * dt)
        if keys[pygame.K_UP]:
            self.drag_modifier = min(3.0, self.drag_modifier + 0.5 * dt)
        if keys[pygame.K_DOWN]:
            self.drag_modifier = max(0.5, self.drag_modifier - 0.5 * dt)

        # Control authority scales with dynamic pressure
        airspeed = math.sqrt(self.vx**2 + self.vy**2 + self.vz**2)
        rho = self.get_air_density(self.z)
        q = 0.5 * rho * airspeed**2
        q_ref = 0.5 * self.RHO_SL * (200 * 1.68781)**2
        ctrl = min(q / q_ref, 2.0) if q_ref > 0 else 0

        # Commanded angular rates — F6F Hellcat was renowned for crisp, responsive controls.
        # Original HOTP: small deltas snap instantly. We use higher rates + lower damping
        # to match that responsive feel. Historical: ~75 deg/s roll, fast pitch authority.
        pitch_cmd = elevator * 60 * ctrl * (1.0 - self.dmg_elevator)
        roll_cmd = aileron * 140 * ctrl * (1.0 - self.dmg_aileron)
        yaw_cmd = rudder * 20 * ctrl * (1.0 - self.dmg_rudder)

        # Aerodynamic damping (lower = more responsive, higher = more stable)
        damp_p = 3.0 * ctrl
        damp_r = 3.5 * ctrl
        damp_y = 2.5 * ctrl

        # Stability: trim pitch, wings-level tendency, stall nose-drop
        pitch_stab = 0
        if elevator == 0:
            pitch_stab = (2.0 - self.pitch) * 1.0 * ctrl
        if self.stalled and elevator >= 0:
            pitch_stab -= 20 * ctrl

        # Dihedral effect: restoring moment proportional to sin(roll).
        # Zero at 0° (upright) and 180° (inverted) - both are equilibria.
        # Maximum at ±90° bank. This allows sustained inverted flight.
        roll_stab = 0
        if aileron == 0:
            roll_stab = -math.sin(math.radians(self.roll)) * 50 * ctrl

        # Angular accelerations — high gain for snappy WWII fighter response
        # HOTP original: small corrections apply instantly (delta<8 rule)
        self.pitch_rate += (pitch_cmd + pitch_stab - self.pitch_rate * damp_p) * 8.0 * dt
        self.roll_rate += (roll_cmd + roll_stab - self.roll_rate * damp_r) * 10.0 * dt
        self.yaw_rate += (yaw_cmd - self.yaw_rate * damp_y) * 5.0 * dt

        # Update attitudes from angular rates
        # Full aerobatic pitch range: allows loops, split-S, Immelmann
        self.pitch = max(-89, min(89, self.pitch + self.pitch_rate * dt))
        self.roll = self.roll + self.roll_rate * dt
        # Wrap roll to -180..180
        self.roll = ((self.roll + 180) % 360) - 180
        self.heading = (self.heading + self.yaw_rate * dt) % 360

        # Coordinated turn: bank produces heading change via lift vector tilt.
        # Use tan(roll) directly (correct for all roll angles including inverted).
        # Clamp the TURN RATE, not the roll angle, to avoid singularity at ±90°.
        if airspeed > 100:
            roll_for_turn = math.radians(self.roll)
            cos_roll = math.cos(roll_for_turn)
            if abs(cos_roll) > 0.05:  # Avoid division issues near knife-edge
                bank_turn = math.degrees(self.G * math.sin(roll_for_turn) / (airspeed * cos_roll))
                bank_turn = max(-25, min(25, bank_turn))  # Clamp turn rate
                self.heading = (self.heading + bank_turn * dt) % 360

        lift, drag, thrust, weight, airspeed_kts, q, eff_lift, cd0 = self.calculate_forces()
        self._cached_lift = lift
        self._cached_weight = weight

        v_total = math.sqrt(self.vx**2 + self.vy**2 + self.vz**2)
        v_total = max(v_total, 1)

        ux, uy, uz = self.vx / v_total, self.vy / v_total, self.vz / v_total
        hdg_rad = math.radians(self.heading)
        roll_rad = math.radians(self.roll)
        pitch_rad = math.radians(self.pitch)
        cos_roll = math.cos(roll_rad)

        # Thrust decomposition: thrust acts along body longitudinal axis.
        # The vertical component must account for roll (inverted = thrust pushes down).
        thrust_fwd = thrust * math.cos(pitch_rad)
        thrust_up_body = thrust * math.sin(pitch_rad)
        thrust_x = thrust_fwd * math.sin(hdg_rad) + thrust_up_body * math.sin(roll_rad) * math.cos(hdg_rad)
        thrust_y = thrust_fwd * math.cos(hdg_rad) - thrust_up_body * math.sin(roll_rad) * math.sin(hdg_rad)
        thrust_z = thrust_up_body * cos_roll  # Inverted: cos(180°)=-1 → thrust pushes down

        drag_x, drag_y, drag_z = -drag * ux, -drag * uy, -drag * uz

        # Lift decomposition (already correct: cos(180°) = -1 → lift pushes down when inverted)
        lift_vertical = lift * eff_lift
        lift_horizontal = lift * math.sin(roll_rad)
        lift_x = lift_horizontal * math.cos(hdg_rad)
        lift_y = -lift_horizontal * math.sin(hdg_rad)
        lift_z = lift_vertical

        weight_z = -weight

        fx = thrust_x + drag_x + lift_x
        fy = thrust_y + drag_y + lift_y
        fz = thrust_z + drag_z + lift_z + weight_z

        mass = self.weight / self.G
        ax, ay, az = fx / mass, fy / mass, fz / mass

        self.vx += ax * dt
        self.vy += ay * dt
        self.vz += az * dt

        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += self.vz * dt

        self.lift_deficit = lift_vertical < weight

        if math.sqrt(self.vx**2 + self.vy**2) > 50:
            vel_heading = math.degrees(math.atan2(self.vx, self.vy))
            hdg_diff = ((vel_heading - self.heading + 180) % 360) - 180
            self.heading = (self.heading + hdg_diff * 3.0 * dt) % 360

        if self.z <= 0:
            self.z = 0
            self.vz = 0
            if v_total * 0.592484 > 150:
                return "CRASHED - Too fast!"
            if abs(self.pitch) > 15:
                return "CRASHED - Bad attitude!"
            if abs(self.roll) > 20:
                return "CRASHED - Wings not level!"
            self.vx *= 0.95
            self.vy *= 0.95
            self.on_ground = True
            if v_total < 5:
                return "LANDED"
            return "ROLLING"
        self.on_ground = False

        self.overspeed = airspeed_kts > self.VNE

        fuel_flow = self.throttle * 150 / 3600
        # Fuel leak from damage
        fuel_leak = self.dmg_fuel * 500 / 3600  # Up to 500 lbs/hr leak
        self.fuel = max(0, self.fuel - (fuel_flow * 6 + fuel_leak) * dt)
        self.weight = self.EMPTY_WEIGHT + self.fuel

        # Fire spreads damage over time
        if self.on_fire:
            self.dmg_engine = min(1.0, self.dmg_engine + 0.05 * dt)
            self.dmg_fuel = min(1.0, self.dmg_fuel + 0.1 * dt)
            self.dmg_pilot = min(1.0, self.dmg_pilot + 0.02 * dt)

        # Pilot incapacitation
        if self.dmg_pilot >= 1.0:
            return "CRASHED - Pilot incapacitated!"

        # G-force effects on pilot vision
        g = self.get_load_factor()
        if g > self.g_tolerance:
            # Positive G: greyout -> tunnel vision -> blackout -> GLOC
            excess = (g - self.g_tolerance) / 3.0  # 3G above tolerance = full blackout
            self.g_effect = min(1.0, self.g_effect + excess * 1.5 * dt)
        elif g < -2.0:
            # Negative G: redout (blood rushes to head, lower tolerance)
            excess = (-g - 2.0) / 2.0  # 2G negative above -2 = full redout
            self.g_effect = min(1.0, self.g_effect + excess * 2.0 * dt)
        else:
            # Recovery: vision clears when G returns to normal
            self.g_effect = max(0.0, self.g_effect - 1.5 * dt)

        # GLOC: if g_effect reaches 1.0, pilot blacks out for a few seconds
        if self.g_effect >= 1.0:
            if self.g_loc_timer <= 0:
                self.g_loc_timer = 3.0  # 3 seconds of unconsciousness
        if self.g_loc_timer > 0:
            self.g_loc_timer -= dt
            self.g_effect = 1.0  # Stay fully blacked out during GLOC
            # Controls frozen during GLOC (pitch/roll/yaw rates decay naturally)
            return "!! G-LOC - UNCONSCIOUS !!"

        if self.stalled:
            return "** STALL **"
        if self.overspeed:
            return "!! OVERSPEED !!"
        if self.on_fire:
            return "!! FIRE - LAND IMMEDIATELY !!"
        if self.smoking:
            return "** ENGINE DAMAGE **"
        if self.g_effect > 0.3:
            if g < 0:
                return "** REDOUT **"
            return "** BLACKOUT **"
        return "FLYING"

    def get_load_factor(self):
        lift = getattr(self, '_cached_lift', None)
        weight = getattr(self, '_cached_weight', None)
        if lift is None or weight is None:
            lift, _, _, weight, _, _, _, _ = self.calculate_forces()
        return lift / weight if weight > 0 else 1.0


# ============== BOEING 747-200 ==============
class Boeing747_200(Aircraft):
    NAME = "Boeing 747-200"
    DESCRIPTION = "Jumbo Jet Airliner"

    # Specifications
    WING_AREA = 5500.0  # sq ft
    WINGSPAN = 195.7  # ft
    ASPECT_RATIO = WINGSPAN ** 2 / WING_AREA  # ~6.96
    EMPTY_WEIGHT = 380000  # lbs
    FUEL_WEIGHT = 300000  # lbs (full tanks)
    TYPICAL_WEIGHT = 600000  # lbs
    MAX_WEIGHT = 833000  # lbs

    # 4x Pratt & Whitney JT9D-7A engines
    MAX_THRUST_PER_ENGINE = 46500  # lbs
    NUM_ENGINES = 4
    MAX_THRUST = MAX_THRUST_PER_ENGINE * NUM_ENGINES  # 186,000 lbs total

    # Aerodynamics
    CD0_CLEAN = 0.018  # Very clean at cruise
    CD0_GEAR = 0.020  # Big gear!
    CD0_FLAPS_10 = 0.015
    CD0_FLAPS_FULL = 0.065  # Full flaps
    OSWALD_E = 0.82
    CLMAX_CLEAN = 1.2
    CLMAX_FLAPS = 2.4  # With full flaps and slats
    CL_ALPHA = 0.08
    CL0 = 0.25
    CL_FLAPS_BONUS = 0.8

    # Speeds (varies with weight, these are typical)
    VNE = 420  # Vmo ~365 KIAS, Mmo 0.92
    MANEUVERING_SPEED = 280
    FLAPS_MAX_SPEED = 250  # Flaps extended speed
    GEAR_MAX_SPEED = 270
    STALL_SPEED_CLEAN = 160  # At typical weight
    STALL_SPEED_FLAPS = 115

    CRUISE_ALTITUDE = 35000
    CRUISE_MACH = 0.84

    def reset(self):
        self.ref_lat = 40.7288
        self.ref_lon = -73.4134
        self.x, self.y, self.z = 0, 0, 10000  # Start higher
        self.vx, self.vy, self.vz = 0, 280 * 1.68781, 0  # 280 knots
        self.pitch, self.roll, self.heading = 2.5, 0, 0
        self.pitch_rate, self.roll_rate, self.yaw_rate = 0.0, 0.0, 0.0
        self.aoa = 2.5
        self.throttle = 0.70
        self.flaps = False  # 0 = up, True = down (simplified)
        self.flap_setting = 0  # 0, 10, 20, 30 degrees
        self.gear_down = False
        self.fuel = self.FUEL_WEIGHT * 0.7  # 70% fuel
        self.weight = self.TYPICAL_WEIGHT
        self.drag_modifier = 1.0
        self.stalled = False
        self.overspeed = False
        self.on_ground = False
        self.lift_deficit = False
        self.spoilers = False

    def get_engine_thrust(self, altitude, throttle, airspeed_kts):
        # Jet engines: thrust decreases with altitude (air density)
        # and with airspeed (ram drag effect, partially offset by ram compression)
        rho = self.get_air_density(altitude)
        rho_ratio = rho / self.RHO_SL

        # Thrust roughly proportional to air density
        altitude_factor = rho_ratio ** 0.8

        # Speed effect (thrust decreases slightly with speed)
        speed_factor = 1.0 - 0.0003 * airspeed_kts
        speed_factor = max(0.6, speed_factor)

        return self.MAX_THRUST * throttle * altitude_factor * speed_factor

    def calculate_forces(self):
        v_horizontal = math.sqrt(self.vx**2 + self.vy**2)
        airspeed = math.sqrt(self.vx**2 + self.vy**2 + self.vz**2)
        airspeed_kts = airspeed / 1.68781

        rho = self.get_air_density(self.z)
        q = 0.5 * rho * airspeed**2

        if airspeed > 10:
            flight_path_angle = math.degrees(math.atan2(self.vz, v_horizontal))
            self.aoa = self.pitch - flight_path_angle
        else:
            self.aoa = self.pitch

        # Lift coefficient
        cl_max = self.CLMAX_FLAPS if self.flaps else self.CLMAX_CLEAN
        stall_aoa = 16.0 if self.flaps else 12.0
        cl_base = self.CL0 + self.CL_ALPHA * self.aoa

        if self.flaps:
            cl_base += self.CL_FLAPS_BONUS

        if self.aoa < stall_aoa and self.aoa > -6:
            cl = min(cl_base, cl_max)
            self.stalled = False
        else:
            self.stalled = True
            if self.aoa >= stall_aoa:
                excess_aoa = self.aoa - stall_aoa
                cl = cl_max * math.exp(-0.12 * excess_aoa)
                cl = max(cl, 0.2)
            else:
                cl = -0.3

        roll_rad = math.radians(self.roll)
        effective_lift_factor = math.cos(roll_rad)

        # Drag calculation
        cd0 = self.CD0_CLEAN
        if self.gear_down:
            cd0 += self.CD0_GEAR
        if self.flaps:
            cd0 += self.CD0_FLAPS_FULL
        if self.stalled:
            cd0 += 0.03
        if self.spoilers:
            cd0 += 0.04

        cd_induced = cl**2 / (math.pi * self.ASPECT_RATIO * self.OSWALD_E)
        cd_total = (cd0 + cd_induced) * self.drag_modifier

        lift = q * self.WING_AREA * cl
        drag = q * self.WING_AREA * cd_total

        thrust = self.get_engine_thrust(self.z, self.throttle, airspeed_kts)

        weight = self.weight
        return lift, drag, thrust, weight, airspeed_kts, q, effective_lift_factor, cd0

    def update(self, dt, keys):
        # Control surface inputs (-1 to 1)
        elevator = 0
        aileron = 0
        rudder = 0

        if keys[pygame.K_s]: elevator += 1
        if keys[pygame.K_w]: elevator -= 1
        if keys[pygame.K_d]: aileron += 1
        if keys[pygame.K_a]: aileron -= 1
        if keys[pygame.K_e]: rudder += 1
        if keys[pygame.K_q]: rudder -= 1
        if keys[pygame.K_LSHIFT]:
            self.throttle = min(1.0, self.throttle + 0.3 * dt)
        if keys[pygame.K_LCTRL]:
            self.throttle = max(0.0, self.throttle - 0.3 * dt)
        if keys[pygame.K_UP]:
            self.drag_modifier = min(3.0, self.drag_modifier + 0.5 * dt)
        if keys[pygame.K_DOWN]:
            self.drag_modifier = max(0.5, self.drag_modifier - 0.5 * dt)

        # Control authority scales with dynamic pressure
        airspeed = math.sqrt(self.vx**2 + self.vy**2 + self.vz**2)
        rho = self.get_air_density(self.z)
        q = 0.5 * rho * airspeed**2
        q_ref = 0.5 * self.RHO_SL * (280 * 1.68781)**2
        ctrl = min(q / q_ref, 1.5) if q_ref > 0 else 0

        # 747 is much more sluggish than a fighter
        pitch_cmd = elevator * 8 * ctrl
        roll_cmd = aileron * 18 * ctrl
        yaw_cmd = rudder * 5 * ctrl

        # Heavy damping for large aircraft
        damp_p = 3.0 * ctrl
        damp_r = 3.5 * ctrl
        damp_y = 2.5 * ctrl

        # Stability
        pitch_stab = 0
        if elevator == 0:
            pitch_stab = (2.5 - self.pitch) * 0.6 * ctrl
        if self.stalled and elevator >= 0:
            pitch_stab -= 10 * ctrl

        roll_stab = 0
        if aileron == 0:
            roll_stab = -self.roll * 0.5 * ctrl

        # Angular accelerations (747 has high inertia = lower gain)
        self.pitch_rate += (pitch_cmd + pitch_stab - self.pitch_rate * damp_p) * 2.5 * dt
        self.roll_rate += (roll_cmd + roll_stab - self.roll_rate * damp_r) * 3.0 * dt
        self.yaw_rate += (yaw_cmd - self.yaw_rate * damp_y) * 2.0 * dt

        # Update attitudes from angular rates
        self.pitch = max(-20, min(25, self.pitch + self.pitch_rate * dt))
        self.roll = max(-50, min(50, self.roll + self.roll_rate * dt))
        self.heading = (self.heading + self.yaw_rate * dt) % 360

        # Coordinated turn: bank angle naturally changes heading
        if airspeed > 150:
            bank_turn = math.degrees(self.G * math.tan(math.radians(self.roll)) / airspeed)
            self.heading = (self.heading + bank_turn * dt) % 360

        lift, drag, thrust, weight, airspeed_kts, q, eff_lift, cd0 = self.calculate_forces()
        self._cached_lift = lift
        self._cached_weight = weight

        v_total = math.sqrt(self.vx**2 + self.vy**2 + self.vz**2)
        v_total = max(v_total, 1)

        ux, uy, uz = self.vx / v_total, self.vy / v_total, self.vz / v_total
        hdg_rad = math.radians(self.heading)
        roll_rad = math.radians(self.roll)
        pitch_rad = math.radians(self.pitch)

        thrust_x = thrust * math.sin(hdg_rad) * math.cos(pitch_rad)
        thrust_y = thrust * math.cos(hdg_rad) * math.cos(pitch_rad)
        thrust_z = thrust * math.sin(pitch_rad)

        drag_x, drag_y, drag_z = -drag * ux, -drag * uy, -drag * uz

        lift_vertical = lift * eff_lift
        lift_horizontal = lift * math.sin(roll_rad)
        lift_x = lift_horizontal * math.cos(hdg_rad)
        lift_y = -lift_horizontal * math.sin(hdg_rad)
        lift_z = lift_vertical

        weight_z = -weight

        fx = thrust_x + drag_x + lift_x
        fy = thrust_y + drag_y + lift_y
        fz = thrust_z + drag_z + lift_z + weight_z

        mass = self.weight / self.G
        ax, ay, az = fx / mass, fy / mass, fz / mass

        self.vx += ax * dt
        self.vy += ay * dt
        self.vz += az * dt

        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += self.vz * dt

        self.lift_deficit = lift_vertical < weight

        if math.sqrt(self.vx**2 + self.vy**2) > 50:
            vel_heading = math.degrees(math.atan2(self.vx, self.vy))
            hdg_diff = ((vel_heading - self.heading + 180) % 360) - 180
            self.heading = (self.heading + hdg_diff * 1.5 * dt) % 360

        if self.z <= 0:
            self.z = 0
            self.vz = 0
            touchdown_speed = v_total * 0.592484
            if touchdown_speed > 180:
                return "CRASHED - Too fast!"
            if abs(self.pitch) > 12:
                return "CRASHED - Bad attitude!"
            if abs(self.roll) > 10:
                return "CRASHED - Wings not level!"
            self.vx *= 0.98
            self.vy *= 0.98
            self.on_ground = True
            if v_total < 10:
                return "LANDED"
            return "ROLLING"
        self.on_ground = False

        self.overspeed = airspeed_kts > self.VNE

        # Fuel burn (much higher for 747!)
        fuel_flow = self.throttle * 12000 / 3600  # ~12000 lbs/hr at full throttle
        self.fuel = max(0, self.fuel - fuel_flow * dt)
        self.weight = self.EMPTY_WEIGHT + self.fuel

        if self.stalled:
            return "** STALL **"
        if self.overspeed:
            return "!! OVERSPEED !!"
        return "FLYING"

    def get_load_factor(self):
        lift = getattr(self, '_cached_lift', None)
        weight = getattr(self, '_cached_weight', None)
        if lift is None or weight is None:
            lift, _, _, weight, _, _, _, _ = self.calculate_forces()
        return lift / weight if weight > 0 else 1.0


# ============== DISASTER SCENARIOS ==============
class DisasterScenario:
    """Base class for disaster recreations"""
    NAME = "Unknown Disaster"
    DESCRIPTION = "Description"
    AIRCRAFT_CLASS = Boeing747_200
    DATE = "Unknown"

    # Starting conditions
    START_LAT = 40.7
    START_LON = -73.5
    START_ALT = 10000
    START_HEADING = 90
    START_SPEED = 300  # knots

    # Disaster trigger
    TRIGGER_TYPE = "time"  # "time" or "position"
    TRIGGER_TIME = 10  # seconds after start
    TRIGGER_ALT = None

    # Effects when triggered
    THRUST_MULTIPLIER = 0.0  # 0 = total thrust loss
    DRAG_MULTIPLIER = 2.0  # 2x drag

    def __init__(self):
        self.triggered = False
        self.trigger_timer = 0
        self.flight_time = 0

    def check_trigger(self, aircraft, dt):
        """Check if disaster should trigger"""
        self.flight_time += dt

        if self.triggered:
            return True

        if self.TRIGGER_TYPE == "time" and self.flight_time >= self.TRIGGER_TIME:
            self.triggered = True
            return True

        return False

    def apply_effects(self, aircraft):
        """Apply disaster effects to aircraft"""
        if self.triggered:
            aircraft.throttle = min(aircraft.throttle, self.THRUST_MULTIPLIER)
            aircraft.drag_modifier = max(aircraft.drag_modifier, self.DRAG_MULTIPLIER)


class TWA800(DisasterScenario):
    """
    TWA Flight 800 - July 17, 1996
    Boeing 747-131 exploded 12 minutes after takeoff from JFK

    Details:
    - Departed JFK at 8:19 PM bound for Paris
    - Center fuel tank exploded at 8:31 PM
    - Altitude: ~13,760 feet, climbing
    - Speed: ~380 knots
    - Location: 8 miles south of Moriches, Long Island
    - All 230 aboard killed
    - Cause: Short circuit ignited fuel tank vapors

    The nose section separated first. The rest of the aircraft
    continued climbing momentarily before descending into the Atlantic.
    """
    NAME = "TWA Flight 800"
    DESCRIPTION = "747 Fuel Tank Explosion - July 17, 1996"
    AIRCRAFT_CLASS = Boeing747_200
    DATE = "July 17, 1996"

    # Starting position - approaching the explosion point
    # Explosion occurred at approximately 40.727°N, 72.660°W
    # We'll start a bit before that, heading ENE out of JFK
    START_LAT = 40.68
    START_LON = -73.0  # Start west of explosion point
    START_ALT = 13000  # Climbing through 13,000 ft
    START_HEADING = 70  # East-northeast toward Europe
    START_SPEED = 365  # knots - climb speed

    # Trigger after 15 seconds of flight (gives time to observe)
    TRIGGER_TYPE = "time"
    TRIGGER_TIME = 15

    # Effects: Total thrust loss, doubled drag (structural breakup)
    THRUST_MULTIPLIER = 0.0
    DRAG_MULTIPLIER = 2.5  # Severe drag from structural damage

    INFO_TEXT = [
        "TWA FLIGHT 800 - DISASTER RECREATION",
        "Date: July 17, 1996 | Aircraft: Boeing 747-131",
        "Route: New York JFK to Paris CDG",
        "",
        "At 8:31 PM, 12 minutes after takeoff, the center",
        "fuel tank exploded at 13,760 feet. The nose section",
        "separated immediately. The main fuselage continued",
        "climbing briefly before falling into the Atlantic.",
        "",
        "You have 15 seconds before the explosion.",
        "After detonation: ALL ENGINES LOST, SEVERE DRAG",
        "Try to see how far you can glide..."
    ]


class DisasterAircraft(Boeing747_200):
    """Modified 747 for disaster scenarios"""

    def __init__(self, scenario):
        self.scenario = scenario  # Set scenario BEFORE calling super().__init__()
        super().__init__()
        self.setup_scenario()

    def setup_scenario(self):
        """Configure aircraft for scenario starting conditions"""
        self.ref_lat = self.scenario.START_LAT
        self.ref_lon = self.scenario.START_LON
        self.x, self.y = 0, 0
        self.z = self.scenario.START_ALT

        # Set velocity based on heading and speed
        speed_fps = self.scenario.START_SPEED * 1.68781
        hdg_rad = math.radians(self.scenario.START_HEADING)
        self.vx = speed_fps * math.sin(hdg_rad)
        self.vy = speed_fps * math.cos(hdg_rad)
        self.vz = 500 / 60  # Slight climb rate (~500 fpm)

        self.heading = self.scenario.START_HEADING
        self.pitch = 3  # Slight nose up for climb
        self.roll = 0
        self.throttle = 0.85  # Climb power

    def reset(self):
        super().reset()
        if hasattr(self, 'scenario') and self.scenario:
            self.scenario.triggered = False
            self.scenario.trigger_timer = 0
            self.scenario.flight_time = 0
            self.setup_scenario()

    def update(self, dt, keys):
        # Check for disaster trigger
        just_triggered = False
        if not self.scenario.triggered:
            if self.scenario.check_trigger(self, dt):
                just_triggered = True

        # Apply disaster effects
        self.scenario.apply_effects(self)

        # Normal physics update
        result = super().update(dt, keys)

        if just_triggered:
            msg = getattr(self.scenario, "TRIGGER_MESSAGE", "!! EXPLOSION - Loss OF THRUST !!")
            return msg

        # Apply post-physics control degradation if scenario set it
        degradation = getattr(self, "_control_degradation", 1.0)
        if degradation < 1.0:
            self.pitch_rate *= degradation
            self.roll_rate  *= degradation
            self.yaw_rate   *= degradation

        return result


class PanAm103(DisasterScenario):
    """
    Pan Am Flight 103 - December 21, 1988
    Boeing 747-121 destroyed by bomb in cargo hold over Lockerbie, Scotland

    Details:
    - En route London Heathrow to New York JFK
    - Libyan intelligence bomb in a Samsonite suitcase detonated at FL310
    - Altitude: 31,000 ft, speed ~310 knots
    - Location: over Lockerbie, Scotland (55.12N, 3.35W)
    - All 259 aboard killed; 11 Lockerbie residents killed by falling debris
    - CVR captured a 0.4-second anomaly before silence
    - Wreckage scattered over 845 sq miles; nose/cockpit found intact in field
    """
    NAME = "Pan Am Flight 103"
    DESCRIPTION = "747 Bomb Detonation - December 21, 1988"
    AIRCRAFT_CLASS = Boeing747_200
    DATE = "December 21, 1988"

    START_LAT = 55.12
    START_LON = -3.35
    START_ALT = 31000
    START_HEADING = 45
    START_SPEED = 310

    TRIGGER_TYPE = "time"
    TRIGGER_TIME = 20

    THRUST_MULTIPLIER = 0.0
    DRAG_MULTIPLIER = 3.0

    TRIGGER_MESSAGE = "!! BOMB DETONATION - STRUCTURAL BREAKUP !!"

    INFO_TEXT = [
        "PAN AM FLIGHT 103 - DISASTER RECREATION",
        "Date: December 21, 1988 | Aircraft: Boeing 747-121",
        "Route: London Heathrow to New York JFK",
        "",
        "A Semtex bomb concealed in a Samsonite suitcase",
        "detonated in the forward cargo hold at FL310.",
        "The explosion tore through the fuselage and severed",
        "all structural integrity within milliseconds.",
        "259 aboard and 11 Lockerbie residents were killed.",
        "",
        "You have 20 seconds before detonation at FL310.",
        "After explosion: ALL THRUST LOST, SEVERE STRUCTURAL DRAG",
    ]


class JAL123(DisasterScenario):
    """
    Japan Airlines Flight 123 - August 12, 1985
    Boeing 747SR-46, rear pressure bulkhead failure severed all 4 hydraulic systems

    Details:
    - En route Tokyo Haneda to Osaka Itami
    - Improperly repaired bulkhead (after 1978 tail strike) ruptured at cruise altitude
    - Explosive decompression blew out the vertical stabilizer
    - All hydraulic fluid lost; crew used differential engine thrust for control
    - 32 minutes of uncontrolled flight before impact with Mt. Osutaka
    - 520 of 524 aboard killed - worst single-aircraft disaster in aviation history
    - 4 survivors found in wreckage the following morning
    """
    NAME = "JAL Flight 123"
    DESCRIPTION = "747SR Hydraulic Failure - August 12, 1985"
    AIRCRAFT_CLASS = Boeing747_200
    DATE = "August 12, 1985"

    START_LAT = 35.62
    START_LON = 138.73
    START_ALT = 24000
    START_HEADING = 315
    START_SPEED = 300

    TRIGGER_TYPE = "time"
    TRIGGER_TIME = 25

    THRUST_MULTIPLIER = 1.0
    DRAG_MULTIPLIER = 1.8

    TRIGGER_MESSAGE = "!! BULKHEAD FAILURE - HYDRAULICS LOST !!"

    INFO_TEXT = [
        "JAL FLIGHT 123 - DISASTER RECREATION",
        "Date: August 12, 1985 | Aircraft: Boeing 747SR-46",
        "Route: Tokyo Haneda to Osaka Itami",
        "",
        "The aft pressure bulkhead failed catastrophically,",
        "blowing out the vertical stabilizer and severing",
        "all four independent hydraulic systems.",
        "",
        "ENGINES STILL WORK - use throttle to control descent!",
        "Controls are severely degraded (15% effectiveness).",
        "The real crew survived 32 minutes using engine thrust.",
        "520 of 524 perished - worst single-aircraft disaster.",
    ]

    def apply_effects(self, aircraft):
        """Hydraulic failure: engines functional but controls nearly gone."""
        if self.triggered:
            aircraft.drag_modifier = max(aircraft.drag_modifier, self.DRAG_MULTIPLIER)
            aircraft._control_degradation = 0.15


class Helios522(DisasterScenario):
    """
    Helios Airways Flight 522 - August 14, 2005
    Boeing 737-31S, pressurization failure led to crew hypoxia and a ghost flight

    Details:
    - En route Larnaca to Athens
    - Ground crew left pressurization in MANUAL after maintenance check
    - Crew failed to switch to AUTO; aircraft depressurized during climb
    - Crew incapacitated by hypoxia; autopilot flew for ~2.5 hours
    - One flight attendant (Andreas Prodromou) briefly took controls near end
    - All 121 aboard killed when aircraft crashed after fuel exhaustion
    - MECHANIC: Hypoxia progressively strips control authority over 45 seconds
    - SURVIVAL: Descend below 10,000 ft to recover before full incapacitation
    """
    NAME = "Helios Flight 522"
    DESCRIPTION = "737 Pressurization Failure / Hypoxia - August 14, 2005"
    AIRCRAFT_CLASS = Boeing747_200
    DATE = "August 14, 2005"

    START_LAT = 37.95
    START_LON = 23.72
    START_ALT = 34000
    START_HEADING = 180
    START_SPEED = 310

    TRIGGER_TYPE = "time"
    TRIGGER_TIME = 15

    THRUST_MULTIPLIER = 1.0
    DRAG_MULTIPLIER = 1.0

    TRIGGER_MESSAGE = "!! CABIN PRESSURE LOST - HYPOXIA ONSET !!"

    INFO_TEXT = [
        "HELIOS FLIGHT 522 - DISASTER RECREATION",
        "Date: August 14, 2005 | Aircraft: Boeing 737-31S",
        "Route: Larnaca to Athens",
        "",
        "Cabin pressurization was left in MANUAL after maintenance.",
        "The crew failed to notice - oxygen starvation began at altitude.",
        "Engines ran perfectly. The aircraft flew itself for ~2.5 hours.",
        "",
        "SURVIVAL MECHANIC: Descend below 10,000 ft within 45 seconds!",
        "Hypoxia will progressively strip your control authority.",
        "Below 10,000 ft you can breathe - controls begin to return.",
        "All 121 aboard perished when fuel ran out. Don't join them.",
    ]

    def apply_effects(self, aircraft):
        """
        Progressive hypoxia model.

        Control degrades linearly from 1.0 to 0.05 over 45 seconds post-trigger.
        Descending below 10,000 ft partially restores control (recoverable hypoxia).
        """
        if not self.triggered:
            return

        time_since = max(0.0, self.flight_time - self.TRIGGER_TIME)

        # Linear degradation: full control at t=0s, near-zero at t=45s
        degradation = max(0.05, 1.0 - time_since / 45.0)

        # Survival window: fresh air below 10,000 ft restores significant control
        if aircraft.z < 10000:
            degradation = min(1.0, degradation + 0.5)

        # No engine changes - engines kept running throughout the incident
        aircraft.drag_modifier = max(aircraft.drag_modifier, self.DRAG_MULTIPLIER)
        aircraft._control_degradation = degradation


# Available disaster scenarios
DISASTER_SCENARIOS = [TWA800, PanAm103, JAL123, Helios522]


# ============== AIRCRAFT RENDERING ==============
def draw_f6f_rendering(surface, x, y, scale=1.0):
    """Draw F6F-5 Hellcat side view - Glossy Sea Blue scheme"""
    s = scale
    NAVY = (40, 55, 100)
    NAVY_D = (25, 40, 75)
    NAVY_L = (55, 75, 125)
    COWL = (50, 50, 55)
    METAL = (140, 140, 140)

    # Fuselage (rounded, tapers to tail)
    fuse_top = [
        (x - 85*s, y - 2*s), (x - 75*s, y - 14*s), (x - 40*s, y - 18*s),
        (x + 20*s, y - 16*s), (x + 55*s, y - 14*s), (x + 85*s, y - 8*s),
        (x + 100*s, y - 2*s)
    ]
    fuse_bot = [
        (x + 100*s, y + 2*s), (x + 85*s, y + 6*s), (x + 55*s, y + 8*s),
        (x + 20*s, y + 10*s), (x - 40*s, y + 10*s), (x - 75*s, y + 8*s),
        (x - 85*s, y + 2*s)
    ]
    fuselage = fuse_top + fuse_bot
    pygame.draw.polygon(surface, NAVY, fuselage)
    # Fuselage belly highlight
    belly = [
        (x - 75*s, y + 2*s), (x + 80*s, y + 2*s),
        (x + 80*s, y + 7*s), (x - 75*s, y + 7*s)
    ]
    pygame.draw.polygon(surface, NAVY_L, belly)
    pygame.draw.polygon(surface, NAVY_D, fuselage, 2)

    # Engine cowling (round, dark)
    cowl_pts = [
        (x - 85*s, y - 2*s), (x - 98*s, y - 10*s), (x - 100*s, y),
        (x - 98*s, y + 10*s), (x - 85*s, y + 2*s)
    ]
    pygame.draw.polygon(surface, COWL, cowl_pts)
    pygame.draw.polygon(surface, (30, 30, 30), cowl_pts, 2)

    # Exhaust stacks
    for ey in range(-6, 8, 3):
        pygame.draw.circle(surface, (80, 60, 40), (int(x - 82*s), int(y + ey*s)), int(2*s))

    # Propeller disc
    pygame.draw.ellipse(surface, (60, 60, 60), (int(x - 105*s), int(y - 28*s),
                                                  int(10*s), int(56*s)))
    # Prop hub
    pygame.draw.circle(surface, (80, 80, 80), (int(x - 100*s), int(y)), int(5*s))

    # Wing (side view - shows thickness and chord)
    wing = [
        (x - 30*s, y + 6*s), (x - 65*s, y + 38*s), (x - 55*s, y + 42*s),
        (x + 5*s, y + 12*s)
    ]
    pygame.draw.polygon(surface, NAVY_L, wing)
    pygame.draw.polygon(surface, NAVY_D, wing, 2)

    # Flap (trailing edge)
    [(x - 10*s, y + 10*s), (x - 40*s, y + 36*s),
            (x - 35*s, y + 38*s), (x - 5*s, y + 12*s)]
    pygame.draw.line(surface, NAVY_D, (int(x - 10*s), int(y + 10*s)),
                     (int(x - 38*s), int(y + 37*s)), 1)

    # Horizontal tail
    htail = [
        (x + 78*s, y - 6*s), (x + 98*s, y - 20*s), (x + 105*s, y - 18*s),
        (x + 95*s, y - 4*s)
    ]
    pygame.draw.polygon(surface, NAVY_L, htail)
    pygame.draw.polygon(surface, NAVY_D, htail, 2)

    # Vertical tail
    vtail = [
        (x + 78*s, y - 14*s), (x + 88*s, y - 38*s), (x + 98*s, y - 36*s),
        (x + 100*s, y - 12*s)
    ]
    pygame.draw.polygon(surface, NAVY, vtail)
    pygame.draw.polygon(surface, NAVY_D, vtail, 2)
    # Rudder hinge line
    pygame.draw.line(surface, NAVY_D, (int(x + 92*s), int(y - 35*s)),
                     (int(x + 95*s), int(y - 10*s)), 1)

    # Cockpit canopy (bubble, framed)
    canopy = [
        (x - 15*s, y - 16*s), (x - 20*s, y - 24*s), (x - 10*s, y - 28*s),
        (x + 10*s, y - 28*s), (x + 25*s, y - 22*s), (x + 30*s, y - 16*s)
    ]
    pygame.draw.polygon(surface, (100, 150, 210), canopy)
    pygame.draw.polygon(surface, (60, 60, 70), canopy, 2)
    # Canopy frame ribs
    for cx_off in [-5, 5, 15]:
        pygame.draw.line(surface, (60, 60, 70),
                         (int(x + cx_off*s), int(y - 16*s)),
                         (int(x + cx_off*s), int(y - 27*s)), 1)

    # Landing gear (retracted position - wheel well cover)
    pygame.draw.ellipse(surface, NAVY_D,
                        (int(x - 55*s), int(y + 4*s), int(18*s), int(6*s)))

    # Arresting hook (stowed)
    pygame.draw.line(surface, METAL, (int(x + 75*s), int(y + 8*s)),
                     (int(x + 85*s), int(y + 6*s)), 2)

    # Star insignia with bars (US Navy marking)
    star_x, star_y = int(x + 25*s), int(y)
    r_out = int(14*s)
    r_in = int(9*s)
    pygame.draw.circle(surface, WHITE, (star_x, star_y), r_out)
    pygame.draw.circle(surface, NAVY, (star_x, star_y), r_in)
    # Insignia bars
    pygame.draw.rect(surface, WHITE, (star_x - int(22*s), star_y - int(5*s),
                                      int(44*s), int(10*s)))
    pygame.draw.rect(surface, NAVY, (star_x - r_in, star_y - r_in,
                                     r_in * 2, r_in * 2))
    pygame.draw.circle(surface, WHITE, (star_x, star_y), r_in)
    pygame.draw.circle(surface, NAVY, (star_x, star_y), int(6*s))

    # BuNo / side number
    num = font_tiny.render("19", True, WHITE)
    surface.blit(num, (int(x + 55*s), int(y - 12*s)))


def draw_747_rendering(surface, x, y, scale=1.0):
    """Draw 747 side view"""
    s = scale
    # Fuselage
    fuselage = [
        (x - 120*s, y), (x - 110*s, y - 20*s), (x + 100*s, y - 20*s),
        (x + 130*s, y - 10*s), (x + 140*s, y), (x + 130*s, y + 10*s),
        (x + 100*s, y + 20*s), (x - 110*s, y + 20*s), (x - 120*s, y)
    ]
    pygame.draw.polygon(surface, (240, 240, 245), fuselage)
    pygame.draw.polygon(surface, (100, 100, 100), fuselage, 2)

    # Nose hump (747 distinctive)
    hump = [
        (x - 110*s, y - 20*s), (x - 100*s, y - 35*s), (x - 60*s, y - 40*s),
        (x - 20*s, y - 35*s), (x, y - 20*s)
    ]
    pygame.draw.polygon(surface, (240, 240, 245), hump)
    pygame.draw.lines(surface, (100, 100, 100), False, hump, 2)

    # Windows
    for wx in range(-90, 100, 15):
        pygame.draw.ellipse(surface, (100, 150, 200), (x + wx*s, y - 8*s, 8*s, 10*s))

    # Wing
    wing = [
        (x - 30*s, y + 15*s), (x - 80*s, y + 60*s), (x - 60*s, y + 65*s),
        (x + 30*s, y + 25*s)
    ]
    pygame.draw.polygon(surface, (220, 220, 225), wing)

    # Engines (2 visible on this side)
    for ex in [-60, -35]:
        pygame.draw.ellipse(surface, (80, 80, 80), (x + ex*s - 8*s, y + 45*s, 20*s, 12*s))

    # Tail
    tail = [
        (x + 100*s, y - 20*s), (x + 110*s, y - 55*s), (x + 135*s, y - 55*s),
        (x + 125*s, y - 15*s)
    ]
    pygame.draw.polygon(surface, (220, 220, 225), tail)

    # Airline stripe
    pygame.draw.line(surface, (200, 50, 50), (x - 110*s, y), (x + 120*s, y), int(4*s))


# ============== HOME SCREEN ==============
def draw_home_screen(surface, selected_index, menu_items, current_menu):
    """Draw aircraft/scenario selection screen"""
    # Background gradient
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = int(20 + 40 * ratio)
        g = int(30 + 50 * ratio)
        b = int(60 + 80 * ratio)
        pygame.draw.line(surface, (r, g, b), (0, y), (WIDTH, y))

    # Title
    title = font_title.render("FLIGHT SIMULATOR", True, WHITE)
    title_rect = title.get_rect(center=(WIDTH // 2, 50))
    surface.blit(title, title_rect)

    # Menu tabs
    tab_y = 100
    tabs = ["FREE FLIGHT", "MISSIONS", "DISASTERS", "CAMPAIGN"]
    tab_width = 220
    total_tab_width = len(tabs) * tab_width
    tab_start_x = (WIDTH - total_tab_width) // 2

    for i, tab_name in enumerate(tabs):
        tab_x = tab_start_x + i * tab_width
        is_active = (i == current_menu)
        tab_color = (60, 100, 140) if is_active else (40, 50, 60)
        border_color = HUD_GREEN if is_active else (80, 80, 80)

        pygame.draw.rect(surface, tab_color, (tab_x, tab_y, tab_width - 10, 40), border_radius=5)
        pygame.draw.rect(surface, border_color, (tab_x, tab_y, tab_width - 10, 40), 2, border_radius=5)

        tab_text = font_med.render(tab_name, True, WHITE if is_active else (150, 150, 150))
        text_rect = tab_text.get_rect(center=(tab_x + tab_width // 2 - 5, tab_y + 20))
        surface.blit(tab_text, text_rect)

    if current_menu == 0:
        # Free Flight - Aircraft selection
        subtitle = font_med.render("Select Your Aircraft", True, HUD_GREEN)
        sub_rect = subtitle.get_rect(center=(WIDTH // 2, 165))
        surface.blit(subtitle, sub_rect)

        # Aircraft cards
        card_width = 500
        card_height = 280
        card_spacing = 80
        total_width = len(menu_items) * card_width + (len(menu_items) - 1) * card_spacing
        start_x = (WIDTH - total_width) // 2

        for i, aircraft_class in enumerate(menu_items):
            card_x = start_x + i * (card_width + card_spacing)
            card_y = 200

            is_selected = (i == selected_index)
            card_color = (60, 80, 100) if is_selected else (40, 50, 60)
            border_color = HUD_GREEN if is_selected else (80, 80, 80)

            pygame.draw.rect(surface, card_color, (card_x, card_y, card_width, card_height), border_radius=10)
            pygame.draw.rect(surface, border_color, (card_x, card_y, card_width, card_height), 3, border_radius=10)

            render_x = card_x + card_width // 2
            render_y = card_y + 90

            if aircraft_class == F6F_Hellcat:
                draw_f6f_rendering(surface, render_x, render_y, 1.8)
            else:
                draw_747_rendering(surface, render_x, render_y, 1.5)

            name = font_large.render(aircraft_class.NAME, True, WHITE)
            name_rect = name.get_rect(center=(card_x + card_width // 2, card_y + 185))
            surface.blit(name, name_rect)

            desc = font_med.render(aircraft_class.DESCRIPTION, True, HUD_AMBER)
            desc_rect = desc.get_rect(center=(card_x + card_width // 2, card_y + 220))
            surface.blit(desc, desc_rect)

            if aircraft_class == F6F_Hellcat:
                specs = ["Max Speed: 380 kts", "Engine: 2,000 HP", "Weight: 12,598 lbs"]
            else:
                specs = ["Cruise: Mach 0.84", "Engines: 4x 46,500 lbf", "Weight: 600,000 lbs"]

            for j, spec in enumerate(specs):
                spec_text = font_tiny.render(spec, True, (180, 180, 180))
                surface.blit(spec_text, (card_x + 20, card_y + 245 + j * 16))

        # Selection arrow
        arrow_x = start_x + selected_index * (card_width + card_spacing) + card_width // 2
        pygame.draw.polygon(surface, HUD_GREEN, [
            (arrow_x, 185), (arrow_x - 15, 170), (arrow_x + 15, 170)
        ])

    elif current_menu == 1:
        # Missions
        subtitle = font_med.render("Combat Missions - Solomon Islands, 1943", True, HUD_GREEN)
        sub_rect = subtitle.get_rect(center=(WIDTH // 2, 165))
        surface.blit(subtitle, sub_rect)

        # Mission cards
        card_width = 220
        card_height = 320
        cards_per_row = min(5, len(menu_items))
        total_w = cards_per_row * card_width + (cards_per_row - 1) * 10
        start_x = (WIDTH - total_w) // 2
        card_y = 200

        for i, mission_class in enumerate(menu_items):
            m = mission_class()
            cx = start_x + i * (card_width + 10)
            is_selected = (i == selected_index)

            bg_color = (40, 60, 40) if is_selected else (30, 35, 30)
            border_color = HUD_GREEN if is_selected else (60, 80, 60)

            pygame.draw.rect(surface, bg_color, (cx, card_y, card_width, card_height), border_radius=8)
            pygame.draw.rect(surface, border_color, (cx, card_y, card_width, card_height), 2, border_radius=8)

            # Mission name
            name = font_med.render(m.NAME, True, WHITE)
            surface.blit(name, (cx + 10, card_y + 10))

            # Difficulty stars
            stars_str = "*" * m.DIFFICULTY
            stars = font_small.render(stars_str, True, HUD_AMBER)
            surface.blit(stars, (cx + 10, card_y + 40))

            # Objective (wrapped)
            words = m.OBJECTIVE.split()
            line = ""
            y_off = 70
            for word in words:
                test = line + word + " "
                if font_tiny.size(test)[0] > card_width - 20:
                    obj_line = font_tiny.render(line, True, (180, 180, 180))
                    surface.blit(obj_line, (cx + 10, card_y + y_off))
                    y_off += 18
                    line = word + " "
                else:
                    line = test
            if line:
                obj_line = font_tiny.render(line, True, (180, 180, 180))
                surface.blit(obj_line, (cx + 10, card_y + y_off))

            # Selection arrow
            if is_selected:
                pygame.draw.polygon(surface, HUD_GREEN, [
                    (cx + card_width // 2, card_y - 10),
                    (cx + card_width // 2 - 10, card_y - 22),
                    (cx + card_width // 2 + 10, card_y - 22)
                ])

    elif current_menu == 2:
        # Disaster Recreations
        subtitle = font_med.render("Historic Aviation Disasters", True, HUD_RED)
        sub_rect = subtitle.get_rect(center=(WIDTH // 2, 165))
        surface.blit(subtitle, sub_rect)

        warning = font_small.render("Educational recreations of real accidents - In memory of those lost", True, (180, 180, 180))
        warn_rect = warning.get_rect(center=(WIDTH // 2, 190))
        surface.blit(warning, warn_rect)

        # Disaster cards
        card_width = 700
        card_height = 350
        start_x = (WIDTH - card_width) // 2
        card_y = 220

        for i, scenario_class in enumerate(menu_items):
            is_selected = (i == selected_index)
            card_color = (80, 40, 40) if is_selected else (50, 30, 30)
            border_color = HUD_RED if is_selected else (100, 50, 50)

            pygame.draw.rect(surface, card_color, (start_x, card_y, card_width, card_height), border_radius=10)
            pygame.draw.rect(surface, border_color, (start_x, card_y, card_width, card_height), 3, border_radius=10)

            # 747 rendering
            draw_747_rendering(surface, start_x + 150, card_y + 80, 1.2)

            # Explosion effect
            pygame.draw.circle(surface, (255, 100, 0), (start_x + 120, card_y + 70), 30)
            pygame.draw.circle(surface, (255, 200, 0), (start_x + 120, card_y + 70), 20)
            pygame.draw.circle(surface, (255, 255, 200), (start_x + 120, card_y + 70), 10)

            # Scenario info
            name = font_large.render(scenario_class.NAME, True, WHITE)
            surface.blit(name, (start_x + 280, card_y + 20))

            date = font_med.render(scenario_class.DATE, True, HUD_AMBER)
            surface.blit(date, (start_x + 280, card_y + 60))

            desc = font_med.render(scenario_class.DESCRIPTION, True, (200, 200, 200))
            surface.blit(desc, (start_x + 280, card_y + 95))

            # Info text
            if hasattr(scenario_class, 'INFO_TEXT'):
                for j, line in enumerate(scenario_class.INFO_TEXT[:8]):
                    line_color = HUD_RED if "EXPLOSION" in line or "LOST" in line else (170, 170, 170)
                    info = font_tiny.render(line, True, line_color)
                    surface.blit(info, (start_x + 30, card_y + 150 + j * 22))

            # Selection indicator
            if is_selected:
                pygame.draw.polygon(surface, HUD_RED, [
                    (start_x - 20, card_y + card_height // 2),
                    (start_x - 35, card_y + card_height // 2 - 15),
                    (start_x - 35, card_y + card_height // 2 + 15)
                ])

    elif current_menu == 3:
        # Campaign mode
        subtitle = font_med.render("Campaign Mode", True, HUD_AMBER)
        sub_rect = subtitle.get_rect(center=(WIDTH // 2, 165))
        surface.blit(subtitle, sub_rect)

        desc = font_small.render("Fly all 8 missions in order. Damage carries between sorties.", True, (180, 180, 180))
        desc_rect = desc.get_rect(center=(WIDTH // 2, 195))
        surface.blit(desc, desc_rect)

        # Show mission list preview
        y = 230
        for i, mc in enumerate(Campaign.MISSION_ORDER):
            m = mc()
            stars = "*" * m.DIFFICULTY
            color = HUD_GREEN if i == 0 else (120, 120, 120)
            line = font_small.render(f"{i+1}. {m.NAME}  {stars}", True, color)
            surface.blit(line, (WIDTH // 2 - 150, y))
            y += 28

        start_hint = font_med.render("Press ENTER to begin campaign", True, HUD_AMBER)
        hint_rect = start_hint.get_rect(center=(WIDTH // 2, y + 30))
        surface.blit(start_hint, hint_rect)

    # Instructions
    inst = font_med.render("TAB: Switch Menu | A/D: Select | ENTER: Start | ESC: Quit", True, WHITE)
    inst_rect = inst.get_rect(center=(WIDTH // 2, HEIGHT - 50))
    surface.blit(inst, inst_rect)

    drag_hint = font_small.render("In-flight: [ / ] keys adjust drag coefficient", True, (150, 150, 150))
    drag_rect = drag_hint.get_rect(center=(WIDTH // 2, HEIGHT - 25))
    surface.blit(drag_hint, drag_rect)


# ============== GAME DRAWING FUNCTIONS ==============
# ============== CAMERA VIEWS ==============
CAMERA_OVERHEAD = 0
CAMERA_COCKPIT = 1
CAMERA_CHASE = 2
CAMERA_NAMES = ["OVERHEAD", "COCKPIT", "CHASE"]


def draw_perspective_ground(surface, aircraft, map_img, horizon_y):
    """Draw satellite map with perspective projection - simple flat scanlines.
    Roll is handled by rotating the output surface in draw_cockpit_view."""
    alt = max(aircraft.z, 50)
    hdg_rad = math.radians(aircraft.heading)
    pitch_rad = math.radians(aircraft.pitch)
    ac_x, ac_y = aircraft.x, aircraft.y

    surf_w = surface.get_width()
    surf_h = surface.get_height()
    view_cx = surf_w * 0.5
    focal_length = surf_h * 0.85
    pitch_inv = 1.0 / max(math.cos(pitch_rad), 0.1)

    # GTA-style fog wall
    fog_wall = min(alt * 12, 60000)
    fog_start = fog_wall * 0.3
    FOG = (180, 195, 210)

    sin_h, cos_h = math.sin(hdg_rad), math.cos(hdg_rad)

    # Precompute coordinate conversion
    lon_range = MAP_SE_LON - MAP_NW_LON
    lat_range = MAP_NW_LAT - MAP_SE_LAT
    px_base = (aircraft.ref_lon - MAP_NW_LON) / lon_range * MAP_WIDTH
    px_scale = MAP_WIDTH / (lon_range * 288000)
    py_base = (MAP_NW_LAT - aircraft.ref_lat) / lat_range * MAP_HEIGHT
    py_scale = -MAP_HEIGHT / (lat_range * 364000)

    screen_y = int(max(0, horizon_y + 1))
    while screen_y < surf_h:
        pixels_below = screen_y - horizon_y
        if pixels_below <= 0:
            screen_y += 2
            continue

        ground_dist = alt * focal_length / pixels_below * pitch_inv

        # Progressive LOD
        if ground_dist > fog_wall * 0.6:
            sx, sy = 12, 6
        elif ground_dist > fog_wall * 0.3:
            sx, sy = 7, 4
        elif ground_dist > fog_wall * 0.1:
            sx, sy = 4, 3
        else:
            sx, sy = 3, 2

        if ground_dist > fog_wall or ground_dist < 10:
            pygame.draw.rect(surface, FOG, (0, screen_y, surf_w, sy))
            screen_y += sy
            continue

        if ground_dist > fog_start:
            fog = (ground_dist - fog_start) / (fog_wall - fog_start)
            fog = fog * fog
        else:
            fog = 0.0
        inv_fog = 1.0 - fog
        fr, fg, fb = FOG[0] * fog, FOG[1] * fog, FOG[2] * fog

        ground_width = ground_dist * surf_w / focal_length

        for screen_x in range(0, surf_w, sx):
            x_ratio = (screen_x - view_cx) / surf_w
            lateral = x_ratio * ground_width

            wx = ac_x + sin_h * ground_dist + cos_h * lateral
            wy = ac_y + cos_h * ground_dist - sin_h * lateral

            mx = int(px_base + wx * px_scale) % MAP_WIDTH
            my = int(py_base + wy * py_scale) % MAP_HEIGHT

            if 0 <= mx < MAP_WIDTH and 0 <= my < MAP_HEIGHT:
                try:
                    c = map_img.get_at((mx, my))
                    color = (int(c[0] * inv_fog + fr),
                             int(c[1] * inv_fog + fg),
                             int(c[2] * inv_fog + fb))
                except Exception:
                    color = FOG
            else:
                color = (int(40 * inv_fog + fr), int(60 * inv_fog + fg), int(100 * inv_fog + fb))

            pygame.draw.rect(surface, color, (screen_x, screen_y, sx, sy))

        screen_y += sy


# Pre-allocate cockpit world surface (avoids per-frame allocation)
_cockpit_world_size = 0
_cockpit_world_surf = None


def draw_cockpit_view(surface, aircraft, map_img, time_elapsed):
    """First-person cockpit view - renders world flat, rotates by roll.
    Sky/ground/horizon/pitch ladder rotate together as the outside world.
    Crosshair/heading tape/velocity vector stay aircraft-fixed."""
    global _cockpit_world_size, _cockpit_world_surf

    pitch_offset = aircraft.pitch * 8
    roll_deg = aircraft.roll
    math.radians(roll_deg)

    # View area (between cockpit pillars and above instrument panel)
    view_x = 80
    view_w = WIDTH - 160   # 1120
    view_h = HEIGHT - 100  # 800

    # Temp surface big enough that rotation doesn't clip visible area.
    # Diagonal of view rectangle = max dimension needed after any rotation.
    diag = int(math.sqrt(view_w * view_w + view_h * view_h)) + 40
    if diag != _cockpit_world_size:
        _cockpit_world_size = diag
        _cockpit_world_surf = pygame.Surface((diag, diag))

    temp = _cockpit_world_surf
    tcx = diag // 2
    tcy = diag // 2

    # --- WORLD RENDERING (no roll - flat) ---

    # Sky gradient
    t_horizon = tcy + int(pitch_offset)
    temp.fill((50, 100, 180))  # Deep sky blue base

    # Gradient bands approaching horizon
    grad_top = max(0, int(t_horizon - 250))
    grad_bottom = max(0, int(t_horizon))
    band_count = 10
    band_h = max(1, (grad_bottom - grad_top) // band_count)
    for i in range(band_count):
        by = grad_top + i * band_h
        ratio = (i + 0.5) / band_count
        c = (int(50 + 135 * ratio), int(100 + 106 * ratio), int(180 + 55 * ratio))
        pygame.draw.rect(temp, c, (0, by, diag, band_h + 1))
    # Near-horizon haze
    if 0 < t_horizon < diag:
        haze_h = min(60, diag - int(t_horizon))
        pygame.draw.rect(temp, (185, 206, 235), (0, int(t_horizon), diag, haze_h))

    # Perspective ground (flat scanlines, no roll)
    draw_perspective_ground(temp, aircraft, map_img, t_horizon)

    # Horizon line (horizontal on temp - will tilt after rotation)
    pygame.draw.line(temp, WHITE, (0, int(t_horizon)), (diag, int(t_horizon)), 3)

    # Pitch ladder (horizontal marks - rotate with world)
    for pitch_mark in range(-20, 25, 5):
        if pitch_mark == 0:
            continue
        mark_y = int(tcy + pitch_offset - pitch_mark * 8)
        mark_len = 60 if pitch_mark % 10 == 0 else 30
        color = HUD_GREEN if pitch_mark > 0 else HUD_AMBER
        pygame.draw.line(temp, color, (tcx - mark_len, mark_y), (tcx + mark_len, mark_y), 2)
        if pitch_mark % 10 == 0:
            label = font_tiny.render(str(abs(pitch_mark)), True, color)
            temp.blit(label, (tcx + mark_len + 10, mark_y - 8))

    # --- ROTATE WORLD BY ROLL ---
    rotated = pygame.transform.rotate(temp, roll_deg)

    # Crop from center of rotated surface to fill view area
    rcx = rotated.get_width() // 2
    rcy = rotated.get_height() // 2
    crop_rect = (rcx - view_w // 2, rcy - view_h // 2, view_w, view_h)
    surface.blit(rotated, (view_x, 0), crop_rect)

    # --- AIRCRAFT-FIXED HUD (drawn after rotation, stays level) ---
    cx, cy = WIDTH // 2, HEIGHT // 2

    # Fixed crosshair / aircraft reference
    pygame.draw.line(surface, HUD_GREEN, (cx - 80, cy), (cx - 30, cy), 3)
    pygame.draw.line(surface, HUD_GREEN, (cx + 30, cy), (cx + 80, cy), 3)
    pygame.draw.line(surface, HUD_GREEN, (cx - 30, cy), (cx - 30, cy + 15), 3)
    pygame.draw.line(surface, HUD_GREEN, (cx + 30, cy), (cx + 30, cy + 15), 3)
    pygame.draw.circle(surface, HUD_GREEN, (cx, cy), 5, 2)

    # Heading tape at top
    pygame.draw.rect(surface, (0, 0, 0, 150), (cx - 150, 10, 300, 35))
    hdg = aircraft.heading
    for h_offset in range(-30, 35, 10):
        h_val = (int(hdg) + h_offset) % 360
        h_x = cx + h_offset * 4
        pygame.draw.line(surface, HUD_GREEN, (h_x, 35), (h_x, 45), 2)
        if h_val % 30 == 0:
            cardinal = {0: "N", 90: "E", 180: "S", 270: "W"}.get(h_val, str(h_val))
            h_label = font_tiny.render(cardinal, True, HUD_GREEN)
            surface.blit(h_label, (h_x - 8, 15))
    pygame.draw.polygon(surface, HUD_GREEN, [(cx, 45), (cx - 8, 55), (cx + 8, 55)])

    # Velocity vector (flight path marker)
    if aircraft.get_airspeed_kts() > 50:
        vv_x = cx + int(math.sin(math.radians(aircraft.heading - math.degrees(math.atan2(aircraft.vx, aircraft.vy)))) * 50)
        vv_y = cy - int(aircraft.aoa * 8)
        pygame.draw.circle(surface, HUD_GREEN, (vv_x, vv_y), 12, 2)
        pygame.draw.line(surface, HUD_GREEN, (vv_x - 20, vv_y), (vv_x - 12, vv_y), 2)
        pygame.draw.line(surface, HUD_GREEN, (vv_x + 12, vv_y), (vv_x + 20, vv_y), 2)
        pygame.draw.line(surface, HUD_GREEN, (vv_x, vv_y - 12), (vv_x, vv_y - 20), 2)

    # Cockpit frame - F6F Hellcat canopy and instrument panel
    is_hellcat = isinstance(aircraft, F6F_Hellcat)
    FRAME = (28, 28, 32) if is_hellcat else (25, 25, 28)
    FRAME_L = (42, 42, 48)
    FRAME_D = (18, 18, 20)
    panel_h = 100

    # Instrument panel (glare shield on top)
    pygame.draw.rect(surface, FRAME, (0, HEIGHT - panel_h, WIDTH, panel_h))
    # Glare shield (slightly lighter strip along top of panel)
    pygame.draw.rect(surface, FRAME_L, (0, HEIGHT - panel_h, WIDTH, 6))
    pygame.draw.line(surface, FRAME_D, (0, HEIGHT - panel_h), (WIDTH, HEIGHT - panel_h), 2)

    # Side pillars
    pygame.draw.rect(surface, FRAME_D, (0, 0, 80, HEIGHT))
    pygame.draw.rect(surface, FRAME_D, (WIDTH - 80, 0, 80, HEIGHT))
    # Pillar edge highlight
    pygame.draw.line(surface, FRAME_L, (80, 0), (80, HEIGHT - panel_h), 1)
    pygame.draw.line(surface, FRAME_L, (WIDTH - 80, 0), (WIDTH - 80, HEIGHT - panel_h), 1)

    # Windscreen frame - angled A-pillars
    pygame.draw.line(surface, FRAME_L, (80, 0), (200, HEIGHT - panel_h), 10)
    pygame.draw.line(surface, FRAME_L, (WIDTH - 80, 0), (WIDTH - 200, HEIGHT - panel_h), 10)

    if is_hellcat:
        # Center windscreen bow (vertical divider)
        pygame.draw.line(surface, FRAME_L, (WIDTH // 2, 0), (WIDTH // 2, 50), 4)

        # Canopy arch ribs (curved top frame)
        for rib_x in [WIDTH // 4 + 40, WIDTH // 2, WIDTH * 3 // 4 - 40]:
            pygame.draw.line(surface, (35, 35, 40), (rib_x, 0), (rib_x, 20), 3)

        # Gunsight (illuminated reticle mount)
        gs_x, gs_y = WIDTH // 2, 65
        # Gunsight frame
        pygame.draw.rect(surface, (40, 40, 45), (gs_x - 20, gs_y - 15, 40, 30))
        pygame.draw.rect(surface, FRAME_L, (gs_x - 20, gs_y - 15, 40, 30), 1)
        # Reflecting glass (slightly transparent)
        glass = pygame.Surface((36, 26), pygame.SRCALPHA)
        glass.fill((80, 120, 160, 30))
        surface.blit(glass, (gs_x - 18, gs_y - 13))

        # Canopy rail (runs along bottom of canopy)
        pygame.draw.line(surface, FRAME, (80, HEIGHT - panel_h - 3),
                         (WIDTH - 80, HEIGHT - panel_h - 3), 3)


def draw_chase_perspective_ground(surface, aircraft, map_img, horizon_y):
    """Draw perspective ground for chase camera - GTA-style fog wall and LOD"""
    chase_offset = 300
    chase_alt_offset = 100
    alt = max(aircraft.z + chase_alt_offset, 200)

    hdg_rad = math.radians(aircraft.heading)
    sin_h, cos_h = math.sin(hdg_rad), math.cos(hdg_rad)

    cam_x = aircraft.x - sin_h * chase_offset
    cam_y = aircraft.y - cos_h * chase_offset

    focal_length = HEIGHT * 0.7
    half_w = WIDTH * 0.5

    # GTA-style fog wall
    fog_wall = min(alt * 12, 60000)
    fog_start = fog_wall * 0.3
    FOG = (180, 195, 210)

    # Precompute coordinate conversion
    lon_range = MAP_SE_LON - MAP_NW_LON
    lat_range = MAP_NW_LAT - MAP_SE_LAT
    px_base = (aircraft.ref_lon - MAP_NW_LON) / lon_range * MAP_WIDTH
    px_scale = MAP_WIDTH / (lon_range * 288000)
    py_base = (MAP_NW_LAT - aircraft.ref_lat) / lat_range * MAP_HEIGHT
    py_scale = -MAP_HEIGHT / (lat_range * 364000)

    screen_y = int(max(0, horizon_y + 1))
    while screen_y < HEIGHT:
        pixels_below = screen_y - horizon_y
        if pixels_below <= 0:
            screen_y += 2
            continue

        ground_dist = alt * focal_length / pixels_below

        # Progressive LOD
        if ground_dist > fog_wall * 0.6:
            sx, sy = 12, 6
        elif ground_dist > fog_wall * 0.3:
            sx, sy = 7, 4
        elif ground_dist > fog_wall * 0.1:
            sx, sy = 5, 3
        else:
            sx, sy = 3, 2

        if ground_dist > fog_wall or ground_dist < 10:
            pygame.draw.rect(surface, FOG, (0, screen_y, WIDTH, sy))
            screen_y += sy
            continue

        if ground_dist > fog_start:
            fog = (ground_dist - fog_start) / (fog_wall - fog_start)
            fog = fog * fog
        else:
            fog = 0.0
        inv_fog = 1.0 - fog
        fr, fg, fb = FOG[0] * fog, FOG[1] * fog, FOG[2] * fog

        ground_width = ground_dist * WIDTH / focal_length
        fwd_x = sin_h * ground_dist
        fwd_y = cos_h * ground_dist

        for screen_x in range(0, WIDTH, sx):
            lateral = (screen_x - half_w) / WIDTH * ground_width

            wx = cam_x + fwd_x + cos_h * lateral
            wy = cam_y + fwd_y - sin_h * lateral

            mx = int(px_base + wx * px_scale) % MAP_WIDTH
            my = int(py_base + wy * py_scale) % MAP_HEIGHT

            if 0 <= mx < MAP_WIDTH and 0 <= my < MAP_HEIGHT:
                try:
                    c = map_img.get_at((mx, my))
                    color = (int(c[0] * inv_fog + fr),
                             int(c[1] * inv_fog + fg),
                             int(c[2] * inv_fog + fb))
                except Exception:
                    color = FOG
            else:
                color = (int(50 * inv_fog + fr), int(70 * inv_fog + fg), int(110 * inv_fog + fb))

            pygame.draw.rect(surface, color, (screen_x, screen_y, sx, sy))

        screen_y += sy


def draw_chase_view(surface, aircraft, map_img, time_elapsed):
    """Third-person chase camera view"""
    # Ground/sky split based on pitch
    horizon_y = HEIGHT // 2 - aircraft.pitch * 5

    # Sky gradient (band fills instead of per-row draw.line)
    sky_top = int(max(0, horizon_y + 20))
    if sky_top > 0:
        bands = 10
        band_h = max(1, sky_top // bands)
        for i in range(bands):
            by = i * band_h
            ratio = (i + 0.5) / bands
            c = (int(100 + 85 * ratio), int(150 + 56 * ratio), int(200 + 35 * ratio))
            pygame.draw.rect(surface, c, (0, by, WIDTH, band_h + 1))

    # Draw perspective satellite ground
    draw_chase_perspective_ground(surface, aircraft, map_img, horizon_y)

    # Horizon line
    pygame.draw.line(surface, (200, 200, 200), (0, int(horizon_y)), (WIDTH, int(horizon_y)), 2)

    # Draw aircraft from behind
    cx, cy = WIDTH // 2, HEIGHT // 2 + 100
    scale = 2.5
    roll_rad = math.radians(aircraft.roll)

    def tp(px, py):
        """Transform point with roll and perspective foreshortening"""
        rx = px * math.cos(roll_rad) - py * math.sin(roll_rad) * 0.3
        ry = px * math.sin(roll_rad) + py * math.cos(roll_rad)
        return (cx + rx * scale, cy + ry * scale * 0.5)

    is_747 = isinstance(aircraft, Boeing747_200) or isinstance(aircraft, DisasterAircraft)

    if is_747:
        # --- Boeing 747 ---
        DARK = (180, 180, 185)
        MID = (210, 210, 215)
        LITE = (235, 235, 240)
        TRIM = (200, 50, 50)

        # Wings (swept, thicker root)
        wing = [(-18, -5), (-130, 15), (-125, 22), (-18, 12),
                (18, 12), (125, 22), (130, 15), (18, -5)]
        pygame.draw.polygon(surface, DARK, [tp(*p) for p in wing])
        pygame.draw.polygon(surface, (120, 120, 120), [tp(*p) for p in wing], 2)

        # Engine pylons + nacelles (4 engines)
        for ex in [-85, -45, 45, 85]:
            pylon = [(ex - 2, 5), (ex + 2, 5), (ex + 2, 15), (ex - 2, 15)]
            pygame.draw.polygon(surface, (100, 100, 100), [tp(*p) for p in pylon])
            nacelle = [(ex - 6, 15), (ex + 6, 15), (ex + 5, 25), (ex - 5, 25)]
            pygame.draw.polygon(surface, (90, 90, 90), [tp(*p) for p in nacelle])
            if aircraft.throttle > 0.3:
                ep = tp(ex, 27)
                pygame.draw.circle(surface, (255, 180, 80), (int(ep[0]), int(ep[1])),
                                   int(3 + aircraft.throttle * 6))

        # Horizontal stabilizer
        stab = [(-10, -60), (-45, -52), (-42, -48), (-10, -54),
                (10, -54), (42, -48), (45, -52), (10, -60)]
        pygame.draw.polygon(surface, DARK, [tp(*p) for p in stab])

        # Fuselage (round cross-section)
        fuse = [(0, -65), (16, -55), (16, 40), (12, 55), (0, 60),
                (-12, 55), (-16, 40), (-16, -55)]
        pygame.draw.polygon(surface, MID, [tp(*p) for p in fuse])
        # Fuselage highlight (lighter center)
        fuse_hi = [(0, -60), (8, -50), (8, 45), (0, 55),
                   (-8, 45), (-8, -50)]
        pygame.draw.polygon(surface, LITE, [tp(*p) for p in fuse_hi])
        pygame.draw.polygon(surface, (130, 130, 130), [tp(*p) for p in fuse], 2)

        # Upper deck hump (747 distinctive)
        hump = [(0, -65), (10, -60), (12, -40), (10, -20), (0, -15),
                (-10, -20), (-12, -40), (-10, -60)]
        pygame.draw.polygon(surface, LITE, [tp(*p) for p in hump])

        # Vertical tail (tall)
        vtail = [(0, -65), (-2, -100), (2, -100), (6, -65)]
        pygame.draw.polygon(surface, MID, [tp(*p) for p in vtail])
        pygame.draw.polygon(surface, (130, 130, 130), [tp(*p) for p in vtail], 2)

        # Airline stripe
        stripe_l = [(-16, -10), (-16, 0), (16, 0), (16, -10)]
        pygame.draw.polygon(surface, TRIM, [tp(*p) for p in stripe_l])

        # Window row (dots along fuselage)
        for wy in range(-45, 40, 8):
            for wx in [-12, 12]:
                wp = tp(wx, wy)
                pygame.draw.circle(surface, (120, 160, 200), (int(wp[0]), int(wp[1])), 1)
    else:
        # --- F6F-5 Hellcat (Glossy Sea Blue scheme) ---
        NAVY_DARK = (25, 40, 75)     # Shadow/underside
        NAVY_MID = (40, 55, 100)     # Main body
        NAVY_LITE = (55, 75, 125)    # Highlights
        NAVY_WING = (35, 50, 95)     # Wing surfaces
        METAL = (140, 140, 140)
        COWL = (50, 50, 55)

        # Wings - F6F had slight gull-wing (root dips down, then sweeps up)
        # Left wing: root to mid (dips), mid to tip (rises)
        wing_l = [(-12, -8), (-25, -3), (-45, 2), (-72, 8),
                  (-70, 14), (-45, 10), (-25, 6), (-12, 4)]
        wing_r = [(12, -8), (25, -3), (45, 2), (72, 8),
                  (70, 14), (45, 10), (25, 6), (12, 4)]
        pygame.draw.polygon(surface, NAVY_WING, [tp(*p) for p in wing_l])
        pygame.draw.polygon(surface, NAVY_WING, [tp(*p) for p in wing_r])
        pygame.draw.polygon(surface, NAVY_DARK, [tp(*p) for p in wing_l], 2)
        pygame.draw.polygon(surface, NAVY_DARK, [tp(*p) for p in wing_r], 2)

        # Wing fold lines (Hellcat had folding wings)
        fold_l = [tp(-28, -2), tp(-28, 6)]
        fold_r = [tp(28, -2), tp(28, 6)]
        pygame.draw.line(surface, NAVY_DARK, fold_l[0], fold_l[1], 1)
        pygame.draw.line(surface, NAVY_DARK, fold_r[0], fold_r[1], 1)

        # Star insignia on wings
        for wx_sign in [-1, 1]:
            star_cx = wx_sign * 42
            sp = tp(star_cx, 5)
            pygame.draw.circle(surface, WHITE, (int(sp[0]), int(sp[1])), int(8 * scale * 0.5))
            pygame.draw.circle(surface, NAVY_WING, (int(sp[0]), int(sp[1])), int(5 * scale * 0.5))

        # Horizontal stabilizer (squared tips, F6F style)
        stab = [(-8, -38), (-28, -33), (-26, -28), (-8, -32),
                (8, -32), (26, -28), (28, -33), (8, -38)]
        pygame.draw.polygon(surface, NAVY_WING, [tp(*p) for p in stab])
        pygame.draw.polygon(surface, NAVY_DARK, [tp(*p) for p in stab], 2)

        # Fuselage (round cross-section, tapers aft)
        fuse = [(0, -42), (12, -35), (12, 25), (10, 38),
                (0, 42), (-10, 38), (-12, 25), (-12, -35)]
        pygame.draw.polygon(surface, NAVY_MID, [tp(*p) for p in fuse])
        # Fuselage center highlight
        fuse_hi = [(0, -38), (6, -32), (6, 30), (0, 40),
                   (-6, 30), (-6, -32)]
        pygame.draw.polygon(surface, NAVY_LITE, [tp(*p) for p in fuse_hi])
        pygame.draw.polygon(surface, NAVY_DARK, [tp(*p) for p in fuse], 2)

        # Fuselage star insignia
        fuse_star = tp(0, -5)
        pygame.draw.circle(surface, WHITE, (int(fuse_star[0]), int(fuse_star[1])),
                           int(7 * scale * 0.5))
        pygame.draw.circle(surface, NAVY_MID, (int(fuse_star[0]), int(fuse_star[1])),
                           int(4 * scale * 0.5))
        # Insignia bars
        bar_l = tp(-10, -5)
        bar_r = tp(10, -5)
        pygame.draw.line(surface, WHITE, (int(bar_l[0]), int(bar_l[1])),
                         (int(fuse_star[0]) - int(7 * scale * 0.5), int(fuse_star[1])), 3)
        pygame.draw.line(surface, WHITE, (int(bar_r[0]), int(bar_r[1])),
                         (int(fuse_star[0]) + int(7 * scale * 0.5), int(fuse_star[1])), 3)

        # Vertical tail (tall, rounded top)
        vtail = [(-2, -42), (-2, -62), (0, -65), (2, -62), (6, -42)]
        pygame.draw.polygon(surface, NAVY_WING, [tp(*p) for p in vtail])
        pygame.draw.polygon(surface, NAVY_DARK, [tp(*p) for p in vtail], 2)

        # Rudder line
        rud_top = tp(0, -60)
        rud_bot = tp(0, -42)
        pygame.draw.line(surface, NAVY_DARK, (int(rud_top[0]), int(rud_top[1])),
                         (int(rud_bot[0]), int(rud_bot[1])), 1)

        # Engine cowling (round, dark)
        cowl = [(0, 42), (11, 40), (13, 45), (12, 50),
                (0, 52), (-12, 50), (-13, 45), (-11, 40)]
        pygame.draw.polygon(surface, COWL, [tp(*p) for p in cowl])
        pygame.draw.polygon(surface, (30, 30, 30), [tp(*p) for p in cowl], 2)

        # Exhaust stacks (along sides of cowling)
        for ex_sign in [-1, 1]:
            for ey in [43, 46, 49]:
                ep = tp(ex_sign * 14, ey)
                pygame.draw.circle(surface, (80, 60, 40), (int(ep[0]), int(ep[1])), 2)

        # Propeller disc (translucent blur when running)
        prop_c = tp(0, 53)
        prop_r = int(22 * scale * 0.5)
        if aircraft.throttle > 0.1:
            prop_surf = pygame.Surface((prop_r * 2 + 4, prop_r * 2 + 4), pygame.SRCALPHA)
            pygame.draw.circle(prop_surf, (180, 180, 180, 60),
                               (prop_r + 2, prop_r + 2), prop_r)
            pygame.draw.circle(prop_surf, (200, 200, 200, 100),
                               (prop_r + 2, prop_r + 2), prop_r, 2)
            surface.blit(prop_surf, (int(prop_c[0]) - prop_r - 2, int(prop_c[1]) - prop_r - 2))

        # Canopy (bubble canopy, rear view - arch shape)
        canopy = [(-8, -20), (-6, -28), (0, -30), (6, -28), (8, -20)]
        pygame.draw.lines(surface, (120, 170, 220), False,
                          [tp(*p) for p in canopy], 2)
        # Canopy frame ribs
        for cf_y in [-22, -25, -28]:
            cf_l = tp(-7, cf_y)
            cf_r = tp(7, cf_y)
            pygame.draw.line(surface, (80, 80, 90),
                             (int(cf_l[0]), int(cf_l[1])),
                             (int(cf_r[0]), int(cf_r[1])), 1)

        # Arresting hook (small line below tail)
        hook_top = tp(0, -38)
        hook_bot = tp(0, -32)
        pygame.draw.line(surface, METAL,
                         (int(hook_top[0]), int(hook_top[1]) + 8),
                         (int(hook_bot[0]), int(hook_bot[1]) + 12), 2)

        # Landing gear (if down)
        if aircraft.gear_down:
            for gx in [-18, 18]:
                g1 = tp(gx, 15)
                tp(gx, 15)
                pygame.draw.line(surface, METAL, (int(g1[0]), int(g1[1])),
                                 (int(g1[0]), int(g1[1]) + 20), 2)
                pygame.draw.circle(surface, (40, 40, 40),
                                   (int(g1[0]), int(g1[1]) + 22), 4)
            # Tail wheel
            tw = tp(0, -35)
            pygame.draw.line(surface, METAL, (int(tw[0]), int(tw[1])),
                             (int(tw[0]), int(tw[1]) + 8), 1)

        # Flaps (visible deflection when down)
        if aircraft.flaps:
            for fx_sign in [-1, 1]:
                flap = [(fx_sign * 15, 6), (fx_sign * 28, 9),
                        (fx_sign * 27, 14), (fx_sign * 14, 10)]
                pygame.draw.polygon(surface, (45, 60, 105), [tp(*p) for p in flap])
                pygame.draw.polygon(surface, NAVY_DARK, [tp(*p) for p in flap], 1)


def draw_minimap(surface, aircraft, map_img, x, y, size=200):
    """Draw a mini navigation map in corner"""
    # Create minimap surface
    minimap = pygame.Surface((size, size))
    minimap.fill((0, 40, 80))  # Ocean blue background

    # Get aircraft position in pixel coordinates
    px, py = feet_to_pixel(aircraft.x, aircraft.y, aircraft.ref_lat, aircraft.ref_lon)

    # Calculate view area (centered on aircraft, zoomed out more than main view)
    zoom = 0.5  # Show more area
    view_width = int(size / zoom)
    view_height = int(size / zoom)

    src_x = int(px - view_width // 2)
    src_y = int(py - view_height // 2)

    # Extract and scale map portion
    src_rect = pygame.Rect(src_x, src_y, view_width, view_height)

    # Handle boundaries
    src_rect.x = max(src_rect.x, 0)
    src_rect.y = max(src_rect.y, 0)
    if src_rect.right > MAP_WIDTH:
        src_rect.width = MAP_WIDTH - src_rect.x
    if src_rect.bottom > MAP_HEIGHT:
        src_rect.height = MAP_HEIGHT - src_rect.y

    if src_rect.width > 0 and src_rect.height > 0:
        try:
            map_portion = map_img.subsurface(src_rect.clip(map_img.get_rect()))
            scaled = pygame.transform.scale(map_portion, (size, size))
            minimap.blit(scaled, (0, 0))
        except Exception:
            pass  # Handle edge cases

    # Draw aircraft symbol on minimap
    ac_x = size // 2
    ac_y = size // 2

    # Heading indicator
    hdg_rad = math.radians(aircraft.heading)
    arrow_len = 15
    arrow_points = [
        (ac_x + arrow_len * math.sin(hdg_rad), ac_y - arrow_len * math.cos(hdg_rad)),
        (ac_x - 6 * math.sin(hdg_rad + 2.5), ac_y + 6 * math.cos(hdg_rad + 2.5)),
        (ac_x - 6 * math.sin(hdg_rad - 2.5), ac_y + 6 * math.cos(hdg_rad - 2.5)),
    ]
    pygame.draw.polygon(minimap, HUD_GREEN, arrow_points)
    pygame.draw.polygon(minimap, WHITE, arrow_points, 1)

    # Range rings
    for ring_nm in [1, 2, 5]:
        ring_px = int(ring_nm * 6076 / MAP_SCALE_FT_PER_PIXEL * zoom)
        if ring_px < size // 2:
            pygame.draw.circle(minimap, (100, 100, 100), (ac_x, ac_y), ring_px, 1)

    # North indicator
    pygame.draw.line(minimap, HUD_RED, (size - 20, 10), (size - 20, 25), 2)
    n_label = font_tiny.render("N", True, HUD_RED)
    minimap.blit(n_label, (size - 25, 26))

    # Compass rose (cardinal directions around edge)
    for angle, label in [(0, "N"), (90, "E"), (180, "S"), (270, "W")]:
        rad = math.radians(angle)
        lx = ac_x + (size // 2 - 15) * math.sin(rad)
        ly = ac_y - (size // 2 - 15) * math.cos(rad)
        dir_label = font_tiny.render(label, True, (150, 150, 150))
        minimap.blit(dir_label, (lx - 5, ly - 7))

    # Border
    pygame.draw.rect(minimap, HUD_GREEN, (0, 0, size, size), 2)

    # Scale indicator
    scale_nm = 2  # Show 2nm scale bar
    scale_px = int(scale_nm * 6076 / MAP_SCALE_FT_PER_PIXEL * zoom)
    pygame.draw.line(minimap, WHITE, (10, size - 15), (10 + scale_px, size - 15), 2)
    pygame.draw.line(minimap, WHITE, (10, size - 18), (10, size - 12), 2)
    pygame.draw.line(minimap, WHITE, (10 + scale_px, size - 18), (10 + scale_px, size - 12), 2)
    scale_label = font_tiny.render(f"{scale_nm} nm", True, WHITE)
    minimap.blit(scale_label, (10, size - 30))

    # Position info
    lat = aircraft.ref_lat + aircraft.y / 364000
    lon = aircraft.ref_lon + aircraft.x / 288000
    pos_text = font_tiny.render(f"{lat:.3f}N {abs(lon):.3f}W", True, HUD_GREEN)
    minimap.blit(pos_text, (5, 5))

    # Blit to main surface
    surface.blit(minimap, (x, y))

    # Label
    map_label = font_tiny.render("NAV MAP", True, HUD_GREEN)
    surface.blit(map_label, (x + size // 2 - 25, y - 18))


def draw_weapons_overhead(surface, weapons_mgr, aircraft):
    """Draw projectiles on overhead map view"""
    # Compute aircraft pixel position once for all loops
    ac_px, ac_py = feet_to_pixel(aircraft.x, aircraft.y, aircraft.ref_lat, aircraft.ref_lon)
    hw, hh = WIDTH // 2, HEIGHT // 2

    # Draw bullets (only tracers visible)
    for bullet in weapons_mgr.bullets:
        if bullet.is_tracer:
            px, py = feet_to_pixel(bullet.x, bullet.y, aircraft.ref_lat, aircraft.ref_lon)
            screen_x = int(hw + (px - ac_px))
            screen_y = int(hh + (py - ac_py))
            if 0 <= screen_x < WIDTH and 0 <= screen_y < HEIGHT:
                pygame.draw.circle(surface, (255, 255, 100), (screen_x, screen_y), 2)

    # Draw rockets
    for rocket in weapons_mgr.rockets:
        px, py = feet_to_pixel(rocket.x, rocket.y, aircraft.ref_lat, aircraft.ref_lon)
        screen_x = int(hw + (px - ac_px))
        screen_y = int(hh + (py - ac_py))
        if 0 <= screen_x < WIDTH and 0 <= screen_y < HEIGHT:
            pygame.draw.circle(surface, (255, 100, 50), (screen_x, screen_y), 4)
            for i, (tx, ty, tz, age) in enumerate(rocket.smoke_trail):
                tpx, tpy = feet_to_pixel(tx, ty, aircraft.ref_lat, aircraft.ref_lon)
                tsx = int(hw + (tpx - ac_px))
                tsy = int(hh + (tpy - ac_py))
                if 0 <= tsx < WIDTH and 0 <= tsy < HEIGHT:
                    gray = 150 + int(50 * (1 - age))
                    pygame.draw.circle(surface, (gray, gray, gray), (tsx, tsy), max(1, 3 - int(age * 3)))

    # Draw bombs
    for bomb in weapons_mgr.bombs:
        px, py = feet_to_pixel(bomb.x, bomb.y, aircraft.ref_lat, aircraft.ref_lon)
        screen_x = int(hw + (px - ac_px))
        screen_y = int(hh + (py - ac_py))
        if 0 <= screen_x < WIDTH and 0 <= screen_y < HEIGHT:
            pygame.draw.circle(surface, (80, 80, 80), (screen_x, screen_y), 6)
            pygame.draw.circle(surface, (50, 50, 50), (screen_x, screen_y), 6, 2)

    # Draw explosions
    for exp_x, exp_y, exp_z, age, size in weapons_mgr.explosions:
        px, py = feet_to_pixel(exp_x, exp_y, aircraft.ref_lat, aircraft.ref_lon)
        screen_x = int(hw + (px - ac_px))
        screen_y = int(hh + (py - ac_py))
        if 0 <= screen_x < WIDTH and 0 <= screen_y < HEIGHT:
            # Expanding fireball
            radius = int(size * (0.3 + age * 0.5))
            max(0, 255 - int(age * 150))
            # Multiple layers for explosion effect
            if age < 0.5:
                pygame.draw.circle(surface, (255, 255, 200), (screen_x, screen_y), radius)
            pygame.draw.circle(surface, (255, 150, 50), (screen_x, screen_y), int(radius * 0.8))
            pygame.draw.circle(surface, (255, 50, 0), (screen_x, screen_y), int(radius * 0.5))


def draw_weapons_cockpit(surface, weapons_mgr, aircraft):
    """Draw projectiles in cockpit view (tracers, rockets visible ahead)"""
    cx, cy = WIDTH // 2, HEIGHT // 2

    # Draw tracers streaking forward
    for bullet in weapons_mgr.bullets:
        if not bullet.is_tracer:
            continue
        # Calculate relative position
        dx = bullet.x - aircraft.x
        dy = bullet.y - aircraft.y
        dz = bullet.z - aircraft.z

        # Transform to aircraft-relative coordinates
        hdg_rad = math.radians(aircraft.heading)
        forward = dx * math.sin(hdg_rad) + dy * math.cos(hdg_rad)
        lateral = dx * math.cos(hdg_rad) - dy * math.sin(hdg_rad)

        # Only draw if ahead
        if forward > 0:
            # Project to screen
            scale = 500 / max(forward, 50)
            screen_x = int(cx + lateral * scale)
            screen_y = int(cy - dz * scale)
            if 80 < screen_x < WIDTH - 80 and 0 < screen_y < HEIGHT - 100:
                # Tracer: thin bright streak converging toward crosshair
                # Trail end is closer to screen center (bullet moving away)
                trail_len = max(4, int(15 * scale))
                # Trail points toward the gun (screen center), fading
                tx = screen_x + int((cx - screen_x) * 0.08)
                ty = screen_y + int((cy - screen_y) * 0.08) + trail_len
                pygame.draw.line(surface, (255, 255, 180), (screen_x, screen_y),
                                 (tx, ty), 2)
                # Bright head
                pygame.draw.circle(surface, (255, 255, 220), (screen_x, screen_y), 2)

    # Draw rockets
    for rocket in weapons_mgr.rockets:
        dx = rocket.x - aircraft.x
        dy = rocket.y - aircraft.y
        dz = rocket.z - aircraft.z

        hdg_rad = math.radians(aircraft.heading)
        forward = dx * math.sin(hdg_rad) + dy * math.cos(hdg_rad)
        lateral = dx * math.cos(hdg_rad) - dy * math.sin(hdg_rad)

        if forward > 0:
            scale = 500 / max(forward, 50)
            screen_x = int(cx + lateral * scale)
            screen_y = int(cy - dz * scale)
            if 80 < screen_x < WIDTH - 80 and 0 < screen_y < HEIGHT - 100:
                # Rocket flame
                if rocket.burning:
                    pygame.draw.circle(surface, (255, 200, 100), (screen_x, screen_y), 8)
                    pygame.draw.circle(surface, (255, 100, 50), (screen_x, screen_y), 5)
                else:
                    pygame.draw.circle(surface, (100, 100, 100), (screen_x, screen_y), 4)

    # Draw explosions
    for exp_x, exp_y, exp_z, age, size in weapons_mgr.explosions:
        dx = exp_x - aircraft.x
        dy = exp_y - aircraft.y
        dz = exp_z - aircraft.z

        hdg_rad = math.radians(aircraft.heading)
        forward = dx * math.sin(hdg_rad) + dy * math.cos(hdg_rad)
        lateral = dx * math.cos(hdg_rad) - dy * math.sin(hdg_rad)

        if forward > -500:  # Can see explosions a bit behind too
            scale = 500 / max(abs(forward), 100)
            screen_x = int(cx + lateral * scale)
            screen_y = int(cy - dz * scale)
            if 0 < screen_x < WIDTH and 0 < screen_y < HEIGHT:
                radius = int(size * scale * (0.5 + age))
                if radius > 2:
                    pygame.draw.circle(surface, (255, 200, 100), (screen_x, screen_y), radius)
                    pygame.draw.circle(surface, (255, 100, 0), (screen_x, screen_y), int(radius * 0.6))


def draw_weapons_hud(surface, aircraft):
    """Draw weapons status HUD"""
    if not hasattr(aircraft, 'mg_ammo'):
        return  # Not a Hellcat

    x_start = 85
    y_start = HEIGHT - 95

    # Background panel
    pygame.draw.rect(surface, (20, 30, 20), (x_start, y_start, 180, 105))
    pygame.draw.rect(surface, HUD_GREEN, (x_start, y_start, 180, 105), 1)

    # Title
    title = font_tiny.render("WEAPONS", True, HUD_GREEN)
    surface.blit(title, (x_start + 60, y_start + 3))

    weapon_names = ["MG .50 CAL", "HVAR ROCKET", "500LB BOMB", "MK13 TORPEDO"]
    weapon_counts = [aircraft.mg_ammo, aircraft.rockets, aircraft.bombs,
                     getattr(aircraft, 'torpedoes', 0)]
    weapon_maxes = [2400, 6, 1, 1]

    for i, (name, count, max_count) in enumerate(zip(weapon_names, weapon_counts, weapon_maxes)):
        y_pos = y_start + 22 + i * 18

        # Selection indicator
        if aircraft.selected_weapon == i:
            pygame.draw.polygon(surface, HUD_GREEN, [
                (x_start + 5, y_pos + 5),
                (x_start + 12, y_pos + 10),
                (x_start + 5, y_pos + 15)
            ])

        # Weapon name
        color = HUD_GREEN if count > 0 else HUD_RED
        name_text = font_tiny.render(name, True, color)
        surface.blit(name_text, (x_start + 15, y_pos + 2))

        # Count/bar
        if i == 0:  # MG shows count
            count_text = font_tiny.render(f"{count}", True, color)
            surface.blit(count_text, (x_start + 130, y_pos + 2))
        else:  # Rockets/bombs show pips
            for j in range(max_count):
                pip_x = x_start + 130 + j * 12
                if j < count:
                    pygame.draw.rect(surface, HUD_GREEN, (pip_x, y_pos + 4, 8, 10))
                else:
                    pygame.draw.rect(surface, (50, 50, 50), (pip_x, y_pos + 4, 8, 10))
                    pygame.draw.rect(surface, (80, 80, 80), (pip_x, y_pos + 4, 8, 10), 1)

    # Firing indicator (shown when MG firing)
    if hasattr(aircraft, 'mg_firing') and aircraft.mg_firing:
        pygame.draw.circle(surface, HUD_RED, (x_start + 170, y_start + 10), 5)


def draw_targets_overhead(surface, target_mgr, aircraft):
    """Draw targets on overhead map view"""
    ac_px, ac_py = feet_to_pixel(aircraft.x, aircraft.y, aircraft.ref_lat, aircraft.ref_lon)

    # Draw ships
    for ship in target_mgr.ships:
        px, py = feet_to_pixel(ship.x, ship.y, aircraft.ref_lat, aircraft.ref_lon)
        screen_x = int(WIDTH // 2 + (px - ac_px))
        screen_y = int(HEIGHT // 2 + (py - ac_py))

        if -100 < screen_x < WIDTH + 100 and -100 < screen_y < HEIGHT + 100:
            # Draw ship shape
            hdg_rad = math.radians(ship.heading)
            half_len = ship.length / MAP_SCALE_FT_PER_PIXEL / 2
            half_wid = ship.width / MAP_SCALE_FT_PER_PIXEL / 2

            # Ship corners
            cos_h, sin_h = math.cos(hdg_rad), math.sin(hdg_rad)
            points = [
                (screen_x + half_len * sin_h - half_wid * cos_h,
                 screen_y - half_len * cos_h - half_wid * sin_h),
                (screen_x + half_len * sin_h + half_wid * cos_h,
                 screen_y - half_len * cos_h + half_wid * sin_h),
                (screen_x - half_len * sin_h + half_wid * cos_h,
                 screen_y + half_len * cos_h + half_wid * sin_h),
                (screen_x - half_len * sin_h - half_wid * cos_h,
                 screen_y + half_len * cos_h - half_wid * sin_h),
            ]

            if ship.alive:
                color = (150, 150, 150) if ship.ship_type != 'carrier' else (180, 100, 100)
                pygame.draw.polygon(surface, color, points)
                if ship.burning:
                    pygame.draw.circle(surface, (255, 150, 0), (screen_x, screen_y), 5)
            else:
                pygame.draw.polygon(surface, (80, 80, 80), points)
                # Sinking animation
                pygame.draw.circle(surface, (100, 100, 150), (screen_x, screen_y), 8, 2)

    # Draw ground targets
    for target in target_mgr.ground_targets:
        px, py = feet_to_pixel(target.x, target.y, aircraft.ref_lat, aircraft.ref_lon)
        screen_x = int(WIDTH // 2 + (px - ac_px))
        screen_y = int(HEIGHT // 2 + (py - ac_py))

        if 0 < screen_x < WIDTH and 0 < screen_y < HEIGHT:
            radius = max(3, int(target.radius / MAP_SCALE_FT_PER_PIXEL))
            if target.alive:
                if target.ground_type == 'aa_gun':
                    color = (200, 50, 50)
                elif target.ground_type == 'fuel_tank':
                    color = (200, 150, 50)
                elif target.ground_type == 'hangar':
                    color = (150, 150, 100)
                else:
                    color = (120, 120, 120)
                pygame.draw.circle(surface, color, (screen_x, screen_y), radius)
                if target.burning:
                    pygame.draw.circle(surface, (255, 200, 0), (screen_x, screen_y), radius + 2, 2)
            else:
                pygame.draw.circle(surface, (50, 50, 50), (screen_x, screen_y), radius)

    # Draw enemy aircraft as small planform shapes
    for enemy in target_mgr.enemy_aircraft:
        px, py = feet_to_pixel(enemy.x, enemy.y, aircraft.ref_lat, aircraft.ref_lon)
        screen_x = int(WIDTH // 2 + (px - ac_px))
        screen_y = int(HEIGHT // 2 + (py - ac_py))

        if 0 < screen_x < WIDTH and 0 < screen_y < HEIGHT:
            if enemy.alive:
                hdg_rad = math.radians(enemy.heading)
                cos_h, sin_h = math.cos(hdg_rad), math.sin(hdg_rad)
                def er(px, py):
                    return (screen_x + px * cos_h - py * sin_h,
                            screen_y + px * sin_h + py * cos_h)
                if enemy.variant == 'bomber':
                    # G4M Betty - larger, twin-engine silhouette
                    body = [er(0, -10), er(2, 8), er(0, 12), er(-2, 8)]
                    wl = [er(-3, 0), er(-18, 3), er(-17, 5), er(-3, 3)]
                    wr = [er(3, 0), er(18, 3), er(17, 5), er(3, 3)]
                    pygame.draw.polygon(surface, (200, 80, 80), wl)
                    pygame.draw.polygon(surface, (200, 80, 80), wr)
                    pygame.draw.polygon(surface, (220, 60, 60), body)
                    # Engine nacelles
                    for ex_s in [-8, 8]:
                        ep = er(ex_s, 2)
                        pygame.draw.circle(surface, (180, 50, 50), (int(ep[0]), int(ep[1])), 2)
                else:
                    # A6M Zero - small fighter planform
                    body = [er(0, -8), er(3, 6), er(0, 9), er(-3, 6)]
                    wl = [er(-3, 0), er(-14, 2), er(-13, 4), er(-3, 3)]
                    wr = [er(3, 0), er(14, 2), er(13, 4), er(3, 3)]
                    pygame.draw.polygon(surface, (200, 80, 80), wl)
                    pygame.draw.polygon(surface, (200, 80, 80), wr)
                    pygame.draw.polygon(surface, (220, 60, 60), body)
                    # Rising sun roundels
                    for wx_s in [-8, 8]:
                        rp = er(wx_s, 2)
                        pygame.draw.circle(surface, (255, 40, 40), (int(rp[0]), int(rp[1])), 2)
                # Smoke if damaged
                if enemy.smoke_trail:
                    sp = er(0, -6)
                    pygame.draw.circle(surface, (120, 120, 120), (int(sp[0]), int(sp[1])), 3)
            else:
                # Crashing/crashed
                pygame.draw.circle(surface, (150, 50, 50), (screen_x, screen_y), 4)
                if enemy.z > 0:
                    pygame.draw.circle(surface, (100, 100, 100), (screen_x + 3, screen_y + 3), 3)


# ============== 3D ENEMY AIRCRAFT MODELS ==============
# Model coordinates: x=forward, y=right, z=up (feet from center of mass)

# A6M Zero - wingspan 39ft, length 30ft
ZERO_MODEL_PTS = [
    (15, 0, 0),       # 0: nose
    (-15, 0, 0),      # 1: tail
    (2, -19, 0.5),    # 2: left wingtip LE
    (-3, -17, 0.3),   # 3: left wingtip TE
    (2, 19, 0.5),     # 4: right wingtip LE
    (-3, 17, 0.3),    # 5: right wingtip TE
    (5, -3, 0),       # 6: left wing root LE
    (-4, -3, 0),      # 7: left wing root TE
    (5, 3, 0),        # 8: right wing root LE
    (-4, 3, 0),       # 9: right wing root TE
    (-13, 0, 5),      # 10: vertical tail top
    (-12, -7, 0),     # 11: left htail tip
    (-12, 7, 0),      # 12: right htail tip
    (3, 0, 1.5),      # 13: canopy top
]

ZERO_MODEL_LINES = [
    # Fuselage
    (0, 1, (60, 80, 50)),
    (0, 13, (60, 80, 50)),
    (13, 1, (60, 80, 50)),
    # Left wing
    (6, 2, (70, 90, 55)),
    (2, 3, (70, 90, 55)),
    (3, 7, (70, 90, 55)),
    # Right wing
    (8, 4, (70, 90, 55)),
    (4, 5, (70, 90, 55)),
    (5, 9, (70, 90, 55)),
    # Vertical tail
    (1, 10, (50, 65, 40)),
    # Horizontal tail
    (11, 1, (50, 65, 40)),
    (1, 12, (50, 65, 40)),
]

ZERO_MODEL_POLYS = [
    # Wing fill (left): root LE, tip LE, tip TE, root TE
    ([6, 2, 3, 7], (65, 85, 50)),
    # Wing fill (right)
    ([8, 4, 5, 9], (65, 85, 50)),
    # Htail fill
    ([11, 1, 12], (55, 70, 45)),
]

# G4M Betty bomber - wingspan 82ft, length 65ft
BETTY_MODEL_PTS = [
    (32, 0, 0),       # 0: nose
    (-32, 0, 0),      # 1: tail
    (2, -40, 0),      # 2: left wingtip LE
    (-8, -38, 0),     # 3: left wingtip TE
    (2, 40, 0),       # 4: right wingtip LE
    (-8, 38, 0),      # 5: right wingtip TE
    (8, -5, 0),       # 6: left wing root LE
    (-6, -5, 0),      # 7: left wing root TE
    (8, 5, 0),        # 8: right wing root LE
    (-6, 5, 0),       # 9: right wing root TE
    (-28, 0, 7),      # 10: vertical tail top
    (-27, -10, 0),    # 11: left htail tip
    (-27, 10, 0),     # 12: right htail tip
    (5, -14, -1),     # 13: left engine nacelle
    (5, 14, -1),      # 14: right engine nacelle
]

BETTY_MODEL_LINES = [
    (0, 1, (80, 90, 65)),
    (6, 2, (85, 95, 70)),
    (2, 3, (85, 95, 70)),
    (3, 7, (85, 95, 70)),
    (8, 4, (85, 95, 70)),
    (4, 5, (85, 95, 70)),
    (5, 9, (85, 95, 70)),
    (1, 10, (65, 75, 50)),
    (11, 1, (65, 75, 50)),
    (1, 12, (65, 75, 50)),
    # Engine nacelles
    (6, 13, (70, 70, 60)),
    (8, 14, (70, 70, 60)),
]

BETTY_MODEL_POLYS = [
    ([6, 2, 3, 7], (75, 85, 60)),
    ([8, 4, 5, 9], (75, 85, 60)),
    ([11, 1, 12], (60, 70, 48)),
]


def _project_model_3d(model_pts, obj_x, obj_y, obj_z, obj_hdg, obj_pitch, obj_roll,
                       cam_x, cam_y, cam_z, cam_hdg, focal, cx, cy):
    """Transform 3D model points to screen coordinates.
    Returns list of (sx, sy) or None for points behind camera."""
    # Enemy rotation trig
    h = math.radians(obj_hdg)
    p = math.radians(obj_pitch)
    r = math.radians(obj_roll)
    sh, ch = math.sin(h), math.cos(h)
    sp, cp = math.sin(p), math.cos(p)
    sr, cr = math.sin(r), math.cos(r)

    # Camera rotation
    ch2 = math.cos(math.radians(cam_hdg))
    sh2 = math.sin(math.radians(cam_hdg))

    result = []
    for (mx, my, mz) in model_pts:
        # Rotate by heading (yaw around z)
        rx = mx * ch - my * sh
        ry = mx * sh + my * ch
        rz = mz

        # Rotate by pitch (around y-axis)
        rx2 = rx * cp + rz * sp
        ry2 = ry
        rz2 = -rx * sp + rz * cp

        # Rotate by roll (around x-axis)
        rx3 = rx2
        ry3 = ry2 * cr - rz2 * sr
        rz3 = ry2 * sr + rz2 * cr

        # Translate to world position
        wx = obj_x + rx3
        wy = obj_y + ry3
        wz = obj_z + rz3

        # Camera-relative
        dx = wx - cam_x
        dy = wy - cam_y
        dz = wz - cam_z

        # Rotate to camera space (heading only)
        forward = dx * sh2 + dy * ch2
        lateral = dx * ch2 - dy * sh2

        if forward < 20:
            result.append(None)
            continue

        scale = focal / forward
        sx = int(cx + lateral * scale)
        sy = int(cy - dz * scale)
        result.append((sx, sy))

    return result


def draw_enemy_aircraft_3d(surface, enemy, aircraft, cx, cy):
    """Draw a single enemy aircraft as a 3D wireframe/polygon model"""
    dx = enemy.x - aircraft.x
    dy = enemy.y - aircraft.y
    dz = enemy.z - aircraft.z

    hdg_rad = math.radians(aircraft.heading)
    forward = dx * math.sin(hdg_rad) + dy * math.cos(hdg_rad)

    if forward < 50:
        return  # Behind camera

    dist_3d = math.sqrt(dx*dx + dy*dy + dz*dz)

    # At very long range (>8000 ft), just draw a dot
    if dist_3d > 8000:
        lateral = dx * math.cos(hdg_rad) - dy * math.sin(hdg_rad)
        scale = 400 / max(forward, 100)
        sx = int(cx + lateral * scale)
        sy = int(cy - dz * scale)
        if 80 < sx < WIDTH - 80 and 0 < sy < HEIGHT - 100:
            color = (200, 50, 50) if enemy.alive else (100, 50, 50)
            pygame.draw.circle(surface, color, (sx, sy), max(2, int(4000 / dist_3d)))
            # Smoke trail for damaged
            if enemy.smoke_trail and enemy.alive:
                pygame.draw.circle(surface, (100, 100, 100),
                                   (sx + random.randint(-3, 3), sy + random.randint(-3, 3)),
                                   max(1, int(3000 / dist_3d)))
        return

    # Select model
    if enemy.variant == 'bomber':
        model_pts = BETTY_MODEL_PTS
        model_lines = BETTY_MODEL_LINES
        model_polys = BETTY_MODEL_POLYS
    else:
        model_pts = ZERO_MODEL_PTS
        model_lines = ZERO_MODEL_LINES
        model_polys = ZERO_MODEL_POLYS

    # Project all points
    focal = 400
    pts = _project_model_3d(model_pts,
                             enemy.x, enemy.y, enemy.z,
                             enemy.heading, enemy.pitch, enemy.roll,
                             aircraft.x, aircraft.y, aircraft.z,
                             aircraft.heading, focal, cx, cy)

    # Check if any points are visible
    visible = [p for p in pts if p is not None
               and 0 < p[0] < WIDTH and 0 < p[1] < HEIGHT - 100]
    if not visible:
        return

    # Determine line width from distance
    if dist_3d < 1000:
        lw = 3
    elif dist_3d < 3000:
        lw = 2
    else:
        lw = 1

    if not enemy.alive:
        # Dead aircraft - dark red, no fill
        for (i, j, _) in model_lines:
            if pts[i] and pts[j]:
                pygame.draw.line(surface, (120, 40, 40), pts[i], pts[j], lw)
        # Smoke puff
        if enemy.z > 0 and visible:
            avg_x = sum(p[0] for p in visible) // len(visible)
            avg_y = sum(p[1] for p in visible) // len(visible)
            for _ in range(3):
                pygame.draw.circle(surface, (80, 80, 80),
                    (avg_x + random.randint(-8, 8), avg_y + random.randint(-8, 8)),
                    random.randint(2, 5))
        return

    # Draw filled polygons first (behind wireframe)
    for (indices, color) in model_polys:
        poly_pts = [pts[i] for i in indices]
        if all(p is not None for p in poly_pts):
            try:
                pygame.draw.polygon(surface, color, poly_pts)
            except Exception:
                pass

    # Draw wireframe lines on top
    for (i, j, color) in model_lines:
        if pts[i] and pts[j]:
            pygame.draw.line(surface, color, pts[i], pts[j], lw)

    # Rising sun hinomaru on wings — scale from actual projected wing span
    if dist_3d < 3000:
        # Left wing
        if pts[2] and pts[6]:
            wcx = (pts[2][0] + pts[6][0]) // 2
            wcy = (pts[2][1] + pts[6][1]) // 2
            # Radius = ~15% of projected wing half-span
            wing_span_px = math.sqrt((pts[2][0]-pts[6][0])**2 + (pts[2][1]-pts[6][1])**2)
            r_size = max(2, int(wing_span_px * 0.15))
            pygame.draw.circle(surface, (200, 30, 30), (wcx, wcy), r_size)
        # Right wing
        if pts[4] and pts[8]:
            wcx = (pts[4][0] + pts[8][0]) // 2
            wcy = (pts[4][1] + pts[8][1]) // 2
            wing_span_px = math.sqrt((pts[4][0]-pts[8][0])**2 + (pts[4][1]-pts[8][1])**2)
            r_size = max(2, int(wing_span_px * 0.15))
            pygame.draw.circle(surface, (200, 30, 30), (wcx, wcy), r_size)

    # Smoke trail for damaged aircraft
    if enemy.smoke_trail:
        if pts[1]:  # Tail position
            for _ in range(2):
                pygame.draw.circle(surface, (100, 100, 100),
                    (pts[1][0] + random.randint(-5, 5), pts[1][1] + random.randint(-5, 5)),
                    random.randint(2, 4))

    # Muzzle flash when firing
    if enemy.firing and pts[0]:
        pygame.draw.circle(surface, (255, 255, 100), pts[0], max(2, int(5 * 400 / dist_3d)))


def draw_targets_cockpit(surface, target_mgr, aircraft):
    """Draw targets visible from cockpit"""
    cx, cy = WIDTH // 2, HEIGHT // 2

    # Draw enemy aircraft with 3D models
    for enemy in target_mgr.enemy_aircraft:
        draw_enemy_aircraft_3d(surface, enemy, aircraft, cx, cy)

    # Draw ships (visible from reasonable altitude)
    if aircraft.z < 15000:
        for ship in target_mgr.ships:
            dx = ship.x - aircraft.x
            dy = ship.y - aircraft.y
            dz = -aircraft.z  # Ships at sea level

            hdg_rad = math.radians(aircraft.heading)
            forward = dx * math.sin(hdg_rad) + dy * math.cos(hdg_rad)
            lateral = dx * math.cos(hdg_rad) - dy * math.sin(hdg_rad)

            if 500 < forward < 30000:
                scale = 400 / max(forward, 500)
                screen_x = int(cx + lateral * scale)
                screen_y = int(cy - dz * scale)

                if 80 < screen_x < WIDTH - 80 and HEIGHT // 2 < screen_y < HEIGHT - 100:
                    # Ship silhouette
                    ship_w = max(4, int(ship.length * scale / 10))
                    ship_h = max(2, int(ship.width * scale / 10))
                    if ship.alive:
                        color = (120, 120, 120)
                        pygame.draw.ellipse(surface, color,
                                          (screen_x - ship_w // 2, screen_y - ship_h // 2, ship_w, ship_h))
                        if ship.burning:
                            pygame.draw.circle(surface, (255, 150, 50), (screen_x, screen_y - 2), 3)


def draw_wingmen_3d(surface, wingmen, aircraft):
    """Draw friendly wingmen in cockpit/chase 3D view."""
    cx, cy = WIDTH // 2, HEIGHT // 2
    hdg_rad = math.radians(aircraft.heading)

    for wm in wingmen:
        if not wm.alive and wm.z <= 0:
            continue

        dx = wm.x - aircraft.x
        dy = wm.y - aircraft.y
        dz = wm.z - aircraft.z

        forward = dx * math.sin(hdg_rad) + dy * math.cos(hdg_rad)
        lateral = dx * math.cos(hdg_rad) - dy * math.sin(hdg_rad)

        if forward < 20:
            continue  # Behind camera

        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        focal = 400
        scale = focal / max(forward, 50)
        sx = int(cx + lateral * scale)
        sy = int(cy - dz * scale)

        if not (0 < sx < WIDTH and 0 < sy < HEIGHT):
            continue

        is_bomber = isinstance(wm, FriendlyBomber)

        if is_bomber:
            # B-17 Flying Fortress — olive drab, much larger
            OD = (80, 90, 60)
            OD_L = (100, 110, 75)
        else:
            # F6F Hellcat wingman — navy blue
            OD = (40, 55, 100)
            OD_L = (55, 75, 125)

        if dist > 8000:
            pygame.draw.circle(surface, OD_L, (sx, sy), max(2, int(4000 / dist)))
            continue

        # Scale based on distance — bombers are ~2.5x bigger than fighters
        size_mult = 2.5 if is_bomber else 1.0
        ws = max(2, int(20 * scale * size_mult))

        # Wings
        lw = max(1, ws // 5)
        pygame.draw.line(surface, OD_L, (sx - ws, sy + int(ws*0.05)),
                         (sx + ws, sy + int(ws*0.05)), lw)
        # Fuselage
        fl = max(2, int(ws * 0.8))
        pygame.draw.line(surface, OD, (sx, sy - fl), (sx, sy + fl), max(1, ws // 7))
        # Horizontal tail
        tw = max(1, ws // 3)
        pygame.draw.line(surface, OD, (sx - tw, sy - fl + 2), (sx + tw, sy - fl + 2), 1)
        # Vertical tail
        pygame.draw.line(surface, OD, (sx, sy - fl), (sx, sy - fl - max(1, tw // 2)), 1)

        if is_bomber:
            # B-17: 4 engines (dots on wings)
            for eng_x in [-ws*0.6, -ws*0.3, ws*0.3, ws*0.6]:
                ex = int(sx + eng_x)
                pygame.draw.circle(surface, (60, 60, 60), (ex, sy + 2), max(1, lw))

        # Engine exhaust
        if wm.speed > 150:
            pygame.draw.circle(surface, (150, 150, 200), (sx, sy + fl + 2), max(1, ws // 8))

        # Smoke trail if damaged
        is_smoking = getattr(wm, 'smoke_trail', False) or getattr(wm, 'smoking', False)
        if is_smoking:
            pygame.draw.circle(surface, (120, 120, 120),
                               (sx + random.randint(-3, 3), sy - fl - random.randint(2, 6)),
                               max(1, int(2000 / dist)))
        # Fire effect for bombers
        if getattr(wm, 'on_fire', False):
            pygame.draw.circle(surface, (255, 100, 30),
                               (sx + random.randint(-2, 2), sy + random.randint(-3, 3)),
                               max(2, int(3000 / dist)))

        # Muzzle flash when firing
        if wm.firing:
            pygame.draw.circle(surface, (255, 255, 100), (sx, sy + fl + 1),
                               max(2, int(4 * scale)))

        # Green IFF marker above
        if dist < 4000:
            marker_y = sy - fl - max(3, int(8 * scale))
            pygame.draw.circle(surface, HUD_GREEN, (sx, marker_y), 3)


def draw_score_display(surface, target_mgr):
    """Draw score and kills"""
    x_pos = WIDTH - 200
    y_pos = 10

    # Background
    pygame.draw.rect(surface, (0, 0, 0, 150), (x_pos - 5, y_pos - 5, 195, 75))
    pygame.draw.rect(surface, HUD_GREEN, (x_pos - 5, y_pos - 5, 195, 75), 1)

    # Score
    score_text = font_med.render(f"SCORE: {target_mgr.score}", True, HUD_GREEN)
    surface.blit(score_text, (x_pos, y_pos))

    # Kills
    kills_text = font_tiny.render(
        f"Ships: {target_mgr.kills['ship']}  Ground: {target_mgr.kills['ground']}  Air: {target_mgr.kills['aircraft']}",
        True, WHITE)
    surface.blit(kills_text, (x_pos, y_pos + 30))

    # Targets remaining
    ships_left = sum(1 for s in target_mgr.ships if s.alive)
    ground_left = sum(1 for t in target_mgr.ground_targets if t.alive)
    air_left = sum(1 for e in target_mgr.enemy_aircraft if e.alive)
    remain_text = font_tiny.render(f"Remaining: {ships_left}S {ground_left}G {air_left}A", True, HUD_AMBER)
    surface.blit(remain_text, (x_pos, y_pos + 50))


def draw_map_view(surface, aircraft, map_img):
    px, py = feet_to_pixel(aircraft.x, aircraft.y, aircraft.ref_lat, aircraft.ref_lon)
    view_x = int(px - WIDTH // 2)
    view_y = int(py - HEIGHT // 2)

    _map_surface.fill((0, 50, 100))

    src_rect = pygame.Rect(view_x, view_y, WIDTH, HEIGHT)
    dest_x, dest_y = 0, 0

    if view_x < 0:
        dest_x = -view_x
        src_rect.x = 0
        src_rect.width = WIDTH + view_x
    if view_y < 0:
        dest_y = -view_y
        src_rect.y = 0
        src_rect.height = HEIGHT + view_y
    if src_rect.right > MAP_WIDTH:
        src_rect.width = MAP_WIDTH - src_rect.x
    if src_rect.bottom > MAP_HEIGHT:
        src_rect.height = MAP_HEIGHT - src_rect.y

    if src_rect.width > 0 and src_rect.height > 0:
        visible = map_img.subsurface(src_rect.clip(map_img.get_rect()))
        _map_surface.blit(visible, (dest_x, dest_y))

    alt_factor = min(1.0, aircraft.z / 20000)
    _haze_surface.fill((200, 220, 255, int(80 * alt_factor)))
    _map_surface.blit(_haze_surface, (0, 0))

    surface.blit(_map_surface, (0, 0))


def draw_friendly_carrier(surface, carrier, aircraft):
    """Draw friendly carrier on overhead map"""
    ac_px, ac_py = feet_to_pixel(aircraft.x, aircraft.y, aircraft.ref_lat, aircraft.ref_lon)
    cx, cy = feet_to_pixel(carrier.x, carrier.y, aircraft.ref_lat, aircraft.ref_lon)
    screen_x = int(WIDTH // 2 + (cx - ac_px))
    screen_y = int(HEIGHT // 2 + (cy - ac_py))

    if -200 < screen_x < WIDTH + 200 and -200 < screen_y < HEIGHT + 200:
        hdg_rad = math.radians(carrier.heading)
        half_l = carrier.LENGTH / MAP_SCALE_FT_PER_PIXEL / 2
        half_w = carrier.WIDTH / MAP_SCALE_FT_PER_PIXEL / 2
        cos_h, sin_h = math.cos(hdg_rad), math.sin(hdg_rad)

        points = [
            (screen_x + half_l * sin_h - half_w * cos_h,
             screen_y - half_l * cos_h - half_w * sin_h),
            (screen_x + half_l * sin_h + half_w * cos_h,
             screen_y - half_l * cos_h + half_w * sin_h),
            (screen_x - half_l * sin_h + half_w * cos_h,
             screen_y + half_l * cos_h + half_w * sin_h),
            (screen_x - half_l * sin_h - half_w * cos_h,
             screen_y + half_l * cos_h - half_w * sin_h),
        ]
        pygame.draw.polygon(surface, (80, 120, 80), points)
        pygame.draw.polygon(surface, HUD_GREEN, points, 2)

        # Label
        label = font_tiny.render("CV", True, HUD_GREEN)
        surface.blit(label, (screen_x - 8, screen_y - 8))


def draw_aircraft_symbol(surface, aircraft):
    """Draw player aircraft planform (top-down) on overhead map"""
    cx, cy = WIDTH // 2, HEIGHT // 2
    hdg_rad = math.radians(aircraft.heading)
    cos_h, sin_h = math.cos(hdg_rad), math.sin(hdg_rad)

    def rot(px, py):
        return (cx + px * cos_h - py * sin_h, cy + px * sin_h + py * cos_h)

    if isinstance(aircraft, Boeing747_200) or isinstance(aircraft, DisasterAircraft):
        # 747 planform (top view) - swept wings, 4 engines
        body = [rot(0, -30), rot(4, -25), rot(5, 25), rot(3, 35), rot(0, 38),
                rot(-3, 35), rot(-5, 25), rot(-4, -25)]
        wing_l = [rot(-5, -2), rot(-35, 8), rot(-33, 12), rot(-5, 5)]
        wing_r = [rot(5, -2), rot(35, 8), rot(33, 12), rot(5, 5)]
        stab_l = [rot(-3, -25), rot(-14, -22), rot(-13, -19), rot(-3, -22)]
        stab_r = [rot(3, -25), rot(14, -22), rot(13, -19), rot(3, -22)]
        vtail = [rot(0, -25), rot(1, -32), rot(-1, -32)]
        pygame.draw.polygon(surface, (200, 200, 205), wing_l)
        pygame.draw.polygon(surface, (200, 200, 205), wing_r)
        pygame.draw.polygon(surface, (220, 220, 225), body)
        pygame.draw.polygon(surface, (200, 200, 205), stab_l)
        pygame.draw.polygon(surface, (200, 200, 205), stab_r)
        pygame.draw.polygon(surface, (200, 200, 205), vtail)
        pygame.draw.polygon(surface, (120, 120, 120), body, 2)
        # Red stripe
        pygame.draw.line(surface, (200, 50, 50), rot(-5, 0), rot(5, 0), 2)
    else:
        # F6F Hellcat planform (top view) - wide straight wings, round cowl
        body = [rot(0, -28), rot(4, -22), rot(5, 20), rot(3, 28), rot(0, 30),
                rot(-3, 28), rot(-5, 20), rot(-4, -22)]
        wing_l = [rot(-5, 0), rot(-28, 4), rot(-27, 8), rot(-5, 5)]
        wing_r = [rot(5, 0), rot(28, 4), rot(27, 8), rot(5, 5)]
        stab_l = [rot(-3, -22), rot(-12, -19), rot(-11, -17), rot(-3, -19)]
        stab_r = [rot(3, -22), rot(12, -19), rot(11, -17), rot(3, -19)]
        vtail = [rot(0, -22), rot(1, -28), rot(-1, -28)]
        pygame.draw.polygon(surface, (55, 75, 120), wing_l)
        pygame.draw.polygon(surface, (55, 75, 120), wing_r)
        pygame.draw.polygon(surface, (45, 60, 105), body)
        pygame.draw.polygon(surface, (55, 75, 120), stab_l)
        pygame.draw.polygon(surface, (55, 75, 120), stab_r)
        pygame.draw.polygon(surface, (55, 75, 120), vtail)
        pygame.draw.polygon(surface, (25, 40, 75), body, 2)
        # Wing star insignia (tiny)
        for wx_s in [-1, 1]:
            sp = rot(wx_s * 16, 3)
            pygame.draw.circle(surface, WHITE, (int(sp[0]), int(sp[1])), 3)
        # Prop disc
        pp = rot(0, 30)
        pygame.draw.circle(surface, (100, 100, 100), (int(pp[0]), int(pp[1])), 5, 1)


def draw_attitude_indicator(surface, x, y, pitch, roll, size=140):
    pygame.draw.circle(surface, BLACK, (x, y), size + 5)

    # Build sky/ground scene on a temp surface (replaces ~78k set_at calls)
    buf = int(size * 2.8)
    scene = pygame.Surface((buf, buf))
    half = buf // 2
    pitch_px = int(pitch * 3)
    horizon_y = half + pitch_px

    # Sky fill
    scene.fill((100, 150, 220))
    # Ground fill
    if horizon_y < buf:
        pygame.draw.rect(scene, (139, 90, 43), (0, max(0, horizon_y), buf, buf))
    if horizon_y <= 0:
        scene.fill((139, 90, 43))
    # Horizon line
    if 0 < horizon_y < buf:
        pygame.draw.line(scene, WHITE, (0, horizon_y), (buf, horizon_y), 2)
    # Pitch ladder marks
    for p in [-20, -10, -5, 5, 10, 20]:
        my = horizon_y - p * 3
        ml = 25 if abs(p) >= 10 else 12
        if 0 < my < buf:
            pygame.draw.line(scene, WHITE, (half - ml, my), (half + ml, my), 1)

    # Rotate by roll angle
    rotated = pygame.transform.rotate(scene, roll)

    # Crop center to diameter x diameter
    diam = size * 2
    rr = rotated.get_rect()
    crop_x = rr.centerx - size
    crop_y = rr.centery - size
    cropped = pygame.Surface((diam, diam))
    cropped.blit(rotated, (0, 0), area=pygame.Rect(crop_x, crop_y, diam, diam))

    # Clip to circle using cached colorkey mask
    cropped.blit(_get_ai_mask(size), (0, 0))
    cropped.set_colorkey((1, 1, 1))

    surface.blit(cropped, (x - size, y - size))

    # Fixed aircraft reference and bezel
    pygame.draw.line(surface, HUD_AMBER, (x - 50, y), (x - 20, y), 4)
    pygame.draw.line(surface, HUD_AMBER, (x + 20, y), (x + 50, y), 4)
    pygame.draw.circle(surface, HUD_AMBER, (x, y), 6, 3)
    pygame.draw.circle(surface, (100, 100, 100), (x, y), size, 4)


def draw_radar(surface, aircraft, target_mgr, cx, cy, radius=50, carrier=None, friendlies=None):
    """Draw circular radar scope showing targets relative to player"""
    _radar_friendlies = friendlies or []
    if not hasattr(aircraft, 'radar_range'):
        return

    range_ft = aircraft.radar_range * 6076.12  # nm to feet
    hdg_rad = math.radians(aircraft.heading)
    sin_h, cos_h = math.sin(hdg_rad), math.cos(hdg_rad)

    # Radar background
    pygame.draw.circle(surface, (0, 20, 0), (cx, cy), radius + 2)
    pygame.draw.circle(surface, (0, 40, 0), (cx, cy), radius)

    # Range rings
    for ring in [0.33, 0.66]:
        pygame.draw.circle(surface, (0, 60, 0), (cx, cy), int(radius * ring), 1)

    # Crosshairs
    pygame.draw.line(surface, (0, 60, 0), (cx, cy - radius), (cx, cy + radius), 1)
    pygame.draw.line(surface, (0, 60, 0), (cx - radius, cy), (cx + radius, cy), 1)

    # Player blip (center)
    pygame.draw.rect(surface, HUD_GREEN, (cx - 2, cy - 2, 4, 4))

    # Plot targets
    def plot_blip(tx, ty, color, size=2):
        dx = tx - aircraft.x
        dy = ty - aircraft.y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist > range_ft:
            return
        # Rotate to aircraft-relative (forward = up on scope)
        rel_x = (dx * cos_h - dy * sin_h) / range_ft * radius
        rel_y = -(dx * sin_h + dy * cos_h) / range_ft * radius
        sx = int(cx + rel_x)
        sy = int(cy + rel_y)
        if (sx - cx)**2 + (sy - cy)**2 <= radius * radius:
            pygame.draw.rect(surface, color, (sx - size, sy - size, size * 2, size * 2))

    # Enemy aircraft (red)
    for enemy in target_mgr.enemy_aircraft:
        if enemy.alive:
            plot_blip(enemy.x, enemy.y, HUD_RED, 2)

    # Ships (yellow for enemy)
    for ship in target_mgr.ships:
        if ship.alive:
            plot_blip(ship.x, ship.y, HUD_AMBER, 3)

    # Ground targets (dim red)
    for tgt in target_mgr.ground_targets:
        if tgt.alive:
            plot_blip(tgt.x, tgt.y, (150, 50, 50), 2)

    # Friendly carrier (bright green blip)
    if carrier:
        plot_blip(carrier.x, carrier.y, HUD_GREEN, 4)

    # Friendly wingmen (green, smaller than carrier)
    for wm in _radar_friendlies:
        if wm.alive:
            plot_blip(wm.x, wm.y, HUD_GREEN, 2)

    # Radar bezel and labels
    pygame.draw.circle(surface, (0, 100, 0), (cx, cy), radius, 2)
    range_label = font_tiny.render(f"{aircraft.radar_range}nm", True, HUD_GREEN)
    surface.blit(range_label, (cx - 12, cy + radius + 3))
    radar_title = font_tiny.render("RADAR", True, HUD_GREEN)
    surface.blit(radar_title, (cx - 18, cy - radius - 16))


def draw_instruments(surface, aircraft, status):
    surface.blit(_panel_surface, (0, HEIGHT - 250))

    panel_y = HEIGHT - 240

    # Title
    title = font_large.render(aircraft.NAME, True, HUD_GREEN)
    surface.blit(title, (20, panel_y))

    status_color = HUD_GREEN
    if "STALL" in status or "OVERSPEED" in status or "CRASH" in status:
        status_color = HUD_RED

    status_text = font_med.render(status, True, status_color)
    surface.blit(status_text, (20, panel_y + 45))

    # Airspeed gauge
    ias = aircraft.get_airspeed_kts()
    spd_color = HUD_GREEN
    stall_spd = aircraft.STALL_SPEED_FLAPS if aircraft.flaps else aircraft.STALL_SPEED_CLEAN
    if ias < stall_spd + 10 or ias > aircraft.VNE:
        spd_color = HUD_RED

    spd_cx, spd_cy = 75, panel_y + 140
    spd_radius = 55
    pygame.draw.circle(surface, (30, 30, 30), (spd_cx, spd_cy), spd_radius + 3)
    pygame.draw.circle(surface, (50, 50, 50), (spd_cx, spd_cy), spd_radius)

    max_spd = 450 if isinstance(aircraft, Boeing747_200) else 400
    for spd_mark in range(0, max_spd + 50, 50):
        angle = math.radians(225 - (spd_mark / max_spd) * 270)
        inner_r, outer_r = spd_radius - 10, spd_radius - 3
        x1 = spd_cx + inner_r * math.cos(angle)
        y1 = spd_cy - inner_r * math.sin(angle)
        x2 = spd_cx + outer_r * math.cos(angle)
        y2 = spd_cy - outer_r * math.sin(angle)
        pygame.draw.line(surface, WHITE, (x1, y1), (x2, y2), 2)

    needle_angle = math.radians(225 - (min(ias, max_spd) / max_spd) * 270)
    needle_len = spd_radius - 15
    nx = spd_cx + needle_len * math.cos(needle_angle)
    ny = spd_cy - needle_len * math.sin(needle_angle)
    pygame.draw.line(surface, spd_color, (spd_cx, spd_cy), (nx, ny), 3)
    pygame.draw.circle(surface, spd_color, (spd_cx, spd_cy), 5)

    spd_text = font_med.render(f"{int(ias)}", True, spd_color)
    surface.blit(spd_text, (spd_cx - 20, spd_cy + 15))
    spd_label = font_tiny.render("KNOTS", True, HUD_GREEN)
    surface.blit(spd_label, (spd_cx - 22, spd_cy + 38))

    # Altitude
    alt = aircraft.z
    pygame.draw.rect(surface, (40, 40, 40), (145, panel_y + 85, 100, 140))
    alt_text = font_large.render(f"{int(alt)}", True, HUD_GREEN)
    surface.blit(alt_text, (150, panel_y + 130))
    alt_label = font_tiny.render("FT MSL", True, HUD_GREEN)
    surface.blit(alt_label, (170, panel_y + 180))

    # Heading
    hdg = int(aircraft.heading)
    pygame.draw.rect(surface, (40, 40, 40), (255, panel_y + 85, 80, 140))
    hdg_text = font_large.render(f"{hdg:03d}", True, HUD_GREEN)
    surface.blit(hdg_text, (260, panel_y + 130))
    hdg_label = font_tiny.render("HDG", True, HUD_GREEN)
    surface.blit(hdg_label, (280, panel_y + 180))

    # VSI gauge
    vsi = aircraft.get_vertical_speed()
    vsi_color = HUD_GREEN if vsi >= 0 else HUD_AMBER
    if vsi < -2000:
        vsi_color = HUD_RED

    vsi_cx, vsi_cy = 400, panel_y + 140
    vsi_radius = 55
    pygame.draw.circle(surface, (30, 30, 30), (vsi_cx, vsi_cy), vsi_radius + 3)
    pygame.draw.circle(surface, (50, 50, 50), (vsi_cx, vsi_cy), vsi_radius)

    vsi_range = 6000 if isinstance(aircraft, Boeing747_200) else 4000
    for fpm_mark in range(-vsi_range, vsi_range + 1000, 1000):
        angle = math.radians(90 - (fpm_mark / vsi_range) * 90)
        inner_r, outer_r = vsi_radius - 10, vsi_radius - 3
        x1 = vsi_cx + inner_r * math.cos(angle)
        y1 = vsi_cy - inner_r * math.sin(angle)
        x2 = vsi_cx + outer_r * math.cos(angle)
        y2 = vsi_cy - outer_r * math.sin(angle)
        pygame.draw.line(surface, WHITE, (x1, y1), (x2, y2), 2)

    vsi_clamped = max(-vsi_range, min(vsi_range, vsi))
    vsi_angle = math.radians(90 - (vsi_clamped / vsi_range) * 90)
    needle_len = vsi_radius - 15
    nx = vsi_cx + needle_len * math.cos(vsi_angle)
    ny = vsi_cy - needle_len * math.sin(vsi_angle)
    pygame.draw.line(surface, vsi_color, (vsi_cx, vsi_cy), (nx, ny), 3)
    pygame.draw.circle(surface, vsi_color, (vsi_cx, vsi_cy), 5)

    vsi_text = font_small.render(f"{int(vsi):+d}", True, vsi_color)
    surface.blit(vsi_text, (vsi_cx - 25, vsi_cy + 20))

    # Attitude indicator
    draw_attitude_indicator(surface, 540, panel_y + 130, aircraft.pitch, aircraft.roll, 90)

    # Throttle
    pygame.draw.rect(surface, (40, 40, 40), (660, panel_y + 85, 30, 140))
    thr_height = int(130 * aircraft.throttle)
    pygame.draw.rect(surface, HUD_GREEN, (665, panel_y + 220 - thr_height, 20, thr_height))
    thr_label = font_tiny.render(f"{int(aircraft.throttle*100)}%", True, HUD_GREEN)
    surface.blit(thr_label, (655, panel_y + 65))

    # AoA and G
    aoa_color = HUD_RED if abs(aircraft.aoa) > 12 else (HUD_AMBER if abs(aircraft.aoa) > 8 else HUD_GREEN)
    aoa_text = font_med.render(f"AoA: {aircraft.aoa:.1f}°", True, aoa_color)
    surface.blit(aoa_text, (720, panel_y + 85))

    g_load = aircraft.get_load_factor()
    g_color = HUD_RED if g_load > 4 or g_load < 0 else HUD_GREEN
    g_text = font_med.render(f"G: {g_load:.1f}", True, g_color)
    surface.blit(g_text, (720, panel_y + 115))

    if hasattr(aircraft, 'lift_deficit') and aircraft.lift_deficit:
        lift_warn = font_small.render("LIFT < WEIGHT!", True, HUD_RED)
        surface.blit(lift_warn, (720, panel_y + 145))

    # Flaps/Gear status with clear indication
    flap_color = HUD_GREEN if aircraft.flaps else (100, 100, 100)
    gear_color = HUD_GREEN if aircraft.gear_down else (100, 100, 100)

    pygame.draw.rect(surface, (40, 40, 40), (870, panel_y + 75, 120, 60))
    flap_text = font_med.render("FLAPS", True, flap_color)
    surface.blit(flap_text, (880, panel_y + 80))
    flap_status = font_small.render("DOWN" if aircraft.flaps else "UP", True, flap_color)
    surface.blit(flap_status, (880, panel_y + 105))

    pygame.draw.rect(surface, (40, 40, 40), (1000, panel_y + 75, 120, 60))
    gear_text = font_med.render("GEAR", True, gear_color)
    surface.blit(gear_text, (1010, panel_y + 80))
    gear_status = font_small.render("DOWN" if aircraft.gear_down else "UP", True, gear_color)
    surface.blit(gear_status, (1010, panel_y + 105))

    # Damage indicators (Hellcat only)
    if hasattr(aircraft, 'dmg_engine'):
        dmg_x = 870
        dmg_y = panel_y + 140
        components = [
            ('ENG', aircraft.dmg_engine), ('AIL', aircraft.dmg_aileron),
            ('ELV', aircraft.dmg_elevator), ('RUD', aircraft.dmg_rudder),
            ('FLP', aircraft.dmg_flaps), ('GER', aircraft.dmg_gear),
            ('FUL', aircraft.dmg_fuel), ('PLT', aircraft.dmg_pilot),
        ]
        for i, (name, dmg) in enumerate(components):
            x = dmg_x + (i % 4) * 62
            y = dmg_y + (i // 4) * 16
            if dmg > 0.7:
                color = HUD_RED
            elif dmg > 0.3:
                color = HUD_AMBER
            elif dmg > 0:
                color = (200, 200, 0)
            else:
                color = (60, 60, 60)
            label = font_tiny.render(f"{name}", True, color)
            surface.blit(label, (x, y))

    # Drag modifier
    pygame.draw.rect(surface, (80, 20, 20), (870, panel_y + 145, 250, 45))
    drag_text = font_med.render(f"CD MULT: {aircraft.drag_modifier:.2f}x", True, HUD_AMBER)
    surface.blit(drag_text, (880, panel_y + 155))

    # Controls
    controls = "W/S: Pitch | A/D: Roll | Q/E: Yaw | SHIFT/CTRL: Throttle | F: Flaps | G: Gear | [/]: Drag"
    ctrl_text = font_tiny.render(controls, True, (150, 150, 150))
    surface.blit(ctrl_text, (20, panel_y + 220))

    # Menu hint
    menu_hint = font_tiny.render("M: Return to Menu | R: Reset", True, (120, 120, 120))
    surface.blit(menu_hint, (WIDTH - 250, panel_y + 220))


def draw_stall_warning(surface, aircraft, time_elapsed):
    if aircraft.stalled:
        if int(time_elapsed * 4) % 2:
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((255, 0, 0, 70))
            surface.blit(overlay, (0, 0))

        warn = font_large.render("** STALL - PUSH NOSE DOWN! **", True, HUD_RED)
        rect = warn.get_rect(center=(WIDTH // 2, 100))
        pygame.draw.rect(surface, BLACK, rect.inflate(20, 10))
        surface.blit(warn, rect)

        recovery = font_med.render("Press W to lower nose and regain airspeed", True, WHITE)
        rect2 = recovery.get_rect(center=(WIDTH // 2, 145))
        surface.blit(recovery, rect2)

    ias = aircraft.get_airspeed_kts()
    stall_spd = aircraft.STALL_SPEED_FLAPS if aircraft.flaps else aircraft.STALL_SPEED_CLEAN
    if ias < stall_spd + 15 and not aircraft.stalled:
        warn_color = HUD_AMBER if ias > stall_spd + 5 else HUD_RED
        if int(time_elapsed * 3) % 2:
            low_spd = font_med.render(f"LOW AIRSPEED: {int(ias)} KTS", True, warn_color)
            rect = low_spd.get_rect(center=(WIDTH // 2, 80))
            surface.blit(low_spd, rect)


def draw_g_effects(surface, aircraft):
    """Draw blackout/redout/GLOC visual effects based on G-forces.
    Blackout (positive G): vision tunnels inward, goes grey then black.
    Redout (negative G): vision floods red from edges.
    GLOC: full black with warning text."""
    g_effect = getattr(aircraft, 'g_effect', 0.0)
    if g_effect <= 0.02:
        return

    g = aircraft.get_load_factor()
    is_redout = g < 0
    g_loc = getattr(aircraft, 'g_loc_timer', 0) > 0

    # Intensity (0..1 maps to subtle..total)
    intensity = min(1.0, g_effect)

    if g_loc:
        # Full GLOC: black screen with warning
        overlay = pygame.Surface((WIDTH, HEIGHT))
        overlay.fill((0, 0, 0))
        overlay.set_alpha(240)
        surface.blit(overlay, (0, 0))
        # Warning text
        warn = font_large.render("G-LOC", True, HUD_RED)
        rect = warn.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 30))
        surface.blit(warn, rect)
        sub = font_med.render("UNCONSCIOUS - Controls frozen", True, HUD_AMBER)
        rect2 = sub.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 20))
        surface.blit(sub, rect2)
        return

    if is_redout:
        # Redout: red flooding from edges, intensifying toward center
        alpha = int(180 * intensity)
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        # Red vignette - outer ring fully red, inner partially
        overlay.fill((200, 0, 0, alpha))
        # Clear center slightly for low intensity
        if intensity < 0.8:
            clear_r = int((1.0 - intensity) * min(WIDTH, HEIGHT) * 0.3)
            if clear_r > 20:
                inner_alpha = max(0, int(alpha * 0.4))
                pygame.draw.circle(overlay, (200, 0, 0, inner_alpha),
                                   (WIDTH // 2, HEIGHT // 2), clear_r)
        surface.blit(overlay, (0, 0))
        if intensity > 0.5:
            warn = font_med.render("REDOUT", True, (255, 100, 100))
            rect = warn.get_rect(center=(WIDTH // 2, 100))
            surface.blit(warn, rect)
    else:
        # Blackout: tunnel vision narrowing inward, grey -> black
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

        # Outer black vignette that closes in with intensity
        # At intensity 0.3: slight darkening at edges
        # At intensity 0.7: strong tunnel vision
        # At intensity 1.0: nearly all black
        edge_alpha = int(220 * intensity)
        overlay.fill((0, 0, 0, edge_alpha))

        # Tunnel vision: clear circle in center that shrinks with intensity
        if intensity < 0.95:
            # Circle radius shrinks from large to tiny as intensity grows
            max_r = int(min(WIDTH, HEIGHT) * 0.45)
            circle_r = int(max_r * (1.0 - intensity * 0.9))
            circle_r = max(10, circle_r)
            # Feathered edge: draw several concentric circles with decreasing alpha
            steps = 6
            for i in range(steps):
                r = circle_r + (max_r - circle_r) * i // steps
                a = max(0, edge_alpha - int(edge_alpha * (1 - i / steps)))
                pygame.draw.circle(overlay, (0, 0, 0, a),
                                   (WIDTH // 2, HEIGHT // 2), r)
            # Clear the inner circle
            pygame.draw.circle(overlay, (0, 0, 0, 0),
                               (WIDTH // 2, HEIGHT // 2), circle_r)

        surface.blit(overlay, (0, 0))

        # Grey tint increases with intensity (greyout before blackout)
        if intensity > 0.2:
            grey_alpha = int(80 * min(1.0, (intensity - 0.2) / 0.5))
            grey = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            grey.fill((128, 128, 128, grey_alpha))
            surface.blit(grey, (0, 0))

        if intensity > 0.5:
            warn = font_med.render("BLACKOUT", True, (180, 180, 180))
            rect = warn.get_rect(center=(WIDTH // 2, 100))
            surface.blit(warn, rect)


# ============== MAIN PROGRAM ==============
def main():
    aircraft_list = [F6F_Hellcat, Boeing747_200]
    mission_list = MISSIONS
    disaster_list = DISASTER_SCENARIOS

    current_menu = 0  # 0 = Free Flight, 1 = Missions, 2 = Disaster Recreations, 3 = Campaign
    selected_index = 0

    game_state = "MENU"  # MENU, BRIEFING, FLYING, TAKEOFF, CAMPAIGN, DOSSIER
    aircraft = None
    active_scenario = None
    active_mission = None
    pilot_dossier = PilotDossier()
    show_dossier = False
    status = "FLYING"
    crashed = False
    time_elapsed = 0
    disaster_triggered = False

    # Flight data recorder for plots
    fdr = FlightDataRecorder(max_samples=600)

    # Weapons manager
    weapons_mgr = WeaponsManager()

    # Target manager (initialized with Hellcat start position)
    target_mgr = TargetManager(40.7288, -73.4134)

    # Friendly carrier (positioned south of start, heading north)
    friendly_carrier = FriendlyCarrier(0, -5000, heading=0)

    # New systems
    sound_mgr = SoundManager()
    wingmen = []  # Populated when flying Hellcat
    input_recorder = InputRecorder()
    weather = Weather(Weather.CLEAR)
    time_of_day = TimeOfDay(TimeOfDay.DAY)
    radio = RadioChatter()
    campaign = Campaign()

    # Carrier takeoff state
    takeoff_throttle_held = 0.0  # seconds throttle held at full for deck launch
    takeoff_roll_dist = 0.0      # feet rolled down deck

    # Camera view
    camera_view = CAMERA_OVERHEAD

    running = True
    while running:
        clock.tick(60)
        dt = PHYSICS_DT  # Fixed timestep for deterministic replay
        time_elapsed += dt

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if game_state in ("FLYING", "TAKEOFF"):
                        game_state = "MENU"
                        aircraft = None
                        active_scenario = None
                        disaster_triggered = False
                        weapons_mgr.clear()
                        target_mgr.clear()
                        weather.set_condition(Weather.CLEAR)
                        time_of_day.set_day()
                    elif game_state == "CAMPAIGN":
                        game_state = "MENU"
                    else:
                        running = False

                # M key returns to menu (save mission result first)
                if event.key == pygame.K_m and game_state in ("FLYING", "TAKEOFF"):
                    if active_mission and active_mission.status != "active":
                        pilot_dossier.add_mission_result(active_mission)
                        if campaign.active:
                            campaign.save_aircraft_state(aircraft)
                            campaign.advance(active_mission)
                    game_state = "MENU"
                    aircraft = None
                    active_scenario = None
                    active_mission = None
                    disaster_triggered = False
                    weapons_mgr.clear()
                    target_mgr.clear()
                    weather.set_condition(Weather.CLEAR)
                    time_of_day.set_day()

                # L key drops illumination flare (night missions)
                if event.key == pygame.K_l and game_state == "FLYING" and time_of_day.is_night():
                    if aircraft:
                        time_of_day.drop_flare(aircraft.x + aircraft.vx * 2,
                                               aircraft.y + aircraft.vy * 2,
                                               aircraft.z - 100)

                # P key toggles pilot dossier
                if event.key == pygame.K_p:
                    show_dossier = not show_dossier

                if game_state == "BRIEFING":
                    if event.key == pygame.K_RETURN:
                        # Set weather and time of day from mission
                        weather.set_condition(active_mission.WEATHER)
                        if active_mission.TIME_OF_DAY == TimeOfDay.NIGHT:
                            time_of_day.set_night()
                        else:
                            time_of_day.set_day()
                        radio.messages.clear()
                        radio.cooldowns.clear()

                        # Launch mission
                        aircraft = F6F_Hellcat()
                        active_mission.setup_targets(target_mgr, friendly_carrier)
                        status = "FLYING"
                        crashed = False
                        disaster_triggered = False
                        time_elapsed = 0
                        fdr.clear()
                        weapons_mgr.clear()
                        wingmen.clear()
                        wingmen.append(FriendlyAircraft(aircraft, offset_side=1))
                        wingmen.append(FriendlyAircraft(aircraft, offset_side=-1))
                        input_recorder.start_recording(hotp_rng.state)

                        # Apply campaign state if active
                        if campaign.active:
                            campaign.apply_aircraft_state(aircraft)

                        # Carrier takeoff or airborne start
                        if active_mission.CARRIER_TAKEOFF:
                            sx, sy, sh = friendly_carrier.get_takeoff_position()
                            aircraft.x, aircraft.y, aircraft.z = sx, sy, 65  # deck height
                            aircraft.vx, aircraft.vy, aircraft.vz = 0, 0, 0
                            aircraft.heading = sh
                            aircraft.throttle = 0.0
                            aircraft.on_ground = True
                            aircraft.gear_down = True
                            takeoff_throttle_held = 0.0
                            takeoff_roll_dist = 0.0
                            game_state = "TAKEOFF"
                            status = "ON DECK - Full throttle to launch"
                            radio.call('carrier', 'launch', cooldown=30.0,
                                       wind=int(weather.wind_speed))
                        else:
                            aircraft.z = active_mission.START_ALT
                            speed_fps = active_mission.START_SPEED * 1.68781
                            hdg_rad = math.radians(active_mission.START_HEADING)
                            aircraft.vx = math.sin(hdg_rad) * speed_fps
                            aircraft.vy = math.cos(hdg_rad) * speed_fps
                            aircraft.heading = active_mission.START_HEADING
                            game_state = "FLYING"
                            radio.call('command', 'mission_start', cooldown=30.0)
                    elif event.key == pygame.K_ESCAPE:
                        game_state = "MENU"
                        active_mission = None

                if game_state == "CAMPAIGN":
                    if event.key == pygame.K_RETURN:
                        mc = campaign.get_current_mission_class()
                        if mc:
                            active_mission = mc()
                            active_scenario = None
                            game_state = "BRIEFING"
                            continue
                    elif event.key == pygame.K_ESCAPE:
                        game_state = "MENU"

                if game_state == "MENU":
                    # Switch between menus
                    if event.key == pygame.K_TAB:
                        current_menu = (current_menu + 1) % 4
                        selected_index = 0

                    # Get current menu items
                    if current_menu < 3:
                        menu_items = [aircraft_list, mission_list, disaster_list][current_menu]
                    else:
                        menu_items = []  # Campaign has no selectable items

                    if menu_items:
                        if event.key == pygame.K_a or event.key == pygame.K_LEFT:
                            selected_index = (selected_index - 1) % len(menu_items)
                        if event.key == pygame.K_d or event.key == pygame.K_RIGHT:
                            selected_index = (selected_index + 1) % len(menu_items)

                    if event.key == pygame.K_RETURN:
                        if current_menu == 3:
                            # Campaign mode
                            if campaign.is_complete() or not campaign.active:
                                campaign.start()
                            game_state = "CAMPAIGN"
                            continue
                        if current_menu == 0:
                            # Free flight
                            aircraft = menu_items[selected_index]()
                            active_scenario = None
                            active_mission = None
                        elif current_menu == 1:
                            # Mission mode - show briefing then launch
                            mission_class = menu_items[selected_index]
                            active_mission = mission_class()
                            active_scenario = None
                            game_state = "BRIEFING"
                            continue
                        else:
                            # Disaster recreation
                            scenario_class = menu_items[selected_index]
                            active_scenario = scenario_class()
                            aircraft = DisasterAircraft(active_scenario)
                            active_mission = None

                        game_state = "FLYING"
                        status = "FLYING"
                        crashed = False
                        disaster_triggered = False
                        time_elapsed = 0
                        fdr.clear()
                        # Spawn wingmen for Hellcat flights
                        wingmen.clear()
                        if isinstance(aircraft, F6F_Hellcat):
                            wingmen.append(FriendlyAircraft(aircraft, offset_side=1))
                            wingmen.append(FriendlyAircraft(aircraft, offset_side=-1))
                            # Start recording for replay
                            input_recorder.start_recording(hotp_rng.state)

                if game_state == "FLYING":
                    if event.key == pygame.K_r:
                        aircraft.reset()
                        status = "FLYING"
                        crashed = False
                        disaster_triggered = False
                        time_elapsed = 0
                        fdr.clear()  # Clear flight data recorder
                        weapons_mgr.clear()  # Clear weapons
                        target_mgr.clear()  # Reset targets
                        if active_scenario:
                            active_scenario.triggered = False
                            active_scenario.flight_time = 0

                    if event.key == pygame.K_f:
                        ias = aircraft.get_airspeed_kts()
                        if ias < aircraft.FLAPS_MAX_SPEED or aircraft.flaps:
                            aircraft.flaps = not aircraft.flaps

                    if event.key == pygame.K_g:
                        ias = aircraft.get_airspeed_kts()
                        if ias < aircraft.GEAR_MAX_SPEED or aircraft.gear_down:
                            aircraft.gear_down = not aircraft.gear_down

                    # Drag coefficient adjustment with [ and ] keys
                    if event.key == pygame.K_RIGHTBRACKET or event.key == pygame.K_EQUALS:
                        aircraft.drag_modifier = min(5.0, aircraft.drag_modifier + 0.1)
                    if event.key == pygame.K_LEFTBRACKET or event.key == pygame.K_MINUS:
                        aircraft.drag_modifier = max(0.2, aircraft.drag_modifier - 0.1)

                    # Camera view cycle with V key
                    if event.key == pygame.K_v:
                        camera_view = (camera_view + 1) % 3

                    # Radar range cycle with TAB
                    if event.key == pygame.K_TAB and hasattr(aircraft, 'radar_range'):
                        ranges = [1, 3, 15]
                        idx = ranges.index(aircraft.radar_range) if aircraft.radar_range in ranges else 0
                        aircraft.radar_range = ranges[(idx + 1) % 3]

                    # Weapon selection (Hellcat only)
                    if hasattr(aircraft, 'selected_weapon'):
                        if event.key == pygame.K_1:
                            aircraft.selected_weapon = 0  # Machine guns
                        if event.key == pygame.K_2:
                            aircraft.selected_weapon = 1  # Rockets
                        if event.key == pygame.K_3:
                            aircraft.selected_weapon = 2  # Bombs
                        if event.key == pygame.K_4:
                            aircraft.selected_weapon = 3  # Torpedo

                        # Fire rockets, drop bombs, or launch torpedo with SPACE
                        if event.key == pygame.K_SPACE:
                            if aircraft.selected_weapon == 1:
                                if weapons_mgr.fire_rocket(aircraft):
                                    sound_mgr.play('rocket')
                            elif aircraft.selected_weapon == 2:
                                if weapons_mgr.drop_bomb(aircraft):
                                    sound_mgr.play('explosion')
                            elif aircraft.selected_weapon == 3:
                                if weapons_mgr.drop_torpedo(aircraft):
                                    sound_mgr.play('torpedo')
                                elif getattr(aircraft, 'torpedoes', 0) > 0:
                                    # Failed constraints - show why
                                    if aircraft.z > 300:
                                        status = "TORPEDO: TOO HIGH - Below 300 ft!"
                                    elif aircraft.get_airspeed_kts() > 150:
                                        status = "TORPEDO: TOO FAST - Below 150 kts!"

        keys = pygame.key.get_pressed()

        # === CARRIER TAKEOFF STATE ===
        if game_state == "TAKEOFF" and aircraft:
            # Player must hold full throttle to build up and roll down deck
            if keys[pygame.K_LSHIFT]:
                aircraft.throttle = min(1.0, aircraft.throttle + 1.0 * dt)
            if keys[pygame.K_LCTRL]:
                aircraft.throttle = max(0.0, aircraft.throttle - 1.0 * dt)

            if aircraft.throttle >= 0.95:
                takeoff_throttle_held += dt
            else:
                takeoff_throttle_held = 0

            # After 1.5s at full throttle, release brakes — start rolling
            if takeoff_throttle_held > 1.5:
                # Accelerate down deck
                hdg_rad = math.radians(friendly_carrier.heading)
                power = aircraft.get_engine_power(65, aircraft.throttle)
                accel = power * 550 / max(100, aircraft.weight) * 0.3  # simplified
                aircraft.vx += math.sin(hdg_rad) * accel * dt
                aircraft.vy += math.cos(hdg_rad) * accel * dt
                v = math.sqrt(aircraft.vx**2 + aircraft.vy**2)
                takeoff_roll_dist += v * dt
                aircraft.x += aircraft.vx * dt
                aircraft.y += aircraft.vy * dt

                # Update carrier position too
                friendly_carrier.update(dt)

                ias_kts = v / 1.68781
                status = f"ROLLING - {ias_kts:.0f} kts"

                # Check if reached end of deck (~400 ft roll)
                if takeoff_roll_dist > friendly_carrier.LENGTH * 0.8:
                    # Airborne!
                    aircraft.z = 80  # Just above deck edge
                    aircraft.on_ground = False
                    aircraft.gear_down = True  # Player retracts later
                    aircraft.heading = friendly_carrier.heading
                    game_state = "FLYING"
                    status = "AIRBORNE - Gear up!"
                    radio.call('command', 'mission_start', cooldown=30.0)
            else:
                status = f"ON DECK - Throttle {aircraft.throttle*100:.0f}% (hold SHIFT for full power)"
                friendly_carrier.update(dt)
                # Keep aircraft on deck
                sx, sy, sh = friendly_carrier.get_takeoff_position()
                aircraft.x, aircraft.y = sx, sy
                aircraft.heading = sh

            sound_mgr.update_engine(aircraft.throttle, True)
            weather.update(dt)
            time_of_day.update(dt)
            radio.update(dt)

        # Continuous drag adjustment while holding keys
        if game_state == "FLYING":
            if keys[pygame.K_RIGHTBRACKET] or keys[pygame.K_EQUALS]:
                aircraft.drag_modifier = min(5.0, aircraft.drag_modifier + 1.0 * dt)
            if keys[pygame.K_LEFTBRACKET] or keys[pygame.K_MINUS]:
                aircraft.drag_modifier = max(0.2, aircraft.drag_modifier - 1.0 * dt)

            # Machine gun firing (hold SPACE when MG selected)
            if hasattr(aircraft, 'mg_firing'):
                if keys[pygame.K_SPACE] and aircraft.selected_weapon == 0 and not crashed:
                    aircraft.mg_firing = True
                    # Fire rate: 80 rounds per second total (6 guns at 800 rpm each)
                    if time_elapsed - aircraft.last_mg_fire > 0.0125:  # ~80 rounds/sec
                        weapons_mgr.fire_guns(aircraft)
                        sound_mgr.play('guns')
                        aircraft.last_mg_fire = time_elapsed
                else:
                    aircraft.mg_firing = False

            # Record input for replay
            if input_recorder.recording:
                input_recorder.record_frame(keys)

            # Update weapons
            weapons_mgr.update(dt)

            # Update targets (only for Hellcat - combat mode)
            if hasattr(aircraft, 'mg_ammo'):
                target_mgr.update(dt, weapons_mgr, aircraft, friendly_carrier, wingmen=wingmen)

            # Update friendly carrier
            friendly_carrier.update(dt)

            # Check carrier deck landing (Hellcat only)
            if hasattr(aircraft, 'mg_ammo') and aircraft.z <= 65 and aircraft.z > 0:
                if friendly_carrier.check_on_deck(aircraft.x, aircraft.y):
                    aircraft.z = 65  # Deck height ~65 ft above water
                    caught, wire = friendly_carrier.check_wire_catch(
                        aircraft.x, aircraft.y, aircraft.vz,
                        aircraft.get_airspeed_kts(), aircraft.gear_down)
                    if caught and aircraft.vz <= 0:
                        # Arrested landing!
                        aircraft.vz = 0
                        aircraft.vx *= 0.85  # Wire deceleration
                        aircraft.vy *= 0.85
                        aircraft.on_ground = True
                        v_total = math.sqrt(aircraft.vx**2 + aircraft.vy**2)
                        if v_total < 10:
                            status = f"CARRIER LANDING - Wire {wire}!"
                            sound_mgr.play('wire_catch')
                            pilot_dossier.record_carrier_landing()
                            radio.call('carrier', 'trapped', cooldown=30.0, wire=wire)
                    elif aircraft.vz < 0:
                        # On deck but missed wires - bolter
                        aircraft.vz = 0
                        aircraft.on_ground = True
                        radio.call('carrier', 'bolter', cooldown=10.0)

            # Update weather, time of day, radio
            weather.update(dt)
            weather.apply_turbulence(aircraft, dt)
            time_of_day.update(dt)
            radio.update(dt)

            # Apply wind to aircraft velocity
            wx, wy = weather.get_wind_vector()
            aircraft.vx += wx * 0.01 * dt  # Gentle wind influence
            aircraft.vy += wy * 0.01 * dt

            # Auto-generate radio calls
            if hasattr(aircraft, 'mg_ammo'):
                radio.check_context(aircraft, target_mgr, friendly_carrier, wingmen, active_mission)

            # Radio calls for mission events
            if active_mission:
                if active_mission.status == "success":
                    radio.call('command', 'rtb', cooldown=30.0)
                elif active_mission.status == "failed":
                    radio.call('command', 'mission_fail', cooldown=30.0)

        if game_state == "MENU":
            if current_menu < 3:
                menu_items = [aircraft_list, mission_list, disaster_list][current_menu]
            else:
                menu_items = []
            draw_home_screen(screen, selected_index, menu_items, current_menu)

        elif game_state == "BRIEFING":
            draw_mission_briefing(screen, active_mission)

        elif game_state == "CAMPAIGN":
            draw_campaign_status(screen, campaign, pilot_dossier)

        elif game_state == "TAKEOFF":
            # Draw takeoff sequence using overhead view
            screen.fill(BLACK)
            draw_map_view(screen, aircraft, satellite_map)
            draw_friendly_carrier(screen, friendly_carrier, aircraft)
            draw_aircraft_symbol(screen, aircraft)
            draw_instruments(screen, aircraft, status)
            # Takeoff HUD
            bar = pygame.Surface((500, 80), pygame.SRCALPHA)
            bar.fill((0, 0, 0, 180))
            screen.blit(bar, (WIDTH // 2 - 250, 50))
            t1 = font_med.render(status, True, HUD_AMBER)
            screen.blit(t1, (WIDTH // 2 - t1.get_width() // 2, 60))
            pct = min(1.0, takeoff_throttle_held / 1.5) if aircraft.throttle >= 0.95 else 0
            # Throttle bar
            pygame.draw.rect(screen, (50, 50, 50), (WIDTH // 2 - 150, 95, 300, 20))
            pygame.draw.rect(screen, HUD_GREEN if pct >= 1.0 else HUD_AMBER,
                             (WIDTH // 2 - 150, 95, int(300 * pct), 20))
            t2 = font_tiny.render("THROTTLE HOLD", True, WHITE)
            screen.blit(t2, (WIDTH // 2 - t2.get_width() // 2, 118))
            # Night overlay for takeoff
            if time_of_day.is_night():
                night_overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                night_overlay.fill((0, 0, 15, time_of_day.get_night_overlay_alpha()))
                screen.blit(night_overlay, (0, 0))
            weather.draw_rain(screen)
            radio.draw(screen)

        elif game_state == "FLYING":
            if not crashed:
                status = aircraft.update(dt, keys)

                # Update sounds
                sound_mgr.update_engine(aircraft.throttle, aircraft.z > 0)
                if aircraft.stalled:
                    if not sound_mgr.channels.get('alerts', None) or \
                       not sound_mgr.channels['alerts'].get_busy():
                        sound_mgr.play('stall', loop=True)
                else:
                    sound_mgr.stop('alerts')

                # Record flight data
                fdr.record(
                    time_elapsed,
                    aircraft.z,
                    aircraft.get_airspeed_kts(),
                    aircraft.get_vertical_speed(),
                    aircraft.x,
                    aircraft.y
                )

                # Check for disaster trigger
                if active_scenario and active_scenario.triggered and not disaster_triggered:
                    disaster_triggered = True
                    fdr.mark_disaster(time_elapsed)
                    status = "!! EXPLOSION - ALL ENGINES LOST !!"

                if "CRASHED" in status:
                    crashed = True

                # Check mission objectives
                if active_mission and active_mission.status == "active":
                    mission_result = active_mission.check_objectives(aircraft, target_mgr, friendly_carrier)
                    if mission_result == "success":
                        active_mission.status = "success"
                    elif mission_result == "failed":
                        active_mission.status = "failed"
                    if crashed and active_mission.status == "active":
                        active_mission.status = "failed"

            screen.fill(BLACK)

            # Draw based on camera view
            if camera_view == CAMERA_OVERHEAD:
                draw_map_view(screen, aircraft, satellite_map)
                # Draw friendly carrier
                draw_friendly_carrier(screen, friendly_carrier, aircraft)
                # Draw targets (Hellcat only)
                if hasattr(aircraft, 'mg_ammo'):
                    draw_targets_overhead(screen, target_mgr, aircraft)
                draw_weapons_overhead(screen, weapons_mgr, aircraft)
                draw_aircraft_symbol(screen, aircraft)
                # Draw wingmen on overhead
                for wm in wingmen:
                    if wm.alive:
                        wpx, wpy = feet_to_pixel(wm.x, wm.y, aircraft.ref_lat, aircraft.ref_lon)
                        ac_px, ac_py = feet_to_pixel(aircraft.x, aircraft.y, aircraft.ref_lat, aircraft.ref_lon)
                        sx = int(WIDTH//2 + (wpx - ac_px))
                        sy = int(HEIGHT//2 + (wpy - ac_py))
                        if 0 < sx < WIDTH and 0 < sy < HEIGHT:
                            pygame.draw.circle(screen, HUD_GREEN, (sx, sy), 5)
                            pygame.draw.circle(screen, WHITE, (sx, sy), 5, 1)
                # Draw escort bombers on overhead
                if active_mission and hasattr(active_mission, 'bombers'):
                    ac_px, ac_py = feet_to_pixel(aircraft.x, aircraft.y, aircraft.ref_lat, aircraft.ref_lon)
                    for b in active_mission.bombers:
                        bpx, bpy = feet_to_pixel(b.x, b.y, aircraft.ref_lat, aircraft.ref_lon)
                        sx = int(WIDTH//2 + (bpx - ac_px))
                        sy = int(HEIGHT//2 + (bpy - ac_py))
                        if 0 < sx < WIDTH and 0 < sy < HEIGHT:
                            color = (100, 150, 255) if b.alive else (80, 80, 80)
                            # Large bomber symbol
                            pygame.draw.circle(screen, color, (sx, sy), 7)
                            pygame.draw.line(screen, color, (sx-10, sy), (sx+10, sy), 2)
                            if b.smoking:
                                pygame.draw.circle(screen, (150, 150, 150), (sx+3, sy+3), 4)
            elif camera_view == CAMERA_COCKPIT:
                draw_cockpit_view(screen, aircraft, satellite_map, time_elapsed)
                # Draw targets and wingmen in cockpit view
                if hasattr(aircraft, 'mg_ammo'):
                    draw_targets_cockpit(screen, target_mgr, aircraft)
                if wingmen:
                    draw_wingmen_3d(screen, wingmen, aircraft)
                    # Draw escort bombers if in bomber escort mission
                    if active_mission and hasattr(active_mission, 'bombers'):
                        draw_wingmen_3d(screen, active_mission.bombers, aircraft)
                draw_weapons_cockpit(screen, weapons_mgr, aircraft)
                # Add minimap for navigation
                draw_minimap(screen, aircraft, satellite_map, 10, 120, 180)
            elif camera_view == CAMERA_CHASE:
                draw_chase_view(screen, aircraft, satellite_map, time_elapsed)
                # Draw targets and wingmen in chase view
                if hasattr(aircraft, 'mg_ammo'):
                    draw_targets_cockpit(screen, target_mgr, aircraft)
                if wingmen:
                    draw_wingmen_3d(screen, wingmen, aircraft)
                    # Draw escort bombers if in bomber escort mission
                    if active_mission and hasattr(active_mission, 'bombers'):
                        draw_wingmen_3d(screen, active_mission.bombers, aircraft)
                draw_weapons_cockpit(screen, weapons_mgr, aircraft)
                # Add minimap for navigation
                draw_minimap(screen, aircraft, satellite_map, 10, 120, 180)

            draw_instruments(screen, aircraft, status)
            draw_stall_warning(screen, aircraft, time_elapsed)
            draw_g_effects(screen, aircraft)

            # Near-miss screen shake effect
            if hasattr(aircraft, 'near_miss_shake') and aircraft.near_miss_shake > 0.01:
                shake = aircraft.near_miss_shake
                sx = int((hotp_rng.next() % 20 - 10) * shake)
                sy = int((hotp_rng.next() % 14 - 7) * shake)
                # Shift the screen slightly for a flinch effect
                temp = screen.copy()
                screen.fill(BLACK)
                screen.blit(temp, (sx, sy))
                aircraft.near_miss_shake *= max(0, 1.0 - 8.0 * dt)

            # Radar and weapons HUD (Hellcat only)
            if hasattr(aircraft, 'mg_ammo'):
                radar_friends = list(wingmen)
                if active_mission and hasattr(active_mission, 'bombers'):
                    radar_friends.extend(active_mission.bombers)
                draw_radar(screen, aircraft, target_mgr, 800, HEIGHT - 120, 50,
                           friendly_carrier, friendlies=radar_friends)
                draw_weapons_hud(screen, aircraft)
                draw_score_display(screen, target_mgr)

            # Flight data plots on right side
            draw_flight_plots(screen, fdr, active_scenario)

            # Cloud layer effect
            weather.draw_cloud_layer(screen, aircraft)

            # Night overlay
            if time_of_day.is_night():
                night_alpha = time_of_day.get_night_overlay_alpha()
                night_surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                night_surf.fill((0, 0, 15, night_alpha))
                screen.blit(night_surf, (0, 0))
                # Searchlights from AA guns (cockpit/chase views)
                if camera_view in (CAMERA_COCKPIT, CAMERA_CHASE):
                    time_of_day.draw_searchlights(screen, target_mgr.ground_targets, aircraft)
                    time_of_day.draw_flares(screen, aircraft)
                # Stars in cockpit view
                if camera_view == CAMERA_COCKPIT:
                    time_of_day.draw_night_sky(screen)

            # Rain overlay
            weather.draw_rain(screen)

            # Weather indicator
            if weather.condition > Weather.CLEAR:
                wx_text = font_tiny.render(
                    f"WX: {Weather.NAMES[weather.condition]} | Wind {weather.wind_speed:.0f}kt "
                    f"@ {weather.wind_heading:.0f}° | Vis {weather.visibility*100:.0f}%",
                    True, HUD_AMBER)
                screen.blit(wx_text, (WIDTH // 2 - wx_text.get_width() // 2, HEIGHT - 275))

            # Radio messages
            radio.draw(screen)

            # Camera view indicator
            view_text = font_small.render(f"VIEW: {CAMERA_NAMES[camera_view]} (V to change)", True, WHITE)
            screen.blit(view_text, (WIDTH // 2 - 100, HEIGHT - 255))

            # Disaster scenario overlay
            if active_scenario:
                draw_disaster_overlay(screen, active_scenario, time_elapsed, crashed)

            # Mission HUD and results
            if active_mission:
                if active_mission.status == "active":
                    draw_mission_hud(screen, active_mission)
                elif active_mission.status in ("success", "failed"):
                    draw_mission_result(screen, active_mission)
                    # Campaign: auto-record and prompt for next
                    if campaign.active and active_mission.status in ("success", "failed"):
                        campaign_hint = font_small.render(
                            "Press M to continue campaign", True, HUD_AMBER)
                        screen.blit(campaign_hint, (WIDTH // 2 - campaign_hint.get_width() // 2,
                                                    HEIGHT // 2 + 120))

            if crashed:
                overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 180))
                screen.blit(overlay, (0, 0))

                crash_text = font_large.render(status, True, HUD_RED)
                rect = crash_text.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 50))
                screen.blit(crash_text, rect)

                # Show distance traveled after disaster
                if active_scenario and active_scenario.triggered:
                    dist_nm = math.sqrt(aircraft.x**2 + aircraft.y**2) / 6076
                    dist_text = font_med.render(f"Distance traveled after explosion: {dist_nm:.1f} nautical miles", True, HUD_AMBER)
                    dist_rect = dist_text.get_rect(center=(WIDTH // 2, HEIGHT // 2))
                    screen.blit(dist_text, dist_rect)

                restart = font_med.render("Press R to restart, ESC for menu", True, WHITE)
                rect2 = restart.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 50))
                screen.blit(restart, rect2)

        # Dossier overlay (drawn on top of everything)
        if show_dossier:
            draw_dossier(screen, pilot_dossier)

        # Rank display on menu screen
        if game_state == "MENU":
            rank_text = font_small.render(
                f"{pilot_dossier.get_rank()} {pilot_dossier.name} | Score: {pilot_dossier.total_score:,} | P: Dossier",
                True, HUD_GREEN)
            screen.blit(rank_text, (10, HEIGHT - 20))

        pygame.display.flip()

    pygame.quit()


def draw_flight_plots(surface, fdr, scenario=None):
    """Draw real-time flight data plots on the right side"""
    if len(fdr.time) < 2:
        return

    # Plot area dimensions
    plot_x = WIDTH - 280
    plot_width = 260
    plot_height = 160
    plot_spacing = 15
    start_y = 20

    # Colors
    PLOT_BG = (20, 25, 35)
    GRID_COLOR = (50, 60, 70)
    AXIS_COLOR = (100, 110, 120)
    DISASTER_COLOR = HUD_RED

    plots = [
        ("ALTITUDE (ft)", fdr.altitude, 0, max(20000, max(fdr.altitude) * 1.1) if fdr.altitude else 20000, HUD_GREEN),
        ("AIRSPEED (kts)", fdr.airspeed, 0, max(500, max(fdr.airspeed) * 1.1) if fdr.airspeed else 500, HUD_AMBER),
        ("VERT SPEED (fpm)", fdr.vsi, -5000, 5000, (100, 200, 255)),
    ]

    for i, (title, data, y_min, y_max, color) in enumerate(plots):
        py = start_y + i * (plot_height + plot_spacing)

        # Background
        pygame.draw.rect(surface, PLOT_BG, (plot_x, py, plot_width, plot_height))
        pygame.draw.rect(surface, AXIS_COLOR, (plot_x, py, plot_width, plot_height), 1)

        # Title
        title_surf = font_tiny.render(title, True, color)
        surface.blit(title_surf, (plot_x + 5, py + 3))

        # Grid lines
        for j in range(1, 4):
            gy = py + j * plot_height // 4
            pygame.draw.line(surface, GRID_COLOR, (plot_x, gy), (plot_x + plot_width, gy), 1)

        # Y-axis labels
        for j in range(5):
            val = y_max - (y_max - y_min) * j / 4
            label = font_tiny.render(f"{int(val)}", True, AXIS_COLOR)
            label_y = py + j * plot_height // 4
            surface.blit(label, (plot_x + plot_width - 45, label_y - 6))

        # Plot data
        if len(data) > 1:
            points = []
            for j, val in enumerate(data):
                px = plot_x + 5 + (plot_width - 55) * j / (len(data) - 1)
                # Clamp and scale value
                val_clamped = max(y_min, min(y_max, val))
                py_val = py + plot_height - 5 - (plot_height - 25) * (val_clamped - y_min) / (y_max - y_min)
                points.append((px, py_val))

            if len(points) > 1:
                pygame.draw.lines(surface, color, False, points, 2)

        # Mark disaster point
        if fdr.disaster_time and len(fdr.time) > 1:
            # Find index of disaster time
            for j, t in enumerate(fdr.time):
                if t >= fdr.disaster_time:
                    dx = plot_x + 5 + (plot_width - 55) * j / (len(fdr.time) - 1)
                    pygame.draw.line(surface, DISASTER_COLOR, (dx, py + 18), (dx, py + plot_height - 5), 2)
                    break

        # Current value
        if data:
            current = data[-1]
            val_text = font_small.render(f"{int(current)}", True, WHITE)
            surface.blit(val_text, (plot_x + 5, py + plot_height - 22))

    # Distance traveled
    if fdr.distance:
        dist_text = font_med.render(f"DIST: {fdr.distance[-1]:.2f} nm", True, HUD_AMBER)
        dist_y = start_y + 3 * (plot_height + plot_spacing)
        surface.blit(dist_text, (plot_x + 10, dist_y))

        # Time elapsed
        if fdr.time:
            time_text = font_med.render(f"TIME: {fdr.time[-1]:.1f} sec", True, HUD_GREEN)
            surface.blit(time_text, (plot_x + 10, dist_y + 28))

        # Distance after disaster
        if fdr.disaster_time and scenario:
            time_since = fdr.time[-1] - fdr.disaster_time
            if time_since > 0:
                # Find distance at disaster time
                disaster_dist = 0
                for j, t in enumerate(fdr.time):
                    if t >= fdr.disaster_time:
                        disaster_dist = fdr.distance[j]
                        break
                dist_after = fdr.distance[-1] - disaster_dist
                after_text = font_med.render(f"POST-EVENT: {dist_after:.2f} nm", True, HUD_RED)
                surface.blit(after_text, (plot_x + 10, dist_y + 56))


def draw_disaster_overlay(surface, scenario, time_elapsed, crashed):
    """Draw disaster scenario information overlay"""
    # Timer until disaster
    if not scenario.triggered:
        time_remaining = max(0, scenario.TRIGGER_TIME - scenario.flight_time)
        timer_color = HUD_GREEN if time_remaining > 5 else (HUD_AMBER if time_remaining > 2 else HUD_RED)

        timer_text = font_large.render(f"Time to event: {time_remaining:.1f}s", True, timer_color)
        rect = timer_text.get_rect(center=(WIDTH // 2, 50))
        pygame.draw.rect(surface, (0, 0, 0, 180), rect.inflate(20, 10))
        surface.blit(timer_text, rect)

        scenario_name = font_med.render(scenario.NAME, True, WHITE)
        name_rect = scenario_name.get_rect(center=(WIDTH // 2, 85))
        surface.blit(scenario_name, name_rect)

    # Disaster has occurred
    elif not crashed:
        # Flashing warning
        if int(time_elapsed * 3) % 2:
            warn_text = font_large.render("!! CATASTROPHIC FAILURE !!", True, HUD_RED)
            rect = warn_text.get_rect(center=(WIDTH // 2, 50))
            pygame.draw.rect(surface, (0, 0, 0, 200), rect.inflate(20, 10))
            surface.blit(warn_text, rect)

        # Show time since disaster
        time_since = scenario.flight_time - scenario.TRIGGER_TIME
        time_text = font_med.render(f"Time since explosion: {time_since:.1f}s", True, HUD_AMBER)
        time_rect = time_text.get_rect(center=(WIDTH // 2, 85))
        surface.blit(time_text, time_rect)


if __name__ == "__main__":
    main()
