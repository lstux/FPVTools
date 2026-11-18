"""Settings the firmware rewrites by itself (calibration at boot): not a change made by the pilot.

They stay in the stored ``diff all`` text, but they neither create a snapshot nor show up as changes in
the comparison (unless asked).
"""

from __future__ import annotations

import hashlib
import re

# INAV stores the gyro offsets and the measured gravity after each calibration.
VOLATILE_SETTINGS = (
    "gyro_zero_x",
    "gyro_zero_y",
    "gyro_zero_z",
    "ins_gravity_cmss",
)

_VOLATILE_RE = re.compile(r"^\s*set\s+(%s)\s*=" % "|".join(map(re.escape, VOLATILE_SETTINGS)))


def is_volatile(line: str) -> bool:
    return bool(_VOLATILE_RE.match(line))


def mask(line: str) -> str:
    """The line with its value hidden, so that two calibrations compare equal."""
    m = _VOLATILE_RE.match(line)
    return "set %s = <calibration>" % m.group(1) if m else line


def config_hash(text: str) -> str:
    """Hash of a snapshot text, blind to the calibration values."""
    return hashlib.sha256("\n".join(mask(ln) for ln in text.split("\n")).encode()).hexdigest()
