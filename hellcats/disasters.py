"""Historical disaster scenarios."""
import math
from hellcats.aircraft import Boeing747_200

# ============== DISASTER SCENARIOS ==============
class DisasterScenario:
    """Base class for disaster recreations"""
    NAME = "Unknown Disaster"
    DESCRIPTION = "Description"
    AIRCRAFT_CLASS = Boeing747_200
    DATE = "Unknown"

    # Starting conditions
    START_LAT = 40.7
    START_LON = -73.5
    START_ALT = 10000
    START_HEADING = 90
    START_SPEED = 300  # knots

    # Disaster trigger
    TRIGGER_TYPE = "time"  # "time" or "position"
    TRIGGER_TIME = 10  # seconds after start
    TRIGGER_ALT = None

    # Effects when triggered
    THRUST_MULTIPLIER = 0.0  # 0 = total thrust loss
    DRAG_MULTIPLIER = 2.0  # 2x drag

    def __init__(self):
        self.triggered = False
        self.trigger_timer = 0
        self.flight_time = 0

    def check_trigger(self, aircraft, dt):
        """Check if disaster should trigger"""
        self.flight_time += dt

        if self.triggered:
            return True

        if self.TRIGGER_TYPE == "time" and self.flight_time >= self.TRIGGER_TIME:
            self.triggered = True
            return True

        return False

    def apply_effects(self, aircraft):
        """Apply disaster effects to aircraft"""
        if self.triggered:
            aircraft.throttle = min(aircraft.throttle, self.THRUST_MULTIPLIER)
            aircraft.drag_modifier = max(aircraft.drag_modifier, self.DRAG_MULTIPLIER)


class TWA800(DisasterScenario):
    """
    TWA Flight 800 - July 17, 1996
    Boeing 747-131 exploded 12 minutes after takeoff from JFK

    Details:
    - Departed JFK at 8:19 PM bound for Paris
    - Center fuel tank exploded at 8:31 PM
    - Altitude: ~13,760 feet, climbing
    - Speed: ~380 knots
    - Location: 8 miles south of Moriches, Long Island
    - All 230 aboard killed
    - Cause: Short circuit ignited fuel tank vapors

    The nose section separated first. The rest of the aircraft
    continued climbing momentarily before descending into the Atlantic.
    """
    NAME = "TWA Flight 800"
    DESCRIPTION = "747 Fuel Tank Explosion - July 17, 1996"
    AIRCRAFT_CLASS = Boeing747_200
    DATE = "July 17, 1996"

    # Starting position - approaching the explosion point
    # Explosion occurred at approximately 40.727°N, 72.660°W
    # We'll start a bit before that, heading ENE out of JFK
    START_LAT = 40.68
    START_LON = -73.0  # Start west of explosion point
    START_ALT = 13000  # Climbing through 13,000 ft
    START_HEADING = 70  # East-northeast toward Europe
    START_SPEED = 365  # knots - climb speed

    # Trigger after 15 seconds of flight (gives time to observe)
    TRIGGER_TYPE = "time"
    TRIGGER_TIME = 15

    # Effects: Total thrust loss, doubled drag (structural breakup)
    THRUST_MULTIPLIER = 0.0
    DRAG_MULTIPLIER = 2.5  # Severe drag from structural damage

    INFO_TEXT = [
        "TWA FLIGHT 800 - DISASTER RECREATION",
        "Date: July 17, 1996 | Aircraft: Boeing 747-131",
        "Route: New York JFK to Paris CDG",
        "",
        "At 8:31 PM, 12 minutes after takeoff, the center",
        "fuel tank exploded at 13,760 feet. The nose section",
        "separated immediately. The main fuselage continued",
        "climbing briefly before falling into the Atlantic.",
        "",
        "You have 15 seconds before the explosion.",
        "After detonation: ALL ENGINES LOST, SEVERE DRAG",
        "Try to see how far you can glide..."
    ]


