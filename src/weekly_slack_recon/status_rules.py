from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set


@dataclass(frozen=True)
class StatusCategory:
    CLOSED: str = "CLOSED"
    IN_PROCESS_EXPLICIT: str = "IN PROCESS — explicit"
    IN_PROCESS_UNCLEAR: str = "IN PROCESS — unclear"


# Emojis are Slack "name" values (without colons) that we treat as signals.
# Note: ⛔ (no_entry / no_entry_sign) on the parent submission message is treated as an
# authoritative manual "declined" override in the inference logic.
CLOSED_EMOJIS_BASE: Set[str] = {
    "x",  # :x:
    "no_entry",
    "no_entry_sign",
    "thumbsdown",
    "stop_sign",  # 🛑
    "octagonal_sign",  # 🛑 (alternative Slack name)
    "stop_button",  # 🛑 (alternative Slack name)
    "no_good",
    "warning",
    "minus",  # ➖
    "heavy_minus_sign",  # ➖ (alternative Slack name)
}

CONFUSED_EMOJI: str = "confused"  # :confused:

# In-process emoji signals. On the parent submission message, 👀 (eyes) and ⏳
# (hourglass_flowing_sand) are treated as explicit in-process manual annotations.
IN_PROCESS_EMOJIS: Set[str] = {
    "white_check_mark",
    "thumbsup",
    "eyes",
    "arrows_counterclockwise",
    "hourglass_flowing_sand",
}

# Keyword sets (lowercased, simple substring match)
CLOSED_KEYWORDS_HARD: List[str] = [
    "pass",
    "passing",
    "no go",
    "reject",
    "rejected",
    "decline",
    "declined",
    "not moving forward",
    "won't proceed",
    "wont proceed",
    "not a fit",
    "doesn't make sense",
    "doesnt make sense",
    "we'll pass",
    "well pass",
    "closing the loop",
    "closed the loop",
]

CLOSED_KEYWORDS_SOFT: List[str] = [
    "not right now",
    "not at this time",
    "table this",
    "circle back later",
    "keeping warm",
    "put on ice",
    "waitlist",
]

IN_PROCESS_KEYWORDS: List[str] = [
    "tech screen",
    "screening",
    "onsite",
    "loop",
    "interview",
    "next round",
    "moving forward",
    "advancing",
    "hm screen",
    "panel",
    "follow-up",
    "follow up",
]


def text_contains_any(text: str, needles: List[str]) -> bool:
    """Check if text contains any of the needle phrases.
    
    Uses word-boundary-aware matching to avoid false positives.
    For multi-word phrases, requires the full phrase to be present.
    """
    if not text:
        return False
    
    import re
    lowered = text.lower()
    
    for needle in needles:
        # For multi-word phrases, check if the full phrase exists
        if " " in needle:
            if needle in lowered:
                return True
        else:
            # For single words, use word boundaries to avoid partial matches
            # e.g., "no" shouldn't match "not" or "know"
            pattern = r'\b' + re.escape(needle) + r'\b'
            if re.search(pattern, lowered):
                return True
    
    return False
