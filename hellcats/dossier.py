"""Pilot dossier and input replay."""
import json
import os
import pygame
from hellcats.bootstrap import (
    WIDTH, HEIGHT, PHYSICS_DT, HUD_GREEN, HUD_AMBER, HUD_RED, WHITE,
    font_title, font_large, font_med, font_small, font_tiny,
)
from hellcats.hotp import HOTP_RNG, hotp_rng

# ============== RANKING & DOSSIER ==============
RANKS = [
    (0, "Ensign"),
    (2000, "Lt. Junior Grade"),
    (5000, "Lieutenant"),
    (10000, "Lt. Commander"),
    (20000, "Commander"),
    (40000, "Captain"),
]

SAVE_FILE = os.path.join(os.path.expanduser('~'), 'hellcat_save.json')


class PilotDossier:
    """Persistent pilot record"""
    def __init__(self, name="PLAYER"):
        self.name = name
        self.total_score = 0
        self.total_kills = {'aircraft': 0, 'ship': 0, 'ground': 0}
        self.missions_completed = []
        self.missions_attempted = 0
        self.carrier_landings = 0
        self.best_landing_grade = None
        self.landing_points = 0
        self.sbd_qual_complete = False
        self.load()

    def get_rank(self):
        rank = "Ensign"
        for threshold, name in RANKS:
            if self.total_score >= threshold:
                rank = name
        return rank

    def get_next_rank_progress(self):
        current_idx = 0
        for i, (threshold, name) in enumerate(RANKS):
            if self.total_score >= threshold:
                current_idx = i
        if current_idx >= len(RANKS) - 1:
            return 1.0  # Max rank
        current_threshold = RANKS[current_idx][0]
        next_threshold = RANKS[current_idx + 1][0]
        return (self.total_score - current_threshold) / (next_threshold - current_threshold)

    def add_mission_result(self, mission):
        self.missions_attempted += 1
        if mission.status == "success":
            score = mission.get_score()
            self.total_score += score
            if mission.NAME not in self.missions_completed:
                self.missions_completed.append(mission.NAME)
                self.total_score += 500  # Bonus for first completion
        self.save()

    def record_carrier_landing(self, landing_result=None):
        """Record trap; landing_result from LandingScorer.score_trap()."""
        self.carrier_landings += 1
        if landing_result:
            grade = landing_result.get('grade', 'C')
            points = landing_result.get('points', 50)
            self.landing_points += points
            self.total_score += points
            if self.best_landing_grade is None:
                self.best_landing_grade = grade
            else:
                from hellcats.carrier_ops import GRADE_ORDER
                if GRADE_ORDER.index(grade) < GRADE_ORDER.index(self.best_landing_grade):
                    self.best_landing_grade = grade
            if landing_result.get('aircraft_name', '').startswith('SBD') and grade in ('S', 'A', 'B'):
                self.sbd_qual_complete = True
        else:
            self.total_score += 50
        self.save()

    def save(self):
        import json
        data = {
            'name': self.name,
            'total_score': self.total_score,
            'total_kills': self.total_kills,
            'missions_completed': self.missions_completed,
            'missions_attempted': self.missions_attempted,
            'carrier_landings': self.carrier_landings,
            'best_landing_grade': self.best_landing_grade,
            'landing_points': self.landing_points,
            'sbd_qual_complete': self.sbd_qual_complete,
        }
        try:
            with open(SAVE_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def load(self):
        import json
        try:
            with open(SAVE_FILE) as f:
                data = json.load(f)
            self.name = data.get('name', self.name)
            self.total_score = data.get('total_score', 0)
            self.total_kills = data.get('total_kills', self.total_kills)
            self.missions_completed = data.get('missions_completed', [])
            self.missions_attempted = data.get('missions_attempted', 0)
            self.carrier_landings = data.get('carrier_landings', 0)
            self.best_landing_grade = data.get('best_landing_grade')
            self.landing_points = data.get('landing_points', 0)
            self.sbd_qual_complete = data.get('sbd_qual_complete', False)
        except Exception:
            pass


# ============== DETERMINISTIC REPLAY ==============
class _ReplayKeys:
    """Mimics pygame.key.get_pressed() using recorded bitmask."""
    def __init__(self, state, key_list):
        self._map = {k: i for i, k in enumerate(key_list)}
        self._state = state

    def __getitem__(self, key):
        idx = self._map.get(key)
        return bool(self._state & (1 << idx)) if idx is not None else False


class InputRecorder:
    """Records and replays input for deterministic replay with HOTP_RNG."""
    TRACKED_KEYS = [
        pygame.K_w, pygame.K_s, pygame.K_a, pygame.K_d,
        pygame.K_q, pygame.K_e, pygame.K_LSHIFT, pygame.K_LCTRL,
        pygame.K_SPACE, pygame.K_f, pygame.K_g,
        pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4,
        pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET,
        pygame.K_EQUALS, pygame.K_MINUS,
        pygame.K_UP, pygame.K_DOWN,
    ]

    def __init__(self):
        self.frames = []
        self.rng_seed = 0
        self.recording = False
        self.playing = False
        self.play_index = 0

    def start_recording(self, rng_seed):
        self.frames = []
        self.rng_seed = rng_seed
        self.recording = True
        self.playing = False

    def stop_recording(self):
        self.recording = False

    def record_frame(self, keys):
        state = 0
        for i, k in enumerate(self.TRACKED_KEYS):
            if keys[k]:
                state |= (1 << i)
        self.frames.append(state)

    def start_playback(self):
        global hotp_rng
        hotp_rng = HOTP_RNG(self.rng_seed)
        self.playing = True
        self.recording = False
        self.play_index = 0

    def get_frame_keys(self):
        if self.play_index >= len(self.frames):
            self.playing = False
            return None
        state = self.frames[self.play_index]
        self.play_index += 1
        return _ReplayKeys(state, self.TRACKED_KEYS)

    def save(self, filename):
        import json
        with open(filename, 'w') as f:
            json.dump({'rng_seed': self.rng_seed, 'frames': self.frames, 'version': 1}, f)

    def load(self, filename):
        import json
        with open(filename) as f:
            data = json.load(f)
        self.rng_seed = data['rng_seed']
        self.frames = data['frames']

    @property
    def frame_count(self):
        return len(self.frames)


def draw_dossier(surface, dossier):
    """Draw pilot dossier overlay"""
    # Background
    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 220))
    surface.blit(overlay, (0, 0))

    cx = WIDTH // 2

    # Title
    title = font_title.render("PILOT DOSSIER", True, HUD_GREEN)
    surface.blit(title, title.get_rect(center=(cx, 50)))

    # Rank and name
    rank = dossier.get_rank()
    rank_text = font_large.render(f"{rank} {dossier.name}", True, HUD_AMBER)
    surface.blit(rank_text, rank_text.get_rect(center=(cx, 110)))

    # Score
    score_text = font_large.render(f"Total Score: {dossier.total_score:,}", True, WHITE)
    surface.blit(score_text, score_text.get_rect(center=(cx, 160)))

    # Rank progress bar
    progress = dossier.get_next_rank_progress()
    bar_w = 400
    bar_x = cx - bar_w // 2
    pygame.draw.rect(surface, (40, 40, 40), (bar_x, 195, bar_w, 20))
    pygame.draw.rect(surface, HUD_GREEN, (bar_x, 195, int(bar_w * progress), 20))
    pygame.draw.rect(surface, HUD_GREEN, (bar_x, 195, bar_w, 20), 2)
    prog_label = font_tiny.render("Next Rank", True, (150, 150, 150))
    surface.blit(prog_label, (bar_x + bar_w + 10, 198))

    # Stats
    stats_y = 240
    stats = [
        f"Missions Attempted: {dossier.missions_attempted}",
        f"Missions Completed: {len(dossier.missions_completed)}",
        f"Carrier Landings: {dossier.carrier_landings}",
        f"Best Trap Grade: {dossier.best_landing_grade or '—'}",
        f"Landing Points: {dossier.landing_points:,}",
        f"SBD Carrier Qual: {'PASSED' if dossier.sbd_qual_complete else 'Incomplete'}",
        f"Aircraft Kills: {dossier.total_kills.get('aircraft', 0)}",
        f"Ships Sunk: {dossier.total_kills.get('ship', 0)}",
        f"Ground Targets: {dossier.total_kills.get('ground', 0)}",
    ]
    for i, stat in enumerate(stats):
        text = font_med.render(stat, True, (200, 200, 200))
        surface.blit(text, (cx - 200, stats_y + i * 35))

    # Mission awards
    awards_y = stats_y + len(stats) * 35 + 30
    awards_title = font_med.render("Mission Awards:", True, HUD_GREEN)
    surface.blit(awards_title, (cx - 200, awards_y))
    if dossier.missions_completed:
        for i, mission_name in enumerate(dossier.missions_completed):
            award = font_small.render(f"  * {mission_name}", True, HUD_AMBER)
            surface.blit(award, (cx - 180, awards_y + 30 + i * 25))
    else:
        none_text = font_small.render("  No awards yet", True, (120, 120, 120))
        surface.blit(none_text, (cx - 180, awards_y + 30))

    # Instructions
    hint = font_med.render("Press ESC to close", True, (150, 150, 150))
    surface.blit(hint, hint.get_rect(center=(cx, HEIGHT - 40)))


