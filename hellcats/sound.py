"""Procedural sound effects."""
import math
import pygame

# ============== SOUND SYSTEM ==============
class SoundManager:
    """Procedural sound effects generated at startup. No external audio files needed."""

    def __init__(self):
        self.enabled = True
        self.sounds = {}
        try:
            self._generate_all()
            self.channels = {
                'engine': pygame.mixer.Channel(0),
                'weapons': pygame.mixer.Channel(1),
                'effects': pygame.mixer.Channel(2),
                'alerts': pygame.mixer.Channel(3),
            }
            self._engine_playing = None
        except Exception:
            self.enabled = False

    def _make_sound(self, duration, gen_func, sr=22050):
        """Generate a Sound from a waveform callback gen_func(t, i, n) -> [-1,1]."""
        n = int(sr * duration)
        buf = bytearray(n * 2)
        for i in range(n):
            t = i / sr
            val = gen_func(t, i, n)
            sample = int(max(-32768, min(32767, val * 32767)))
            buf[i * 2] = sample & 0xFF
            buf[i * 2 + 1] = (sample >> 8) & 0xFF
        return pygame.mixer.Sound(buffer=bytes(buf))

    def _generate_all(self):
        # Engine idle: low rumble with harmonics
        self.sounds['engine_idle'] = self._make_sound(1.0, lambda t, i, n:
            math.sin(2*math.pi*80*t)*0.15 + math.sin(2*math.pi*120*t)*0.10 +
            math.sin(2*math.pi*47*t)*0.08)

        # Engine full power: higher pitch
        self.sounds['engine_full'] = self._make_sound(1.0, lambda t, i, n:
            math.sin(2*math.pi*160*t)*0.15 + math.sin(2*math.pi*240*t)*0.10 +
            math.sin(2*math.pi*95*t)*0.08)

        # Machine guns: short crackling burst
        self.sounds['guns'] = self._make_sound(0.12, lambda t, i, n:
            (math.sin(2*math.pi*800*t + 5*math.sin(2*math.pi*60*t)) +
             (random.random()-0.5)*0.8) * max(0, 1-t*10) * 0.35)

        # Explosion: low boom with pitch drop
        self.sounds['explosion'] = self._make_sound(1.0, lambda t, i, n:
            math.sin(2*math.pi*(60+40*max(0,1-t*3))*t)*0.5 *
            max(0, 1-t*1.5) + (random.random()-0.5)*0.2*max(0,1-t*2))

        # Large explosion: deeper, longer
        self.sounds['explosion_large'] = self._make_sound(1.5, lambda t, i, n:
            math.sin(2*math.pi*(40+30*max(0,1-t*2))*t)*0.6 *
            max(0, 1-t*0.8) + (random.random()-0.5)*0.3*max(0,1-t*1))

        # Stall horn: pulsing beep
        self.sounds['stall'] = self._make_sound(2.0, lambda t, i, n:
            math.sin(2*math.pi*800*t) * 0.3 * (1.0 if (t*3)%1.0 < 0.5 else 0.0))

        # Wire catch: metallic screech
        self.sounds['wire_catch'] = self._make_sound(0.5, lambda t, i, n:
            (math.sin(2*math.pi*2000*t + 10*math.sin(2*math.pi*50*t)) +
             math.sin(2*math.pi*3500*t)*0.3) * max(0, 1-t*4) * 0.25)

        # Bullet snap (near miss)
        self.sounds['bullet_snap'] = self._make_sound(0.06, lambda t, i, n:
            (random.random()-0.5) * max(0, 1-t*30) * 0.5)

        # Rocket whoosh
        self.sounds['rocket'] = self._make_sound(0.8, lambda t, i, n:
            ((random.random()-0.5)*0.4 + math.sin(2*math.pi*(200+400*t)*t)*0.2) *
            min(1, t*10) * max(0, 1-t*2))

        # Torpedo splash
        self.sounds['torpedo'] = self._make_sound(0.4, lambda t, i, n:
            ((random.random()-0.5)*0.4 + math.sin(2*math.pi*100*t)*0.3) *
            max(0, 1-t*3) * min(1, t*15))

    def play(self, name, loop=False):
        if not self.enabled or name not in self.sounds:
            return
        ch_name = 'effects'
        if 'engine' in name: ch_name = 'engine'
        elif name in ('guns', 'rocket', 'torpedo'): ch_name = 'weapons'
        elif name == 'stall': ch_name = 'alerts'
        ch = self.channels.get(ch_name)
        if ch:
            ch.play(self.sounds[name], loops=(-1 if loop else 0))

    def stop(self, channel_name):
        if self.enabled and channel_name in self.channels:
            self.channels[channel_name].stop()

    def update_engine(self, throttle, flying=True):
        if not self.enabled:
            return
        ch = self.channels.get('engine')
        if not ch:
            return
        if not flying:
            ch.stop()
            self._engine_playing = None
            return
        target = 'engine_full' if throttle > 0.5 else 'engine_idle'
        if self._engine_playing != target:
            ch.play(self.sounds[target], loops=-1)
            self._engine_playing = target
        ch.set_volume(0.15 + throttle * 0.35)


