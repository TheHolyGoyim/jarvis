"""
cs2_knowledge.py — Complete CS2 Agent & Map Knowledge Base
Every agent skin, hitbox profile, map callouts, terrain navigation,
and positioning data for pro-level spatial awareness.
"""

import math
import numpy as np

# ─────────────────────────────────────────────────────────────
# AGENT PROFILES — Visual detection data for every agent skin
# ─────────────────────────────────────────────────────────────

# Each agent has:
# - primary_colors: dominant HSV ranges for detection
# - head_offset: how far head is above detection centroid (% of height)
# - silhouette: body shape characteristics
# - team: T or CT
# - visibility: how easy to spot (1=easy 5=hard)

AGENTS = {
    # ── COUNTER-TERRORIST AGENTS ──────────────────────────────

    "operator": {
        "team": "CT", "name": "Operator",
        "colors": [(50, 80, 40, 130, 60, 180)],  # dark olive/green military
        "head_offset": 0.15, "visibility": 3,
        "notes": "Dark olive green, blends with many maps"
    },
    "sir_bloody_miami_darryl": {
        "team": "CT", "name": "Sir Bloody Miami Darryl",
        "colors": [(15, 150, 150, 25, 255, 255)],  # bright orange suit
        "head_offset": 0.12, "visibility": 1,
        "notes": "Bright orange — extremely visible"
    },
    "special_agent_ava": {
        "team": "CT", "name": "Special Agent Ava",
        "colors": [(0, 0, 80, 180, 30, 160)],  # dark grey/black
        "head_offset": 0.14, "visibility": 4,
        "notes": "Dark grey suit, hard to spot"
    },
    "cmdr_frank_fletcher": {
        "team": "CT", "name": "Cmdr. Frank Fletcher",
        "colors": [(100, 40, 60, 140, 120, 140)],  # navy blue
        "head_offset": 0.13, "visibility": 3,
        "notes": "Navy blue naval uniform"
    },
    "lieutenant_rex_krikey": {
        "team": "CT", "name": "Lt. Rex Krikey",
        "colors": [(20, 80, 100, 40, 200, 220)],  # khaki/tan
        "head_offset": 0.14, "visibility": 2,
        "notes": "Khaki uniform, somewhat bright"
    },
    "chef_darryl": {
        "team": "CT", "name": "Chef Darryl",
        "colors": [(0, 0, 220, 180, 20, 255)],  # white chef outfit
        "head_offset": 0.12, "visibility": 1,
        "notes": "Pure white — most visible CT agent"
    },
    "chem_haz_capitaine": {
        "team": "CT", "name": "Chem-Haz Capitaine",
        "colors": [(22, 150, 150, 35, 255, 255)],  # yellow hazmat
        "head_offset": 0.10, "visibility": 1,
        "notes": "Bright yellow hazmat suit"
    },
    "cmdr_margaret_easier": {
        "team": "CT", "name": "Cmdr. Margaret 'Grim' Easier",
        "colors": [(0, 0, 60, 180, 40, 130)],  # very dark
        "head_offset": 0.14, "visibility": 5,
        "notes": "Very dark outfit — hardest to see"
    },
    "doctor_romanov": {
        "team": "CT", "name": "Doctor Romanov",
        "colors": [(0, 0, 180, 180, 30, 240)],  # white lab coat
        "head_offset": 0.13, "visibility": 1,
        "notes": "White lab coat over dark clothes"
    },
    "sabre_ct": {
        "team": "CT", "name": "Sabre CT",
        "colors": [(0, 0, 50, 180, 60, 120)],  # dark tactical
        "head_offset": 0.14, "visibility": 4,
        "notes": "Dark tactical gear"
    },
    "ground_rebel": {
        "team": "CT", "name": "Ground Rebel",
        "colors": [(15, 60, 80, 35, 160, 180)],  # tan/brown
        "head_offset": 0.13, "visibility": 3,
        "notes": "Tan/brown casual clothes"
    },
    "enforcer": {
        "team": "CT", "name": "Enforcer",
        "colors": [(0, 0, 40, 180, 50, 100)],  # black tactical
        "head_offset": 0.13, "visibility": 5,
        "notes": "Full black — very hard to see on dark maps"
    },

    # ── TERRORIST AGENTS ─────────────────────────────────────

    "ground_rebel_t": {
        "team": "T", "name": "Ground Rebel",
        "colors": [(15, 60, 80, 35, 160, 180)],  # tan/brown
        "head_offset": 0.13, "visibility": 3,
        "notes": "Casual tan/brown clothes"
    },
    "osiris": {
        "team": "T", "name": "Osiris",
        "colors": [(0, 0, 40, 30, 80, 120)],  # dark brown/black
        "head_offset": 0.14, "visibility": 4,
        "notes": "Dark brown hooded"
    },
    "the_doctor": {
        "team": "T", "name": "The Doctor's Paperboy",
        "colors": [(0, 0, 180, 180, 25, 240)],  # white/light
        "head_offset": 0.12, "visibility": 1,
        "notes": "Light colored shirt — visible"
    },
    "sabre_t": {
        "team": "T", "name": "Sabre T",
        "colors": [(100, 40, 40, 140, 100, 120)],  # dark blue/grey
        "head_offset": 0.14, "visibility": 4,
        "notes": "Dark tactical, hard to spot"
    },
    "number_k": {
        "team": "T", "name": "Number K",
        "colors": [(25, 40, 60, 45, 120, 140)],  # olive/military green
        "head_offset": 0.13, "visibility": 3,
        "notes": "Military green top"
    },
    "sir_bloody_skullhead_darryl": {
        "team": "T", "name": "Sir Bloody Skullhead Darryl",
        "colors": [(0, 0, 30, 180, 60, 80)],  # very dark
        "head_offset": 0.12, "visibility": 5,
        "notes": "Dark skull mask — very hard to see"
    },
    "vypa_sista": {
        "team": "T", "name": "Vypa Sista of the Revolution",
        "colors": [(160, 100, 100, 180, 220, 220)],  # purple/magenta
        "head_offset": 0.13, "visibility": 1,
        "notes": "Bright purple — stands out"
    },
    "the_professionals": {
        "team": "T", "name": "The Professionals",
        "colors": [(20, 80, 120, 40, 180, 200)],  # tan/brown suit
        "head_offset": 0.13, "visibility": 2,
        "notes": "Light tan suit"
    },
    "little_kev": {
        "team": "T", "name": "Little Kev",
        "colors": [(100, 30, 80, 140, 100, 160)],  # dark blue hoodie
        "head_offset": 0.13, "visibility": 4,
        "notes": "Dark blue hoodie"
    },
    "street_soldier": {
        "team": "T", "name": "Street Soldier",
        "colors": [(0, 0, 40, 30, 80, 120)],  # dark clothing
        "head_offset": 0.13, "visibility": 4,
        "notes": "Dark casual street clothes"
    },
    "soldier": {
        "team": "T", "name": "Soldier",  # default T
        "colors": [(15, 80, 100, 35, 180, 200)],  # tan/brown military
        "head_offset": 0.14, "visibility": 3,
        "notes": "Default T — tan military look"
    },
    "seal_t": {
        "team": "CT", "name": "SEAL Frogman",
        "colors": [(90, 80, 40, 130, 160, 120)],  # dark green wetsuit
        "head_offset": 0.12, "visibility": 4,
        "notes": "Dark green/teal wetsuit"
    },
}

