"""Historical disaster scenarios."""
import math
import random
from hellcats.aircraft import Boeing747_200, Boeing737_300, AirbusA330_200


class DisasterScenario:
    """Base class for disaster recreations"""
    NAME = "Unknown Disaster"
    DESCRIPTION = "Description"
    AIRCRAFT_CLASS = Boeing747_200
    DATE = "Unknown"

    START_LAT = 40.7
    START_LON = -73.5
    START_ALT = 10000
    START_HEADING = 90
    START_SPEED = 300

    TRIGGER_TYPE = "time"
    TRIGGER_TIME = 10
    TRIGGER_ALT = None

    THRUST_MULTIPLIER = 0.0
    DRAG_MULTIPLIER = 2.0

    def __init__(self):
        self.triggered = False
        self.trigger_timer = 0
        self.flight_time = 0

    def check_trigger(self, aircraft, dt):
        self.flight_time += dt
        if self.triggered:
            return True
        if self.TRIGGER_TYPE == "time" and self.flight_time >= self.TRIGGER_TIME:
            self.triggered = True
            return True
        return False

    def apply_effects(self, aircraft):
        if self.triggered:
            aircraft.throttle = min(aircraft.throttle, self.THRUST_MULTIPLIER)
            aircraft.drag_modifier = max(aircraft.drag_modifier, self.DRAG_MULTIPLIER)


def create_disaster_aircraft(scenario):
    """Build a flyable aircraft wired to a disaster scenario."""
    base_cls = scenario.AIRCRAFT_CLASS

    class DisasterAircraft(base_cls):
        def __init__(self):
            self.scenario = scenario
            super().__init__()
            self.setup_scenario()

        def setup_scenario(self):
            self.ref_lat = self.scenario.START_LAT
            self.ref_lon = self.scenario.START_LON
            self.x, self.y = 0, 0
            self.z = self.scenario.START_ALT
            speed_fps = self.scenario.START_SPEED * 1.68781
            hdg_rad = math.radians(self.scenario.START_HEADING)
            self.vx = speed_fps * math.sin(hdg_rad)
            self.vy = speed_fps * math.cos(hdg_rad)
            self.vz = 500 / 60
            self.heading = self.scenario.START_HEADING
            self.pitch = 3
            self.roll = 0
            self.throttle = 0.85

        def reset(self):
            super().reset()
            if hasattr(self, 'scenario') and self.scenario:
                self.scenario.triggered = False
                self.scenario.trigger_timer = 0
                self.scenario.flight_time = 0
                self.setup_scenario()

        def update(self, dt, keys):
            just_triggered = False
            if not self.scenario.triggered:
                if self.scenario.check_trigger(self, dt):
                    just_triggered = True
            self.scenario.apply_effects(self)
            result = super().update(dt, keys)
            if just_triggered:
                msg = getattr(self.scenario, "TRIGGER_MESSAGE", "!! CATASTROPHIC FAILURE !!")
                return msg
            degradation = getattr(self, "_control_degradation", 1.0)
            if degradation < 1.0:
                self.pitch_rate *= degradation
                self.roll_rate *= degradation
                self.yaw_rate *= degradation
            if getattr(self, "_autopilot_drift", False):
                self.pitch = max(-15, self.pitch - 0.03 * dt * 60)
                # Slow, near-imperceptible descent (the crew never noticed it),
                # not an accelerating dive. Ease toward a gentle ~600 fpm sink
                # and hold it so the altimeter is the only cue.
                target_vz = -600 / 60  # ft/s
                self.vz = max(target_vz, self.vz - 4 * dt)
            return result

    return DisasterAircraft()


# Keep alias for imports
DisasterAircraft = None  # use create_disaster_aircraft()


class TWA800(DisasterScenario):
    NAME = "TWA Flight 800"
    DESCRIPTION = "747 Fuel Tank Explosion - July 17, 1996"
    AIRCRAFT_CLASS = Boeing747_200
    DATE = "July 17, 1996"
    START_LAT = 40.68
    START_LON = -73.0
    START_ALT = 13000
    START_HEADING = 70
    START_SPEED = 365
    TRIGGER_TIME = 15
    THRUST_MULTIPLIER = 0.0
    DRAG_MULTIPLIER = 2.5
    INFO_TEXT = [
        "TWA FLIGHT 800 - DISASTER RECREATION",
        "Date: July 17, 1996 | Aircraft: Boeing 747-131",
        "Center fuel tank explosion at 13,760 feet.",
        "You have 15 seconds before detonation.",
        "After explosion: ALL ENGINES LOST, SEVERE DRAG",
    ]


class PanAm103(DisasterScenario):
    NAME = "Pan Am Flight 103"
    DESCRIPTION = "747 Bomb Detonation - December 21, 1988"
    AIRCRAFT_CLASS = Boeing747_200
    DATE = "December 21, 1988"
    START_LAT = 55.12
    START_LON = -3.35
    START_ALT = 31000
    START_HEADING = 45
    START_SPEED = 310
    TRIGGER_TIME = 20
    THRUST_MULTIPLIER = 0.0
    DRAG_MULTIPLIER = 3.0
    TRIGGER_MESSAGE = "!! BOMB DETONATION - STRUCTURAL BREAKUP !!"
    INFO_TEXT = [
        "PAN AM FLIGHT 103 - DISASTER RECREATION",
        "Semtex bomb in forward cargo hold at FL310.",
        "You have 20 seconds before detonation.",
    ]


