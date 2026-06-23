"""Main game loop."""
import math
import pygame
from hellcats import bootstrap
from hellcats.bootstrap import (
    screen, clock, WIDTH, HEIGHT, PHYSICS_DT,
    WHITE, HUD_GREEN, HUD_AMBER, HUD_RED,
    font_large, font_med, font_small, font_tiny,
    satellite_map, CAMERA_OVERHEAD, CAMERA_COCKPIT, CAMERA_CHASE,
)
from hellcats.hotp import hotp_rng
from hellcats.weather import Weather
from hellcats.time_of_day import TimeOfDay
from hellcats.radio import RadioChatter
from hellcats.sound import SoundManager
from hellcats.fdr import FlightDataRecorder
from hellcats.weapons import WeaponsManager
from hellcats.targets import TargetManager
from hellcats.friendly import FriendlyCarrier, FriendlyAircraft
from hellcats.missions import MISSIONS, Campaign
from hellcats.dossier import (
    PilotDossier, InputRecorder, draw_dossier,
    draw_mission_briefing, draw_mission_hud, draw_mission_result,
)
from hellcats.aircraft import F6F_Hellcat, F4U_Corsair, SBD_Dauntless, Boeing747_200
from hellcats.disasters import DISASTER_SCENARIOS, DisasterAircraft
from hellcats.ui_menu import draw_home_screen
from hellcats.missions import draw_campaign_status
from hellcats.render_game import (
    draw_cockpit_view, draw_chase_view, draw_map_view,
    draw_instruments, draw_stall_warning, draw_g_effects,
    draw_weapons_overhead, draw_weapons_cockpit, draw_weapons_hud,
    draw_targets_overhead, draw_targets_cockpit, draw_wingmen_3d,
    draw_score_display, draw_friendly_carrier, draw_aircraft_symbol,
    draw_radar, draw_minimap,
)

