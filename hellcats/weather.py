"""Weather system."""
import math
import pygame
from hellcats.hotp import hotp_rng

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