# Combined color profiles for fast detection
# Maps each team to their likely color ranges
TEAM_COLORS = {
    "CT": {
        "dark_agents": [  # Most common CT colors
            {"hue": (0, 180), "sat": (0, 80),  "val": (40, 140)},   # dark grey/black
            {"hue": (95, 135), "sat": (30, 120), "val": (40, 130)},  # navy blue
            {"hue": (35, 75),  "sat": (40, 130), "val": (50, 160)},  # olive/green
        ],
        "bright_agents": [
            {"hue": (15, 30), "sat": (140, 255), "val": (150, 255)}, # orange
            {"hue": (0, 180), "sat": (0, 20),   "val": (200, 255)},  # white
            {"hue": (22, 38), "sat": (150, 255), "val": (150, 255)}, # yellow
        ],
    },
    "T": {
        "dark_agents": [
            {"hue": (0, 35),   "sat": (40, 160), "val": (60, 160)},  # tan/brown
            {"hue": (0, 180),  "sat": (0, 70),   "val": (30, 110)},  # dark grey
            {"hue": (95, 140), "sat": (25, 100), "val": (40, 120)},  # dark blue
        ],
        "bright_agents": [
            {"hue": (150, 180), "sat": (80, 255), "val": (100, 255)}, # purple
            {"hue": (0, 180),   "sat": (0, 25),   "val": (200, 255)}, # white/light
        ],
    },
}


