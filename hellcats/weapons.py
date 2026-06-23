"""Weapons and projectiles."""
import math
import pygame
from hellcats.hotp import hotp_rng
from hellcats.bootstrap import PHYSICS_DT

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


