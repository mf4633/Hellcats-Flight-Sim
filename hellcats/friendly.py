"""Friendly carrier, wingmen, bombers."""
import math
from hellcats.hotp import (
    hotp_rng, hotp_delta_smooth, hotp_aero_lookup,
    HOTP_FLAG_JITTER_AXIS1, HOTP_FLAG_JITTER_AXIS2,
)
from hellcats.bootstrap import PHYSICS_DT

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

    def check_wire_catch(self, px, py, vz, airspeed_kts, gear_down, max_wire_speed=150):
        """Check if landing in arresting wire zone. Returns (caught, wire_num) or (False, 0)"""
        if not gear_down:
            return False, 0
        if airspeed_kts > max_wire_speed:
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