class JAL123(DisasterScenario):
    NAME = "JAL Flight 123"
    DESCRIPTION = "747SR Hydraulic Failure - August 12, 1985"
    AIRCRAFT_CLASS = Boeing747_200
    DATE = "August 12, 1985"
    START_LAT = 35.62
    START_LON = 138.73
    START_ALT = 24000
    START_HEADING = 315
    START_SPEED = 300
    TRIGGER_TIME = 25
    THRUST_MULTIPLIER = 1.0
    DRAG_MULTIPLIER = 1.8
    TRIGGER_MESSAGE = "!! BULKHEAD FAILURE - HYDRAULICS LOST !!"
    INFO_TEXT = [
        "JAL FLIGHT 123 - DISASTER RECREATION",
        "All hydraulics lost. Engines still work.",
        "Use throttle for pitch control. 15% authority.",
    ]

    def apply_effects(self, aircraft):
        if self.triggered:
            aircraft.drag_modifier = max(aircraft.drag_modifier, self.DRAG_MULTIPLIER)
            aircraft._control_degradation = 0.15


class Helios522(DisasterScenario):
    NAME = "Helios Flight 522"
    DESCRIPTION = "737 Pressurization / Hypoxia - August 14, 2005"
    AIRCRAFT_CLASS = Boeing737_300
    DATE = "August 14, 2005"
    START_LAT = 37.95
    START_LON = 23.72
    START_ALT = 34000
    START_HEADING = 180
    START_SPEED = 310
    TRIGGER_TIME = 15
    THRUST_MULTIPLIER = 1.0
    DRAG_MULTIPLIER = 1.0
    TRIGGER_MESSAGE = "!! CABIN PRESSURE LOST - HYPOXIA ONSET !!"
    INFO_TEXT = [
        "HELIOS FLIGHT 522 - Boeing 737-31S",
        "Pressurization left in MANUAL after maintenance.",
        "Descend below 10,000 ft within 45 seconds!",
        "Engines run fine — hypoxia steals your controls.",
    ]

    def apply_effects(self, aircraft):
        if not self.triggered:
            return
        time_since = max(0.0, self.flight_time - self.TRIGGER_TIME)
        degradation = max(0.05, 1.0 - time_since / 45.0)
        if aircraft.z < 10000:
            degradation = min(1.0, degradation + 0.5)
        aircraft._control_degradation = degradation


class AirFrance447(DisasterScenario):
    """Pitot icing → unreliable airspeed → high-altitude stall."""
    NAME = "Air France Flight 447"
    DESCRIPTION = "A330 Pitot Icing / Stall - June 1, 2009"
    AIRCRAFT_CLASS = AirbusA330_200
    DATE = "June 1, 2009"
    START_LAT = 2.0
    START_LON = -30.0
    START_ALT = 35000
    START_HEADING = 45
    START_SPEED = 275
    TRIGGER_TIME = 18
    THRUST_MULTIPLIER = 1.0
    DRAG_MULTIPLIER = 1.0
    TRIGGER_MESSAGE = "!! UNRELIABLE AIRSPEED — PITOT ICING !!"
    INFO_TEXT = [
        "AIR FRANCE 447 - Airbus A330-203",
        "Tropical icing blocks pitot tubes at FL350.",
        "Airspeed indicators become unreliable.",
        "Maintain gentle pitch — avoid aggressive pull-up.",
        "Recovery: level wings, reduce pitch, hold thrust.",
    ]

    def apply_effects(self, aircraft):
        if not self.triggered:
            return
        aircraft._airspeed_unreliable = True
        # Let the erroneous reading wander smoothly rather than resampling a
        # fresh random value every frame (which reads as 60 Hz strobing).
        prev = getattr(aircraft, "_display_airspeed_offset", 0.0)
        aircraft._display_airspeed_offset = max(-60.0, min(40.0, prev + random.uniform(-4, 4)))
        time_since = max(0.0, self.flight_time - self.TRIGGER_TIME)
        degradation = max(0.2, 1.0 - time_since / 60.0)
        if aircraft.pitch > 8:
            degradation *= 0.5
        aircraft._control_degradation = degradation
        if aircraft.stalled and aircraft.z > 20000:
            aircraft.drag_modifier = max(aircraft.drag_modifier, 1.5)


class Eastern401(DisasterScenario):
    """Autopilot disconnect + distracted crew → slow unnoticed descent."""
    NAME = "Eastern Air Lines 401"
    DESCRIPTION = "L1011 Autopilot / Descent - December 29, 1972"
    AIRCRAFT_CLASS = Boeing747_200
    DATE = "December 29, 1972"
    START_LAT = 25.75
    START_LON = -80.35
    START_ALT = 2000
    START_HEADING = 270
    START_SPEED = 220
    TRIGGER_TIME = 25
    THRUST_MULTIPLIER = 0.75
    DRAG_MULTIPLIER = 1.0
    TRIGGER_MESSAGE = "!! AUTOPILOT DISCONNECT — CHECK ALTITUDE !!"
    INFO_TEXT = [
        "EASTERN 401 - Lockheed L1011 TriStar (747 proxy)",
        "Crew distracted by landing gear indicator.",
        "Autopilot silently disconnected over the Everglades.",
        "Aircraft slowly descends — watch your altimeter!",
        "Maintain 2,000 ft MSL. You have ~25 seconds.",
    ]

    def apply_effects(self, aircraft):
        if not self.triggered:
            return
        aircraft._autopilot_drift = True
        aircraft.throttle = min(aircraft.throttle, self.THRUST_MULTIPLIER)


DISASTER_SCENARIOS = [
    TWA800, PanAm103, JAL123, Helios522, AirFrance447, Eastern401,
]