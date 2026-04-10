"""
Hellcats Over the Pacific - Enhanced Edition
=============================================
Complete flight simulator with combat, missions, realistic aircraft physics,
terrain rendering, cockpit instruments, and sound effects.

Consolidated from the original prototype and enhanced edition.
"""

import pygame
import math
import time
import random
import array
from typing import List, Dict, Tuple, Optional
from aircraft import PlayerAircraft, EnemyAircraft, BaseAircraft, Vector3, AircraftType, AIBehavior
from enum import Enum

# Constants
SCREEN_WIDTH = 1024
SCREEN_HEIGHT = 768
FPS = 60

# Colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
BLUE = (0, 100, 200)
GREEN = (0, 128, 0)
BROWN = (139, 69, 19)
GRAY = (128, 128, 128)
RED = (255, 0, 0)
YELLOW = (255, 255, 0)
BEACH_COLOR = (238, 203, 173)
JUNGLE_COLOR = (34, 139, 34)
MOUNTAIN_COLOR = (105, 105, 105)
WATER_COLOR = (0, 105, 148)


class GameState(Enum):
    MAIN_MENU = "main_menu"
    FLYING = "flying"


class ViewMode(Enum):
    FIRST_PERSON = "first_person"
    THIRD_PERSON = "third_person"


class Projectile:
    """Bullet/shell projectile"""
    def __init__(self, position: Vector3, velocity: Vector3, damage: float, owner: BaseAircraft):
        self.position = position
        self.velocity = velocity
        self.damage = damage
        self.owner = owner
        self.time_to_live = 3.0
        self.active = True

    def update(self, dt: float):
        if not self.active:
            return
        self.position = self.position + (self.velocity * dt)
        self.velocity.y -= 9.8 * dt
        self.time_to_live -= dt
        if self.time_to_live <= 0:
            self.active = False


class Mission:
    """Mission data and objectives"""
    def __init__(self, name: str, description: str, objectives: List[str]):
        self.name = name
        self.description = description
        self.objectives = objectives
        self.completed_objectives = set()
        self.time_limit = 1200.0
        self.enemy_aircraft: List[BaseAircraft] = []
        self.friendly_aircraft: List[BaseAircraft] = []

    def add_enemy(self, aircraft_type: AircraftType, position: Vector3, behavior: AIBehavior = AIBehavior.PATROL):
        enemy = EnemyAircraft(aircraft_type, position, behavior)
        self.enemy_aircraft.append(enemy)

    def add_friendly(self, aircraft_type: AircraftType, position: Vector3):
        friendly = EnemyAircraft(aircraft_type, position, AIBehavior.DEFEND)
        friendly.color = BLUE
        self.friendly_aircraft.append(friendly)


