"""Satellite map loading and geo projection."""
import math
import os
import pygame

# Load satellite map
def _resource_path(filename):
    """Get path to bundled resource (works for PyInstaller and normal execution)"""
    import sys
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, filename)
    return os.path.join(os.path.expanduser('~'), filename)

MAP_FILE = _resource_path("long_island_satellite.png")

# Default Long Island bounds (matches long_island_satellite.png)
_DEFAULT_NW = (41.1125, -73.8281)
_DEFAULT_SE = (40.5806, -72.7734)


def _placeholder_satellite_map(width=1536, height=1024):
    surf = pygame.Surface((width, height))
    surf.fill((0, 105, 148))  # water blue, matches in-game ocean color
    try:
        font = pygame.font.SysFont("Arial", 36, bold=True)
        notice = font.render("satellite map unavailable - placeholder", True, (255, 200, 0))
        for x in range(0, width, 700):
            for y in range(0, height, 250):
                surf.blit(notice, (x + 20, y + 20))
    except pygame.error:
        pass
    return surf


def _slippy_tile_xy(lat, lon, zoom):
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def _download_satellite_tiles(lat_n, lon_w, lat_s, lon_e, zoom=11):
    """Fetch ESRI World Imagery tiles for a bbox; stitch + crop to exact bounds.
    Cached to ~/.hellcat_tile_cache/. Returns a pygame.Surface."""
    import urllib.request, io, hashlib
    cache_dir = os.path.join(os.path.expanduser('~'), '.hellcat_tile_cache')
    os.makedirs(cache_dir, exist_ok=True)
    key = hashlib.md5(f"{lat_n:.4f}_{lon_w:.4f}_{lat_s:.4f}_{lon_e:.4f}_{zoom}".encode()).hexdigest()[:16]
    cache_file = os.path.join(cache_dir, f"map_{key}.png")
    if os.path.exists(cache_file):
        try:
            return pygame.image.load(cache_file)
        except pygame.error:
            pass

    fx_w, fy_n = _slippy_tile_xy(lat_n, lon_w, zoom)
    fx_e, fy_s = _slippy_tile_xy(lat_s, lon_e, zoom)
    x0, y0 = int(math.floor(fx_w)), int(math.floor(fy_n))
    x1, y1 = int(math.ceil(fx_e)), int(math.ceil(fy_s))
    n_tiles = max(0, (x1 - x0)) * max(0, (y1 - y0))
    if n_tiles <= 0:
        raise ValueError("Empty tile range; check bounds.")
    if n_tiles > 200:
        raise ValueError(f"Region too large ({n_tiles} tiles at z={zoom}); narrow your bounds.")

    print(f"Fetching {n_tiles} satellite tiles from ESRI World Imagery...")
    big = pygame.Surface(((x1 - x0) * 256, (y1 - y0) * 256))
    url_t = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    headers = {'User-Agent': 'HellcatsSim/1.0 (personal flight sim)'}
    fetched = 0
    for tx in range(x0, x1):
        for ty in range(y0, y1):
            url = url_t.format(z=zoom, x=tx, y=ty)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read()
            big.blit(pygame.image.load(io.BytesIO(data)), ((tx - x0) * 256, (ty - y0) * 256))
            fetched += 1
            if fetched % 10 == 0 or fetched == n_tiles:
                print(f"  {fetched}/{n_tiles}")

    crop_x = int(round((fx_w - x0) * 256))
    crop_y = int(round((fy_n - y0) * 256))
    crop_w = max(1, int(round((fx_e - fx_w) * 256)))
    crop_h = max(1, int(round((fy_s - fy_n) * 256)))
    cropped = big.subsurface(pygame.Rect(crop_x, crop_y, crop_w, crop_h)).copy()
    pygame.image.save(cropped, cache_file)
    return cropped


def _geocode(query):
    """Nominatim lookup. Returns (n, w, s, e, label) or None."""
    import urllib.request, urllib.parse, json
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        "q": query, "format": "json", "limit": 1,
    })
    req = urllib.request.Request(url, headers={'User-Agent': 'HellcatsSim/1.0 (personal flight sim)'})
    with urllib.request.urlopen(req, timeout=10) as r:
        results = json.loads(r.read())
    if not results:
        return None
    item = results[0]
    lat = float(item['lat'])
    lon = float(item['lon'])
    span_lat, span_lon = 0.5, 1.0  # match Long Island's footprint
    n, s = lat + span_lat / 2, lat - span_lat / 2
    e, w = lon + span_lon / 2, lon - span_lon / 2
    return n, w, s, e, item.get('display_name', query)


def _pick_flight_area():
    import sys
    if not sys.stdin.isatty():
        return None
    print()
    print("=" * 60)
    print(" HELLCATS FLIGHT SIM - choose your area of operations")
    print("=" * 60)
    print(" Enter a place (e.g. 'Pearl Harbor', 'Wake Island', 'Midway')")
    print(" Or coordinates as 'lat,lon' (e.g. '21.36,-157.96')")
    print(" Press Enter for Long Island.")
    try:
        return input(" > ").strip() or None
    except (EOFError, KeyboardInterrupt):
        return None


def _resolve_area(text):
    """Returns (n, w, s, e, label) for a non-default area, or None for Long Island."""
    if not text:
        return None
    if text.lower() in ('long island', 'longisland', 'li'):
        return None
    import re
    m = re.match(r'^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$', text)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        return lat + 0.25, lon - 0.5, lat - 0.25, lon + 0.5, f"{lat:.4f},{lon:.4f}"
    try:
        result = _geocode(text)
        if result is None:
            print(f"  Could not geocode '{text}'. Falling back to Long Island.")
        return result
    except Exception as e:
        print(f"  Geocode failed: {e}. Falling back to Long Island.")
        return None


def geo_to_pixel(lat, lon):
    from hellcats import bootstrap
    x = (lon - bootstrap.MAP_NW_LON) / (bootstrap.MAP_SE_LON - bootstrap.MAP_NW_LON) * bootstrap.MAP_WIDTH
    y = (bootstrap.MAP_NW_LAT - lat) / (bootstrap.MAP_NW_LAT - bootstrap.MAP_SE_LAT) * bootstrap.MAP_HEIGHT
    return x, y


def feet_to_pixel(x_ft, y_ft, ref_lat, ref_lon):
    d_lat = y_ft / 364000
    d_lon = x_ft / 288000
    return geo_to_pixel(ref_lat + d_lat, ref_lon + d_lon)

