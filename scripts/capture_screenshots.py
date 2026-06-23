"""Capture README screenshots without manual playtesting."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "docs", "screenshots")
os.makedirs(OUT, exist_ok=True)

os.environ.setdefault("SDL_VIDEODRIVER", "windib")

import importlib
import pygame
from hellcats import bootstrap
from hellcats.bootstrap import init

init(pick_area=False)

# Modules bind font globals at import — reload after init()
import hellcats.render_aircraft as render_aircraft
import hellcats.ui_menu as ui_menu
import hellcats.dossier as dossier_mod
import hellcats.render_game as render_game
for mod in (render_aircraft, ui_menu, dossier_mod, render_game):
    importlib.reload(mod)

from hellcats.missions import MissionMidwayDive, MISSIONS
from hellcats.aircraft import SBD_Dauntless, F6F_Hellcat
draw_home_screen = ui_menu.draw_home_screen
draw_mission_briefing = dossier_mod.draw_mission_briefing
draw_cockpit_view = render_game.draw_cockpit_view
draw_landing_grade = render_game.draw_landing_grade


def save(name):
    path = os.path.join(OUT, name)
    pygame.image.save(bootstrap.screen, path)
    print(f"Saved {path}")


# 1. Main menu — Free Flight
draw_home_screen(bootstrap.screen, 0, [F6F_Hellcat, SBD_Dauntless], 0)
save("01_menu_free_flight.png")

# 2. Missions tab
draw_home_screen(bootstrap.screen, 0, MISSIONS, 1)
save("02_menu_missions.png")

# 3. Midway Dive briefing
mission = MissionMidwayDive()
draw_mission_briefing(bootstrap.screen, mission)
save("03_midway_dive_briefing.png")

# 4. Cockpit view (Hellcat in flight)
ac = F6F_Hellcat()
ac.z = 8000
ac.throttle = 0.8
ac.pitch = 5
ac.heading = 45
bootstrap.satellite_map  # ensure loaded
draw_cockpit_view(bootstrap.screen, ac, bootstrap.satellite_map, 42.0)
save("04_cockpit_hellcat.png")

# 5. LSO grade card
bootstrap.screen.fill((10, 15, 25))
draw_landing_grade(bootstrap.screen, {
    "grade": "S",
    "points": 200,
    "label": "PERFECT TRAP — LSO grade S",
    "breakdown": [
        "Wire 3: 100/100",
        "Speed 108 kts (ideal 95-115): 100/100",
        "Sink rate 420 fpm: 100/100",
        "Centerline 4 ft off: 100/100",
    ],
    "total_score": 96.5,
})
save("05_lso_grade_s.png")

print("Done.")
pygame.quit()