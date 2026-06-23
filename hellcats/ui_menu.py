"""Home screen and menus."""
import pygame
from hellcats.bootstrap import (
    WIDTH, HEIGHT, WHITE, HUD_GREEN, HUD_AMBER,
    font_title, font_large, font_med, font_small, font_tiny,
)
from hellcats.render_aircraft import (
    draw_f6f_rendering, draw_f4u_rendering, draw_747_rendering, draw_sbd_rendering,
)
from hellcats.aircraft import F6F_Hellcat, F4U_Corsair, SBD_Dauntless, Boeing747_200

# ============== HOME SCREEN ==============
def draw_home_screen(surface, selected_index, menu_items, current_menu):
    """Draw aircraft/scenario selection screen"""
    # Background gradient
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = int(20 + 40 * ratio)
        g = int(30 + 50 * ratio)
        b = int(60 + 80 * ratio)
        pygame.draw.line(surface, (r, g, b), (0, y), (WIDTH, y))

    # Title
    title = font_title.render("HELLCATS OVER THE PACIFIC", True, WHITE)
    title_rect = title.get_rect(center=(WIDTH // 2, 50))
    surface.blit(title, title_rect)

    # Menu tabs
    tab_y = 100
    tabs = ["FREE FLIGHT", "MISSIONS", "DISASTERS", "CAMPAIGN"]
    tab_width = 220
    total_tab_width = len(tabs) * tab_width
    tab_start_x = (WIDTH - total_tab_width) // 2

    for i, tab_name in enumerate(tabs):
        tab_x = tab_start_x + i * tab_width
        is_active = (i == current_menu)
        tab_color = (60, 100, 140) if is_active else (40, 50, 60)
        border_color = HUD_GREEN if is_active else (80, 80, 80)

        pygame.draw.rect(surface, tab_color, (tab_x, tab_y, tab_width - 10, 40), border_radius=5)
        pygame.draw.rect(surface, border_color, (tab_x, tab_y, tab_width - 10, 40), 2, border_radius=5)

        tab_text = font_med.render(tab_name, True, WHITE if is_active else (150, 150, 150))
        text_rect = tab_text.get_rect(center=(tab_x + tab_width // 2 - 5, tab_y + 20))
        surface.blit(tab_text, text_rect)

    if current_menu == 0:
        # Free Flight - Aircraft selection
        subtitle = font_med.render("Select Your Aircraft", True, HUD_GREEN)
        sub_rect = subtitle.get_rect(center=(WIDTH // 2, 165))
        surface.blit(subtitle, sub_rect)

        # Aircraft cards - size adapts to the number of aircraft so they fit
        n_cards = len(menu_items)
        card_height = 280
        card_spacing = 40
        card_width = min(500, (WIDTH - 80 - (n_cards - 1) * card_spacing) // n_cards)
        # Scale the side-view art to the card width (1.8 in the original 500px card)
        art_scale = min(1.8, card_width / 280.0)
        total_width = n_cards * card_width + (n_cards - 1) * card_spacing
        start_x = (WIDTH - total_width) // 2

        for i, aircraft_class in enumerate(menu_items):
            card_x = start_x + i * (card_width + card_spacing)
            card_y = 200

            is_selected = (i == selected_index)
            card_color = (60, 80, 100) if is_selected else (40, 50, 60)
            border_color = HUD_GREEN if is_selected else (80, 80, 80)

            pygame.draw.rect(surface, card_color, (card_x, card_y, card_width, card_height), border_radius=10)
            pygame.draw.rect(surface, border_color, (card_x, card_y, card_width, card_height), 3, border_radius=10)

            render_x = card_x + card_width // 2
            render_y = card_y + 90

            if aircraft_class == F6F_Hellcat:
                draw_f6f_rendering(surface, render_x, render_y, art_scale)
            elif aircraft_class == F4U_Corsair:
                draw_f4u_rendering(surface, render_x, render_y, art_scale)
            elif aircraft_class == SBD_Dauntless:
                draw_sbd_rendering(surface, render_x, render_y, art_scale)
            else:
                draw_747_rendering(surface, render_x, render_y, art_scale * 0.85)

            name = font_large.render(aircraft_class.NAME, True, WHITE)
            name_rect = name.get_rect(center=(card_x + card_width // 2, card_y + 185))
            surface.blit(name, name_rect)

            desc = font_med.render(aircraft_class.DESCRIPTION, True, HUD_AMBER)
            desc_rect = desc.get_rect(center=(card_x + card_width // 2, card_y + 220))
            surface.blit(desc, desc_rect)

            if aircraft_class == F6F_Hellcat:
                specs = ["Max Speed: 380 kts", "Engine: 2,000 HP", "Weight: 12,598 lbs"]
            elif aircraft_class == F4U_Corsair:
                specs = ["Max Speed: 395 kts", "Engine: 2,250 HP", "Weight: 12,039 lbs"]
            elif aircraft_class == SBD_Dauntless:
                specs = ["Max Speed: 255 kts", "Engine: 1,200 HP", "Weight: 9,450 lbs"]
            else:
                specs = ["Cruise: Mach 0.84", "Engines: 4x 46,500 lbf", "Weight: 600,000 lbs"]

            for j, spec in enumerate(specs):
                spec_text = font_tiny.render(spec, True, (180, 180, 180))
                surface.blit(spec_text, (card_x + 20, card_y + 245 + j * 16))

        # Selection arrow
        arrow_x = start_x + selected_index * (card_width + card_spacing) + card_width // 2
        pygame.draw.polygon(surface, HUD_GREEN, [
            (arrow_x, 185), (arrow_x - 15, 170), (arrow_x + 15, 170)
        ])

    elif current_menu == 1:
        # Missions
        subtitle = font_med.render("Combat Missions - Pacific Theater, 1942-43", True, HUD_GREEN)
        sub_rect = subtitle.get_rect(center=(WIDTH // 2, 165))
        surface.blit(subtitle, sub_rect)

        # Mission cards
        card_width = 220
        card_height = 320
        cards_per_row = min(5, len(menu_items))
        total_w = cards_per_row * card_width + (cards_per_row - 1) * 10
        start_x = (WIDTH - total_w) // 2
        card_y = 200

        for i, mission_class in enumerate(menu_items):
            m = mission_class()
            cx = start_x + i * (card_width + 10)
            is_selected = (i == selected_index)

            bg_color = (40, 60, 40) if is_selected else (30, 35, 30)
            border_color = HUD_GREEN if is_selected else (60, 80, 60)

            pygame.draw.rect(surface, bg_color, (cx, card_y, card_width, card_height), border_radius=8)
            pygame.draw.rect(surface, border_color, (cx, card_y, card_width, card_height), 2, border_radius=8)

            # Mission name
            name = font_med.render(m.NAME, True, WHITE)
            surface.blit(name, (cx + 10, card_y + 10))

            # Difficulty stars
            stars_str = "*" * m.DIFFICULTY
            stars = font_small.render(stars_str, True, HUD_AMBER)
            surface.blit(stars, (cx + 10, card_y + 40))

            # Objective (wrapped)
            words = m.OBJECTIVE.split()
            line = ""
            y_off = 70
            for word in words:
                test = line + word + " "
                if font_tiny.size(test)[0] > card_width - 20:
                    obj_line = font_tiny.render(line, True, (180, 180, 180))
                    surface.blit(obj_line, (cx + 10, card_y + y_off))
                    y_off += 18
                    line = word + " "
                else:
                    line = test
            if line:
                obj_line = font_tiny.render(line, True, (180, 180, 180))
                surface.blit(obj_line, (cx + 10, card_y + y_off))

            # Selection arrow
            if is_selected:
                pygame.draw.polygon(surface, HUD_GREEN, [
                    (cx + card_width // 2, card_y - 10),
                    (cx + card_width // 2 - 10, card_y - 22),
                    (cx + card_width // 2 + 10, card_y - 22)
                ])

    elif current_menu == 2:
        # Disaster Recreations
        subtitle = font_med.render("Historic Aviation Disasters", True, HUD_RED)
        sub_rect = subtitle.get_rect(center=(WIDTH // 2, 165))
        surface.blit(subtitle, sub_rect)

        warning = font_small.render("Educational recreations of real accidents - In memory of those lost", True, (180, 180, 180))
        warn_rect = warning.get_rect(center=(WIDTH // 2, 190))
        surface.blit(warning, warn_rect)

        # Disaster cards
        card_width = 700
        card_height = 350
        start_x = (WIDTH - card_width) // 2
        card_y = 220

        for i, scenario_class in enumerate(menu_items):
            is_selected = (i == selected_index)
            card_color = (80, 40, 40) if is_selected else (50, 30, 30)
            border_color = HUD_RED if is_selected else (100, 50, 50)

            pygame.draw.rect(surface, card_color, (start_x, card_y, card_width, card_height), border_radius=10)
            pygame.draw.rect(surface, border_color, (start_x, card_y, card_width, card_height), 3, border_radius=10)

            # 747 rendering
            draw_747_rendering(surface, start_x + 150, card_y + 80, 1.2)

            # Explosion effect
            pygame.draw.circle(surface, (255, 100, 0), (start_x + 120, card_y + 70), 30)
            pygame.draw.circle(surface, (255, 200, 0), (start_x + 120, card_y + 70), 20)
            pygame.draw.circle(surface, (255, 255, 200), (start_x + 120, card_y + 70), 10)

            # Scenario info
            name = font_large.render(scenario_class.NAME, True, WHITE)
            surface.blit(name, (start_x + 280, card_y + 20))

            date = font_med.render(scenario_class.DATE, True, HUD_AMBER)
            surface.blit(date, (start_x + 280, card_y + 60))

            desc = font_med.render(scenario_class.DESCRIPTION, True, (200, 200, 200))
            surface.blit(desc, (start_x + 280, card_y + 95))

            # Info text
            if hasattr(scenario_class, 'INFO_TEXT'):
                for j, line in enumerate(scenario_class.INFO_TEXT[:8]):
                    line_color = HUD_RED if "EXPLOSION" in line or "LOST" in line else (170, 170, 170)
                    info = font_tiny.render(line, True, line_color)
                    surface.blit(info, (start_x + 30, card_y + 150 + j * 22))

            # Selection indicator
            if is_selected:
                pygame.draw.polygon(surface, HUD_RED, [
                    (start_x - 20, card_y + card_height // 2),
                    (start_x - 35, card_y + card_height // 2 - 15),
                    (start_x - 35, card_y + card_height // 2 + 15)
                ])

    elif current_menu == 3:
        # Campaign mode
        subtitle = font_med.render("Campaign Mode", True, HUD_AMBER)
        sub_rect = subtitle.get_rect(center=(WIDTH // 2, 165))
        surface.blit(subtitle, sub_rect)

        desc = font_small.render("Fly all 12 missions in order. Damage carries between sorties.", True, (180, 180, 180))
        desc_rect = desc.get_rect(center=(WIDTH // 2, 195))
        surface.blit(desc, desc_rect)

        # Show mission list preview
        y = 230
        for i, mc in enumerate(Campaign.MISSION_ORDER):
            m = mc()
            stars = "*" * m.DIFFICULTY
            color = HUD_GREEN if i == 0 else (120, 120, 120)
            line = font_small.render(f"{i+1}. {m.NAME}  {stars}", True, color)
            surface.blit(line, (WIDTH // 2 - 150, y))
            y += 28

        start_hint = font_med.render("Press ENTER to begin campaign", True, HUD_AMBER)
        hint_rect = start_hint.get_rect(center=(WIDTH // 2, y + 30))
        surface.blit(start_hint, hint_rect)

    # Instructions
    inst = font_med.render("TAB: Switch Menu | A/D: Select | ENTER: Start | ESC: Quit", True, WHITE)
    inst_rect = inst.get_rect(center=(WIDTH // 2, HEIGHT - 50))
    surface.blit(inst, inst_rect)

    drag_hint = font_small.render("In-flight: [ / ] keys adjust drag coefficient", True, (150, 150, 150))
    drag_rect = drag_hint.get_rect(center=(WIDTH // 2, HEIGHT - 25))
    surface.blit(drag_hint, drag_rect)


