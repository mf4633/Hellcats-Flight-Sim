# Hellcats Over the Pacific - Enhanced Edition

A WWII Pygame flight simulator and historical disaster recreation, inspired by the classic 1991 *Hellcats Over the Pacific*. Fly Pacific Theater combat missions, campaign sorties, and forensic simulations of historic aviation accidents — all in one physics engine.

## Features

### Flyable Aircraft
- **F6F-5 Hellcat** — US Navy fleet defender; 6× .50 cal, HVAR rockets, bombs, torpedo
- **F4U-1D Corsair** — faster, higher VNE dive limit; 6× .50 cal, 8× HVAR, 2× 1,000 lb bombs
- **SBD-5 Dauntless** — carrier dive bomber; hold **B** for dive brakes during attack runs
- **Boeing 747-200** — airliner physics for free flight and disaster scenarios

### Enemy Aircraft
- **A6M Zero** — superior turn rate, historical AI dogfighting
- **G4M Betty** — bomber targets in scramble and strike missions

### Combat Missions (10)
1. **Flight School** — practice takeoff, flight, carrier landing
2. **Bomb Base** — strike an enemy airfield and RTB
3. **Scramble** — intercept inbound bomber strike
4. **Coral Sea** — defend the task force (May 1942)
5. **Midway CAP** — break the first wave over Midway (June 1942)
6. **Divine Wind** — kamikaze defense
7. **Flat Top** — sink the enemy carrier
8. **Bomber Escort** — protect B-17s to the target
9. **Torpedo Run** — low-level convoy attack
10. **Night Strike** — fuel depot raid under searchlights

### Disaster Recreations (4)
- **TWA Flight 800** (1996) — center fuel tank explosion
- **Pan Am Flight 103** (1988) — Lockerbie bomb detonation
- **JAL Flight 123** (1985) — hydraulic failure; engines still work
- **Helios Flight 522** (2005) — hypoxia; descend below 10,000 ft to survive

### Other Modes
- **Campaign** — linear mission progression with persistent aircraft state
- **Pilot Dossier** — rank, score, and mission awards (**P** in flight)
- **Satellite maps** — pick any area on startup (Pearl Harbor, Midway, etc.)
- **Deterministic replay** — HOTP RNG reconstructed from the 1991 game binary

## Installation

1. Python 3.8+
2. Install dependencies:

```bash
pip install -r requirements.txt
```

## Running

```bash
python hellcat_sim.py
```

Or on Windows:

```bat
run_simulator.bat
```

Module entry point:

```bash
python -m hellcats
```

## Controls

### Flight
| Key | Action |
|-----|--------|
| W/S | Pitch up/down |
| A/D | Roll left/right |
| Q/E | Rudder left/right |
| Shift/Ctrl | Throttle up/down |
| F | Flaps |
| G | Gear |
| B | Dive brakes (SBD only) |
| V | Cycle camera (Overhead / Cockpit / Chase) |
| +/- or ]/[ | Drag coefficient |
| R | Reset |
| M | Return to menu |
| ESC | Menu / quit |

### Combat (Hellcat family)
| Key | Action |
|-----|--------|
| 1 | Machine guns |
| 2 | HVAR rockets |
| 3 | 500 lb bomb |
| 4 | Mk 13 torpedo |
| Space | Fire selected weapon |
| L | Drop flare (night missions) |

### Menu
| Key | Action |
|-----|--------|
| Tab | Switch mode (Free Flight / Missions / Disasters / Campaign) |
| A/D or ←/→ | Select item |
| Enter | Launch |

## Project Structure

```
hellcat_sim.py          # Entry point
hellcats/
  bootstrap.py          # Pygame init, fonts, map loading
  hotp.py               # Authentic 1991 RNG & aero tables
  aircraft.py           # Flight models
  missions.py           # Combat missions & campaign
  disasters.py          # Historical accident scenarios
  weapons.py / targets.py / friendly.py
  render_game.py        # Cockpit, chase, HUD, instruments
  game.py               # Main loop
```

## Technical Notes

- **Pygame** for rendering and input
- **Custom 3D projection** for enemy aircraft
- **ESRI World Imagery** tiles downloaded on demand (cached in `~/.hellcat_tile_cache/`)
- Monolithic source was split into the `hellcats/` package in 2026; `hellcat_sim.py` remains the launcher

## Historical Accuracy

The simulator emphasizes authentic flight characteristics, Pacific Theater scenarios, and early-1990s flat-shaded presentation. Disaster scenarios are educational simulations — not entertainment glorifying tragedy — built to illustrate failure modes and emergency response windows.

---

*"The Hellcat was the fighter that won the Pacific war in the air."* — Naval Aviation Museum