class DisasterAircraft(Boeing747_200):
    """Modified 747 for disaster scenarios"""

    def __init__(self, scenario):
        self.scenario = scenario  # Set scenario BEFORE calling super().__init__()
        super().__init__()
        self.setup_scenario()

    def setup_scenario(self):
        """Configure aircraft for scenario starting conditions"""
        self.ref_lat = self.scenario.START_LAT
        self.ref_lon = self.scenario.START_LON
        self.x, self.y = 0, 0
        self.z = self.scenario.START_ALT

        # Set velocity based on heading and speed
        speed_fps = self.scenario.START_SPEED * 1.68781
        hdg_rad = math.radians(self.scenario.START_HEADING)
        self.vx = speed_fps * math.sin(hdg_rad)
        self.vy = speed_fps * math.cos(hdg_rad)
        self.vz = 500 / 60  # Slight climb rate (~500 fpm)

        self.heading = self.scenario.START_HEADING
        self.pitch = 3  # Slight nose up for climb
        self.roll = 0
        self.throttle = 0.85  # Climb power

    def reset(self):
        super().reset()
        if hasattr(self, 'scenario') and self.scenario:
            self.scenario.triggered = False
            self.scenario.trigger_timer = 0
            self.scenario.flight_time = 0
            self.setup_scenario()

    def update(self, dt, keys):
        # Check for disaster trigger
        just_triggered = False
        if not self.scenario.triggered:
            if self.scenario.check_trigger(self, dt):
                just_triggered = True

        # Apply disaster effects
        self.scenario.apply_effects(self)

        # Normal physics update
        result = super().update(dt, keys)

        if just_triggered:
            msg = getattr(self.scenario, "TRIGGER_MESSAGE", "!! EXPLOSION - Loss OF THRUST !!")
            return msg

        # Apply post-physics control degradation if scenario set it
        degradation = getattr(self, "_control_degradation", 1.0)
        if degradation < 1.0:
            self.pitch_rate *= degradation
            self.roll_rate  *= degradation
            self.yaw_rate   *= degradation

        return result


class PanAm103(DisasterScenario):
    """
    Pan Am Flight 103 - December 21, 1988
    Boeing 747-121 destroyed by bomb in cargo hold over Lockerbie, Scotland

    Details:
    - En route London Heathrow to New York JFK
    - Libyan intelligence bomb in a Samsonite suitcase detonated at FL310
    - Altitude: 31,000 ft, speed ~310 knots
    - Location: over Lockerbie, Scotland (55.12N, 3.35W)
    - All 259 aboard killed; 11 Lockerbie residents killed by falling debris
    - CVR captured a 0.4-second anomaly before silence
    - Wreckage scattered over 845 sq miles; nose/cockpit found intact in field
    """
    NAME = "Pan Am Flight 103"
    DESCRIPTION = "747 Bomb Detonation - December 21, 1988"
    AIRCRAFT_CLASS = Boeing747_200
    DATE = "December 21, 1988"

    START_LAT = 55.12
    START_LON = -3.35
    START_ALT = 31000
    START_HEADING = 45
    START_SPEED = 310

    TRIGGER_TYPE = "time"
    TRIGGER_TIME = 20

    THRUST_MULTIPLIER = 0.0
    DRAG_MULTIPLIER = 3.0

    TRIGGER_MESSAGE = "!! BOMB DETONATION - STRUCTURAL BREAKUP !!"

    INFO_TEXT = [
        "PAN AM FLIGHT 103 - DISASTER RECREATION",
        "Date: December 21, 1988 | Aircraft: Boeing 747-121",
        "Route: London Heathrow to New York JFK",
        "",
        "A Semtex bomb concealed in a Samsonite suitcase",
        "detonated in the forward cargo hold at FL310.",
        "The explosion tore through the fuselage and severed",
        "all structural integrity within milliseconds.",
        "259 aboard and 11 Lockerbie residents were killed.",
        "",
        "You have 20 seconds before detonation at FL310.",
        "After explosion: ALL THRUST LOST, SEVERE STRUCTURAL DRAG",
    ]


