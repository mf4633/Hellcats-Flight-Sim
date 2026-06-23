"""Procedural sound effects and background music."""
import math
import random
import pygame


class SoundManager:
    """Procedural audio — no external files required."""

    def __init__(self):
        self.enabled = True
        self.sounds = {}
        self._music_track = None
        self._engine_playing = None
        self.music_enabled = True
        self.music_volume = 0.20
        self.sfx_volume = 1.0
        try:
            self._generate_sfx()
            self._generate_music()
            self.channels = {
                'engine': pygame.mixer.Channel(0),
                'weapons': pygame.mixer.Channel(1),
                'effects': pygame.mixer.Channel(2),
                'alerts': pygame.mixer.Channel(3),
                'music': pygame.mixer.Channel(4),
            }
        except Exception:
            self.enabled = False

    def _make_sound(self, duration, gen_func, sr=22050):
        n = int(sr * duration)
        buf = bytearray(n * 2)
        for i in range(n):
            t = i / sr
            val = gen_func(t, i, n)
            sample = int(max(-32768, min(32767, val * 32767)))
            buf[i * 2] = sample & 0xFF
            buf[i * 2 + 1] = (sample >> 8) & 0xFF
        return pygame.mixer.Sound(buffer=bytes(buf))

    def _generate_sfx(self):
        self.sounds['engine_idle'] = self._make_sound(1.0, lambda t, i, n:
            math.sin(2 * math.pi * 80 * t) * 0.15 + math.sin(2 * math.pi * 120 * t) * 0.10 +
            math.sin(2 * math.pi * 47 * t) * 0.08)

        self.sounds['engine_full'] = self._make_sound(1.0, lambda t, i, n:
            math.sin(2 * math.pi * 160 * t) * 0.15 + math.sin(2 * math.pi * 240 * t) * 0.10 +
            math.sin(2 * math.pi * 95 * t) * 0.08)

        self.sounds['guns'] = self._make_sound(0.12, lambda t, i, n:
            (math.sin(2 * math.pi * 800 * t + 5 * math.sin(2 * math.pi * 60 * t)) +
             (random.random() - 0.5) * 0.8) * max(0, 1 - t * 10) * 0.35)

        self.sounds['explosion'] = self._make_sound(1.0, lambda t, i, n:
            math.sin(2 * math.pi * (60 + 40 * max(0, 1 - t * 3)) * t) * 0.5 *
            max(0, 1 - t * 1.5) + (random.random() - 0.5) * 0.2 * max(0, 1 - t * 2))

        self.sounds['explosion_large'] = self._make_sound(1.5, lambda t, i, n:
            math.sin(2 * math.pi * (40 + 30 * max(0, 1 - t * 2)) * t) * 0.6 *
            max(0, 1 - t * 0.8) + (random.random() - 0.5) * 0.3 * max(0, 1 - t * 1))

        self.sounds['stall'] = self._make_sound(2.0, lambda t, i, n:
            math.sin(2 * math.pi * 800 * t) * 0.3 * (1.0 if (t * 3) % 1.0 < 0.5 else 0.0))

        self.sounds['wire_catch'] = self._make_sound(0.5, lambda t, i, n:
            (math.sin(2 * math.pi * 2000 * t + 10 * math.sin(2 * math.pi * 50 * t)) +
             math.sin(2 * math.pi * 3500 * t) * 0.3) * max(0, 1 - t * 4) * 0.25)

        self.sounds['bullet_snap'] = self._make_sound(0.06, lambda t, i, n:
            (random.random() - 0.5) * max(0, 1 - t * 30) * 0.5)

        self.sounds['rocket'] = self._make_sound(0.8, lambda t, i, n:
            ((random.random() - 0.5) * 0.4 + math.sin(2 * math.pi * (200 + 400 * t) * t) * 0.2) *
            min(1, t * 10) * max(0, 1 - t * 2))

        self.sounds['torpedo'] = self._make_sound(0.4, lambda t, i, n:
            ((random.random() - 0.5) * 0.4 + math.sin(2 * math.pi * 100 * t) * 0.3) *
            max(0, 1 - t * 3) * min(1, t * 15))

        # Per-airframe engine loops
        self.sounds['radial_fighter_idle'] = self.sounds['engine_idle']
        self.sounds['radial_fighter_full'] = self.sounds['engine_full']
        self.sounds['radial_corsair_idle'] = self._make_sound(1.0, lambda t, i, n:
            math.sin(2 * math.pi * 95 * t) * 0.14 + math.sin(2 * math.pi * 140 * t) * 0.09)
        self.sounds['radial_corsair_full'] = self._make_sound(1.0, lambda t, i, n:
            math.sin(2 * math.pi * 175 * t) * 0.14 + math.sin(2 * math.pi * 260 * t) * 0.10)
        self.sounds['radial_sbd_idle'] = self._make_sound(1.0, lambda t, i, n:
            math.sin(2 * math.pi * 70 * t) * 0.14 + math.sin(2 * math.pi * 105 * t) * 0.08)
        self.sounds['radial_sbd_full'] = self._make_sound(1.0, lambda t, i, n:
            math.sin(2 * math.pi * 130 * t) * 0.14 + math.sin(2 * math.pi * 195 * t) * 0.09)
        self.sounds['jet_wide_idle'] = self._make_sound(1.2, lambda t, i, n:
            math.sin(2 * math.pi * 45 * t) * 0.10 + (random.random() - 0.5) * 0.02)
        self.sounds['jet_wide_full'] = self._make_sound(1.2, lambda t, i, n:
            math.sin(2 * math.pi * 85 * t) * 0.12 + math.sin(2 * math.pi * 120 * t) * 0.06)
        self.sounds['jet_narrow_idle'] = self._make_sound(1.0, lambda t, i, n:
            math.sin(2 * math.pi * 110 * t) * 0.09 + math.sin(2 * math.pi * 220 * t) * 0.05)
        self.sounds['jet_narrow_full'] = self._make_sound(1.0, lambda t, i, n:
            math.sin(2 * math.pi * 180 * t) * 0.10 + math.sin(2 * math.pi * 360 * t) * 0.05)
        self.sounds['jet_wide_twin_idle'] = self.sounds['jet_wide_idle']
        self.sounds['jet_wide_twin_full'] = self.sounds['jet_wide_full']

        # Stings
        self.sounds['landing_perfect'] = self._make_sound(1.2, lambda t, i, n:
            sum(math.sin(2 * math.pi * f * t) * 0.12 * max(0, 1 - t * 0.8)
                for f in (523, 659, 784, 1047)) * (1.0 if t < 0.9 else max(0, 1 - (t - 0.9) * 10)))

        self.sounds['mission_success'] = self._make_sound(1.5, lambda t, i, n:
            sum(math.sin(2 * math.pi * f * t) * 0.10 * max(0, 1 - t * 0.6)
                for f in (392, 494, 587, 784)) * max(0, 1 - t * 0.5))

        self.sounds['mission_fail'] = self._make_sound(1.0, lambda t, i, n:
            math.sin(2 * math.pi * (220 - 80 * t) * t) * 0.25 * max(0, 1 - t))

    def _generate_music_loop(self, duration, gen_func, sr=22050):
        return self._make_sound(duration, gen_func, sr)

    def _generate_music(self):
        # Menu: Pacific hymn — slow E-minor arpeggio over ocean wash
        def menu_gen(t, i, n):
            beat = t % 16.0
            notes = [329.6, 392.0, 493.9, 392.0, 329.6, 293.7, 329.6]
            idx = int(beat / 2.0) % len(notes)
            melody = math.sin(2 * math.pi * notes[idx] * t) * 0.06
            swell = math.sin(2 * math.pi * 0.125 * t) * 0.04
            ocean = math.sin(2 * math.pi * 55 * t) * 0.03 + (random.random() - 0.5) * 0.01
            return melody + swell + ocean

        # Combat: tense low pulse
        def combat_gen(t, i, n):
            pulse = (math.sin(2 * math.pi * 2 * t) * 0.5 + 0.5) ** 2
            bass = math.sin(2 * math.pi * 73 * t) * 0.08 * pulse
            tension = math.sin(2 * math.pi * 146 * t) * 0.04 * pulse
            tick = math.sin(2 * math.pi * 800 * t) * 0.02 * (1.0 if (t * 4) % 1.0 < 0.05 else 0.0)
            return bass + tension + tick

        # Disaster: ominous descending drone
        def disaster_gen(t, i, n):
            drift = 55 + 15 * math.sin(2 * math.pi * 0.05 * t)
            drone = math.sin(2 * math.pi * drift * t) * 0.10
            overtone = math.sin(2 * math.pi * drift * 1.5 * t) * 0.05
            heartbeat = math.sin(2 * math.pi * 1.2 * t) * 0.04
            return drone + overtone + heartbeat

        self.sounds['music_menu'] = self._generate_music_loop(16.0, menu_gen)
        self.sounds['music_combat'] = self._generate_music_loop(8.0, combat_gen)
        self.sounds['music_disaster'] = self._generate_music_loop(12.0, disaster_gen)

    def play(self, name, loop=False):
        if not self.enabled or name not in self.sounds:
            return
        ch_name = 'effects'
        if 'engine' in name:
            ch_name = 'engine'
        elif name in ('guns', 'rocket', 'torpedo'):
            ch_name = 'weapons'
        elif name == 'stall':
            ch_name = 'alerts'
        elif name.startswith('music_'):
            ch_name = 'music'
        ch = self.channels.get(ch_name)
        if ch:
            ch.play(self.sounds[name], loops=(-1 if loop else 0))
            if ch_name != 'music':
                ch.set_volume(self.sfx_volume)

    def play_sting(self, name):
        self.play(name, loop=False)

    def play_music(self, track):
        """track: 'menu', 'combat', 'disaster', or None to stop."""
        if not self.enabled or not self.music_enabled:
            if not track:
                self.stop('music')
            return
        key = f'music_{track}' if track else None
        if key == self._music_track:
            ch = self.channels.get('music')
            if ch:
                ch.set_volume(self.music_volume)
            return
        ch = self.channels.get('music')
        if not ch:
            return
        if not track:
            ch.stop()
            self._music_track = None
            return
        if key not in self.sounds:
            return
        ch.play(self.sounds[key], loops=-1)
        ch.set_volume(self.music_volume)
        self._music_track = key

    def toggle_music(self):
        self.music_enabled = not self.music_enabled
        if not self.music_enabled:
            self.stop('music')
        return self.music_enabled

    def stop_music(self):
        self.play_music(None)

    def stop(self, channel_name):
        if self.enabled and channel_name in self.channels:
            self.channels[channel_name].stop()
            if channel_name == 'music':
                self._music_track = None

    def update_engine(self, aircraft, throttle, flying=True):
        if not self.enabled:
            return
        ch = self.channels.get('engine')
        if not ch:
            return
        if not flying:
            ch.stop()
            self._engine_playing = None
            return
        sound_base = getattr(aircraft.__class__, 'ENGINE_SOUND', 'radial_fighter')
        target = f"{sound_base}_{'full' if throttle > 0.5 else 'idle'}"
        if target not in self.sounds:
            target = 'engine_full' if throttle > 0.5 else 'engine_idle'
        if self._engine_playing != target:
            ch.play(self.sounds[target], loops=-1)
            self._engine_playing = target
        ch.set_volume((0.12 + throttle * 0.30) * self.sfx_volume)