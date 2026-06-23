"""In-game rendering: views, HUD, instruments."""
import math
import pygame
from hellcats.bootstrap import (
    WIDTH, HEIGHT, WHITE, BLACK, HUD_GREEN, HUD_AMBER, HUD_RED,
    font_large, font_med, font_small, font_tiny,
    satellite_map, MAP_WIDTH, MAP_HEIGHT,
    _get_ai_mask, _panel_surface, _map_surface, _haze_surface,
    CAMERA_OVERHEAD, CAMERA_COCKPIT, CAMERA_CHASE, CAMERA_NAMES,
)
from hellcats.hotp import hotp_rng
from hellcats.map_geo import feet_to_pixel, geo_to_pixel
from hellcats.aircraft import F6F_Hellcat, F4U_Corsair, Boeing747_200
from hellcats.disasters import DisasterAircraft
from hellcats.friendly import FriendlyBomber

# ============== GAME DRAWING FUNCTIONS ==============
# ============== CAMERA VIEWS ==============
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

    is_747 = isinstance(aircraft, (Boeing747_200, DisasterAircraft))

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
                def er(px, py, sx=screen_x, sy=screen_y, ch=cos_h, sh=sin_h):
                    return (sx + px * ch - py * sh,
                            sy + px * sh + py * ch)
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

    if isinstance(aircraft, (Boeing747_200, DisasterAircraft)):
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

    max_spd = 450 if (isinstance(aircraft, Boeing747_200) or getattr(aircraft, 'VNE', 0) > 400) else 400
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