class JAL123(DisasterScenario):
    """
    Japan Airlines Flight 123 - August 12, 1985
    Boeing 747SR-46, rear pressure bulkhead failure severed all 4 hydraulic systems

    Details:
    - En route Tokyo Haneda to Osaka Itami
    - Improperly repaired bulkhead (after 1978 tail strike) ruptured at cruise altitude
    - Explosive decompression blew out the vertical stabilizer
    - All hydraulic fluid lost; crew used differential engine thrust for control
    - 32 minutes of uncontrolled flight before impact with Mt. Osutaka
    - 520 of 524 aboard killed - worst single-aircraft disaster in aviation history
    - 4 survivors found in wreckage the following morning
    """
    NAME = "JAL Flight 123"
    DESCRIPTION = "747SR Hydraulic Failure - August 12, 1985"
    AIRCRAFT_CLASS = Boeing747_200
    DATE = "August 12, 1985"

    START_LAT = 35.62
    START_LON = 138.73
    START_ALT = 24000
    START_HEADING = 315
    START_SPEED = 300

    TRIGGER_TYPE = "time"
    TRIGGER_TIME = 25

    THRUST_MULTIPLIER = 1.0
    DRAG_MULTIPLIER = 1.8

    TRIGGER_MESSAGE = "!! BULKHEAD FAILURE - HYDRAULICS LOST !!"

    INFO_TEXT = [
        "JAL FLIGHT 123 - DISASTER RECREATION",
        "Date: August 12, 1985 | Aircraft: Boeing 747SR-46",
        "Route: Tokyo Haneda to Osaka Itami",
        "",
        "The aft pressure bulkhead failed catastrophically,",
        "blowing out the vertical stabilizer and severing",
        "all four independent hydraulic systems.",
        "",
        "ENGINES STILL WORK - use throttle to control descent!",
        "Controls are severely degraded (15% effectiveness).",
        "The real crew survived 32 minutes using engine thrust.",
        "520 of 524 perished - worst single-aircraft disaster.",
    ]

    def apply_effects(self, aircraft):
        """Hydraulic failure: engines functional but controls nearly gone."""
        if self.triggered:
            aircraft.drag_modifier = max(aircraft.drag_modifier, self.DRAG_MULTIPLIER)
            aircraft._control_degradation = 0.15


class Helios522(DisasterScenario):
    """
    Helios Airways Flight 522 - August 14, 2005
    Boeing 737-31S, pressurization failure led to crew hypoxia and a ghost flight

    Details:
    - En route Larnaca to Athens
    - Ground crew left pressurization in MANUAL after maintenance check
    - Crew failed to switch to AUTO; aircraft depressurized during climb
    - Crew incapacitated by hypoxia; autopilot flew for ~2.5 hours
    - One flight attendant (Andreas Prodromou) briefly took controls near end
    - All 121 aboard killed when aircraft crashed after fuel exhaustion
    - MECHANIC: Hypoxia progressively strips control authority over 45 seconds
    - SURVIVAL: Descend below 10,000 ft to recover before full incapacitation
    """
    NAME = "Helios Flight 522"
    DESCRIPTION = "737 Pressurization Failure / Hypoxia - August 14, 2005"
    AIRCRAFT_CLASS = Boeing747_200
    DATE = "August 14, 2005"

    START_LAT = 37.95
    START_LON = 23.72
    START_ALT = 34000
    START_HEADING = 180
    START_SPEED = 310

    TRIGGER_TYPE = "time"
    TRIGGER_TIME = 15

    THRUST_MULTIPLIER = 1.0
    DRAG_MULTIPLIER = 1.0

    TRIGGER_MESSAGE = "!! CABIN PRESSURE LOST - HYPOXIA ONSET !!"

    INFO_TEXT = [
        "HELIOS FLIGHT 522 - DISASTER RECREATION",
        "Date: August 14, 2005 | Aircraft: Boeing 737-31S",
        "Route: Larnaca to Athens",
        "",
        "Cabin pressurization was left in MANUAL after maintenance.",
        "The crew failed to notice - oxygen starvation began at altitude.",
        "Engines ran perfectly. The aircraft flew itself for ~2.5 hours.",
        "",
        "SURVIVAL MECHANIC: Descend below 10,000 ft within 45 seconds!",
        "Hypoxia will progressively strip your control authority.",
        "Below 10,000 ft you can breathe - controls begin to return.",
        "All 121 aboard perished when fuel ran out. Don't join them.",
    ]

    def apply_effects(self, aircraft):
        """
        Progressive hypoxia model.

        Control degrades linearly from 1.0 to 0.05 over 45 seconds post-trigger.
        Descending below 10,000 ft partially restores control (recoverable hypoxia).
        """
        if not self.triggered:
            return

        time_since = max(0.0, self.flight_time - self.TRIGGER_TIME)

        # Linear degradation: full control at t=0s, near-zero at t=45s
        degradation = max(0.05, 1.0 - time_since / 45.0)

        # Survival window: fresh air below 10,000 ft restores significant control
        if aircraft.z < 10000:
            degradation = min(1.0, degradation + 0.5)

        # No engine changes - engines kept running throughout the incident
        aircraft.drag_modifier = max(aircraft.drag_modifier, self.DRAG_MULTIPLIER)
        aircraft._control_degradation = degradation


# Available disaster scenarios
DISASTER_SCENARIOS = [TWA800, PanAm103, JAL123, Helios522]