# ============== MAIN PROGRAM ==============
def main():
    aircraft_list = [F6F_Hellcat, F4U_Corsair, SBD_Dauntless, Boeing747_200]
    mission_list = MISSIONS
    disaster_list = DISASTER_SCENARIOS

    current_menu = 0  # 0 = Free Flight, 1 = Missions, 2 = Disaster Recreations, 3 = Campaign
    selected_index = 0

    game_state = "MENU"  # MENU, BRIEFING, FLYING, TAKEOFF, CAMPAIGN, DOSSIER
    aircraft = None
    active_scenario = None
    active_mission = None
    pilot_dossier = PilotDossier()
    show_dossier = False
    status = "FLYING"
    crashed = False
    time_elapsed = 0
    disaster_triggered = False

    # Flight data recorder for plots
    fdr = FlightDataRecorder(max_samples=600)

    # Weapons manager
    weapons_mgr = WeaponsManager()

    # Target manager (initialized with Hellcat start position)
    target_mgr = TargetManager(40.7288, -73.4134)

    # Friendly carrier (positioned south of start, heading north)
    friendly_carrier = FriendlyCarrier(0, -5000, heading=0)

    # New systems
    sound_mgr = SoundManager()
    wingmen = []  # Populated when flying Hellcat
    input_recorder = InputRecorder()
    weather = Weather(Weather.CLEAR)
    time_of_day = TimeOfDay(TimeOfDay.DAY)
    radio = RadioChatter()
    campaign = Campaign()

    # Carrier takeoff state
    takeoff_throttle_held = 0.0  # seconds throttle held at full for deck launch
    takeoff_roll_dist = 0.0      # feet rolled down deck

    # Camera view
    camera_view = CAMERA_OVERHEAD

    running = True
    while running:
        clock.tick(60)
        dt = PHYSICS_DT  # Fixed timestep for deterministic replay
        time_elapsed += dt

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if game_state in ("FLYING", "TAKEOFF"):
                        game_state = "MENU"
                        aircraft = None
                        active_scenario = None
                        disaster_triggered = False
                        weapons_mgr.clear()
                        target_mgr.clear()
                        weather.set_condition(Weather.CLEAR)
                        time_of_day.set_day()
                    elif game_state == "CAMPAIGN":
                        game_state = "MENU"
                    else:
                        running = False

                # M key returns to menu (save mission result first)
                if event.key == pygame.K_m and game_state in ("FLYING", "TAKEOFF"):
                    if active_mission and active_mission.status != "active":
                        pilot_dossier.add_mission_result(active_mission)
                        if campaign.active:
                            campaign.save_aircraft_state(aircraft)
                            campaign.advance(active_mission)
                    game_state = "MENU"
                    aircraft = None
                    active_scenario = None
                    active_mission = None
                    disaster_triggered = False
                    weapons_mgr.clear()
                    target_mgr.clear()
                    weather.set_condition(Weather.CLEAR)
                    time_of_day.set_day()

                # L key drops illumination flare (night missions)
                if event.key == pygame.K_l and game_state == "FLYING" and time_of_day.is_night():
                    if aircraft:
                        time_of_day.drop_flare(aircraft.x + aircraft.vx * 2,
                                               aircraft.y + aircraft.vy * 2,
                                               aircraft.z - 100)

                # P key toggles pilot dossier
                if event.key == pygame.K_p:
                    show_dossier = not show_dossier

                if game_state == "BRIEFING":
                    if event.key == pygame.K_RETURN:
                        # Set weather and time of day from mission
                        weather.set_condition(active_mission.WEATHER)
                        if active_mission.TIME_OF_DAY == TimeOfDay.NIGHT:
                            time_of_day.set_night()
                        else:
                            time_of_day.set_day()
                        radio.messages.clear()
                        radio.cooldowns.clear()

                        # Launch mission
                        aircraft = F6F_Hellcat()
                        active_mission.setup_targets(target_mgr, friendly_carrier)
                        status = "FLYING"
                        crashed = False
                        disaster_triggered = False
                        time_elapsed = 0
                        fdr.clear()
                        weapons_mgr.clear()
                        wingmen.clear()
                        wingmen.append(FriendlyAircraft(aircraft, offset_side=1))
                        wingmen.append(FriendlyAircraft(aircraft, offset_side=-1))
                        input_recorder.start_recording(hotp_rng.state)

                        # Apply campaign state if active
                        if campaign.active:
                            campaign.apply_aircraft_state(aircraft)

                        # Carrier takeoff or airborne start
                        if active_mission.CARRIER_TAKEOFF:
                            sx, sy, sh = friendly_carrier.get_takeoff_position()
                            aircraft.x, aircraft.y, aircraft.z = sx, sy, 65  # deck height
                            aircraft.vx, aircraft.vy, aircraft.vz = 0, 0, 0
                            aircraft.heading = sh
                            aircraft.throttle = 0.0
                            aircraft.on_ground = True
                            aircraft.gear_down = True
                            takeoff_throttle_held = 0.0
                            takeoff_roll_dist = 0.0
                            game_state = "TAKEOFF"
                            status = "ON DECK - Full throttle to launch"
                            radio.call('carrier', 'launch', cooldown=30.0,
                                       wind=int(weather.wind_speed))
                        else:
                            aircraft.z = active_mission.START_ALT
                            speed_fps = active_mission.START_SPEED * 1.68781
                            hdg_rad = math.radians(active_mission.START_HEADING)
                            aircraft.vx = math.sin(hdg_rad) * speed_fps
                            aircraft.vy = math.cos(hdg_rad) * speed_fps
                            aircraft.heading = active_mission.START_HEADING
                            game_state = "FLYING"
                            radio.call('command', 'mission_start', cooldown=30.0)
                    elif event.key == pygame.K_ESCAPE:
                        game_state = "MENU"
                        active_mission = None

                if game_state == "CAMPAIGN":
                    if event.key == pygame.K_RETURN:
                        mc = campaign.get_current_mission_class()
                        if mc:
                            active_mission = mc()
                            active_scenario = None
                            game_state = "BRIEFING"
                            continue
                    elif event.key == pygame.K_ESCAPE:
                        game_state = "MENU"

                if game_state == "MENU":
                    # Switch between menus
                    if event.key == pygame.K_TAB:
                        current_menu = (current_menu + 1) % 4
                        selected_index = 0

                    # Get current menu items
                    if current_menu < 3:
                        menu_items = [aircraft_list, mission_list, disaster_list][current_menu]
                    else:
                        menu_items = []  # Campaign has no selectable items

                    if menu_items:
                        if event.key in (pygame.K_a, pygame.K_LEFT):
                            selected_index = (selected_index - 1) % len(menu_items)
                        if event.key in (pygame.K_d, pygame.K_RIGHT):
                            selected_index = (selected_index + 1) % len(menu_items)

                    if event.key == pygame.K_RETURN:
                        if current_menu == 3:
                            # Campaign mode
                            if campaign.is_complete() or not campaign.active:
                                campaign.start()
                            game_state = "CAMPAIGN"
                            continue
                        if current_menu == 0:
                            # Free flight
                            aircraft = menu_items[selected_index]()
                            active_scenario = None
                            active_mission = None
                        elif current_menu == 1:
                            # Mission mode - show briefing then launch
                            mission_class = menu_items[selected_index]
                            active_mission = mission_class()
                            active_scenario = None
                            game_state = "BRIEFING"
                            continue
                        else:
                            # Disaster recreation
                            scenario_class = menu_items[selected_index]
                            active_scenario = scenario_class()
                            aircraft = DisasterAircraft(active_scenario)
                            active_mission = None

                        game_state = "FLYING"
                        status = "FLYING"
                        crashed = False
                        disaster_triggered = False
                        time_elapsed = 0
                        fdr.clear()
                        # Spawn wingmen for Hellcat flights
                        wingmen.clear()
                        if isinstance(aircraft, F6F_Hellcat):
                            wingmen.append(FriendlyAircraft(aircraft, offset_side=1))
                            wingmen.append(FriendlyAircraft(aircraft, offset_side=-1))
                            # Start recording for replay
                            input_recorder.start_recording(hotp_rng.state)

                if game_state == "FLYING":
                    if event.key == pygame.K_r:
                        aircraft.reset()
                        status = "FLYING"
                        crashed = False
                        disaster_triggered = False
                        time_elapsed = 0
                        fdr.clear()  # Clear flight data recorder
                        weapons_mgr.clear()  # Clear weapons
                        target_mgr.clear()  # Reset targets
                        if active_scenario:
                            active_scenario.triggered = False
                            active_scenario.flight_time = 0

                    if event.key == pygame.K_f:
                        ias = aircraft.get_airspeed_kts()
                        if ias < aircraft.FLAPS_MAX_SPEED or aircraft.flaps:
                            aircraft.flaps = not aircraft.flaps

                    if event.key == pygame.K_g:
                        ias = aircraft.get_airspeed_kts()
                        if ias < aircraft.GEAR_MAX_SPEED or aircraft.gear_down:
                            aircraft.gear_down = not aircraft.gear_down

                    # Drag coefficient adjustment with [ and ] keys
                    if event.key in (pygame.K_RIGHTBRACKET, pygame.K_EQUALS):
                        aircraft.drag_modifier = min(5.0, aircraft.drag_modifier + 0.1)
                    if event.key in (pygame.K_LEFTBRACKET, pygame.K_MINUS):
                        aircraft.drag_modifier = max(0.2, aircraft.drag_modifier - 0.1)

                    # Camera view cycle with V key
                    if event.key == pygame.K_v:
                        camera_view = (camera_view + 1) % 3

                    # Radar range cycle with TAB
                    if event.key == pygame.K_TAB and hasattr(aircraft, 'radar_range'):
                        ranges = [1, 3, 15]
                        idx = ranges.index(aircraft.radar_range) if aircraft.radar_range in ranges else 0
                        aircraft.radar_range = ranges[(idx + 1) % 3]

                    # Weapon selection (Hellcat only)
                    if hasattr(aircraft, 'selected_weapon'):
                        if event.key == pygame.K_1:
                            aircraft.selected_weapon = 0  # Machine guns
                        if event.key == pygame.K_2:
                            aircraft.selected_weapon = 1  # Rockets
                        if event.key == pygame.K_3:
                            aircraft.selected_weapon = 2  # Bombs
                        if event.key == pygame.K_4:
                            aircraft.selected_weapon = 3  # Torpedo

                        # Fire rockets, drop bombs, or launch torpedo with SPACE
                        if event.key == pygame.K_SPACE:
                            if aircraft.selected_weapon == 1:
                                if weapons_mgr.fire_rocket(aircraft):
                                    sound_mgr.play('rocket')
                            elif aircraft.selected_weapon == 2:
                                if weapons_mgr.drop_bomb(aircraft):
                                    sound_mgr.play('explosion')
                            elif aircraft.selected_weapon == 3:
                                if weapons_mgr.drop_torpedo(aircraft):
                                    sound_mgr.play('torpedo')
                                elif getattr(aircraft, 'torpedoes', 0) > 0:
                                    # Failed constraints - show why
                                    if aircraft.z > 300:
                                        status = "TORPEDO: TOO HIGH - Below 300 ft!"
                                    elif aircraft.get_airspeed_kts() > 150:
                                        status = "TORPEDO: TOO FAST - Below 150 kts!"

        keys = pygame.key.get_pressed()

        # === CARRIER TAKEOFF STATE ===
        if game_state == "TAKEOFF" and aircraft:
            # Player must hold full throttle to build up and roll down deck
            if keys[pygame.K_LSHIFT]:
                aircraft.throttle = min(1.0, aircraft.throttle + 1.0 * dt)
            if keys[pygame.K_LCTRL]:
                aircraft.throttle = max(0.0, aircraft.throttle - 1.0 * dt)

            if aircraft.throttle >= 0.95:
                takeoff_throttle_held += dt
            else:
                takeoff_throttle_held = 0

            # After 1.5s at full throttle, release brakes — start rolling
            if takeoff_throttle_held > 1.5:
                # Accelerate down deck
                hdg_rad = math.radians(friendly_carrier.heading)
                power = aircraft.get_engine_power(65, aircraft.throttle)
                accel = power * 550 / max(100, aircraft.weight) * 0.3  # simplified
                aircraft.vx += math.sin(hdg_rad) * accel * dt
                aircraft.vy += math.cos(hdg_rad) * accel * dt
                v = math.sqrt(aircraft.vx**2 + aircraft.vy**2)
                takeoff_roll_dist += v * dt
                aircraft.x += aircraft.vx * dt
                aircraft.y += aircraft.vy * dt

                # Update carrier position too
                friendly_carrier.update(dt)

                ias_kts = v / 1.68781
                status = f"ROLLING - {ias_kts:.0f} kts"

                # Check if reached end of deck (~400 ft roll)
                if takeoff_roll_dist > friendly_carrier.LENGTH * 0.8:
                    # Airborne!
                    aircraft.z = 80  # Just above deck edge
                    aircraft.on_ground = False
                    aircraft.gear_down = True  # Player retracts later
                    aircraft.heading = friendly_carrier.heading
                    game_state = "FLYING"
                    status = "AIRBORNE - Gear up!"
                    radio.call('command', 'mission_start', cooldown=30.0)
            else:
                status = f"ON DECK - Throttle {aircraft.throttle*100:.0f}% (hold SHIFT for full power)"
                friendly_carrier.update(dt)
                # Keep aircraft on deck
                sx, sy, sh = friendly_carrier.get_takeoff_position()
                aircraft.x, aircraft.y = sx, sy
                aircraft.heading = sh

            sound_mgr.update_engine(aircraft.throttle, True)
            weather.update(dt)
            time_of_day.update(dt)
            radio.update(dt)

        # Continuous drag adjustment while holding keys
        if game_state == "FLYING":
            if keys[pygame.K_RIGHTBRACKET] or keys[pygame.K_EQUALS]:
                aircraft.drag_modifier = min(5.0, aircraft.drag_modifier + 1.0 * dt)
            if keys[pygame.K_LEFTBRACKET] or keys[pygame.K_MINUS]:
                aircraft.drag_modifier = max(0.2, aircraft.drag_modifier - 1.0 * dt)

            # Machine gun firing (hold SPACE when MG selected)
            if hasattr(aircraft, 'mg_firing'):
                if keys[pygame.K_SPACE] and aircraft.selected_weapon == 0 and not crashed:
                    aircraft.mg_firing = True
                    # Fire rate: 80 rounds per second total (6 guns at 800 rpm each)
                    if time_elapsed - aircraft.last_mg_fire > 0.0125:  # ~80 rounds/sec
                        weapons_mgr.fire_guns(aircraft)
                        sound_mgr.play('guns')
                        aircraft.last_mg_fire = time_elapsed
                else:
                    aircraft.mg_firing = False

            # Record input for replay
            if input_recorder.recording:
                input_recorder.record_frame(keys)

            # Update weapons
            weapons_mgr.update(dt)

            # Update targets (only for Hellcat - combat mode)
            if hasattr(aircraft, 'mg_ammo'):
                target_mgr.update(dt, weapons_mgr, aircraft, friendly_carrier, wingmen=wingmen)

            # Update friendly carrier
            friendly_carrier.update(dt)

            # Check carrier deck landing (Hellcat only)
            if hasattr(aircraft, 'mg_ammo') and aircraft.z <= 65 and aircraft.z > 0:
                if friendly_carrier.check_on_deck(aircraft.x, aircraft.y):
                    aircraft.z = 65  # Deck height ~65 ft above water
                    caught, wire = friendly_carrier.check_wire_catch(
                        aircraft.x, aircraft.y, aircraft.vz,
                        aircraft.get_airspeed_kts(), aircraft.gear_down)
                    if caught and aircraft.vz <= 0:
                        # Arrested landing!
                        aircraft.vz = 0
                        aircraft.vx *= 0.85  # Wire deceleration
                        aircraft.vy *= 0.85
                        aircraft.on_ground = True
                        v_total = math.sqrt(aircraft.vx**2 + aircraft.vy**2)
                        if v_total < 10:
                            status = f"CARRIER LANDING - Wire {wire}!"
                            sound_mgr.play('wire_catch')
                            pilot_dossier.record_carrier_landing()
                            radio.call('carrier', 'trapped', cooldown=30.0, wire=wire)
                    elif aircraft.vz < 0:
                        # On deck but missed wires - bolter
                        aircraft.vz = 0
                        aircraft.on_ground = True
                        radio.call('carrier', 'bolter', cooldown=10.0)

            # Update weather, time of day, radio
            weather.update(dt)
            weather.apply_turbulence(aircraft, dt)
            time_of_day.update(dt)
            radio.update(dt)

            # Apply wind to aircraft velocity
            wx, wy = weather.get_wind_vector()
            aircraft.vx += wx * 0.01 * dt  # Gentle wind influence
            aircraft.vy += wy * 0.01 * dt

            # Auto-generate radio calls
            if hasattr(aircraft, 'mg_ammo'):
                radio.check_context(aircraft, target_mgr, friendly_carrier, wingmen, active_mission)

            # Radio calls for mission events
            if active_mission:
                if active_mission.status == "success":
                    radio.call('command', 'rtb', cooldown=30.0)
                elif active_mission.status == "failed":
                    radio.call('command', 'mission_fail', cooldown=30.0)

        if game_state == "MENU":
            if current_menu < 3:
                menu_items = [aircraft_list, mission_list, disaster_list][current_menu]
            else:
                menu_items = []
            draw_home_screen(screen, selected_index, menu_items, current_menu)

        elif game_state == "BRIEFING":
            draw_mission_briefing(screen, active_mission)

        elif game_state == "CAMPAIGN":
            draw_campaign_status(screen, campaign, pilot_dossier)

        elif game_state == "TAKEOFF":
            # Draw takeoff sequence using overhead view
            screen.fill(BLACK)
            draw_map_view(screen, aircraft, satellite_map)
            draw_friendly_carrier(screen, friendly_carrier, aircraft)
            draw_aircraft_symbol(screen, aircraft)
            draw_instruments(screen, aircraft, status)
            # Takeoff HUD
            bar = pygame.Surface((500, 80), pygame.SRCALPHA)
            bar.fill((0, 0, 0, 180))
            screen.blit(bar, (WIDTH // 2 - 250, 50))
            t1 = font_med.render(status, True, HUD_AMBER)
            screen.blit(t1, (WIDTH // 2 - t1.get_width() // 2, 60))
            pct = min(1.0, takeoff_throttle_held / 1.5) if aircraft.throttle >= 0.95 else 0
            # Throttle bar
            pygame.draw.rect(screen, (50, 50, 50), (WIDTH // 2 - 150, 95, 300, 20))
            pygame.draw.rect(screen, HUD_GREEN if pct >= 1.0 else HUD_AMBER,
                             (WIDTH // 2 - 150, 95, int(300 * pct), 20))
            t2 = font_tiny.render("THROTTLE HOLD", True, WHITE)
            screen.blit(t2, (WIDTH // 2 - t2.get_width() // 2, 118))
            # Night overlay for takeoff
            if time_of_day.is_night():
                night_overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                night_overlay.fill((0, 0, 15, time_of_day.get_night_overlay_alpha()))
                screen.blit(night_overlay, (0, 0))
            weather.draw_rain(screen)
            radio.draw(screen)

        elif game_state == "FLYING":
            if not crashed:
                status = aircraft.update(dt, keys)

                # Update sounds
                sound_mgr.update_engine(aircraft.throttle, aircraft.z > 0)
                if aircraft.stalled:
                    if not sound_mgr.channels.get('alerts', None) or \
                       not sound_mgr.channels['alerts'].get_busy():
                        sound_mgr.play('stall', loop=True)
                else:
                    sound_mgr.stop('alerts')

                # Record flight data
                fdr.record(
                    time_elapsed,
                    aircraft.z,
                    aircraft.get_airspeed_kts(),
                    aircraft.get_vertical_speed(),
                    aircraft.x,
                    aircraft.y
                )

                # Check for disaster trigger
                if active_scenario and active_scenario.triggered and not disaster_triggered:
                    disaster_triggered = True
                    fdr.mark_disaster(time_elapsed)
                    status = "!! EXPLOSION - ALL ENGINES LOST !!"

                if "CRASHED" in status:
                    crashed = True

                # Check mission objectives
                if active_mission and active_mission.status == "active":
                    mission_result = active_mission.check_objectives(aircraft, target_mgr, friendly_carrier)
                    if mission_result == "success":
                        active_mission.status = "success"
                    elif mission_result == "failed":
                        active_mission.status = "failed"
                    if crashed and active_mission.status == "active":
                        active_mission.status = "failed"

            screen.fill(BLACK)

            # Draw based on camera view
            if camera_view == CAMERA_OVERHEAD:
                draw_map_view(screen, aircraft, satellite_map)
                # Draw friendly carrier
                draw_friendly_carrier(screen, friendly_carrier, aircraft)
                # Draw targets (Hellcat only)
                if hasattr(aircraft, 'mg_ammo'):
                    draw_targets_overhead(screen, target_mgr, aircraft)
                draw_weapons_overhead(screen, weapons_mgr, aircraft)
                draw_aircraft_symbol(screen, aircraft)
                # Draw wingmen on overhead
                for wm in wingmen:
                    if wm.alive:
                        wpx, wpy = feet_to_pixel(wm.x, wm.y, aircraft.ref_lat, aircraft.ref_lon)
                        ac_px, ac_py = feet_to_pixel(aircraft.x, aircraft.y, aircraft.ref_lat, aircraft.ref_lon)
                        sx = int(WIDTH//2 + (wpx - ac_px))
                        sy = int(HEIGHT//2 + (wpy - ac_py))
                        if 0 < sx < WIDTH and 0 < sy < HEIGHT:
                            pygame.draw.circle(screen, HUD_GREEN, (sx, sy), 5)
                            pygame.draw.circle(screen, WHITE, (sx, sy), 5, 1)
                # Draw escort bombers on overhead
                if active_mission and hasattr(active_mission, 'bombers'):
                    ac_px, ac_py = feet_to_pixel(aircraft.x, aircraft.y, aircraft.ref_lat, aircraft.ref_lon)
                    for b in active_mission.bombers:
                        bpx, bpy = feet_to_pixel(b.x, b.y, aircraft.ref_lat, aircraft.ref_lon)
                        sx = int(WIDTH//2 + (bpx - ac_px))
                        sy = int(HEIGHT//2 + (bpy - ac_py))
                        if 0 < sx < WIDTH and 0 < sy < HEIGHT:
                            color = (100, 150, 255) if b.alive else (80, 80, 80)
                            # Large bomber symbol
                            pygame.draw.circle(screen, color, (sx, sy), 7)
                            pygame.draw.line(screen, color, (sx-10, sy), (sx+10, sy), 2)
                            if b.smoking:
                                pygame.draw.circle(screen, (150, 150, 150), (sx+3, sy+3), 4)
            elif camera_view == CAMERA_COCKPIT:
                draw_cockpit_view(screen, aircraft, satellite_map, time_elapsed)
                # Draw targets and wingmen in cockpit view
                if hasattr(aircraft, 'mg_ammo'):
                    draw_targets_cockpit(screen, target_mgr, aircraft)
                if wingmen:
                    draw_wingmen_3d(screen, wingmen, aircraft)
                    # Draw escort bombers if in bomber escort mission
                    if active_mission and hasattr(active_mission, 'bombers'):
                        draw_wingmen_3d(screen, active_mission.bombers, aircraft)
                draw_weapons_cockpit(screen, weapons_mgr, aircraft)
                # Add minimap for navigation
                draw_minimap(screen, aircraft, satellite_map, 10, 120, 180)
            elif camera_view == CAMERA_CHASE:
                draw_chase_view(screen, aircraft, satellite_map, time_elapsed)
                # Draw targets and wingmen in chase view
                if hasattr(aircraft, 'mg_ammo'):
                    draw_targets_cockpit(screen, target_mgr, aircraft)
                if wingmen:
                    draw_wingmen_3d(screen, wingmen, aircraft)
                    # Draw escort bombers if in bomber escort mission
                    if active_mission and hasattr(active_mission, 'bombers'):
                        draw_wingmen_3d(screen, active_mission.bombers, aircraft)
                draw_weapons_cockpit(screen, weapons_mgr, aircraft)
                # Add minimap for navigation
                draw_minimap(screen, aircraft, satellite_map, 10, 120, 180)

            draw_instruments(screen, aircraft, status)
            draw_stall_warning(screen, aircraft, time_elapsed)
            draw_g_effects(screen, aircraft)

            # Near-miss screen shake effect
            if hasattr(aircraft, 'near_miss_shake') and aircraft.near_miss_shake > 0.01:
                shake = aircraft.near_miss_shake
                sx = int((hotp_rng.next() % 20 - 10) * shake)
                sy = int((hotp_rng.next() % 14 - 7) * shake)
                # Shift the screen slightly for a flinch effect
                temp = screen.copy()
                screen.fill(BLACK)
                screen.blit(temp, (sx, sy))
                aircraft.near_miss_shake *= max(0, 1.0 - 8.0 * dt)

            # Radar and weapons HUD (Hellcat only)
            if hasattr(aircraft, 'mg_ammo'):
                radar_friends = list(wingmen)
                if active_mission and hasattr(active_mission, 'bombers'):
                    radar_friends.extend(active_mission.bombers)
                draw_radar(screen, aircraft, target_mgr, 800, HEIGHT - 120, 50,
                           friendly_carrier, friendlies=radar_friends)
                draw_weapons_hud(screen, aircraft)
                draw_score_display(screen, target_mgr)

            # Flight data plots on right side
            draw_flight_plots(screen, fdr, active_scenario)

            # Cloud layer effect
            weather.draw_cloud_layer(screen, aircraft)

            # Night overlay
            if time_of_day.is_night():
                night_alpha = time_of_day.get_night_overlay_alpha()
                night_surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                night_surf.fill((0, 0, 15, night_alpha))
                screen.blit(night_surf, (0, 0))
                # Searchlights from AA guns (cockpit/chase views)
                if camera_view in (CAMERA_COCKPIT, CAMERA_CHASE):
                    time_of_day.draw_searchlights(screen, target_mgr.ground_targets, aircraft)
                    time_of_day.draw_flares(screen, aircraft)
                # Stars in cockpit view
                if camera_view == CAMERA_COCKPIT:
                    time_of_day.draw_night_sky(screen)

            # Rain overlay
            weather.draw_rain(screen)

            # Weather indicator
            if weather.condition > Weather.CLEAR:
                wx_text = font_tiny.render(
                    f"WX: {Weather.NAMES[weather.condition]} | Wind {weather.wind_speed:.0f}kt "
                    f"@ {weather.wind_heading:.0f}° | Vis {weather.visibility*100:.0f}%",
                    True, HUD_AMBER)
                screen.blit(wx_text, (WIDTH // 2 - wx_text.get_width() // 2, HEIGHT - 275))

            # Radio messages
            radio.draw(screen)

            # Camera view indicator
            view_text = font_small.render(f"VIEW: {CAMERA_NAMES[camera_view]} (V to change)", True, WHITE)
            screen.blit(view_text, (WIDTH // 2 - 100, HEIGHT - 255))

            # Disaster scenario overlay
            if active_scenario:
                draw_disaster_overlay(screen, active_scenario, time_elapsed, crashed)

            # Mission HUD and results
            if active_mission:
                if active_mission.status == "active":
                    draw_mission_hud(screen, active_mission)
                elif active_mission.status in ("success", "failed"):
                    draw_mission_result(screen, active_mission)
                    # Campaign: auto-record and prompt for next
                    if campaign.active and active_mission.status in ("success", "failed"):
                        campaign_hint = font_small.render(
                            "Press M to continue campaign", True, HUD_AMBER)
                        screen.blit(campaign_hint, (WIDTH // 2 - campaign_hint.get_width() // 2,
                                                    HEIGHT // 2 + 120))

            if crashed:
                overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 180))
                screen.blit(overlay, (0, 0))

                crash_text = font_large.render(status, True, HUD_RED)
                rect = crash_text.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 50))
                screen.blit(crash_text, rect)

                # Show distance traveled after disaster
                if active_scenario and active_scenario.triggered:
                    dist_nm = math.sqrt(aircraft.x**2 + aircraft.y**2) / 6076
                    dist_text = font_med.render(f"Distance traveled after explosion: {dist_nm:.1f} nautical miles", True, HUD_AMBER)
                    dist_rect = dist_text.get_rect(center=(WIDTH // 2, HEIGHT // 2))
                    screen.blit(dist_text, dist_rect)

                restart = font_med.render("Press R to restart, ESC for menu", True, WHITE)
                rect2 = restart.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 50))
                screen.blit(restart, rect2)

        # Dossier overlay (drawn on top of everything)
        if show_dossier:
            draw_dossier(screen, pilot_dossier)

        # Rank display on menu screen
        if game_state == "MENU":
            rank_text = font_small.render(
                f"{pilot_dossier.get_rank()} {pilot_dossier.name} | Score: {pilot_dossier.total_score:,} | P: Dossier",
                True, HUD_GREEN)
            screen.blit(rank_text, (10, HEIGHT - 20))

        pygame.display.flip()

    pygame.quit()


def draw_flight_plots(surface, fdr, scenario=None):
    """Draw real-time flight data plots on the right side"""
    if len(fdr.time) < 2:
        return

    # Plot area dimensions
    plot_x = WIDTH - 280
    plot_width = 260
    plot_height = 160
    plot_spacing = 15
    start_y = 20

    # Colors
    PLOT_BG = (20, 25, 35)
    GRID_COLOR = (50, 60, 70)
    AXIS_COLOR = (100, 110, 120)
    DISASTER_COLOR = HUD_RED

    plots = [
        ("ALTITUDE (ft)", fdr.altitude, 0, max(20000, max(fdr.altitude) * 1.1) if fdr.altitude else 20000, HUD_GREEN),
        ("AIRSPEED (kts)", fdr.airspeed, 0, max(500, max(fdr.airspeed) * 1.1) if fdr.airspeed else 500, HUD_AMBER),
        ("VERT SPEED (fpm)", fdr.vsi, -5000, 5000, (100, 200, 255)),
    ]

    for i, (title, data, y_min, y_max, color) in enumerate(plots):
        py = start_y + i * (plot_height + plot_spacing)

        # Background
        pygame.draw.rect(surface, PLOT_BG, (plot_x, py, plot_width, plot_height))
        pygame.draw.rect(surface, AXIS_COLOR, (plot_x, py, plot_width, plot_height), 1)

        # Title
        title_surf = font_tiny.render(title, True, color)
        surface.blit(title_surf, (plot_x + 5, py + 3))

        # Grid lines
        for j in range(1, 4):
            gy = py + j * plot_height // 4
            pygame.draw.line(surface, GRID_COLOR, (plot_x, gy), (plot_x + plot_width, gy), 1)

        # Y-axis labels
        for j in range(5):
            val = y_max - (y_max - y_min) * j / 4
            label = font_tiny.render(f"{int(val)}", True, AXIS_COLOR)
            label_y = py + j * plot_height // 4
            surface.blit(label, (plot_x + plot_width - 45, label_y - 6))

        # Plot data
        if len(data) > 1:
            points = []
            for j, val in enumerate(data):
                px = plot_x + 5 + (plot_width - 55) * j / (len(data) - 1)
                # Clamp and scale value
                val_clamped = max(y_min, min(y_max, val))
                py_val = py + plot_height - 5 - (plot_height - 25) * (val_clamped - y_min) / (y_max - y_min)
                points.append((px, py_val))

            if len(points) > 1:
                pygame.draw.lines(surface, color, False, points, 2)

        # Mark disaster point
        if fdr.disaster_time and len(fdr.time) > 1:
            # Find index of disaster time
            for j, t in enumerate(fdr.time):
                if t >= fdr.disaster_time:
                    dx = plot_x + 5 + (plot_width - 55) * j / (len(fdr.time) - 1)
                    pygame.draw.line(surface, DISASTER_COLOR, (dx, py + 18), (dx, py + plot_height - 5), 2)
                    break

        # Current value
        if data:
            current = data[-1]
            val_text = font_small.render(f"{int(current)}", True, WHITE)
            surface.blit(val_text, (plot_x + 5, py + plot_height - 22))

    # Distance traveled
    if fdr.distance:
        dist_text = font_med.render(f"DIST: {fdr.distance[-1]:.2f} nm", True, HUD_AMBER)
        dist_y = start_y + 3 * (plot_height + plot_spacing)
        surface.blit(dist_text, (plot_x + 10, dist_y))

        # Time elapsed
        if fdr.time:
            time_text = font_med.render(f"TIME: {fdr.time[-1]:.1f} sec", True, HUD_GREEN)
            surface.blit(time_text, (plot_x + 10, dist_y + 28))

        # Distance after disaster
        if fdr.disaster_time and scenario:
            time_since = fdr.time[-1] - fdr.disaster_time
            if time_since > 0:
                # Find distance at disaster time
                disaster_dist = 0
                for j, t in enumerate(fdr.time):
                    if t >= fdr.disaster_time:
                        disaster_dist = fdr.distance[j]
                        break
                dist_after = fdr.distance[-1] - disaster_dist
                after_text = font_med.render(f"POST-EVENT: {dist_after:.2f} nm", True, HUD_RED)
                surface.blit(after_text, (plot_x + 10, dist_y + 56))


def draw_disaster_overlay(surface, scenario, time_elapsed, crashed):
    """Draw disaster scenario information overlay"""
    # Timer until disaster
    if not scenario.triggered:
        time_remaining = max(0, scenario.TRIGGER_TIME - scenario.flight_time)
        timer_color = HUD_GREEN if time_remaining > 5 else (HUD_AMBER if time_remaining > 2 else HUD_RED)

        timer_text = font_large.render(f"Time to event: {time_remaining:.1f}s", True, timer_color)
        rect = timer_text.get_rect(center=(WIDTH // 2, 50))
        pygame.draw.rect(surface, (0, 0, 0, 180), rect.inflate(20, 10))
        surface.blit(timer_text, rect)

        scenario_name = font_med.render(scenario.NAME, True, WHITE)
        name_rect = scenario_name.get_rect(center=(WIDTH // 2, 85))
        surface.blit(scenario_name, name_rect)

    # Disaster has occurred
    elif not crashed:
        # Flashing warning
        if int(time_elapsed * 3) % 2:
            warn_text = font_large.render("!! CATASTROPHIC FAILURE !!", True, HUD_RED)
            rect = warn_text.get_rect(center=(WIDTH // 2, 50))
            pygame.draw.rect(surface, (0, 0, 0, 200), rect.inflate(20, 10))
            surface.blit(warn_text, rect)

        # Show time since disaster
        time_since = scenario.flight_time - scenario.TRIGGER_TIME
        time_text = font_med.render(f"Time since explosion: {time_since:.1f}s", True, HUD_AMBER)
        time_rect = time_text.get_rect(center=(WIDTH // 2, 85))
        surface.blit(time_text, time_rect)


if __name__ == "__main__":
    main()
