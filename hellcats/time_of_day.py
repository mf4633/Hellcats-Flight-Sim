"""Day/night, stars, flares, searchlights."""
import random
import pygame

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


