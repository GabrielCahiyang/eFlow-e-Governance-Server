"""Convert model duration units before the existing scheduling optimizer."""
import math
import re


def duration_days(value, default=3):
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)(?:\s*[-–]\s*(\d+(?:\.\d+)?))?\s*(hours?|hrs?|days?|weeks?|months?)?\s*", str(value), re.I)
    if not match:
        return default
    amount = float(match[2] or match[1])
    unit = (match[3] or "days").lower()
    multiplier = 1 / 8 if unit.startswith(("hour", "hr")) else 7 if unit.startswith("week") else 30 if unit.startswith("month") else 1
    return max(1, min(36500, math.ceil(amount * multiplier)))
