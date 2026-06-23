"""One-time utility: split hellcat_sim.py into hellcats/ package modules."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "hellcat_sim.py"
PKG = ROOT / "hellcats"

SECTIONS = [
    ("hotp.py", 35, 163, '''"""HOTP authentic RNG and flight math from the 1991 binary."""
import math

'''),
    ("weather.py", 164, 316, '''"""Weather system."""
import math
import pygame
from hellcats.hotp import hotp_rng

'''),
    ("time_of_day.py", 317, 446, '''"""Day/night, stars, flares, searchlights."""
import random
import pygame

'''),
    ("radio.py", 447, 593, '''"""Radio chatter system."""
import random

'''),
    ("sound.py", 594, 705, '''"""Procedural sound effects."""
import math
import pygame

'''),
    ("map_geo.py", 749, 945, '''"""Satellite map loading and geo projection."""
import math
import os
import pygame

'''),
    ("fdr.py", 947, 990, '''"""Flight data recorder."""
from hellcats.bootstrap import PHYSICS_DT

'''),
    ("weapons.py", 991, 1316, '''"""Weapons and projectiles."""
import math
import pygame
from hellcats.hotp import hotp_rng
from hellcats.bootstrap import PHYSICS_DT

'''),
    ("targets.py", 1317, 2301, '''"""Targets, ships, enemies, target manager."""
import math
import pygame
from hellcats.hotp import (
    hotp_rng, HOTP_FLAG_JITTER_AXIS1, HOTP_FLAG_JITTER_AXIS2,
    HOTP_FLAG_CONTROL_GATE, HOTP_FLAG_SMOOTH_CTRL,
    hotp_delta_smooth, hotp_delta_smooth_s16, hotp_aero_lookup,
    hotp_fun_e570, hotp_fun_e468,
)
from hellcats.bootstrap import PHYSICS_DT

'''),
    ("friendly.py", 2302, 2672, '''"""Friendly carrier, wingmen, bombers."""
import math
from hellcats.hotp import hotp_rng
from hellcats.bootstrap import PHYSICS_DT

'''),
    ("missions.py", 2673, 3338, '''"""Combat missions and campaign mode."""
import math
from hellcats.weather import Weather
from hellcats.time_of_day import TimeOfDay
from hellcats.targets import EnemyAircraft, Ship, GroundTarget
from hellcats.friendly import FriendlyBomber
from hellcats.bootstrap import PHYSICS_DT, WIDTH, HEIGHT, HUD_GREEN, HUD_AMBER, WHITE
import pygame

'''),
    ("dossier.py", 3339, 3659, '''"""Pilot dossier and input replay."""
import json
import os
from hellcats.bootstrap import WIDTH, HEIGHT, HUD_GREEN, HUD_AMBER, WHITE
import pygame

'''),
    ("aircraft.py", 3660, 4429, '''"""Flyable aircraft physics."""
import math
import random
from hellcats.bootstrap import (
    MAP_CENTER_LAT, MAP_CENTER_LON, PHYSICS_DT,
)
from hellcats.hotp import hotp_rng

'''),
    ("disasters.py", 4430, 4776, '''"""Historical disaster scenarios."""
import math
from hellcats.aircraft import Boeing747_200

'''),
    ("render_aircraft.py", 4777, 5053, '''"""Side-view aircraft art for menus."""
import pygame
from hellcats.bootstrap import WHITE, HUD_GREEN, HUD_AMBER

'''),
    ("ui_menu.py", 5054, 5301, '''"""Home screen and menus."""
import pygame
from hellcats.bootstrap import (
    WIDTH, HEIGHT, WHITE, HUD_GREEN, HUD_AMBER,
    font_title, font_large, font_med, font_tiny,
)
from hellcats.render_aircraft import draw_f6f_rendering, draw_f4u_rendering, draw_747_rendering

'''),
    ("render_game.py", 5302, 7236, '''"""In-game rendering: views, HUD, instruments."""
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

'''),
    ("game.py", 7237, 8068, '''"""Main game loop."""
import math
import pygame
from hellcats import bootstrap
from hellcats.bootstrap import (
    screen, clock, WIDTH, HEIGHT, PHYSICS_DT,
    WHITE, HUD_GREEN, HUD_AMBER, HUD_RED,
    font_large, font_med, font_small, font_tiny,
    satellite_map, CAMERA_OVERHEAD, CAMERA_COCKPIT, CAMERA_CHASE,
)
from hellcats.hotp import hotp_rng
from hellcats.weather import Weather
from hellcats.time_of_day import TimeOfDay
from hellcats.radio import RadioChatter
from hellcats.sound import SoundManager
from hellcats.fdr import FlightDataRecorder
from hellcats.weapons import WeaponsManager
from hellcats.targets import TargetManager
from hellcats.friendly import FriendlyCarrier, FriendlyAircraft
from hellcats.missions import MISSIONS, Campaign
from hellcats.dossier import PilotDossier, InputRecorder, draw_dossier
from hellcats.aircraft import F6F_Hellcat, F4U_Corsair, Boeing747_200
from hellcats.disasters import DISASTER_SCENARIOS, DisasterAircraft
from hellcats.ui_menu import draw_home_screen, draw_mission_briefing
from hellcats.render_game import (
    draw_cockpit_view, draw_chase_view, draw_map_view,
    draw_instruments, draw_stall_warning, draw_g_effects,
    draw_weapons_overhead, draw_weapons_cockpit, draw_weapons_hud,
    draw_targets_overhead, draw_targets_cockpit, draw_wingmen_3d,
    draw_score_display, draw_friendly_carrier, draw_aircraft_symbol,
    draw_radar, draw_minimap, draw_mission_hud, draw_mission_result,
    draw_campaign_status,
)

'''),
]


def main():
    lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)
    PKG.mkdir(exist_ok=True)

    # bootstrap.py - pygame init block (706-748) + constants from elsewhere
    bootstrap_header = '''"""Display, fonts, and runtime bootstrap."""
import math
import os
import pygame

PHYSICS_DT = 1.0 / 60.0

# Populated by init()
screen = None
clock = None
WIDTH, HEIGHT = 1280, 900
HUD_GREEN = (0, 255, 0)
HUD_AMBER = (255, 191, 0)
HUD_RED = (255, 50, 50)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
NAVY_BLUE = (0, 30, 60)
SKY_BLUE = (135, 206, 235)
font_title = font_large = font_med = font_small = font_tiny = None
_panel_surface = _map_surface = _haze_surface = None
_ai_mask_cache = {}
satellite_map = None
MAP_FILE = None
MAP_NW_LAT = MAP_NW_LON = MAP_SE_LAT = MAP_SE_LON = 0.0
MAP_WIDTH = MAP_HEIGHT = 0
MAP_SCALE_FT_PER_PIXEL = 0.0
MAP_CENTER_LAT = MAP_CENTER_LON = 0.0
CAMERA_OVERHEAD = 0
CAMERA_COCKPIT = 1
CAMERA_CHASE = 2
CAMERA_NAMES = ["OVERHEAD", "COCKPIT", "CHASE"]


def _resource_path(filename):
    import sys
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, filename)
    return os.path.join(os.path.expanduser("~"), filename)


def _get_ai_mask(size):
    if size not in _ai_mask_cache:
        diam = size * 2
        mask = pygame.Surface((diam, diam))
        mask.fill((1, 1, 1))
        pygame.draw.circle(mask, (0, 0, 0), (size, size), size)
        mask.set_colorkey((0, 0, 0))
        _ai_mask_cache[size] = mask
    return _ai_mask_cache[size]


def init(pick_area=True):
    """Initialize pygame, fonts, and satellite map."""
    global screen, clock, font_title, font_large, font_med, font_small, font_tiny
    global _panel_surface, _map_surface, _haze_surface, satellite_map
    global MAP_FILE, MAP_NW_LAT, MAP_NW_LON, MAP_SE_LAT, MAP_SE_LON
    global MAP_WIDTH, MAP_HEIGHT, MAP_SCALE_FT_PER_PIXEL, MAP_CENTER_LAT, MAP_CENTER_LON

    from hellcats.map_geo import (
        _pick_flight_area, _resolve_area, _download_satellite_tiles,
        _placeholder_satellite_map, geo_to_pixel, feet_to_pixel,
    )

    pygame.mixer.pre_init(22050, -16, 1, 512)
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Hellcats Over the Pacific - Enhanced Edition")
    clock = pygame.time.Clock()

    pygame.font.init()
    font_title = pygame.font.Font(None, 72)
    font_large = pygame.font.Font(None, 56)
    font_med = pygame.font.Font(None, 36)
    font_small = pygame.font.Font(None, 28)
    font_tiny = pygame.font.Font(None, 22)

    _panel_surface = pygame.Surface((WIDTH, 250), pygame.SRCALPHA)
    _panel_surface.fill((20, 30, 40, 230))
    _map_surface = pygame.Surface((WIDTH, HEIGHT))
    _haze_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

    MAP_FILE = _resource_path("long_island_satellite.png")
    _DEFAULT_NW = (41.1125, -73.8281)
    _DEFAULT_SE = (40.5806, -72.7734)
    MAP_NW_LAT, MAP_NW_LON = _DEFAULT_NW
    MAP_SE_LAT, MAP_SE_LON = _DEFAULT_SE

    chosen = _resolve_area(_pick_flight_area()) if pick_area else None
    satellite_map = None

    if chosen is None:
        try:
            satellite_map = pygame.image.load(MAP_FILE)
            print(f"Loaded local satellite map: {MAP_FILE}")
        except (FileNotFoundError, pygame.error):
            try:
                satellite_map = _download_satellite_tiles(MAP_NW_LAT, MAP_NW_LON, MAP_SE_LAT, MAP_SE_LON)
            except Exception as e:
                print(f"Long Island tile download failed: {e}")
    else:
        n, w, s, e, label = chosen
        MAP_NW_LAT, MAP_NW_LON = n, w
        MAP_SE_LAT, MAP_SE_LON = s, e
        print(f"Flight area: {label}")
        print(f"  bounds  NW=({n:.3f},{w:.3f})  SE=({s:.3f},{e:.3f})")
        try:
            satellite_map = _download_satellite_tiles(n, w, s, e)
        except Exception as ex:
            print(f"Tile download failed: {ex}")

    if satellite_map is None:
        print("Using placeholder satellite map.")
        satellite_map = _placeholder_satellite_map()

    MAP_WIDTH, MAP_HEIGHT = satellite_map.get_size()
    _center_lat = (MAP_NW_LAT + MAP_SE_LAT) / 2
    _span_lon_ft = abs(MAP_SE_LON - MAP_NW_LON) * 364000 * math.cos(math.radians(_center_lat))
    _span_lat_ft = abs(MAP_NW_LAT - MAP_SE_LAT) * 364000
    MAP_SCALE_FT_PER_PIXEL = ((_span_lon_ft / MAP_WIDTH) + (_span_lat_ft / MAP_HEIGHT)) / 2
    MAP_CENTER_LAT = _center_lat
    MAP_CENTER_LON = (MAP_NW_LON + MAP_SE_LON) / 2

'''
    (PKG / "bootstrap.py").write_text(bootstrap_header, encoding="utf-8")

    for filename, start, end, header in SECTIONS:
        body = "".join(lines[start - 1 : end])
        (PKG / filename).write_text(header + body, encoding="utf-8")
        print(f"Wrote {filename} ({end - start + 1} lines)")

    init_py = '''"""Hellcats Over the Pacific - Enhanced Edition."""
from hellcats.game import main

__all__ = ["main"]
'''
    (PKG / "__init__.py").write_text(init_py, encoding="utf-8")
    print("Wrote __init__.py")


if __name__ == "__main__":
    main()