# ─────────────────────────────────────────────────────────────
# MAP KNOWLEDGE — Callouts, positions, angles
# ─────────────────────────────────────────────────────────────

MAP_KNOWLEDGE = {

    "de_dust2": {
        "name": "Dust 2",
        "callouts": {
            # T-side spawn area
            "t_spawn":      "T Spawn — starting position",
            "long_corner":  "Long Corner — first corner on long A",
            "long_a":       "Long A — main route to A site via long doors",
            "long_doors":   "Long Doors — gate between long and A site",
            "pit":          "Pit — depression at A site, good defensive spot",
            "a_site":       "A Site — bomb site, defend/plant near boxes",
            "short":        "Short — fast route from T spawn to A, via catwalk",
            "catwalk":      "Catwalk — elevated path to A short",
            "a_short":      "A Short — short route connecting catwalk to A site",
            "mid":          "Mid — center of map, controls access to both sites",
            "mid_doors":    "Mid Doors / Xbox — main mid crossing point",
            "top_mid":      "Top Mid — T-side mid opening",
            "b_tunnels":    "B Tunnels — main T route to B site, two tunnels",
            "upper_tunnels":"Upper Tunnels — top path of B tunnels",
            "lower_tunnels":"Lower Tunnels — bottom path of B tunnels",
            "b_site":       "B Site — bomb site near back platform",
            "b_platform":   "B Platform / Back B — elevated platform on B",
            "ct_spawn":     "CT Spawn — CT starting point",
            "a_cross":      "A Cross — exposed area crossing to A site",
            "goose":        "Goose — corner spot at A site near catwalk exit",
            "xbox":         "Xbox — box in mid, common peek spot",
            "palm":         "Palm — corner near A site from CT side",
        },
        "common_angles": {
            "long_a": ["doors", "blue", "car", "near corner"],
            "a_site": ["ct", "platform", "short", "goose", "pit"],
            "b_site": ["van", "big box", "window", "door"],
            "mid":    ["top_mid", "catwalk", "b_doors", "xbox"],
        },
        "rotations": {
            "a_to_b": "A to B: CT spawn → B, ~8 seconds",
            "b_to_a": "B to A: CT → A cross → A site, ~10 seconds",
            "mid_control": "Mid control gives access to both sites faster",
        },
        "pro_tips": [
            "Long A: wide-peek car with AWP, then rush or hold",
            "B tunnels: upper gives better angles than lower",
            "Mid control is crucial — whoever holds mid controls the map",
            "Short push: smokes CT and go fast to avoid catwalk angles",
            "B site: plant near van for easier post-plant angles",
        ],
        "spawns": {"T": "t_spawn", "CT": "ct_spawn"},
    },

    "de_mirage": {
        "name": "Mirage",
        "callouts": {
            "t_spawn":      "T Spawn",
            "t_mid":        "T Mid — T-side mid opening",
            "top_mid":      "Top Mid — elevated mid area",
            "window":       "Window — CT mid window room, key position",
            "connector":    "Connector — links mid to A site",
            "short":        "Short — A short, route from T spawn to A",
            "a_ramp":       "A Ramp — main T entry to A site",
            "a_site":       "A Site — bomb site with van and triple stack",
            "jungle":       "Jungle — area behind A site from CT perspective",
            "ct":           "CT — CT-side A site corner",
            "stairs":       "Stairs — left side of A site",
            "ticket_booth": "Ticket Booth — far right of A site",
            "b_apps":       "B Apps — apartment building, main B route",
            "b_van":        "B Van — van on B site",
            "b_site":       "B Site — bomb site",
            "bench":        "Bench — corner on B site",
            "short_corner": "Short Corner — first corner on A short",
            "sandwich":     "Sandwich — gap between buildings on A short",
        },
        "common_angles": {
            "a_site": ["ct", "jungle", "stairs", "ticket", "van"],
            "b_site": ["van", "bench", "bench_boost", "apps"],
            "mid":    ["window", "top_mid", "connector"],
        },
        "pro_tips": [
            "Window control is essential for T-side",
            "A execute: smoke jungle, ct, stairs simultaneously",
            "B execute: smoke van, ct cross, bench",
            "Mid: connector peek with AWP is standard",
            "B apps: always clear bathroom before pushing",
        ],
        "spawns": {"T": "t_spawn", "CT": "ct_spawn"},
    },

    "de_inferno": {
        "name": "Inferno",
        "callouts": {
            "t_spawn":   "T Spawn",
            "banana":    "Banana — main T route to B site",
            "b_site":    "B Site — bomb site",
            "second_mid":"Second Mid / Cemetery — route to mid",
            "mid":       "Mid — central area",
            "apartments":"Apartments / Apps — main T route to A",
            "a_site":    "A Site — bomb site",
            "arch":      "Arch — entrance to A from apps",
            "library":   "Library — CT side of A site",
            "balcony":   "Balcony — elevated spot at A site",
            "ct_spawn":  "CT Spawn",
            "pit":       "Pit — depression at A site",
            "new_box":   "New Box — box at A site",
            "car":       "Car — cover at B site",
            "dark":      "Dark — corner at B site",
            "coffins":   "Coffins — cover at B site",
        },
        "pro_tips": [
            "Banana: always check car and dark at B",
            "Apps: clear both floors before pushing A",
            "A site: smoke library and arch for clean execute",
            "B execute: smoke car, dark, and CT cross",
            "Mid control: cemetery gives alternative route to both sites",
        ],
    },

    "de_ancient": {
        "name": "Ancient",
        "callouts": {
            "t_spawn":  "T Spawn",
            "mid":      "Mid — central temple area",
            "a_ramp":   "A Ramp — main route to A",
            "a_site":   "A Site",
            "cave":     "Cave — route connecting mid to A",
            "temple":   "Temple — A site area",
            "b_site":   "B Site",
            "b_main":   "B Main — main B route",
            "ct_spawn": "CT Spawn",
            "jungle":   "Jungle — CT-side area near B",
        },
        "pro_tips": [
            "Mid control is crucial on Ancient",
            "Cave provides surprise entry to A",
            "B site: check donut before pushing",
        ],
    },

    "de_nuke": {
        "name": "Nuke",
        "callouts": {
            "t_spawn":  "T Spawn",
            "outside":  "Outside — outside ramp area",
            "ramp":     "Ramp — main entry to upper site",
            "upper":    "Upper Site / A Site",
            "lower":    "Lower Site / B Site",
            "squeaky":  "Squeaky — door to lower site",
            "hut":      "Hut — small building outside",
            "silo":     "Silo — cylindrical structure outside",
            "secret":   "Secret — CT route to lower via vents",
            "vents":    "Vents — connection between upper and lower",
            "lobby":    "Lobby — T-side indoor area",
            "ct_spawn": "CT Spawn",
            "radio":    "Radio — CT-side of upper",
            "trophy":   "Trophy Room — CT-side lower area",
        },
        "pro_tips": [
            "Nuke is CT-sided — T must win outside fast",
            "Upper: control heaven and CT for site control",
            "Lower: enter from ramp or squeaky",
            "Outside: hut boost for AWP angle",
            "Vents: risky but can be game-changing",
        ],
    },

    "de_vertigo": {
        "name": "Vertigo",
        "callouts": {
            "t_spawn":  "T Spawn",
            "mid":      "Mid — center scaffolding",
            "a_site":   "A Site — upper bomb site",
            "b_site":   "B Site — lower bomb site",
            "ramp":     "Ramp — main A entry",
            "a_main":   "A Main — T route to A",
            "b_main":   "B Main — T route to B",
            "ct_spawn": "CT Spawn",
            "stairs":   "Stairs — connection between sites",
            "sink":     "Sink — corner on A site",
        },
        "pro_tips": [
            "Vertigo is T-sided with fast rotations",
            "Mid control is vital for both sites",
            "A site: smoke CT and go fast",
            "B site: always use scaffolding for cover",
        ],
    },
}

