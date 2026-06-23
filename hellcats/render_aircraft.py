"""Side-view aircraft art for menus."""
import pygame
from hellcats.bootstrap import WHITE, HUD_GREEN, HUD_AMBER, font_tiny

# ============== AIRCRAFT RENDERING ==============
def draw_f6f_rendering(surface, x, y, scale=1.0):
    """Draw F6F-5 Hellcat side view - Glossy Sea Blue scheme"""
    s = scale
    NAVY = (40, 55, 100)
    NAVY_D = (25, 40, 75)
    NAVY_L = (55, 75, 125)
    COWL = (50, 50, 55)
    METAL = (140, 140, 140)

    # Fuselage (rounded, tapers to tail)
    fuse_top = [
        (x - 85*s, y - 2*s), (x - 75*s, y - 14*s), (x - 40*s, y - 18*s),
        (x + 20*s, y - 16*s), (x + 55*s, y - 14*s), (x + 85*s, y - 8*s),
        (x + 100*s, y - 2*s)
    ]
    fuse_bot = [
        (x + 100*s, y + 2*s), (x + 85*s, y + 6*s), (x + 55*s, y + 8*s),
        (x + 20*s, y + 10*s), (x - 40*s, y + 10*s), (x - 75*s, y + 8*s),
        (x - 85*s, y + 2*s)
    ]
    fuselage = fuse_top + fuse_bot
    pygame.draw.polygon(surface, NAVY, fuselage)
    # Fuselage belly highlight
    belly = [
        (x - 75*s, y + 2*s), (x + 80*s, y + 2*s),
        (x + 80*s, y + 7*s), (x - 75*s, y + 7*s)
    ]
    pygame.draw.polygon(surface, NAVY_L, belly)
    pygame.draw.polygon(surface, NAVY_D, fuselage, 2)

    # Engine cowling (round, dark)
    cowl_pts = [
        (x - 85*s, y - 2*s), (x - 98*s, y - 10*s), (x - 100*s, y),
        (x - 98*s, y + 10*s), (x - 85*s, y + 2*s)
    ]
    pygame.draw.polygon(surface, COWL, cowl_pts)
    pygame.draw.polygon(surface, (30, 30, 30), cowl_pts, 2)

    # Exhaust stacks
    for ey in range(-6, 8, 3):
        pygame.draw.circle(surface, (80, 60, 40), (int(x - 82*s), int(y + ey*s)), int(2*s))

    # Propeller disc
    pygame.draw.ellipse(surface, (60, 60, 60), (int(x - 105*s), int(y - 28*s),
                                                  int(10*s), int(56*s)))
    # Prop hub
    pygame.draw.circle(surface, (80, 80, 80), (int(x - 100*s), int(y)), int(5*s))

    # Wing (side view - shows thickness and chord)
    wing = [
        (x - 30*s, y + 6*s), (x - 65*s, y + 38*s), (x - 55*s, y + 42*s),
        (x + 5*s, y + 12*s)
    ]
    pygame.draw.polygon(surface, NAVY_L, wing)
    pygame.draw.polygon(surface, NAVY_D, wing, 2)

    # Flap (trailing edge)
    [(x - 10*s, y + 10*s), (x - 40*s, y + 36*s),
            (x - 35*s, y + 38*s), (x - 5*s, y + 12*s)]
    pygame.draw.line(surface, NAVY_D, (int(x - 10*s), int(y + 10*s)),
                     (int(x - 38*s), int(y + 37*s)), 1)

    # Horizontal tail
    htail = [
        (x + 78*s, y - 6*s), (x + 98*s, y - 20*s), (x + 105*s, y - 18*s),
        (x + 95*s, y - 4*s)
    ]
    pygame.draw.polygon(surface, NAVY_L, htail)
    pygame.draw.polygon(surface, NAVY_D, htail, 2)

    # Vertical tail
    vtail = [
        (x + 78*s, y - 14*s), (x + 88*s, y - 38*s), (x + 98*s, y - 36*s),
        (x + 100*s, y - 12*s)
    ]
    pygame.draw.polygon(surface, NAVY, vtail)
    pygame.draw.polygon(surface, NAVY_D, vtail, 2)
    # Rudder hinge line
    pygame.draw.line(surface, NAVY_D, (int(x + 92*s), int(y - 35*s)),
                     (int(x + 95*s), int(y - 10*s)), 1)

    # Cockpit canopy (bubble, framed)
    canopy = [
        (x - 15*s, y - 16*s), (x - 20*s, y - 24*s), (x - 10*s, y - 28*s),
        (x + 10*s, y - 28*s), (x + 25*s, y - 22*s), (x + 30*s, y - 16*s)
    ]
    pygame.draw.polygon(surface, (100, 150, 210), canopy)
    pygame.draw.polygon(surface, (60, 60, 70), canopy, 2)
    # Canopy frame ribs
    for cx_off in [-5, 5, 15]:
        pygame.draw.line(surface, (60, 60, 70),
                         (int(x + cx_off*s), int(y - 16*s)),
                         (int(x + cx_off*s), int(y - 27*s)), 1)

    # Landing gear (retracted position - wheel well cover)
    pygame.draw.ellipse(surface, NAVY_D,
                        (int(x - 55*s), int(y + 4*s), int(18*s), int(6*s)))

    # Arresting hook (stowed)
    pygame.draw.line(surface, METAL, (int(x + 75*s), int(y + 8*s)),
                     (int(x + 85*s), int(y + 6*s)), 2)

    # Star insignia with bars (US Navy marking)
    star_x, star_y = int(x + 25*s), int(y)
    r_out = int(14*s)
    r_in = int(9*s)
    pygame.draw.circle(surface, WHITE, (star_x, star_y), r_out)
    pygame.draw.circle(surface, NAVY, (star_x, star_y), r_in)
    # Insignia bars
    pygame.draw.rect(surface, WHITE, (star_x - int(22*s), star_y - int(5*s),
                                      int(44*s), int(10*s)))
    pygame.draw.rect(surface, NAVY, (star_x - r_in, star_y - r_in,
                                     r_in * 2, r_in * 2))
    pygame.draw.circle(surface, WHITE, (star_x, star_y), r_in)
    pygame.draw.circle(surface, NAVY, (star_x, star_y), int(6*s))

    # BuNo / side number
    num = font_tiny.render("19", True, WHITE)
    surface.blit(num, (int(x + 55*s), int(y - 12*s)))


