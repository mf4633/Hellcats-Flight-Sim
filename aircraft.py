"""
Aircraft models and AI for Hellcats Flight Simulator
====================================================
Contains aircraft specifications and AI behavior for both friendly and enemy aircraft.
"""

import math
import random
import pygame
from dataclasses import dataclass
from typing import List, Optional, Tuple
from enum import Enum

class AircraftType(Enum):
    F6F_HELLCAT = "f6f_hellcat"
    A6M_ZERO = "a6m_zero"
    B5N_KATE = "b5n_kate"  # Japanese torpedo bomber
    D3A_VAL = "d3a_val"    # Japanese dive bomber

class AIBehavior(Enum):
    PATROL = "patrol"
    ATTACK = "attack"
    DEFEND = "defend"
    FLEE = "flee"
    KAMIKAZE = "kamikaze"

@dataclass
class Vector3:
    """3D vector for position, velocity, etc."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    
    def __add__(self, other):
        return Vector3(self.x + other.x, self.y + other.y, self.z + other.z)
    
    def __sub__(self, other):
        return Vector3(self.x - other.x, self.y - other.y, self.z - other.z)
    
    def __mul__(self, scalar):
        return Vector3(self.x * scalar, self.y * scalar, self.z * scalar)
    
    def magnitude(self):
        return math.sqrt(self.x**2 + self.y**2 + self.z**2)
    
    def normalize(self):
        mag = self.magnitude()
        if mag > 0:
            return Vector3(self.x / mag, self.y / mag, self.z / mag)
        return Vector3(0, 0, 0)
    
    def distance_to(self, other):
        return (self - other).magnitude()

@dataclass
class Weapon:
    """Weapon system data"""
    name: str
    ammo: int
    max_ammo: int
    rate_of_fire: float  # rounds per second
    muzzle_velocity: float  # m/s
    damage: float
    last_fire_time: float = 0.0

class BaseAircraft:
    """Base aircraft class with common properties and methods"""
    
    def __init__(self, aircraft_type: AircraftType, position: Vector3):
        self.type = aircraft_type
        self.position = position
        self.velocity = Vector3(0, 0, 0)
        self.pitch = 0.0
        self.roll = 0.0
        self.yaw = 0.0
        
        # Load aircraft-specific specifications
        self._load_specifications()

        # Store base values for damage degradation (prevents compounding)
        self._base_max_speed = self.max_speed
        self._base_climb_rate = self.climb_rate
        self._base_turn_rate = self.turn_rate

        # Current state
        self.throttle = 0.5
        self.current_speed = self.cruise_speed
        self.health = 100.0
        self.fuel = self.max_fuel
        
        # AI properties
        self.is_player = False
        self.ai_behavior = AIBehavior.PATROL
        self.target: Optional['BaseAircraft'] = None
        self.ai_state_time = 0.0
        
        # Weapons
        self.weapons: List[Weapon] = []
        self._setup_weapons()
    
    def _load_specifications(self):
        """Load aircraft specifications based on type"""
        if self.type == AircraftType.F6F_HELLCAT:
            # F6F Hellcat specifications
            self.max_speed = 391.0        # mph
            self.stall_speed = 84.0       # mph
            self.cruise_speed = 180.0     # mph
            self.climb_rate = 2600.0      # ft/min
            self.service_ceiling = 37300.0 # feet
            self.turn_rate = 15.0         # degrees per second
            self.max_fuel = 250.0         # gallons
            self.wing_loading = 37.7      # lb/sq ft
            self.color = (0, 0, 255)      # Blue
            
        elif self.type == AircraftType.A6M_ZERO:
            # A6M Zero specifications (historical opponent)
            self.max_speed = 331.0        # mph
            self.stall_speed = 69.0       # mph  
            self.cruise_speed = 160.0     # mph
            self.climb_rate = 3100.0      # ft/min
            self.service_ceiling = 32800.0 # feet
            self.turn_rate = 25.0         # degrees per second (very maneuverable)
            self.max_fuel = 144.0         # gallons
            self.wing_loading = 21.3      # lb/sq ft (lighter)
            self.color = (255, 0, 0)      # Red
            
        elif self.type == AircraftType.B5N_KATE:
            # B5N Kate torpedo bomber
            self.max_speed = 235.0        # mph
            self.stall_speed = 78.0       # mph
            self.cruise_speed = 150.0     # mph
            self.climb_rate = 1400.0      # ft/min
            self.service_ceiling = 27100.0 # feet
            self.turn_rate = 8.0          # degrees per second (bomber)
            self.max_fuel = 248.0         # gallons
            self.wing_loading = 35.4      # lb/sq ft
            self.color = (255, 165, 0)    # Orange
            
        else:  # Default values
            self.max_speed = 200.0
            self.stall_speed = 70.0
            self.cruise_speed = 120.0
            self.climb_rate = 1000.0
            self.service_ceiling = 20000.0
            self.turn_rate = 10.0
            self.max_fuel = 150.0
            self.wing_loading = 30.0
            self.color = (128, 128, 128)
    
    def _setup_weapons(self):
        """Setup weapons based on aircraft type"""
        if self.type == AircraftType.F6F_HELLCAT:
            # 6 × .50 caliber machine guns
            for i in range(6):
                self.weapons.append(Weapon(
                    name=f".50 Cal MG {i+1}",
                    ammo=400,
                    max_ammo=400,
                    rate_of_fire=13.0,  # rounds per second per gun
                    muzzle_velocity=850.0,  # m/s
                    damage=15.0
                ))
                
        elif self.type == AircraftType.A6M_ZERO:
            # 2 × 20mm cannons + 2 × 7.7mm machine guns
            for i in range(2):
                self.weapons.append(Weapon(
                    name=f"20mm Cannon {i+1}",
                    ammo=60,
                    max_ammo=60,
                    rate_of_fire=8.0,
                    muzzle_velocity=750.0,
                    damage=35.0
                ))
            for i in range(2):
                self.weapons.append(Weapon(
                    name=f"7.7mm MG {i+1}",
                    ammo=680,
                    max_ammo=680,
                    rate_of_fire=15.0,
                    muzzle_velocity=732.0,
                    damage=8.0
                ))
    
    def fire_weapons(self, current_time: float) -> List[dict]:
        """Fire all weapons and return projectile data"""
        projectiles = []
        
        for weapon in self.weapons:
            # Check rate of fire and ammo
            time_since_last_fire = current_time - weapon.last_fire_time
            min_fire_interval = 1.0 / weapon.rate_of_fire
            
            if time_since_last_fire >= min_fire_interval and weapon.ammo > 0:
                weapon.ammo -= 1
                weapon.last_fire_time = current_time
                
                # Calculate projectile starting position and velocity
                # Simplified: projectiles start from aircraft nose
                yaw_rad = math.radians(self.yaw)
                pitch_rad = math.radians(self.pitch)
                
                # Initial position slightly ahead of aircraft
                start_pos = Vector3(
                    self.position.x + 10 * math.sin(yaw_rad),
                    self.position.y + 10 * math.sin(pitch_rad),
                    self.position.z + 10 * math.cos(yaw_rad)
                )
                
                # Projectile velocity = muzzle velocity + aircraft velocity
                projectile_vel = Vector3(
                    weapon.muzzle_velocity * math.sin(yaw_rad) * math.cos(pitch_rad),
                    weapon.muzzle_velocity * math.sin(pitch_rad),
                    weapon.muzzle_velocity * math.cos(yaw_rad) * math.cos(pitch_rad)
                ) + self.velocity
                
                projectiles.append({
                    'position': start_pos,
                    'velocity': projectile_vel,
                    'damage': weapon.damage,
                    'owner': self,
                    'time_to_live': 3.0  # 3 seconds max flight time
                })
        
        return projectiles
    
    def take_damage(self, damage: float):
        """Apply damage to aircraft - uses base values to prevent compounding"""
        self.health = max(0, self.health - damage)

        # Recompute performance from BASE values based on current health
        if self.health < 70:
            self.max_speed = self._base_max_speed * (0.7 + (self.health / 70) * 0.3)
        else:
            self.max_speed = self._base_max_speed

        if self.health < 40:
            self.climb_rate = self._base_climb_rate * (0.5 + (self.health / 40) * 0.5)
        else:
            self.climb_rate = self._base_climb_rate

        if self.health < 20:
            self.turn_rate = self._base_turn_rate * (0.6 + (self.health / 20) * 0.4)
        else:
            self.turn_rate = self._base_turn_rate
    
    def update_ai(self, dt: float, player_aircraft: 'BaseAircraft', all_aircraft: List['BaseAircraft']):
        """Update AI behavior for non-player aircraft"""
        if self.is_player:
            return
        
        self.ai_state_time += dt
        
        # Find nearest enemy
        if not self.target or self.target.health <= 0:
            self.target = self._find_nearest_enemy(all_aircraft)
        
        # Execute AI behavior
        if self.ai_behavior == AIBehavior.PATROL:
            self._ai_patrol(dt)
        elif self.ai_behavior == AIBehavior.ATTACK:
            self._ai_attack(dt)
        elif self.ai_behavior == AIBehavior.DEFEND:
            self._ai_defend(dt)
        elif self.ai_behavior == AIBehavior.FLEE:
            self._ai_flee(dt)
        elif self.ai_behavior == AIBehavior.KAMIKAZE:
            self._ai_kamikaze(dt)
    
    def _find_nearest_enemy(self, all_aircraft: List['BaseAircraft']) -> Optional['BaseAircraft']:
        """Find the nearest enemy aircraft"""
        nearest = None
        min_distance = float('inf')
        
        for aircraft in all_aircraft:
            if aircraft == self or aircraft.health <= 0:
                continue
            
            # Simple friend/foe identification
            is_enemy = False
            if self.type == AircraftType.F6F_HELLCAT:
                is_enemy = aircraft.type in [AircraftType.A6M_ZERO, AircraftType.B5N_KATE, AircraftType.D3A_VAL]
            else:
                is_enemy = aircraft.type == AircraftType.F6F_HELLCAT
            
            if is_enemy:
                distance = self.position.distance_to(aircraft.position)
                if distance < min_distance:
                    min_distance = distance
                    nearest = aircraft
        
        return nearest
    
    def _ai_patrol(self, dt: float):
        """AI patrol behavior - fly in search patterns"""
        # Simple oval patrol pattern
        patrol_time = self.ai_state_time * 0.1
        
        # Calculate desired heading for patrol
        desired_yaw = (math.sin(patrol_time) * 45) % 360
        
        # Turn towards desired heading
        yaw_diff = (desired_yaw - self.yaw + 180) % 360 - 180
        turn_amount = min(abs(yaw_diff), self.turn_rate * dt)
        if yaw_diff > 0:
            self.yaw = (self.yaw + turn_amount) % 360
        else:
            self.yaw = (self.yaw - turn_amount) % 360
        
        # Maintain cruise speed and altitude
        self.throttle = 0.6
        
        # Switch to attack if enemy nearby
        if self.target and self.position.distance_to(self.target.position) < 3000:
            self.ai_behavior = AIBehavior.ATTACK
            self.ai_state_time = 0
    
    def _ai_attack(self, dt: float):
        """AI attack behavior - engage enemy aircraft"""
        if not self.target:
            self.ai_behavior = AIBehavior.PATROL
            return
        
        distance = self.position.distance_to(self.target.position)
        
        # Calculate intercept course
        target_vector = self.target.position - self.position
        
        # Simplified intercept calculation
        desired_yaw = math.degrees(math.atan2(target_vector.x, target_vector.z)) % 360
        desired_pitch = math.degrees(math.atan2(target_vector.y, 
                                    math.sqrt(target_vector.x**2 + target_vector.z**2)))
        
        # Turn towards target
        yaw_diff = (desired_yaw - self.yaw + 180) % 360 - 180
        turn_amount = min(abs(yaw_diff), self.turn_rate * dt)
        if yaw_diff > 0:
            self.yaw = (self.yaw + turn_amount) % 360
        else:
            self.yaw = (self.yaw - turn_amount) % 360
        
        # Pitch towards target (more gradual)
        pitch_diff = desired_pitch - self.pitch
        pitch_amount = min(abs(pitch_diff), self.turn_rate * 0.5 * dt)
        if pitch_diff > 0:
            self.pitch = min(self.pitch + pitch_amount, 45)
        else:
            self.pitch = max(self.pitch - pitch_amount, -45)
        
        # Speed control based on situation
        if distance > 1500:
            self.throttle = 1.0  # Full throttle to close distance
        elif distance < 300:
            self.throttle = 0.3  # Reduce speed for maneuvering
        else:
            self.throttle = 0.8  # Combat speed
        
        # Historical Zero tactics: turn fighting
        if self.type == AircraftType.A6M_ZERO and distance < 800:
            # Zero tries to out-turn the Hellcat
            if abs(yaw_diff) < 30:  # If roughly aligned
                if random.random() < 0.3:  # 30% chance to break into turn fight
                    self.yaw = (self.yaw + (90 if random.random() < 0.5 else -90)) % 360
                    self.throttle = 0.7
        
        # Return to patrol if target too far or lost
        if distance > 10000:
            self.ai_behavior = AIBehavior.PATROL
            self.target = None
    
    def _ai_defend(self, dt: float):
        """AI defensive behavior - protect area or retreat"""
        # Similar to attack but more conservative
        self._ai_attack(dt)
        
        # Retreat if heavily damaged
        if self.health < 30:
            self.ai_behavior = AIBehavior.FLEE
    
    def _ai_flee(self, dt: float):
        """AI flee behavior - escape from combat"""
        # Head away from enemies at full throttle
        self.throttle = 1.0
        
        # Try to climb for safety
        self.pitch = min(self.pitch + 20 * dt, 30)
        
        # Find safe heading (away from enemies)
        if self.target:
            target_vector = self.target.position - self.position
            escape_yaw = (math.degrees(math.atan2(target_vector.x, target_vector.z)) + 180) % 360
            
            yaw_diff = (escape_yaw - self.yaw + 180) % 360 - 180
            turn_amount = min(abs(yaw_diff), self.turn_rate * dt)
            if yaw_diff > 0:
                self.yaw = (self.yaw + turn_amount) % 360
            else:
                self.yaw = (self.yaw - turn_amount) % 360
    
    def _ai_kamikaze(self, dt: float):
        """AI kamikaze behavior - direct attack on target"""
        if not self.target:
            self.ai_behavior = AIBehavior.ATTACK
            return
        
        # Point directly at target at full throttle
        self.throttle = 1.0
        
        target_vector = self.target.position - self.position
        desired_yaw = math.degrees(math.atan2(target_vector.x, target_vector.z)) % 360
        desired_pitch = math.degrees(math.atan2(target_vector.y, 
                                    math.sqrt(target_vector.x**2 + target_vector.z**2)))
        
        # More aggressive turning towards target
        yaw_diff = (desired_yaw - self.yaw + 180) % 360 - 180
        turn_amount = min(abs(yaw_diff), self.turn_rate * 1.5 * dt)
        if yaw_diff > 0:
            self.yaw = (self.yaw + turn_amount) % 360
        else:
            self.yaw = (self.yaw - turn_amount) % 360
        
        pitch_diff = desired_pitch - self.pitch
        pitch_amount = min(abs(pitch_diff), self.turn_rate * dt)
        if pitch_diff > 0:
            self.pitch = min(self.pitch + pitch_amount, 60)
        else:
            self.pitch = max(self.pitch - pitch_amount, -60)
    
    def update_physics(self, dt: float):
        """Update aircraft physics"""
        # Roll induces yaw (coordinated turn) — banked wings redirect lift horizontally
        roll_rad = math.radians(self.roll)
        turn_from_roll = math.sin(roll_rad) * 30.0  # Up to 30 deg/s at max bank
        self.yaw = (self.yaw + turn_from_roll * dt) % 360

        # Roll also causes slight pitch-down due to lift loss (need back pressure in turns)
        lift_loss = 1.0 - math.cos(roll_rad)
        self.pitch += lift_loss * 5.0 * dt

        # Calculate engine power
        engine_power = self.throttle * 2000.0  # Simplified HP

        # Thrust calculation
        thrust_efficiency = 0.8 if self.current_speed < self.cruise_speed else 0.6
        thrust = engine_power * thrust_efficiency * 0.1

        # Drag (increases with speed squared)
        drag = 0.02 * self.current_speed ** 2
        
        # Net acceleration
        mass_factor = self.wing_loading / 30.0  # Normalized mass
        acceleration = (thrust - drag) / (mass_factor * 100.0)
        
        # Update speed
        self.current_speed += acceleration * dt
        self.current_speed = max(self.stall_speed, min(self.current_speed, self.max_speed))
        
        # Stall handling
        if self.current_speed <= self.stall_speed:
            # Force nose down to recover from stall
            self.pitch = min(self.pitch + 30 * dt, 30)
        
        # Convert speed to velocity components
        speed_mps = self.current_speed * 0.44704  # mph to m/s
        
        yaw_rad = math.radians(self.yaw)
        pitch_rad = math.radians(self.pitch)
        
        self.velocity.x = speed_mps * math.cos(pitch_rad) * math.sin(yaw_rad)
        self.velocity.z = speed_mps * math.cos(pitch_rad) * math.cos(yaw_rad)
        self.velocity.y = speed_mps * math.sin(pitch_rad)
        
        # Update position
        self.position = self.position + (self.velocity * dt)
        
        # Apply gravity
        gravity = -32.2 * 3.28084  # ft/s²
        self.velocity.y += gravity * dt
        
        # Ground collision
        if self.position.y <= 0:
            self.position.y = 0
            self.velocity.y = 0
            if self.current_speed > 80:  # Crash landing
                self.health = 0
        
        # Fuel consumption
        fuel_rate = self.throttle * 0.3  # gallons per second
        self.fuel = max(0, self.fuel - fuel_rate * dt)
        
        # Engine failure if no fuel
        if self.fuel <= 0:
            self.throttle = 0
    
    def get_screen_position(self, camera_aircraft: 'BaseAircraft', screen_width: int, screen_height: int) -> Optional[Tuple[int, int]]:
        """Calculate screen position relative to camera aircraft"""
        if camera_aircraft == self:
            return None  # Don't draw self
        
        # Calculate relative position
        relative_pos = self.position - camera_aircraft.position
        
        # Rotate relative to camera orientation
        yaw_rad = math.radians(-camera_aircraft.yaw)
        pitch_rad = math.radians(-camera_aircraft.pitch)
        
        # Simple rotation matrix application
        rotated_x = relative_pos.x * math.cos(yaw_rad) - relative_pos.z * math.sin(yaw_rad)
        rotated_z = relative_pos.x * math.sin(yaw_rad) + relative_pos.z * math.cos(yaw_rad)
        rotated_y = relative_pos.y
        
        # Apply pitch rotation
        final_y = rotated_y * math.cos(pitch_rad) - rotated_z * math.sin(pitch_rad)
        final_z = rotated_y * math.sin(pitch_rad) + rotated_z * math.cos(pitch_rad)
        
        # Perspective projection
        if final_z <= 0:  # Behind camera
            return None
        
        # Project to screen coordinates
        perspective_scale = 500.0 / final_z  # Adjust for viewing distance
        screen_x = screen_width // 2 + int(rotated_x * perspective_scale)
        screen_y = screen_height // 2 - int(final_y * perspective_scale)
        
        # Check if on screen
        if 0 <= screen_x <= screen_width and 0 <= screen_y <= screen_height:
            return (screen_x, screen_y)
        
        return None

class PlayerAircraft(BaseAircraft):
    """Player-controlled F6F Hellcat"""
    
    def __init__(self, position: Vector3):
        super().__init__(AircraftType.F6F_HELLCAT, position)
        self.is_player = True
    
    def handle_input(self, keys_pressed, dt: float):
        """Handle player input for aircraft control.
        keys_pressed is the sequence from pygame.key.get_pressed() — use indexing, not 'in'.
        """
        # Flight controls
        if keys_pressed[pygame.K_w]:  # Pitch up
            self.pitch = max(self.pitch - 45 * dt, -90)
        if keys_pressed[pygame.K_s]:  # Pitch down
            self.pitch = min(self.pitch + 45 * dt, 90)
        if keys_pressed[pygame.K_a]:  # Roll left
            self.roll = max(self.roll - 90 * dt, -90)
        if keys_pressed[pygame.K_d]:  # Roll right
            self.roll = min(self.roll + 90 * dt, 90)
        if keys_pressed[pygame.K_q]:  # Yaw left (rudder)
            self.yaw = (self.yaw - 45 * dt) % 360
        if keys_pressed[pygame.K_e]:  # Yaw right (rudder)
            self.yaw = (self.yaw + 45 * dt) % 360

        # Throttle control
        if keys_pressed[pygame.K_LSHIFT]:
            self.throttle = min(self.throttle + 1.0 * dt, 1.0)
        if keys_pressed[pygame.K_LCTRL]:
            self.throttle = max(self.throttle - 1.0 * dt, 0.0)

        # Roll damping (aircraft naturally levels out)
        if not keys_pressed[pygame.K_a] and not keys_pressed[pygame.K_d]:
            if abs(self.roll) > 1:
                self.roll *= 0.95

class EnemyAircraft(BaseAircraft):
    """AI-controlled enemy aircraft"""
    
    def __init__(self, aircraft_type: AircraftType, position: Vector3, behavior: AIBehavior = AIBehavior.PATROL):
        super().__init__(aircraft_type, position)
        self.ai_behavior = behavior
        self.is_player = False
