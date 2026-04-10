# Hellcats Over the Pacific - Enhanced Edition

A recreation of the classic 1991 flight simulator featuring the F6F Hellcat in Pacific Theater WWII combat scenarios.

## Features

### Aircraft
- **F6F Hellcat** - Historically accurate specifications
  - Max Speed: 391 mph
  - Service Ceiling: 37,300 feet
  - Armament: 6× .50 caliber machine guns
  - Excellent dive performance and ruggedness

- **A6M Zero** - Primary enemy fighter
  - Superior maneuverability 
  - Lower speed but excellent turning
  - Historical tactics implemented

### Missions
1. **Guadalcanal Scramble** - Intercept Japanese bombers attacking Henderson Field
2. **Carrier Strike** - Attack enemy fleet in the Philippine Sea
3. **Kamikaze Defense** - Defend the task force from suicide attacks

### Graphics
- Flat-shaded polygon aircraft (1991 style)
- Real-time horizon and terrain
- Simple but effective 3D perspective
- Cockpit instruments and HUD

### Physics
- Realistic flight models based on historical data
- Accurate stall characteristics
- Fuel consumption and damage systems
- Ballistic projectile physics

## Installation

1. Install Python 3.8+
2. Install requirements:
```bash
pip install -r requirements.txt
```

## Controls

### Flight Controls
- **W/S** - Pitch Up/Down
- **A/D** - Roll Left/Right  
- **Q/E** - Rudder Left/Right
- **Shift/Ctrl** - Throttle Up/Down

### Combat
- **Space** - Fire Guns
- **ESC** - Return to Menu

## How to Play

1. Run `python game.py`
2. Select a mission from the main menu
3. Use flight controls to maneuver your Hellcat
4. Engage enemy aircraft with guns
5. Complete mission objectives
6. Land safely (or try to!)

## Historical Accuracy

The simulator recreates key aspects of Pacific Theater naval aviation:

- **F6F Hellcat**: The backbone of US carrier aviation, with superior speed and firepower
- **A6M Zero**: Early war dominance through maneuverability, later outclassed
- **Tactics**: Hellcat pilots were trained to avoid turning fights and use speed/altitude advantages
- **Scenarios**: Based on actual Pacific battles and carrier operations

## Development Notes

This simulator emphasizes:
- **Authentic flight characteristics** based on pilot reports and technical data
- **Historical mission scenarios** from the Guadalcanal and Philippine Sea campaigns  
- **Simple but effective graphics** reminiscent of early 1990s flight sims
- **Accessible gameplay** that captures the essence of carrier-based combat

## Technical Implementation

- **Pygame** for graphics and input
- **Custom 3D projection** for aircraft positioning
- **Realistic physics simulation** for flight dynamics
- **AI behavior system** for enemy aircraft
- **Modular design** for easy expansion

## Future Enhancements

- Carrier landing operations
- More aircraft types (F4U Corsair, SBD Dauntless)
- Bomb and torpedo attacks
- Weather systems
- Campaign mode
- Sound effects and music
- Enhanced graphics options

---

*"The Hellcat was the fighter that won the Pacific war in the air. It was faster than the Zero, more rugged, and packed more firepower. In the hands of a skilled pilot, it was unbeatable."* - Naval Aviation Museum