# ─────────────────────────────────────────────────────────────
# TERRAIN NAVIGATOR — Spatial awareness & positioning
# ─────────────────────────────────────────────────────────────

class TerrainNavigator:
    """
    Provides CS2 spatial awareness:
    - Current position estimation from visual cues
    - Where to look next based on map knowledge
    - Optimal positioning for current situation
    - Rotation timing
    """

    def __init__(self):
        self.current_map  = "unknown"
        self.current_zone = "unknown"
        self.team         = "CT"
        self.round_time   = 115
        self.alive        = True

    def set_map(self, map_name):
        """Set current map."""
        for key in MAP_KNOWLEDGE:
            if map_name.lower() in key or map_name.lower() in MAP_KNOWLEDGE[key]["name"].lower():
                self.current_map = key
                return f"Map set: {MAP_KNOWLEDGE[key]['name']}"
        self.current_map = "unknown"
        return f"Map '{map_name}' not in database. Using generic awareness."

    def get_callout_info(self, zone):
        """Get info about a specific callout."""
        if self.current_map not in MAP_KNOWLEDGE:
            return f"Map not set. Say 'cs2 map dust2' to set map."
        callouts = MAP_KNOWLEDGE[self.current_map].get("callouts", {})
        zone_lower = zone.lower().replace(" ", "_")
        for k, v in callouts.items():
            if zone_lower in k or zone_lower in v.lower():
                return f"📍 {k}: {v}"
        return f"Callout '{zone}' not found on {self.current_map}"

    def where_to_look(self, current_zone, enemies_heard=""):
        """
        Based on position, tell JARVIS where to pre-aim next.
        Returns prioritized list of angles to check.
        """
        if self.current_map not in MAP_KNOWLEDGE:
            return ["forward", "left", "right"]

        angles = MAP_KNOWLEDGE[self.current_map].get("common_angles", {})
        zone_key = current_zone.lower().replace(" ", "_")

        for k, v in angles.items():
            if zone_key in k:
                return v

        return ["forward", "left corner", "right corner", "behind"]

    def rotation_advice(self, from_zone, event="shots_heard"):
        """Should we rotate? How fast?"""
        if self.current_map not in MAP_KNOWLEDGE:
            return "Hold position and wait for info."

        rot = MAP_KNOWLEDGE[self.current_map].get("rotations", {})
        from_lower = from_zone.lower()

        for k, v in rot.items():
            if from_lower in k:
                return f"Rotation: {v}"

        return f"From {from_zone}: assess whether to rotate based on round time."

    def get_pro_tips(self, zone=""):
        """Get pro tips for current map/position."""
        if self.current_map not in MAP_KNOWLEDGE:
            return "Set a map first: 'cs2 map [mapname]'"

        tips = MAP_KNOWLEDGE[self.current_map].get("pro_tips", [])
        if zone:
            relevant = [t for t in tips
                       if zone.lower() in t.lower()]
            if relevant:
                return "\n".join(f"💡 {t}" for t in relevant)

        return "\n".join(f"💡 {t}" for t in tips[:5])

    def best_position(self, situation):
        """
        Recommend best position based on situation.
        situation: "attacking", "defending", "eco", "awp", "pistol"
        """
        if self.current_map not in MAP_KNOWLEDGE:
            return "Map not set."

        tips = MAP_KNOWLEDGE[self.current_map].get("pro_tips", [])

        if situation == "attacking":
            return f"Attacking on {MAP_KNOWLEDGE[self.current_map]['name']}:\n" + \
                   "\n".join(f"  • {t}" for t in tips[:3])
        elif situation == "defending":
            callouts = MAP_KNOWLEDGE[self.current_map].get("callouts", {})
            ct_positions = {k: v for k, v in callouts.items()
                           if any(x in k for x in ["ct", "window", "library", "arch"])}
            return f"Key CT positions on {MAP_KNOWLEDGE[self.current_map]['name']}:\n" + \
                   "\n".join(f"  • {k}: {v}" for k,v in list(ct_positions.items())[:5])
        return "\n".join(f"  • {t}" for t in tips[:3])