class EnhancedHellcatsSimulator:
    """Main game class — consolidated flight simulator with full combat and mission systems"""

    def __init__(self):
        pygame.init()

        # Sound system
        self.sound_enabled = False
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
            self._init_sounds()
            self.sound_enabled = True
        except Exception:
            print("Sound init failed — running without audio")

        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("Hellcats Over the Pacific - Enhanced Edition")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 24)
        self.big_font = pygame.font.Font(None, 48)
        self.small_font = pygame.font.Font(None, 18)

        # Game state
        self.state = GameState.MAIN_MENU
        self.running = True
        self.player = PlayerAircraft(Vector3(0, 2000, 0))

        # View mode and camera
        self.view_mode = ViewMode.FIRST_PERSON
        self.camera_pitch = 0.0
        self.camera_yaw = 0.0
        self.camera_roll = 0.0
        self.camera_distance = 100.0

        # Combat system
        self.projectiles: List[Projectile] = []
        self.explosions: List[Dict] = []
        self.muzzle_flash_time = 0.0

        # Mission system
        self.current_mission: Optional[Mission] = None
        self.mission_time = 0.0
        self.all_aircraft: List[BaseAircraft] = []

        # Statistics
        self.kills = 0
        self.shots_fired = 0
        self.hits = 0

    # ------------------------------------------------------------------
    # Sound generation (no numpy dependency)
    # ------------------------------------------------------------------

    def _init_sounds(self):
        """Generate sound effects programmatically"""
        self.gun_sound = self._generate_sound(duration=0.05, noise=True, volume=0.4, decay=40.0)
        self.explosion_sound = self._generate_sound(duration=0.4, noise=True, volume=0.6, decay=5.0, lowpass=True)
        self.engine_sound = self._generate_sound(duration=1.0, frequency=80, volume=0.15, decay=0.0)
        self.engine_sound.set_volume(0.15)
        self.engine_channel = pygame.mixer.Channel(0)

    def _generate_sound(self, duration=0.1, frequency=440, volume=0.3,
                        noise=False, decay=10.0, lowpass=False):
        sample_rate = 22050
        num_samples = int(sample_rate * duration)
        samples = array.array('h')
        prev_value = 0.0
        for i in range(num_samples):
            t = i / sample_rate
            envelope = max(0.0, math.exp(-t * decay)) if decay > 0 else 1.0
            if noise:
                value = random.uniform(-1, 1) * volume * envelope
            else:
                value = math.sin(2 * math.pi * frequency * t) * volume * envelope
            if lowpass:
                value = value * 0.3 + prev_value * 0.7
                prev_value = value
            sample = max(-32767, min(32767, int(value * 32767)))
            samples.append(sample)  # L
            samples.append(sample)  # R
        return pygame.mixer.Sound(buffer=samples)

    # ------------------------------------------------------------------
    # Mission factory — creates FRESH instances every time (restart fix)
    # ------------------------------------------------------------------

    def _create_mission(self, mission_key: str) -> Optional[Mission]:
        if mission_key == "guadalcanal":
            m = Mission(
                "Guadalcanal Scramble",
                "November 1942: Enemy bombers approaching Henderson Field. Scramble to intercept!",
                ["destroy_all_enemies", "protect_airfield"]
            )
            m.add_enemy(AircraftType.B5N_KATE, Vector3(5000, 3000, 8000), AIBehavior.ATTACK)
            m.add_enemy(AircraftType.B5N_KATE, Vector3(5200, 3100, 8200), AIBehavior.ATTACK)
            m.add_enemy(AircraftType.A6M_ZERO, Vector3(4800, 3500, 7500), AIBehavior.DEFEND)
            m.add_enemy(AircraftType.A6M_ZERO, Vector3(5400, 3600, 7800), AIBehavior.DEFEND)
            return m

        if mission_key == "carrier_strike":
            m = Mission(
                "Carrier Strike",
                "June 1944: Strike enemy carrier group in the Philippine Sea.",
                ["destroy_carrier", "destroy_escorts"]
            )
            for i in range(4):
                angle = (i * 90) + random.randint(-30, 30)
                dist = 3000 + random.randint(-500, 500)
                pos = Vector3(
                    dist * math.sin(math.radians(angle)),
                    2500 + random.randint(-300, 300),
                    dist * math.cos(math.radians(angle))
                )
                m.add_enemy(AircraftType.A6M_ZERO, pos, AIBehavior.DEFEND)
            return m

        if mission_key == "kamikaze":
            m = Mission(
                "Divine Wind Defense",
                "October 1944: Kamikaze aircraft attacking the task force. Defend the carriers!",
                ["destroy_all_kamikazes", "defend_carrier"]
            )
            for i in range(6):
                angle = random.randint(0, 360)
                dist = 8000 + random.randint(-1000, 1000)
                pos = Vector3(
                    dist * math.sin(math.radians(angle)),
                    1500 + random.randint(-200, 500),
                    dist * math.cos(math.radians(angle))
                )
                m.add_enemy(AircraftType.A6M_ZERO, pos, AIBehavior.KAMIKAZE)
            return m

        return None

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if self.state == GameState.MAIN_MENU:
                    if event.key == pygame.K_1:
                        self.start_mission("guadalcanal")
                    elif event.key == pygame.K_2:
                        self.start_mission("carrier_strike")
                    elif event.key == pygame.K_3:
                        self.start_mission("kamikaze")
                    elif event.key == pygame.K_q:
                        self.running = False
                elif self.state == GameState.FLYING:
                    if event.key == pygame.K_SPACE:
                        self.fire_player_weapons()
                    elif event.key == pygame.K_v:
                        # Toggle first/third person
                        if self.view_mode == ViewMode.FIRST_PERSON:
                            self.view_mode = ViewMode.THIRD_PERSON
                        else:
                            self.view_mode = ViewMode.FIRST_PERSON
                    elif event.key == pygame.K_ESCAPE:
                        if self.sound_enabled:
                            self.engine_channel.stop()
                        self.state = GameState.MAIN_MENU

    # ------------------------------------------------------------------
    # Mission lifecycle
    # ------------------------------------------------------------------

    def start_mission(self, mission_key: str):
        mission = self._create_mission(mission_key)
        if not mission:
            return

        self.current_mission = mission
        self.state = GameState.FLYING
        self.mission_time = 0.0

        self.player = PlayerAircraft(Vector3(0, 2000, 0))

        self.all_aircraft = [self.player]
        self.all_aircraft.extend(self.current_mission.enemy_aircraft)
        self.all_aircraft.extend(self.current_mission.friendly_aircraft)

        self.projectiles.clear()
        self.explosions.clear()
        self.muzzle_flash_time = 0.0

        self.camera_pitch = 0.0
        self.camera_yaw = 0.0
        self.camera_roll = 0.0

        self.kills = 0
        self.shots_fired = 0
        self.hits = 0

        if self.sound_enabled:
            self.engine_channel.play(self.engine_sound, loops=-1)

        print(f"Mission Started: {self.current_mission.name}")
        print(f"Objective: {self.current_mission.description}")

    # ------------------------------------------------------------------
    # Combat
    # ------------------------------------------------------------------

    def fire_player_weapons(self):
        current_time = time.time()
        new_projectiles = self.player.fire_weapons(current_time)

        # Apply slight per-gun spread
        for i, p in enumerate(new_projectiles):
            spread = (i - len(new_projectiles) / 2) * 0.01
            cos_s = math.cos(spread)
            sin_s = math.sin(spread)
            vx, vz = p['velocity'].x, p['velocity'].z
            p['velocity'].x = vx * cos_s - vz * sin_s
            p['velocity'].z = vx * sin_s + vz * cos_s

        self.projectiles.extend([
            Projectile(p['position'], p['velocity'], p['damage'], p['owner'])
            for p in new_projectiles
        ])

        if new_projectiles:
            self.shots_fired += len(new_projectiles)
            self.muzzle_flash_time = 0.1
            if self.sound_enabled:
                self.gun_sound.play()

    def update_combat(self, dt: float):
        # Update projectiles
        for projectile in self.projectiles[:]:
            projectile.update(dt)
            if not projectile.active:
                self.projectiles.remove(projectile)
                continue

            for aircraft in self.all_aircraft:
                if aircraft == projectile.owner or aircraft.health <= 0:
                    continue
                distance = projectile.position.distance_to(aircraft.position)
                if distance < 20:
                    aircraft.take_damage(projectile.damage)
                    self.hits += 1
                    self.explosions.append({
                        'position': Vector3(aircraft.position.x, aircraft.position.y, aircraft.position.z),
                        'time': 0.5,
                        'size': 30 if projectile.damage > 20 else 15
                    })
                    projectile.active = False
                    if projectile in self.projectiles:
                        self.projectiles.remove(projectile)
                    if aircraft.health <= 0 and not aircraft.is_player:
                        self.kills += 1
                        if self.sound_enabled:
                            self.explosion_sound.play()
                        print(f"Enemy {aircraft.type.value} destroyed!")
                    break

        # Update explosions
        for explosion in self.explosions[:]:
            explosion['time'] -= dt
            if explosion['time'] <= 0:
                self.explosions.remove(explosion)

        # AI weapons fire
        current_time = time.time()
        for aircraft in self.all_aircraft:
            if not aircraft.is_player and aircraft.health > 0 and aircraft.target:
                if aircraft.position.distance_to(aircraft.target.position) < 800:
                    target_vector = aircraft.target.position - aircraft.position
                    yaw_rad = math.radians(aircraft.yaw)
                    forward = Vector3(math.sin(yaw_rad), 0, math.cos(yaw_rad))
                    mag = target_vector.magnitude()
                    if mag > 0:
                        dot = (target_vector.x * forward.x + target_vector.z * forward.z) / mag
                        if dot > 0.7 and random.random() < 0.1:
                            ai_proj = aircraft.fire_weapons(current_time)
                            self.projectiles.extend([
                                Projectile(p['position'], p['velocity'], p['damage'], p['owner'])
                                for p in ai_proj
                            ])

    # ------------------------------------------------------------------
    # Game logic
    # ------------------------------------------------------------------

    def update_game_logic(self, dt: float):
        if self.state != GameState.FLYING:
            return

        self.mission_time += dt
        self.muzzle_flash_time = max(0, self.muzzle_flash_time - dt)

        # Player input
        keys_pressed = pygame.key.get_pressed()
        self.player.handle_input(keys_pressed, dt)

        # Continuous fire while space held
        if keys_pressed[pygame.K_SPACE]:
            self.fire_player_weapons()

        # Update all aircraft
        for aircraft in self.all_aircraft:
            if aircraft.health > 0:
                aircraft.update_physics(dt)
                if not aircraft.is_player:
                    aircraft.update_ai(dt, self.player, self.all_aircraft)

        # Update combat
        self.update_combat(dt)

        # Camera smoothing
        if self.view_mode == ViewMode.FIRST_PERSON:
            self.camera_pitch = self.player.pitch * 0.9 + self.camera_pitch * 0.1
            self.camera_yaw = self.player.yaw * 0.9 + self.camera_yaw * 0.1
            self.camera_roll = self.player.roll * 0.9 + self.camera_roll * 0.1
        else:
            self.camera_pitch = (self.player.pitch - 10) * 0.8 + self.camera_pitch * 0.2
            self.camera_yaw = self.player.yaw * 0.9 + self.camera_yaw * 0.1
            self.camera_roll = self.player.roll * 0.5

        # Engine sound pitch follows throttle
        if self.sound_enabled and self.engine_channel.get_busy():
            self.engine_sound.set_volume(0.08 + self.player.throttle * 0.20)

        # Mission checks
        if self.current_mission:
            enemies_alive = sum(1 for a in self.current_mission.enemy_aircraft if a.health > 0)
            if enemies_alive == 0:
                print("Mission Complete - All enemies destroyed!")
                if self.sound_enabled:
                    self.engine_channel.stop()
                self.state = GameState.MAIN_MENU
            if self.player.health <= 0:
                print("Mission Failed - Aircraft destroyed!")
                if self.sound_enabled:
                    self.engine_channel.stop()
                self.state = GameState.MAIN_MENU
            if self.mission_time > self.current_mission.time_limit:
                print("Mission Failed - Time limit exceeded!")
                if self.sound_enabled:
                    self.engine_channel.stop()
                self.state = GameState.MAIN_MENU

    # ------------------------------------------------------------------
    # 3D projection helpers
    # ------------------------------------------------------------------

    def _get_camera_pos(self) -> Vector3:
        if self.view_mode == ViewMode.THIRD_PERSON:
            yaw_rad = math.radians(self.player.yaw)
            return Vector3(
                self.player.position.x - self.camera_distance * math.sin(yaw_rad),
                self.player.position.y + self.camera_distance * 0.3,
                self.player.position.z - self.camera_distance * math.cos(yaw_rad)
            )
        return self.player.position

    def project_3d_to_screen(self, world_pos: Vector3) -> Optional[Tuple[int, int]]:
        camera_pos = self._get_camera_pos()
        relative_pos = world_pos - camera_pos

        yaw_rad = math.radians(-self.camera_yaw)
        pitch_rad = math.radians(-self.camera_pitch)

        rotated_x = relative_pos.x * math.cos(yaw_rad) - relative_pos.z * math.sin(yaw_rad)
        rotated_z = relative_pos.x * math.sin(yaw_rad) + relative_pos.z * math.cos(yaw_rad)
        rotated_y = relative_pos.y

        final_y = rotated_y * math.cos(pitch_rad) - rotated_z * math.sin(pitch_rad)
        final_z = rotated_y * math.sin(pitch_rad) + rotated_z * math.cos(pitch_rad)

        if final_z <= 0:
            return None

        perspective_scale = 400.0 / final_z
        screen_x = SCREEN_WIDTH // 2 + int(rotated_x * perspective_scale)
        screen_y = SCREEN_HEIGHT // 2 - int(final_y * perspective_scale)

        if 0 <= screen_x <= SCREEN_WIDTH and 0 <= screen_y <= SCREEN_HEIGHT:
            return (screen_x, screen_y)
        return None

    # ------------------------------------------------------------------
    # Rendering — scene
    # ------------------------------------------------------------------

    def render_3d_scene(self):
        """Render the full 3D flight scene with roll rotation"""
        if abs(self.camera_roll) > 0.5:
            # Render to temp surface, then rotate for roll effect
            temp_surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
            self._render_scene_to_surface(temp_surface)
            rotated = pygame.transform.rotate(temp_surface, self.camera_roll)
            rect = rotated.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2))
            self.screen.fill(BLACK)
            self.screen.blit(rotated, rect)
        else:
            self._render_scene_to_surface(self.screen)

        # Cockpit frame in first person only
        if self.view_mode == ViewMode.FIRST_PERSON:
            self._render_cockpit_frame()

    def _render_scene_to_surface(self, surface):
        sky_color = (135, 206, 235)
        water_color = (0, 105, 148)
        ground_color = (34, 139, 34)

        horizon_y = SCREEN_HEIGHT // 2 + int(self.camera_pitch * 3)

        # Sky gradient
        for y in range(min(horizon_y, SCREEN_HEIGHT)):
            f = y / SCREEN_HEIGHT
            color = (
                int(sky_color[0] * (1 - f * 0.4)),
                int(sky_color[1] * (1 - f * 0.4)),
                int(sky_color[2])
            )
            pygame.draw.line(surface, color, (0, y), (SCREEN_WIDTH, y))

        # Water/ground gradient
        surface_color = water_color if self.player.position.y > 50 else ground_color
        for y in range(max(0, horizon_y), SCREEN_HEIGHT):
            denom = SCREEN_HEIGHT - horizon_y
            f = (y - horizon_y) / denom if denom > 0 else 0
            color = (
                int(surface_color[0] * (1 - f * 0.6)),
                int(surface_color[1] * (1 - f * 0.6)),
                int(surface_color[2] * (1 - f * 0.6))
            )
            pygame.draw.line(surface, color, (0, y), (SCREEN_WIDTH, y))

        # Terrain
        self._render_guadalcanal_terrain(surface)

        # Aircraft sprites
        for aircraft in self.all_aircraft:
            if aircraft.health > 0:
                if aircraft == self.player:
                    if self.view_mode == ViewMode.THIRD_PERSON:
                        self._render_player_third_person(surface)
                else:
                    screen_pos = aircraft.get_screen_position(
                        self.player if self.view_mode == ViewMode.FIRST_PERSON
                        else self._make_camera_aircraft(),
                        SCREEN_WIDTH, SCREEN_HEIGHT
                    )
                    if screen_pos:
                        self._render_aircraft_sprite(surface, aircraft, screen_pos)

        # Projectiles
        for proj in self.projectiles:
            if proj.active:
                screen_pos = self.project_3d_to_screen(proj.position)
                if screen_pos:
                    pygame.draw.circle(surface, YELLOW, screen_pos, 2)

        # Explosions
        for expl in self.explosions:
            screen_pos = self.project_3d_to_screen(expl['position'])
            if screen_pos:
                size = int(expl['size'] * (1 - expl['time'] / 0.5))
                intensity = int(255 * (expl['time'] / 0.5))
                color = (255, max(0, min(255, intensity)), 0)
                pygame.draw.circle(surface, color, screen_pos, max(1, size))

    def _make_camera_aircraft(self) -> BaseAircraft:
        """Create a dummy aircraft at the camera position for 3rd-person projection"""
        cam = BaseAircraft(AircraftType.F6F_HELLCAT, self._get_camera_pos())
        cam.yaw = self.camera_yaw
        cam.pitch = self.camera_pitch
        return cam

    # ------------------------------------------------------------------
    # Terrain rendering (Guadalcanal)
    # ------------------------------------------------------------------

    def _render_guadalcanal_terrain(self, surface):
        island_center = Vector3(0, 0, 15000)
        relative_pos = island_center - self.player.position
        yaw_rad = math.radians(-self.camera_yaw)

        rotated_x = relative_pos.x * math.cos(yaw_rad) - relative_pos.z * math.sin(yaw_rad)
        rotated_z = relative_pos.x * math.sin(yaw_rad) + relative_pos.z * math.cos(yaw_rad)

        if rotated_z > 100:
            scale = 1000.0 / max(rotated_z, 0.001)
            screen_x = SCREEN_WIDTH // 2 + int(rotated_x * scale)
            screen_y = SCREEN_HEIGHT // 2 + int(self.camera_pitch * 2)

            iw = max(20, int(8000 * scale))
            ih = max(10, int(2000 * scale))

            if -iw <= screen_x <= SCREEN_WIDTH + iw:
                # Beach
                pygame.draw.polygon(surface, BEACH_COLOR, [
                    (screen_x - iw, screen_y),
                    (screen_x + iw, screen_y),
                    (screen_x + iw - 20, screen_y - 20),
                    (screen_x - iw + 20, screen_y - 20)
                ])
                # Jungle
                pygame.draw.polygon(surface, JUNGLE_COLOR, [
                    (screen_x - iw + 20, screen_y - 20),
                    (screen_x + iw - 20, screen_y - 20),
                    (screen_x + iw - 60, screen_y - ih),
                    (screen_x - iw + 60, screen_y - ih)
                ])
                # Mountain peaks
                peaks = [
                    (screen_x - iw // 3, screen_y - ih,
                     screen_x - iw // 3 - 30, screen_y - ih - 60,
                     screen_x - iw // 3 + 30, screen_y - ih - 60),
                    (screen_x, screen_y - ih,
                     screen_x - 25, screen_y - ih - 40,
                     screen_x + 25, screen_y - ih - 40),
                    (screen_x + iw // 3, screen_y - ih,
                     screen_x + iw // 3 - 20, screen_y - ih - 35,
                     screen_x + iw // 3 + 20, screen_y - ih - 35),
                ]
                for p in peaks:
                    pygame.draw.polygon(surface, MOUNTAIN_COLOR,
                                        [(p[0], p[1]), (p[2], p[3]), (p[4], p[5])])

        # Henderson Field airstrip
        airfield_pos = Vector3(-2000, 50, 12000)
        ra = airfield_pos - self.player.position
        ra_x = ra.x * math.cos(yaw_rad) - ra.z * math.sin(yaw_rad)
        ra_z = ra.x * math.sin(yaw_rad) + ra.z * math.cos(yaw_rad)
        if 10 < ra_z < 5000:
            s = 800.0 / ra_z
            sx = SCREEN_WIDTH // 2 + int(ra_x * s)
            sy = SCREEN_HEIGHT // 2 + int(self.camera_pitch * 2)
            if 0 <= sx <= SCREEN_WIDTH:
                rl = max(10, int(300 * s))
                rw = max(2, int(30 * s))
                pygame.draw.rect(surface, GRAY, (sx - rl // 2, sy - rw // 2, rl, rw))

        # Surrounding islands
        for offset_x, offset_z, sz in [(8000, 20000, 0.3), (-15000, 18000, 0.2), (25000, 5000, 0.4)]:
            ip = Vector3(offset_x, 0, offset_z) - self.player.position
            ix = ip.x * math.cos(yaw_rad) - ip.z * math.sin(yaw_rad)
            iz = ip.x * math.sin(yaw_rad) + ip.z * math.cos(yaw_rad)
            if iz > 500:
                s = 600.0 / iz
                sx = SCREEN_WIDTH // 2 + int(ix * s)
                sy = SCREEN_HEIGHT // 2 + int(self.camera_pitch * 2)
                if -100 <= sx <= SCREEN_WIDTH + 100:
                    isz = max(5, int(1000 * sz * s))
                    pygame.draw.polygon(surface, JUNGLE_COLOR, [
                        (sx - isz, sy), (sx + isz, sy), (sx, sy - isz // 2)
                    ])

    # ------------------------------------------------------------------
    # Aircraft sprite rendering
    # ------------------------------------------------------------------

    def _render_aircraft_sprite(self, surface, aircraft: BaseAircraft, screen_pos: Tuple[int, int]):
        x, y = screen_pos
        distance = self.player.position.distance_to(aircraft.position)
        size = max(3, int(50 / (distance / 100)))
        color = aircraft.color

        if aircraft.type == AircraftType.F6F_HELLCAT:
            points = [
                (x, y - size), (x - size // 2, y),
                (x - size // 3, y + size), (x + size // 3, y + size),
                (x + size // 2, y),
            ]
        elif aircraft.type == AircraftType.A6M_ZERO:
            points = [
                (x, y - size), (x - size // 3, y),
                (x - size // 4, y + size), (x + size // 4, y + size),
                (x + size // 3, y),
            ]
        else:
            points = [
                (x, y - size), (x - size, y - size // 2),
                (x - size, y + size), (x + size, y + size),
                (x + size, y - size // 2)
            ]

        pygame.draw.polygon(surface, color, points)

        if aircraft.health < 100:
            hc = GREEN if aircraft.health > 70 else (YELLOW if aircraft.health > 30 else RED)
            hw = int((size * 2) * (aircraft.health / 100))
            pygame.draw.rect(surface, hc, (x - size, y - size - 10, hw, 3))

    # ------------------------------------------------------------------
    # Third-person player aircraft (detailed Hellcat model)
    # ------------------------------------------------------------------

    def _render_player_third_person(self, surface):
        cx = SCREEN_WIDTH // 2
        cy = SCREEN_HEIGHT // 2 + 50
        self._draw_hellcat_detailed(surface, cx, cy, 60, self.player.roll)

    def _draw_hellcat_detailed(self, surface, x, y, size, roll_angle):
        aircraft_blue = (0, 50, 150)
        wing_blue = (0, 70, 180)
        prop_gray = (100, 100, 100)

        roll_rad = math.radians(roll_angle)
        cos_r = math.cos(roll_rad)
        sin_r = math.sin(roll_rad)

        def rp(px, py):
            dx, dy = px - x, py - y
            return (x + dx * cos_r - dy * sin_r, y + dx * sin_r + dy * cos_r)

        # Fuselage
        fuselage = [
            (x, y - size), (x - size // 6, y - size // 2),
            (x + size // 6, y - size // 2), (x - size // 8, y + size // 2),
            (x + size // 8, y + size // 2), (x, y + size)
        ]
        pygame.draw.polygon(surface, aircraft_blue, [rp(px, py) for px, py in fuselage])

        # Left wing
        lw = [(x - size // 6, y - size // 3), (x - size, y - size // 6),
              (x - size + size // 8, y + size // 6), (x - size // 8, y)]
        pygame.draw.polygon(surface, wing_blue, [rp(px, py) for px, py in lw])

        # Right wing
        rw = [(x + size // 6, y - size // 3), (x + size, y - size // 6),
              (x + size - size // 8, y + size // 6), (x + size // 8, y)]
        pygame.draw.polygon(surface, wing_blue, [rp(px, py) for px, py in rw])

        # Propeller
        prop_rot = (time.time() * 2000) % 360
        for i in range(3):
            angle = math.radians(prop_rot + i * 120)
            bx = x + (size // 3) * math.sin(angle)
            by = (y - size) + (size // 3) * math.cos(angle)
            pygame.draw.line(surface, prop_gray, rp(x, y - size), rp(bx, by), 3)

        # Canopy
        canopy = [(x - size // 8, y - size // 2), (x + size // 8, y - size // 2),
                  (x + size // 10, y - size // 4), (x - size // 10, y - size // 4)]
        pygame.draw.polygon(surface, (200, 200, 255), [rp(px, py) for px, py in canopy])

        # Engine cowling
        er = size // 8
        ec = rp(x, y - size + er)
        pygame.draw.circle(surface, (80, 80, 80), (int(ec[0]), int(ec[1])), er)

    # ------------------------------------------------------------------
    # Cockpit & instruments
    # ------------------------------------------------------------------

    def _render_cockpit_frame(self):
        frame = (64, 64, 64)
        pygame.draw.rect(self.screen, frame, (0, 0, SCREEN_WIDTH, 40))
        pygame.draw.rect(self.screen, frame, (0, 0, 60, SCREEN_HEIGHT))
        pygame.draw.rect(self.screen, frame, (SCREEN_WIDTH - 60, 0, 60, SCREEN_HEIGHT))
        pygame.draw.rect(self.screen, frame, (0, SCREEN_HEIGHT - 120, SCREEN_WIDTH, 120))

        self._render_artificial_horizon()
        self._render_compass()

    def _render_artificial_horizon(self):
        cx, cy = 150, SCREEN_HEIGHT - 60
        r = 40
        pygame.draw.circle(self.screen, BLACK, (cx, cy), r)
        pygame.draw.circle(self.screen, WHITE, (cx, cy), r, 2)

        po = int(self.player.pitch * 0.5)
        roll_rad = math.radians(self.player.roll)
        ll = r - 5
        sx = cx - ll * math.cos(roll_rad)
        sy = cy + po - ll * math.sin(roll_rad)
        ex = cx + ll * math.cos(roll_rad)
        ey = cy + po + ll * math.sin(roll_rad)
        pygame.draw.line(self.screen, YELLOW, (sx, sy), (ex, ey), 2)
        pygame.draw.circle(self.screen, RED, (cx, cy), 3)
        pygame.draw.line(self.screen, RED, (cx - 10, cy), (cx + 10, cy), 2)

    def _render_compass(self):
        cx, cy = SCREEN_WIDTH - 150, SCREEN_HEIGHT - 60
        r = 40
        pygame.draw.circle(self.screen, BLACK, (cx, cy), r)
        pygame.draw.circle(self.screen, WHITE, (cx, cy), r, 2)

        for angle, label in [(0, 'N'), (90, 'E'), (180, 'S'), (270, 'W')]:
            a = math.radians(angle - self.player.yaw)
            tx = cx + 30 * math.sin(a)
            ty = cy - 30 * math.cos(a)
            ts = self.font.render(label, True, WHITE)
            tr = ts.get_rect(center=(tx, ty))
            self.screen.blit(ts, tr)

        hr = math.radians(-self.player.yaw)
        pygame.draw.line(self.screen, RED, (cx, cy),
                         (cx + 35 * math.sin(hr), cy + 35 * math.cos(hr)), 3)

    # ------------------------------------------------------------------
    # HUD
    # ------------------------------------------------------------------

    def render_hud(self):
        hud_surface = pygame.Surface((350, 270))
        hud_surface.set_alpha(200)
        hud_surface.fill((0, 20, 0))

        view_label = self.view_mode.value.upper().replace('_', ' ')
        lines = [
            f"ALT: {int(self.player.position.y)} ft",
            f"SPD: {int(self.player.current_speed)} mph",
            f"HDG: {int(self.player.yaw)}\u00b0",
            f"THR: {int(self.player.throttle * 100)}%",
            f"FUEL: {int(self.player.fuel)} gal",
            "",
            f"HEALTH: {int(self.player.health)}%",
            f"AMMO: {sum(w.ammo for w in self.player.weapons)}",
            "",
            f"KILLS: {self.kills}",
            f"ACCURACY: {int(self.hits / max(1, self.shots_fired) * 100)}%",
            f"VIEW: {view_label}",
        ]

        for i, line in enumerate(lines):
            color = WHITE
            if "HEALTH" in line and self.player.health < 50:
                color = RED
            elif "FUEL" in line and self.player.fuel < 50:
                color = YELLOW
            text = self.font.render(line, True, color)
            hud_surface.blit(text, (10, 10 + i * 20))

        self.screen.blit(hud_surface, (SCREEN_WIDTH - 360, 10))

    # ------------------------------------------------------------------
    # Radar
    # ------------------------------------------------------------------

    def render_radar(self):
        rc = (100, 100)
        rr = 80
        rs = pygame.Surface((200, 200))
        rs.set_alpha(180)
        rs.fill((0, 20, 0))

        pygame.draw.circle(rs, GREEN, rc, rr, 2)
        pygame.draw.circle(rs, GREEN, rc, rr // 2, 1)
        pygame.draw.line(rs, GREEN, (rc[0], 20), (rc[0], 180), 1)
        pygame.draw.line(rs, GREEN, (20, rc[1]), (180, rc[1]), 1)

        for aircraft in self.all_aircraft:
            if aircraft == self.player or aircraft.health <= 0:
                continue
            rp = aircraft.position - self.player.position
            d = rp.magnitude()
            if d < 10000:
                s = rr / 10000
                rx = rc[0] + int(rp.x * s)
                ry = rc[1] - int(rp.z * s)
                dc = BLUE if aircraft.type == AircraftType.F6F_HELLCAT else RED
                if 20 <= rx <= 180 and 20 <= ry <= 180:
                    pygame.draw.circle(rs, dc, (rx, ry), 3)

        pygame.draw.circle(rs, WHITE, rc, 4)
        self.screen.blit(rs, (10, 10))

    # ------------------------------------------------------------------
    # Mission HUD
    # ------------------------------------------------------------------

    def render_mission_hud(self):
        if not self.current_mission:
            return

        ss = pygame.Surface((400, 120))
        ss.set_alpha(180)
        ss.fill((20, 0, 0))

        mt = self.font.render(f"MISSION: {self.current_mission.name.upper()}", True, WHITE)
        tr = max(0, self.current_mission.time_limit - self.mission_time)
        tt = self.font.render(f"TIME: {int(tr // 60):02d}:{int(tr % 60):02d}", True, WHITE)

        enemies_alive = sum(1 for a in self.current_mission.enemy_aircraft if a.health > 0)
        ot = self.font.render(f"ENEMIES: {enemies_alive}", True, RED if enemies_alive > 0 else GREEN)

        ss.blit(mt, (10, 10))
        ss.blit(tt, (10, 35))
        ss.blit(ot, (10, 60))

        nearest = float('inf')
        for a in self.all_aircraft:
            if not a.is_player and a.health > 0:
                nearest = min(nearest, self.player.position.distance_to(a.position))
        if nearest < 1000:
            wt = self.font.render("*** ENEMY CLOSE ***", True, RED)
            ss.blit(wt, (10, 85))

        self.screen.blit(ss, (10, SCREEN_HEIGHT - 140))

    # ------------------------------------------------------------------
    # Main menu
    # ------------------------------------------------------------------

    def render_main_menu(self):
        self.screen.fill(BLACK)

        title = self.big_font.render("HELLCATS OVER THE PACIFIC", True, WHITE)
        self.screen.blit(title, title.get_rect(center=(SCREEN_WIDTH // 2, 80)))

        sub = self.font.render("Enhanced Edition - F6F Hellcat Combat Simulator", True, GRAY)
        self.screen.blit(sub, sub.get_rect(center=(SCREEN_WIDTH // 2, 120)))

        missions = [
            ("1. GUADALCANAL SCRAMBLE", "Intercept Japanese bombers attacking Henderson Field"),
            ("2. CARRIER STRIKE", "Attack enemy fleet in the Philippine Sea"),
            ("3. KAMIKAZE DEFENSE", "Defend the task force from suicide attacks"),
            ("", ""),
            ("Q. QUIT", "Exit the simulator")
        ]
        for i, (t, d) in enumerate(missions):
            y = 200 + i * 60
            if t:
                ts = self.font.render(t, True, WHITE)
                self.screen.blit(ts, ts.get_rect(center=(SCREEN_WIDTH // 2, y)))
            if d:
                ds = self.small_font.render(d, True, GRAY)
                self.screen.blit(ds, ds.get_rect(center=(SCREEN_WIDTH // 2, y + 25)))

        ct = self.font.render("FLIGHT CONTROLS", True, WHITE)
        self.screen.blit(ct, (50, 500))

        controls = [
            "W/S: Pitch Up/Down    A/D: Roll Left/Right",
            "Q/E: Rudder Left/Right    Shift/Ctrl: Throttle",
            "SPACE: Fire Guns    V: Toggle View    ESC: Menu"
        ]
        for i, c in enumerate(controls):
            self.screen.blit(self.small_font.render(c, True, GRAY), (50, 530 + i * 20))

        hist = [
            "Historical Note:",
            "The F6F Hellcat was the primary US Navy carrier fighter",
            "during the Pacific War, with a 19:1 kill ratio against",
            "Japanese aircraft. Fast and rugged, it dominated the",
            "skies from 1943-1945."
        ]
        for i, line in enumerate(hist):
            color = YELLOW if i == 0 else GRAY
            self.screen.blit(self.small_font.render(line, True, color),
                             (SCREEN_WIDTH - 400, 500 + i * 20))

    # ------------------------------------------------------------------
    # Master render
    # ------------------------------------------------------------------

    def render(self):
        if self.state == GameState.MAIN_MENU:
            self.render_main_menu()
        elif self.state == GameState.FLYING:
            self.render_3d_scene()
            self.render_hud()
            self.render_radar()
            self.render_mission_hud()

            # Crosshair
            ch_color = YELLOW if self.muzzle_flash_time > 0 else WHITE
            cx, cy = SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2
            pygame.draw.line(self.screen, ch_color, (cx - 15, cy), (cx + 15, cy), 2)
            pygame.draw.line(self.screen, ch_color, (cx, cy - 15), (cx, cy + 15), 2)
            pygame.draw.circle(self.screen, ch_color, (cx, cy), 20, 1)

            # Muzzle flash
            if self.muzzle_flash_time > 0:
                flash_size = int(self.muzzle_flash_time * 200)
                if flash_size > 0:
                    pygame.draw.circle(self.screen, YELLOW, (cx, cy + 100), flash_size)

        pygame.display.flip()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        print("=" * 60)
        print("HELLCATS OVER THE PACIFIC - Enhanced Edition")
        print("=" * 60)
        print("F6F Hellcat Combat Flight Simulator")
        print("Recreating the classic 1991 naval aviation experience")
        print("")
        print("Controls: W/S/A/D + Q/E + Shift/Ctrl + Space + V")
        print("=" * 60)

        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            self.handle_events()
            self.update_game_logic(dt)
            self.render()

        if self.sound_enabled:
            pygame.mixer.quit()
        pygame.quit()


if __name__ == "__main__":
    game = EnhancedHellcatsSimulator()
    game.run()