def draw_f4u_rendering(surface, x, y, scale=1.0):
    """Draw F4U-1D Corsair side view - dark Sea Blue, inverted gull wing."""
    s = scale
    NAVY = (30, 42, 78)
    NAVY_D = (18, 28, 55)
    NAVY_L = (48, 64, 110)
    COWL = (45, 45, 50)
    METAL = (140, 140, 140)

    # Fuselage - long nose (the Corsair's signature), tapers to the tail
    fuse_top = [
        (x - 95*s, y - 2*s), (x - 82*s, y - 13*s), (x - 45*s, y - 17*s),
        (x + 18*s, y - 15*s), (x + 55*s, y - 13*s), (x + 88*s, y - 8*s),
        (x + 102*s, y - 2*s)
    ]
    fuse_bot = [
        (x + 102*s, y + 2*s), (x + 88*s, y + 6*s), (x + 55*s, y + 8*s),
        (x + 18*s, y + 9*s), (x - 45*s, y + 9*s), (x - 82*s, y + 7*s),
        (x - 95*s, y + 2*s)
    ]
    fuselage = fuse_top + fuse_bot
    pygame.draw.polygon(surface, NAVY, fuselage)
    belly = [
        (x - 82*s, y + 2*s), (x + 82*s, y + 2*s),
        (x + 82*s, y + 6*s), (x - 82*s, y + 6*s)
    ]
    pygame.draw.polygon(surface, NAVY_L, belly)
    pygame.draw.polygon(surface, NAVY_D, fuselage, 2)

    # Engine cowling (round, dark) on the long nose
    cowl_pts = [
        (x - 95*s, y - 2*s), (x - 108*s, y - 9*s), (x - 110*s, y),
        (x - 108*s, y + 9*s), (x - 95*s, y + 2*s)
    ]
    pygame.draw.polygon(surface, COWL, cowl_pts)
    pygame.draw.polygon(surface, (28, 28, 28), cowl_pts, 2)

    # Exhaust stacks
    for ey in range(-5, 7, 3):
        pygame.draw.circle(surface, (80, 60, 40), (int(x - 92*s), int(y + ey*s)), int(2*s))

    # Propeller disc + hub (big Hamilton Standard paddle blades)
    pygame.draw.ellipse(surface, (60, 60, 60), (int(x - 116*s), int(y - 32*s),
                                                  int(11*s), int(64*s)))
    pygame.draw.circle(surface, (85, 85, 85), (int(x - 110*s), int(y)), int(5*s))

    # Inverted gull wing - root dips DOWN sharply, then the panel bends back
    # up and out. This is the Corsair's defining feature.
    gull = [
        (x - 28*s, y + 5*s),       # wing root at fuselage
        (x - 18*s, y + 30*s),      # gull bend (lowest point)
        (x - 58*s, y + 22*s),      # outer panel sweeps up and forward
        (x - 70*s, y + 14*s),      # wingtip
        (x - 60*s, y + 10*s),
        (x - 22*s, y + 18*s),
        (x + 2*s, y + 9*s)
    ]
    pygame.draw.polygon(surface, NAVY_L, gull)
    pygame.draw.polygon(surface, NAVY_D, gull, 2)
    # Gull "kink" crease line
    pygame.draw.line(surface, NAVY_D, (int(x - 18*s), int(y + 30*s)),
                     (int(x - 28*s), int(y + 5*s)), 2)

    # Horizontal tail
    htail = [
        (x + 80*s, y - 6*s), (x + 100*s, y - 18*s), (x + 107*s, y - 16*s),
        (x + 96*s, y - 4*s)
    ]
    pygame.draw.polygon(surface, NAVY_L, htail)
    pygame.draw.polygon(surface, NAVY_D, htail, 2)

    # Vertical tail (tall, angular Corsair fin)
    vtail = [
        (x + 80*s, y - 13*s), (x + 88*s, y - 40*s), (x + 99*s, y - 38*s),
        (x + 102*s, y - 11*s)
    ]
    pygame.draw.polygon(surface, NAVY, vtail)
    pygame.draw.polygon(surface, NAVY_D, vtail, 2)
    pygame.draw.line(surface, NAVY_D, (int(x + 94*s), int(y - 37*s)),
                     (int(x + 97*s), int(y - 9*s)), 1)

    # Cockpit canopy (framed bubble, set well back behind the long nose)
    canopy = [
        (x - 5*s, y - 15*s), (x - 10*s, y - 24*s), (x + 2*s, y - 28*s),
        (x + 20*s, y - 28*s), (x + 34*s, y - 22*s), (x + 38*s, y - 15*s)
    ]
    pygame.draw.polygon(surface, (100, 150, 210), canopy)
    pygame.draw.polygon(surface, (55, 55, 65), canopy, 2)
    for cx_off in [4, 14, 24]:
        pygame.draw.line(surface, (55, 55, 65),
                         (int(x + cx_off*s), int(y - 15*s)),
                         (int(x + cx_off*s), int(y - 27*s)), 1)

    # Arresting hook (stowed)
    pygame.draw.line(surface, METAL, (int(x + 78*s), int(y + 8*s)),
                     (int(x + 88*s), int(y + 6*s)), 2)

    # Star-and-bars insignia (US Navy marking)
    star_x, star_y = int(x + 30*s), int(y)
    r_out = int(13*s)
    r_in = int(8*s)
    pygame.draw.circle(surface, WHITE, (star_x, star_y), r_out)
    pygame.draw.rect(surface, WHITE, (star_x - int(20*s), star_y - int(4*s),
                                      int(40*s), int(8*s)))
    pygame.draw.circle(surface, NAVY, (star_x, star_y), r_in)
    pygame.draw.circle(surface, WHITE, (star_x, star_y), int(5*s))
    pygame.draw.circle(surface, NAVY, (star_x, star_y), int(3*s))