# ─────────────────────────────────────────────────────────────
# ENHANCED AGENT DETECTOR
# ─────────────────────────────────────────────────────────────

class AgentDetector:
    """
    Detects specific CS2 agent skins to improve
    head targeting accuracy based on agent height/hitbox.
    """

    def __init__(self):
        self.screen_w = 1920
        self.screen_h = 1080

    def identify_agent(self, frame, enemy_x, enemy_y, enemy_area):
        """
        Try to identify which agent skin is at a given position.
        Returns agent profile with head offset for accurate aiming.
        """
        if frame is None:
            return None

        try:
            import cv2

            h, w = frame.shape[:2]
            # Sample a region around the enemy
            sample_size = max(30, int(math.sqrt(enemy_area) * 1.5))
            x1 = max(0, enemy_x - sample_size // 2)
            x2 = min(w, enemy_x + sample_size // 2)
            y1 = max(0, enemy_y - sample_size)
            y2 = min(h, enemy_y + sample_size // 2)

            if x2 <= x1 or y2 <= y1:
                return None

            region = frame[y1:y2, x1:x2]
            hsv_region = cv2.cvtColor(region, cv2.COLOR_RGB2HSV)

            # Get dominant color stats
            avg_hue = np.mean(hsv_region[:,:,0])
            avg_sat = np.mean(hsv_region[:,:,1])
            avg_val = np.mean(hsv_region[:,:,2])

            # Score each agent by color match
            best_agent = None
            best_score = 0

            for agent_id, agent in AGENTS.items():
                score = 0
                for color_range in agent["colors"]:
                    h_min, s_min, v_min, h_max, s_max, v_max = color_range
                    if h_min <= avg_hue <= h_max:
                        score += 3
                    if s_min <= avg_sat <= s_max:
                        score += 2
                    if v_min <= avg_val <= v_max:
                        score += 1
                if score > best_score:
                    best_score = score
                    best_agent = agent_id

            if best_score >= 3 and best_agent:
                return AGENTS[best_agent]

        except Exception:
            pass

        return None

    def get_head_offset(self, enemy_area, agent_profile=None):
        """
        Calculate accurate head Y offset based on agent and distance.
        Returns pixel offset to subtract from body Y to get head Y.
        """
        if agent_profile:
            base_offset = agent_profile["head_offset"]
        else:
            base_offset = 0.13  # default average

        # Estimate body height from detection area
        estimated_height = math.sqrt(enemy_area) * 1.8

        return int(estimated_height * base_offset)

    def get_team_from_color(self, frame, x, y, area):
        """Estimate if enemy is T or CT based on dominant colors."""
        if frame is None:
            return "unknown"

        try:
            import cv2
            h, w = frame.shape[:2]
            s = max(20, int(math.sqrt(area)))
            x1, x2 = max(0, x-s), min(w, x+s)
            y1, y2 = max(0, y-s), min(h, y+s)
            region = frame[y1:y2, x1:x2]
            hsv = cv2.cvtColor(region, cv2.COLOR_RGB2HSV)
            avg_sat = np.mean(hsv[:,:,1])
            avg_val = np.mean(hsv[:,:,2])
            avg_hue = np.mean(hsv[:,:,0])

            # T agents tend to be tan/brown (hue 15-35)
            # CT agents tend to be grey/dark or blue/green
            if 15 <= avg_hue <= 35 and avg_sat > 60:
                return "T"
            elif avg_val < 100:
                return "CT"  # dark = likely CT
            return "unknown"

        except Exception:
            return "unknown"


# ─────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────

_navigator    = TerrainNavigator()
_agent_detect = AgentDetector()

def cs2_set_map(map_name):
    return _navigator.set_map(map_name)

def cs2_callout(zone):
    return _navigator.get_callout_info(zone)

def cs2_where_to_look(zone):
    angles = _navigator.where_to_look(zone)
    return f"Pre-aim angles from {zone}: {', '.join(angles)}"

def cs2_rotation(from_zone):
    return _navigator.rotation_advice(from_zone)

def cs2_tips(zone=""):
    return _navigator.get_pro_tips(zone)

def cs2_position_advice(situation="defending"):
    return _navigator.best_position(situation)

def cs2_map_list():
    lines = ["🗺️ Known CS2 Maps:"]
    for key, data in MAP_KNOWLEDGE.items():
        n_callouts = len(data.get("callouts", {}))
        lines.append(f"  • {data['name']} ({n_callouts} callouts)")
    lines.append("\nSay 'cs2 map dust2' to set your current map.")
    return "\n".join(lines)

def cs2_agent_list():
    ct  = [v["name"] for v in AGENTS.values() if v["team"]=="CT"]
    t   = [v["name"] for v in AGENTS.values() if v["team"]=="T"]
    hard_to_see = [v["name"] for v in AGENTS.values() if v["visibility"]>=4]
    easy_to_see = [v["name"] for v in AGENTS.values() if v["visibility"]<=2]
    return (f"🎭 CS2 Agents Database ({len(AGENTS)} agents)\n\n"
            f"CT agents ({len(ct)}):\n" +
            "\n".join(f"  • {n}" for n in ct) +
            f"\n\nT agents ({len(t)}):\n" +
            "\n".join(f"  • {n}" for n in t) +
            f"\n\nHardest to see: {', '.join(hard_to_see)}\n"
            f"Easiest to see: {', '.join(easy_to_see)}")

def get_agent_detector():
    return _agent_detect

def get_navigator():
    return _navigator
