"""Radio chatter system."""
import random
import pygame
from hellcats.hotp import hotp_rng
from hellcats.bootstrap import font_tiny, HUD_GREEN, HUD_AMBER, WHITE

# ============== RADIO CHATTER ==============
class RadioChatter:
    """Context-sensitive text comms from wingmen, carrier, and command."""
    def __init__(self):
        self.messages = []   # [(text, sender, time_remaining, priority)]
        self.cooldowns = {}  # message_type -> cooldown timer
        self.max_display = 4
        self.last_callouts = {}

    # Message templates by category
    WINGMAN_CALLS = {
        'tally':     ["Tally ho! Bogeys, {clock} o'clock {alt}!",
                       "Contact! Bandits, {clock} o'clock!",
                       "I see 'em! {clock} o'clock {alt}!"],
        'splash':    ["Splash one!", "Got him! He's going down!",
                       "That's a kill!"],
        'hit':       ["I'm hit! Taking fire!", "Damage! Engine's rough!"],
        'engaging':  ["Engaging the bandit!", "I'm on him!",
                       "Fox two! Guns guns guns!"],
        'clear':     ["Skies clear. No contacts.", "All clear topside."],
        'formation': ["Rejoining formation.", "On your wing, lead."],
    }
    CARRIER_CALLS = {
        'approach':  ["Paddles: Call the ball.",
                       "LSO: You're on glideslope, looking good.",
                       "Tower: Cleared to land, wind down the deck."],
        'waveoff':   ["WAVE OFF! WAVE OFF! Too fast!",
                       "LSO: You're high, go around!"],
        'trapped':   ["Nice trap! Wire {wire}. Welcome aboard.",
                       "Good catch! Taxi forward and shut down."],
        'bolter':    ["Bolter! Bolter! Go around.",
                       "Missed the wires. Come around again."],
        'launch':    ["Cat officer: Ready for launch!",
                       "Tower: Wind is {wind} knots down the deck. You're cleared."],
    }
    COMMAND_CALLS = {
        'mission_start': ["Command: Good hunting, pilot.",
                           "Command: Give 'em hell out there."],
        'objective':     ["Command: Target is bearing {bearing}, {range} miles.",
                           "Command: Objective updated. Check your heading."],
        'rtb':           ["Command: Mission complete. RTB.",
                           "Command: Well done. Bring it home."],
        'warning':       ["Command: Multiple bogeys inbound!",
                           "Command: Heads up, heavy resistance ahead."],
        'mission_fail':  ["Command: Mission failure. Return to base.",
                           "Command: We've lost the objective. Pull back."],
    }

    def push(self, text, sender="RADIO", duration=5.0, priority=0):
        """Add a message to the display queue."""
        self.messages.append([text, sender, duration, priority])
        # Keep limited
        if len(self.messages) > 8:
            self.messages = self.messages[-8:]

    def call(self, category, subcategory, cooldown=8.0, **kwargs):
        """Try to play a radio call. Respects cooldowns."""
        key = f"{category}_{subcategory}"
        if key in self.cooldowns and self.cooldowns[key] > 0:
            return
        self.cooldowns[key] = cooldown
        templates = None
        if category == 'wingman':
            templates = self.WINGMAN_CALLS.get(subcategory)
        elif category == 'carrier':
            templates = self.CARRIER_CALLS.get(subcategory)
        elif category == 'command':
            templates = self.COMMAND_CALLS.get(subcategory)
        if not templates:
            return
        text = templates[hotp_rng.next() % len(templates)]
        # Fill in kwargs
        for k, v in kwargs.items():
            text = text.replace('{' + k + '}', str(v))
        sender = category.upper()
        self.push(text, sender, 5.0)

    def update(self, dt):
        for cd_key in list(self.cooldowns):
            self.cooldowns[cd_key] -= dt
            if self.cooldowns[cd_key] <= 0:
                del self.cooldowns[cd_key]
        for msg in self.messages:
            msg[2] -= dt
        self.messages = [m for m in self.messages if m[2] > 0]

    def check_context(self, aircraft, target_mgr, carrier, wingmen, active_mission):
        """Auto-generate contextual radio calls based on game state."""
        # Tally-ho when enemies detected
        if target_mgr and target_mgr.enemy_aircraft:
            for enemy in target_mgr.enemy_aircraft:
                if not enemy.alive:
                    continue
                dist = math.sqrt((enemy.x - aircraft.x)**2 + (enemy.y - aircraft.y)**2)
                if dist < 15000:
                    # Clock position
                    dx = enemy.x - aircraft.x
                    dy = enemy.y - aircraft.y
                    angle = (math.degrees(math.atan2(dx, dy)) - aircraft.heading) % 360
                    clock = max(1, min(12, int(angle / 30 + 0.5)))
                    if clock == 0:
                        clock = 12
                    alt = "high" if enemy.z > aircraft.z + 1000 else (
                          "low" if enemy.z < aircraft.z - 1000 else "level")
                    self.call('wingman', 'tally', cooldown=15.0, clock=clock, alt=alt)
                    break

        # Carrier approach
        if carrier and hasattr(aircraft, 'mg_ammo'):
            dist_to_carrier = math.sqrt((aircraft.x - carrier.x)**2 + (aircraft.y - carrier.y)**2)
            if dist_to_carrier < 5000 and aircraft.z < 1000:
                self.call('carrier', 'approach', cooldown=20.0)

        # Wingman status
        if wingmen:
            for wm in wingmen:
                if wm.alive and wm.ai_state == 'engage' and wm.firing:
                    self.call('wingman', 'engaging', cooldown=12.0)
                    break
                if wm.alive and wm.ai_state == 'rejoin':
                    self.call('wingman', 'formation', cooldown=20.0)
                    break

    def draw(self, surface):
        """Draw radio messages on screen."""
        if not self.messages:
            return
        y = 95
        for msg in self.messages[-self.max_display:]:
            text, sender, time_left, priority = msg
            # Fade out in last second
            alpha = min(255, int(time_left * 255)) if time_left < 1.0 else 255
            color = (0, 255, 100) if sender == 'WINGMAN' else (
                    (100, 200, 255) if sender == 'CARRIER' else (255, 200, 50))
            # Background bar
            bar = pygame.Surface((500, 22), pygame.SRCALPHA)
            bar.fill((0, 0, 0, min(150, alpha)))
            surface.blit(bar, (10, y))
            # Sender tag
            tag = font_tiny.render(f"[{sender}]", True, color)
            surface.blit(tag, (14, y + 2))
            # Message text
            tw = font_tiny.render(text, True, (min(255, alpha), min(255, alpha), min(255, alpha)))
            surface.blit(tw, (14 + tag.get_width() + 6, y + 2))
            y += 24