def draw_mission_briefing(surface, mission):
    """Draw mission briefing screen"""
    # Background
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = int(10 + 20 * ratio)
        g = int(15 + 25 * ratio)
        b = int(30 + 40 * ratio)
        pygame.draw.rect(surface, (r, g, b), (0, y, WIDTH, 1))

    # Title
    title = font_title.render(mission.NAME, True, HUD_GREEN)
    title_rect = title.get_rect(center=(WIDTH // 2, 60))
    surface.blit(title, title_rect)

    # Difficulty stars
    stars = "*" * mission.DIFFICULTY + " " * (5 - mission.DIFFICULTY)
    diff_text = font_med.render(f"Difficulty: {stars}", True, HUD_AMBER)
    diff_rect = diff_text.get_rect(center=(WIDTH // 2, 100))
    surface.blit(diff_text, diff_rect)

    # Objective
    obj_text = font_med.render(f"Objective: {mission.OBJECTIVE}", True, WHITE)
    obj_rect = obj_text.get_rect(center=(WIDTH // 2, 140))
    surface.blit(obj_text, obj_rect)

    # Briefing text
    pygame.draw.rect(surface, (20, 30, 40), (WIDTH // 2 - 350, 180, 700, 400), border_radius=10)
    pygame.draw.rect(surface, HUD_GREEN, (WIDTH // 2 - 350, 180, 700, 400), 2, border_radius=10)

    for i, line in enumerate(mission.BRIEFING):
        color = HUD_GREEN if i == 0 else (200, 200, 200)
        text = font_med.render(line, True, color)
        surface.blit(text, (WIDTH // 2 - 330, 200 + i * 32))

    # Instructions
    inst = font_large.render("Press ENTER to launch | ESC to cancel", True, WHITE)
    inst_rect = inst.get_rect(center=(WIDTH // 2, HEIGHT - 60))
    surface.blit(inst, inst_rect)


def draw_mission_hud(surface, mission):
    """Draw mission objective status during flight"""
    if not mission or mission.status != "active":
        return

    # Objective bar at top
    pygame.draw.rect(surface, (0, 0, 0, 200), (10, 10, 400, 50))
    pygame.draw.rect(surface, HUD_GREEN, (10, 10, 400, 50), 1)

    name_text = font_small.render(mission.NAME, True, HUD_GREEN)
    surface.blit(name_text, (20, 15))
    obj_text = font_tiny.render(mission.OBJECTIVE[:55], True, WHITE)
    surface.blit(obj_text, (20, 38))


def draw_mission_result(surface, mission):
    """Draw mission success/fail screen"""
    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 180))
    surface.blit(overlay, (0, 0))

    if mission.status == "success":
        color = HUD_GREEN
        title = "MISSION COMPLETE!"
        subtitle = "Excellent work, pilot."
    else:
        color = HUD_RED
        title = "MISSION FAILED"
        subtitle = "Better luck next time."

    title_text = font_title.render(title, True, color)
    title_rect = title_text.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 80))
    surface.blit(title_text, title_rect)

    sub_text = font_large.render(subtitle, True, WHITE)
    sub_rect = sub_text.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 30))
    surface.blit(sub_text, sub_rect)

    score_text = font_med.render(f"Score: {mission.get_score()}", True, HUD_AMBER)
    score_rect = score_text.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 20))
    surface.blit(score_text, score_rect)

    hint = font_med.render("Press M for menu | R to retry", True, (180, 180, 180))
    hint_rect = hint.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 70))
    surface.blit(hint, hint_rect)


