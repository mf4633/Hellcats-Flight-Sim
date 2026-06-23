"""Display, fonts, and runtime bootstrap."""
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