def draw_747_rendering(surface, x, y, scale=1.0):
    """Draw 747 side view"""
    s = scale
    # Fuselage
    fuselage = [
        (x - 120*s, y), (x - 110*s, y - 20*s), (x + 100*s, y - 20*s),
        (x + 130*s, y - 10*s), (x + 140*s, y), (x + 130*s, y + 10*s),
        (x + 100*s, y + 20*s), (x - 110*s, y + 20*s), (x - 120*s, y)
    ]
    pygame.draw.polygon(surface, (240, 240, 245), fuselage)
    pygame.draw.polygon(surface, (100, 100, 100), fuselage, 2)

    # Nose hump (747 distinctive)
    hump = [
        (x - 110*s, y - 20*s), (x - 100*s, y - 35*s), (x - 60*s, y - 40*s),
        (x - 20*s, y - 35*s), (x, y - 20*s)
    ]
    pygame.draw.polygon(surface, (240, 240, 245), hump)
    pygame.draw.lines(surface, (100, 100, 100), False, hump, 2)

    # Windows
    for wx in range(-90, 100, 15):
        pygame.draw.ellipse(surface, (100, 150, 200), (x + wx*s, y - 8*s, 8*s, 10*s))

    # Wing
    wing = [
        (x - 30*s, y + 15*s), (x - 80*s, y + 60*s), (x - 60*s, y + 65*s),
        (x + 30*s, y + 25*s)
    ]
    pygame.draw.polygon(surface, (220, 220, 225), wing)

    # Engines (2 visible on this side)
    for ex in [-60, -35]:
        pygame.draw.ellipse(surface, (80, 80, 80), (x + ex*s - 8*s, y + 45*s, 20*s, 12*s))

    # Tail
    tail = [
        (x + 100*s, y - 20*s), (x + 110*s, y - 55*s), (x + 135*s, y - 55*s),
        (x + 125*s, y - 15*s)
    ]
    pygame.draw.polygon(surface, (220, 220, 225), tail)

    # Airline stripe
    pygame.draw.line(surface, (200, 50, 50), (x - 110*s, y), (x + 120*s, y), int(4*s))


