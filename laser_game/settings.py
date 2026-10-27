"""Settings that can be changed while the game runs (S in the game), saved
to settings.json next to this file.

config.py holds the defaults. settings.json, when it exists, overrides them
at start; it only ever holds the settings listed here. Delete it to go back
to the defaults.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from . import config

PATH = Path(__file__).with_name("settings.json")


@dataclass(eq=False)          # compared by identity: usable as a dict key
class Setting:
    label: str
    name: str                # in config
    index: int = None        # for a (low, high) pair: which one
    step: float = 0.1
    low: float = 0.0
    high: float = 10.0
    unit: str = ""

    def get(self):
        value = getattr(config, self.name)
        return value if self.index is None else value[self.index]

    def set(self, value):
        if isinstance(self.get(), bool):
            value = bool(value)
        else:
            value = min(max(value, self.low), self.high)
            if isinstance(self.get(), int):
                value = int(round(value))
            else:
                value = round(value, 3)
        if self.index is None:
            setattr(config, self.name, value)
        else:
            pair = list(getattr(config, self.name))
            pair[self.index] = value
            setattr(config, self.name, tuple(pair))

    def nudge(self, direction):
        """One step up (+1) or down (-1); a yes/no setting flips."""
        value = self.get()
        self.set(not value if isinstance(value, bool) else value + direction * self.step)

    def text(self):
        value = self.get()
        if isinstance(value, bool):
            return "on" if value else "off"
        if isinstance(value, int):
            return f"{value}{self.unit}"
        decimals = 2 if self.step < 0.1 else 1
        return f"{value:.{decimals}f}{self.unit}"


# (section title, settings). All take effect at once, except where noted
SECTIONS = [
    ("Play zone", [
        Setting("Zone left edge", "ZONE_X_M", 0, 0.1, -4.0, 0.0, " m"),
        Setting("Zone right edge", "ZONE_X_M", 1, 0.1, 0.0, 4.0, " m"),
        Setting("Zone near", "ZONE_DEPTH_M", 0, 0.1, 0.3, 4.0, " m"),
        Setting("Zone far", "ZONE_DEPTH_M", 1, 0.1, 0.5, 8.0, " m"),
        Setting("Floor cut", "ZONE_HEIGHT_M", 0, 0.01, 0.0, 0.5, " m"),
        Setting("Zone top", "ZONE_HEIGHT_M", 1, 0.1, 1.0, 3.0, " m"),
    ]),
    ("Tracking", [
        Setting("Depth band around player", "PLAYER_DEPTH_BAND_M", None, 0.05, 0.1, 1.5, " m"),
        Setting("Edge trim", "EDGE_TRIM_PX", None, 1, 0, 5, " px"),
        Setting("Show real players", "SHOW_REAL_PLAYER"),
    ]),
    ("Game", [
        Setting("Lives (next round)", "LIVES", None, 1, 1, 9),
        Setting("Laser travel time, start", "TRAVEL_START_S", None, 0.1, 0.5, 6.0, " s"),
        Setting("Laser travel time, fastest", "TRAVEL_MIN_S", None, 0.1, 0.3, 4.0, " s"),
        Setting("Time between waves, start", "SPAWN_GAP_START_S", None, 0.1, 0.3, 6.0, " s"),
        Setting("Time between waves, fastest", "SPAWN_GAP_MIN_S", None, 0.1, 0.2, 4.0, " s"),
    ]),
    ("Hits", [
        Setting("Cells to count as a hit", "MIN_HIT_CELLS", None, 1, 1, 40),
        Setting("Frames to count as a hit", "HIT_FRAMES", None, 1, 1, 6),
        Setting("Camera + projector delay", "DISPLAY_LAG_S", None, 0.01, 0.0, 0.5, " s"),
    ]),
]

ALL = [setting for _, settings in SECTIONS for setting in settings]

# config.py's values, before settings.json changes anything
DEFAULTS = {setting: setting.get() for setting in ALL}


def load():
    """Apply settings.json, if there is one. Returns a message or None."""
    if not PATH.exists():
        return None
    try:
        saved = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return f"settings.json not read ({error}): using config.py"

    for name, value in saved.items():
        if hasattr(config, name) and any(s.name == name for s in ALL):
            setattr(config, name, tuple(value) if isinstance(value, list) else value)
    return f"Settings loaded from {PATH.name}"


def save():
    values = {}
    for setting in ALL:
        values[setting.name] = getattr(config, setting.name)
    PATH.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    return f"Saved to laser_game/{PATH.name}"


def reset(setting):
    setting.set(DEFAULTS[setting])
