"""Flight data recorder."""
from hellcats.bootstrap import PHYSICS_DT

# ============== FLIGHT DATA RECORDER ==============
class FlightDataRecorder:
    """Records flight data for plotting"""
    def __init__(self, max_samples=500):
        self.max_samples = max_samples
        self.clear()

    def clear(self):
        self.time = []
        self.altitude = []
        self.airspeed = []
        self.vsi = []
        self.distance = []
        self.start_x = None
        self.start_y = None
        self.disaster_time = None

    def record(self, t, alt, speed, vertical_speed, x, y):
        if self.start_x is None:
            self.start_x = x
            self.start_y = y

        # Calculate distance from start in nm
        dist_ft = math.sqrt((x - self.start_x)**2 + (y - self.start_y)**2)
        dist_nm = dist_ft / 6076.12

        self.time.append(t)
        self.altitude.append(alt)
        self.airspeed.append(speed)
        self.vsi.append(vertical_speed)
        self.distance.append(dist_nm)

        # Trim old data
        if len(self.time) > self.max_samples:
            self.time = self.time[-self.max_samples:]
            self.altitude = self.altitude[-self.max_samples:]
            self.airspeed = self.airspeed[-self.max_samples:]
            self.vsi = self.vsi[-self.max_samples:]
            self.distance = self.distance[-self.max_samples:]

    def mark_disaster(self, t):
        self.disaster_time = t