def draw_sbd_rendering(surface, x, y, scale=1.0):
    """Draw SBD-5 Dauntless side view - two-tone navy scheme."""
    s = scale
    NAVY = (45, 60, 95)
    NAVY_D = (28, 42, 72)
    LIGHT = (170, 185, 200)

    # Fuselage
    fuselage = [
        (x - 95*s, y + 2*s), (x - 85*s, y - 12*s), (x + 55*s, y - 14*s),
        (x + 75*s, y - 8*s), (x + 82*s, y + 2*s), (x + 75*s, y + 10*s),
        (x + 55*s, y + 14*s), (x - 85*s, y + 12*s),
    ]
    pygame.draw.polygon(surface, LIGHT, fuselage)
    pygame.draw.polygon(surface, NAVY_D, fuselage, 2)

    # Lower fuselage / belly (navy)
    belly = [
        (x - 80*s, y + 2*s), (x + 70*s, y + 2*s), (x + 55*s, y + 14*s),
        (x - 85*s, y + 12*s),
    ]
    pygame.draw.polygon(surface, NAVY, belly)

    # Wings (slightly swept, perforated dive-brake hint)
    wing = [
        (x - 15*s, y + 6*s), (x - 70*s, y + 28*s), (x - 55*s, y + 32*s),
        (x + 25*s, y + 16*s),
    ]
    pygame.draw.polygon(surface, NAVY, wing)
    pygame.draw.line(surface, (90, 105, 130), (x - 50*s, y + 22*s), (x - 20*s, y + 14*s), 1)

    # Tail
    tail = [(x + 55*s, y - 14*s), (x + 68*s, y - 38*s), (x + 82*s, y - 36*s), (x + 72*s, y - 10*s)]
    pygame.draw.polygon(surface, NAVY, tail)

    # Radial engine cowl
    pygame.draw.ellipse(surface, NAVY_D, (x - 100*s, y - 18*s, 28*s, 28*s))
    pygame.draw.circle(surface, (20, 20, 20), (int(x - 86*s), int(y - 4*s)), int(5*s))

    # Canopy (pilot + gunner)
    pygame.draw.ellipse(surface, (80, 120, 160), (x - 25*s, y - 22*s, 22*s, 14*s))
    pygame.draw.ellipse(surface, (80, 120, 160), (x + 5*s, y - 20*s, 18*s, 12*s))

    # Centerline bomb
    pygame.draw.ellipse(surface, (60, 60, 60), (x - 5*s, y + 14*s, 10*s, 22*s))


